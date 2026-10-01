#!/usr/bin/env python3
"""ccrelayd -- Telegram straight to the per-folder relay sessions, no OpenClaw.

One long-poll loop on the bot. Each message is routed by (chat, topic) to the
folder bound there and handed to the SAME backend OpenClaw used to call
(claude-tui-backend-multi), in the SAME envelope shape, so everything from
relay-extract-message.py onward runs unchanged. Replies leave through
claude-relay-send.py, which sees this session's transport-<key>.json and talks
to the Bot API directly (relay_tg.py).

What OpenClaw did that lives here now:
  * routing: exact `chat:topic:N` binding first, then the whole group `chat`
  * newcc / unbind / ccstatus: handled here, bindings reload live, no restart
  * cancel: run OUT of the per-topic queue, so it is not stuck behind the very
    turn it is cancelling
  * inbound media: downloaded into <folder>/media/inbound/ccrelay-<id>/
  * button taps (callback_query ccsel:N): answered and passed on as the
    "callback_data: ccsel:N" text the relay already understands

Usage: ccrelayd.py --config ~/.config/ccrelay/test.json
config: {"env": "<file with CCRELAY_BOT_TOKEN=>", "bindings": "<json>",
         "state": "<dir>", "allow_users": [<your telegram user id>],
         "allow_chats": [<chat ids where any member may use bound topics>]}
"""
import argparse
import datetime
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import relay_tg  # noqa: E402

BACKEND = os.path.join(D, "claude-tui-backend-multi")
CODES = os.path.join(D, "relay-codes.json")
RELAY_WORK = os.path.join(D, "relay-work")
OPENCLAW_CFG = os.path.expanduser("~/.openclaw/openclaw.json")

CANCEL_RE = re.compile(r"^\s*(?:/|cc\s+)?(?:cancel|interrupt|esc)(?:@\w+)?\s*$", re.I)
NEWCC_RE = re.compile(r"^\s*/?(?:new[-\s]?cc|new-claude-code)(?:@\w+)?\s+(\d{6})\s*$", re.I)
UNBIND_RE = re.compile(r"^\s*/?(?:unbind|unbind-claude-code)(?:@\w+)?\s*$", re.I)
STATUS_RE = re.compile(r"^\s*/?(?:ccstatus|cc-status|claude-code-status)(?:@\w+)?\s*$", re.I)


def log(msg):
    sys.stdout.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    sys.stdout.flush()


def session_key(folder):
    # Must match claude-relay-group: cr-<md5(`cd folder && pwd`)[:10]>.
    wd = subprocess.run(["bash", "-c", 'cd "$1" && pwd', "_", folder],
                        capture_output=True, text=True).stdout.strip() or folder
    return "cr-" + hashlib.md5(wd.encode()).hexdigest()[:10]


class Bindings:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def load(self):
        try:
            return json.load(open(self.path))
        except Exception:
            return {}

    def save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def lookup(self, chat, thread):
        d = self.load()
        if thread:
            hit = d.get(f"{chat}:topic:{thread}")
            if hit:
                return f"{chat}:topic:{thread}", hit
        hit = d.get(str(chat))
        return (str(chat), hit) if hit else (None, None)


def openclaw_bound_folders():
    """Folders the LIVE OpenClaw relay serves. While both run side by side a
    folder must belong to one of them: one tmux session has one transport, and
    binding it here would silently move that topic's replies to this bot."""
    try:
        cfg = json.load(open(OPENCLAW_CFG))
    except Exception:
        return set()
    agents = {a.get("id"): a.get("workspace") for a in cfg.get("agents", {}).get("list", [])}
    out = set()
    for b in cfg.get("bindings", []):
        ws = agents.get(b.get("agentId"))
        if ws:
            out.add(os.path.realpath(ws))
    return out


class Daemon:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env_path = os.path.expanduser(cfg["env"])
        self.bot = relay_tg.Bot(relay_tg.load_token(self.env_path))
        self.state = os.path.expanduser(cfg["state"])
        os.makedirs(self.state, exist_ok=True)
        self.bindings = Bindings(os.path.expanduser(cfg["bindings"]))
        self.allow = set(int(u) for u in cfg.get("allow_users") or [])
        # chats where ANY member may talk to bound topics (OpenClaw's
        # groups.<id>.allowFrom ["*"]); everywhere else only allow_users.
        self.allow_chats = set(str(c) for c in cfg.get("allow_chats") or [])
        self.offset_path = os.path.join(self.state, "offset")
        self.queues = {}
        self.me = self.bot.call("getMe")
        self.titles = {}

    # --- offset ---------------------------------------------------------------
    def offset(self):
        try:
            return int(open(self.offset_path).read().strip())
        except Exception:
            return 0

    def set_offset(self, n):
        with open(self.offset_path + ".tmp", "w") as f:
            f.write(str(n))
        os.replace(self.offset_path + ".tmp", self.offset_path)

    # --- replies from the daemon itself ---------------------------------------
    def say(self, chat, thread, text):
        try:
            relay_tg.send_text(self.bot, chat, thread, text)
        except Exception as e:
            log(f"say failed {chat}:{thread}: {e}")

    # --- main loop ------------------------------------------------------------
    def run(self):
        log(f"ccrelayd up as @{self.me.get('username')} bindings={self.bindings.path}")
        while True:
            try:
                ups = self.bot.call("getUpdates", {
                    "offset": self.offset(), "timeout": 50,
                    "allowed_updates": ["message", "callback_query"]}, timeout=70)
            except Exception as e:
                log(f"getUpdates: {e}")
                time.sleep(3)
                continue
            for u in ups:
                # Advance the offset BEFORE handling: a message that crashes the
                # handler must not be redelivered forever. Each handler logs.
                self.set_offset(u["update_id"] + 1)
                try:
                    if "message" in u:
                        self.on_message(u["message"])
                    elif "callback_query" in u:
                        self.on_callback(u["callback_query"])
                except Exception:
                    log("handler crashed:\n" + traceback.format_exc())

    # --- routing --------------------------------------------------------------
    @staticmethod
    def where(msg):
        chat = msg["chat"]["id"]
        thread = ""
        if msg["chat"].get("is_forum"):
            thread = str(msg.get("message_thread_id") or 1) if msg.get("is_topic_message") \
                else "1"
        return chat, thread

    def allowed(self, uid, chat):
        return not self.allow or uid in self.allow or str(chat) in self.allow_chats

    def on_callback(self, cq):
        try:
            self.bot.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
        except Exception:
            pass
        msg = cq.get("message") or {}
        if not msg or not self.allowed(cq["from"]["id"], msg["chat"]["id"]):
            return
        data = cq.get("data") or ""
        chat, thread = self.where(msg)
        peer, folder = self.bindings.lookup(chat, thread)
        if not folder:
            return
        self.dispatch(peer, folder, chat, thread, msg["chat"], cq["from"],
                      f"callback_data: {data}", [], msg, immediate=False)

    def on_message(self, msg):
        if msg.get("from", {}).get("is_bot"):
            return
        if not self.allowed(msg.get("from", {}).get("id"), msg["chat"]["id"]):
            return
        if msg.get("migrate_to_chat_id"):
            log(f"chat {msg['chat']['id']} migrated to {msg['migrate_to_chat_id']}; "
                f"re-bind with newcc in the new chat")
            return
        chat, thread = self.where(msg)
        text = msg.get("text") or msg.get("caption") or ""

        # Admin commands work in ANY chat, bound or not.
        admin = not self.allow or msg.get("from", {}).get("id") in self.allow
        m = NEWCC_RE.match(text) if admin else None
        if m:
            return self.cmd_newcc(chat, thread, m.group(1))
        if admin and UNBIND_RE.match(text):
            return self.cmd_unbind(chat, thread)
        if admin and STATUS_RE.match(text):
            return self.cmd_status(chat, thread)

        peer, folder = self.bindings.lookup(chat, thread)
        if not folder:
            log(f"unbound {self.peer_of(chat, thread)} "
                f"({msg['chat'].get('title')}): {text[:40]!r}")
            return                      # unbound: stay silent
        media = self.fetch_media(msg, folder)
        immediate = bool(CANCEL_RE.match(text))
        self.dispatch(peer, folder, chat, thread, msg["chat"], msg["from"], text,
                      media, msg, immediate=immediate)

    # --- media ----------------------------------------------------------------
    def fetch_media(self, msg, folder):
        items = []
        if msg.get("photo"):
            items.append((msg["photo"][-1]["file_id"], "image/jpeg"))
        for k in ("document", "video", "audio", "voice", "video_note", "animation", "sticker"):
            o = msg.get(k)
            if o:
                items.append((o["file_id"], o.get("mime_type") or
                              {"voice": "audio/ogg", "video_note": "video/mp4",
                               "sticker": "image/webp"}.get(k, "application/octet-stream")))
        out = []
        for fid, mime in items:
            dest = os.path.join(folder, "media", "inbound", f"ccrelay-{uuid.uuid4()}")
            try:
                path = self.bot.download(fid, dest)
                orig = (msg.get("document") or {}).get("file_name")
                if orig:
                    nice = os.path.join(dest, os.path.basename(orig))
                    os.replace(path, nice)
                    path = nice
                out.append((path, mime))
            except Exception as e:
                log(f"media download failed: {e}")
        return out

    # --- the hand-off -----------------------------------------------------------
    # --- voice ------------------------------------------------------------------
    AUDIO = ("audio/", "video/")

    def transcribe(self, path):
        """Local whisper.cpp transcript of a voice/audio/video file, or "".
        Same pipeline as the video-transcribe-respond skill: 16k mono wav, then
        large-v3-turbo with language auto-detect (Persian and English both)."""
        model = os.path.expanduser(self.cfg.get(
            "whisper_model", "~/.openclaw/whisper-models/ggml-large-v3-turbo.bin"))
        wcli = self.cfg.get("whisper_cli", "whisper-cli")
        if not os.path.isfile(model):
            log(f"no whisper model at {model}; voice sent as a file only")
            return ""
        base = os.path.join(os.path.dirname(path), "transcript")
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ar", "16000",
                            "-ac", "1", "-c:a", "pcm_s16le", base + ".wav"],
                           check=True, capture_output=True, timeout=300)
            subprocess.run([wcli, "-m", model, "-f", base + ".wav", "-l", "auto",
                            "-otxt", "-of", base], check=True, capture_output=True, timeout=900)
            return open(base + ".txt").read().strip()
        except Exception as e:
            log(f"transcription failed for {path}: {e}")
            return ""
        finally:
            try:
                os.remove(base + ".wav")
            except Exception:
                pass

    def envelope(self, chat_obj, thread, frm, text, media, msg):
        """Same shape OpenClaw composed, so relay-extract-message.py and the
        backend's chat/topic parsing work unchanged."""
        title = chat_obj.get("title") or chat_obj.get("first_name") or "DM"
        when = datetime.datetime.fromtimestamp(msg.get("date") or time.time()) \
            .astimezone().strftime("%a %Y-%m-%d %H:%M:%S %Z")
        name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or "user"
        head = f"[Telegram {title} id:{chat_obj['id']}"
        if thread:
            head += f" topic:{thread}"
        head += f" {when}] {name} ({frm.get('id')}):"
        body = []
        rt = msg.get("reply_to_message")
        # In a forum every message "replies" to its topic's opening service
        # message; that is not a quote.
        if rt and not rt.get("forum_topic_created"):
            rn = " ".join(x for x in ((rt.get("from") or {}).get("first_name"),
                                      (rt.get("from") or {}).get("last_name")) if x)
            rtxt = (rt.get("text") or rt.get("caption") or "").strip()
            body.append("[Reply chain - nearest first]\n"
                        f"[1. {rn} id:{rt.get('message_id')}]\n{rtxt}\n[/Reply chain]")
        for path, mime in media:
            body.append(f"[media attached: {path} ({mime})]")
            if mime.startswith(self.AUDIO):
                tr = self.transcribe(path)
                if tr:
                    body.append(f"[voice transcript]\n{tr}\n[/voice transcript]")
        if text:
            body.append(text)
        return head + "\n\n" + "\n\n".join(body)

    def dispatch(self, peer, folder, chat, thread, chat_obj, frm, text, media, msg,
                 immediate=False):
        key = session_key(folder)
        tp = os.path.join(RELAY_WORK, f"transport-{key}.json")
        rec = {"env": self.env_path, "peer": peer, "daemon": "ccrelayd"}
        try:
            if json.load(open(tp)) != rec:
                raise ValueError
        except Exception:
            with open(tp + ".tmp", "w") as f:
                json.dump(rec, f)
            os.replace(tp + ".tmp", tp)
        job = (peer, folder, chat, thread, (chat_obj, thread, frm, text, media, msg))
        if immediate:
            threading.Thread(target=self.run_backend, args=job, daemon=True).start()
            return
        q = self.queues.get(peer)
        if q is None:
            q = self.queues[peer] = queue.Queue()
            threading.Thread(target=self.worker, args=(q,), daemon=True).start()
        q.put(job)

    def worker(self, q):
        while True:
            self.run_backend(*q.get())

    def run_backend(self, peer, folder, chat, thread, env_args):
        t0 = time.time()
        env_text = self.envelope(*env_args)     # here: transcription can take a while
        try:
            r = subprocess.run([BACKEND, folder, peer, env_text],
                               capture_output=True, text=True, timeout=900)
            out = (r.stdout or "").strip()
            if r.returncode:
                log(f"backend rc={r.returncode} {peer}: {(r.stderr or '')[-300:]}")
        except subprocess.TimeoutExpired:
            out = ""
            log(f"backend timeout {peer}")
        log(f"{peer} handled in {time.time() - t0:.1f}s out={len(out)}")
        # With the watcher model the backend returns "" and the watcher delivers;
        # anything it does print (a menu prompt, an error) is a reply too.
        if out:
            self.say(chat, thread, out)

    # --- admin ----------------------------------------------------------------
    def peer_of(self, chat, thread):
        return f"{chat}:topic:{thread}" if thread else str(chat)

    def cmd_newcc(self, chat, thread, code):
        try:
            folder = json.load(open(CODES)).get(code)
        except Exception:
            folder = None
        if not folder:
            return self.say(chat, thread, f"Unknown code `{code}`.")
        if not os.path.isdir(folder):
            return self.say(chat, thread, f"Folder for `{code}` does not exist: `{folder}`")
        if os.path.realpath(folder) in openclaw_bound_folders():
            return self.say(chat, thread,
                            f"`{folder}` is still bound in OpenClaw. A folder can be served by "
                            f"one relay at a time; unbind it there first.")
        peer = self.peer_of(chat, thread)
        d = self.bindings.load()
        d[peer] = folder
        self.bindings.save(d)
        log(f"bound {peer} -> {folder}")
        self.say(chat, thread, f"Bound to `{folder}` (session `{session_key(folder)}`). "
                               f"Messages here now go to that folder's session.")

    def cmd_unbind(self, chat, thread):
        d = self.bindings.load()
        peer = self.peer_of(chat, thread)
        if peer not in d and thread and str(chat) in d:
            peer = str(chat)
        folder = d.pop(peer, None)
        if not folder:
            return self.say(chat, thread, "This chat isn't bound.")
        self.bindings.save(d)
        try:
            os.remove(os.path.join(RELAY_WORK, f"transport-{session_key(folder)}.json"))
        except Exception:
            pass
        log(f"unbound {peer} (was {folder})")
        self.say(chat, thread, f"Unbound `{peer}` (was `{folder}`).")

    def cmd_status(self, chat, thread):
        d = self.bindings.load()
        lines = [f"`{p}` → `{f}`" for p, f in sorted(d.items())] or ["(no bindings)"]
        self.say(chat, thread, "Bindings:\n" + "\n".join(lines) +
                 f"\n\nThis chat: `{self.peer_of(chat, thread)}`")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    cfg = json.load(open(os.path.expanduser(a.config)))
    Daemon(cfg).run()


if __name__ == "__main__":
    main()
