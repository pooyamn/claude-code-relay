#!/usr/bin/env python3
"""Drive a persistent interactive `claude` TUI in tmux: send a prompt, wait for
the turn, return Claude's reply as clean text. Subscription-billed (the TUI runs
on the Max plan; we just drive it).

Multi-choice support: when Claude shows a selection menu (model picker, plan
approval, any numbered question), we DON'T scrape it as a reply. We return the
options formatted for Telegram and remember a menu is open; the user's next
message (a number) is sent back as an arrow+Enter selection into the TUI.
"""
import subprocess, sys, time, hashlib, re, os, json, shutil, shlex
import queue, threading

SESSION = os.environ.get("CLAUDE_RELAY_SESSION", "clauderelay")
CHAT_ID = os.environ.get("RELAY_CHAT_ID", "")     # telegram chat id (numeric)
THREAD_ID = os.environ.get("RELAY_THREAD_ID", "")  # forum topic id, if any
STREAM = os.environ.get("RELAY_STREAM", "1") != "0"  # live-edit progress; 0 disables
TG_LIMIT = 4096                                    # telegram message hard cap (plain text)
TG_RICH_LIMIT = 32768        # OpenClaw TELEGRAM_RICH_TEXT_LIMIT, when richMessages=true
LIVE_WINDOW = 10000          # chars of the live TUI pane shown in the progress bubble
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay-work")
STATE = os.path.join(STATE_DIR, f"menu-{SESSION}.json")
STREAM_LOG = os.path.join(STATE_DIR, f"stream-{SESSION}.log")
DEBUG = os.path.exists(os.path.join(STATE_DIR, "DEBUG"))  # opt-in frame logging (off by default)
TARGET = os.path.join(STATE_DIR, f"target-{SESSION}.json")    # persisted chat/thread for the watcher
LASTPROMPT = os.path.join(STATE_DIR, f"prompt-{SESSION}.txt")  # last typed prompt (reply anchoring)
DELIVERED = os.path.join(STATE_DIR, f"delivered-{SESSION}.txt")  # last delivered reply hash (dup guard across restarts)
TURNDONE = os.path.join(STATE_DIR, f"turndone-{SESSION}.json")  # Stop-hook 'turn finished' marker (deterministic delivery)
# Persistent-watcher delivery model: a single long-lived watcher per session
# tails the pane and delivers EVERY turn (incl. long/slow ones and out-of-band
# output), while per-message calls only inject. Opt-in via env or a sentinel
# file so the default synchronous path is untouched until you flip it on.
WATCH = (os.environ.get("RELAY_WATCH") == "1"
         or os.path.exists(os.path.join(STATE_DIR, "WATCH")))
# Native-streaming model: emit Claude `stream-json` JSONL on stdout and let
# OpenClaw stream it to the channel with its OWN fast in-process edit loop (the
# backend must be configured output:"jsonl" + jsonlDialect:"claude-stream-json").
# No tg_* calls -- OpenClaw owns delivery. Opt-in via env or a sentinel file.
JSONL = (os.environ.get("RELAY_JSONL") == "1"
         or os.path.exists(os.path.join(STATE_DIR, "JSONL")))

def _thread_args():
    return ["--thread-id", THREAD_ID] if THREAD_ID else []

MSG_OPS = os.path.join(STATE_DIR, "msg-ops.log")

def _oplog(op, mid, text, r=None):
    """Audit trail of EVERY outbound Telegram op (send/edit/delete/buttons) with
    its actual CLI result, so we can see exactly what the relay did and whether
    Telegram accepted it. Always on."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        res = ""
        if r is not None:
            out = (r.stdout or "").strip().replace("\n", " ")
            res = f" rc={r.returncode} out={out[:240]}"
            errs = (r.stderr or "").strip().replace("\n", " ")
            if errs:
                res += f" ERR={errs[:160]}"
        preview = (text or "").replace("\n", "\\n")[:70]
        with open(MSG_OPS, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {op:11} mid={mid or '-':<6} "
                    f"chat={CHAT_ID} thr={THREAD_ID or '-'} len={len(text or '')} "
                    f"text='{preview}'{res}\n")
    except Exception:
        pass

def tg_buttons(question, options):
    """Send native Telegram inline buttons for a menu. Returns the message id.

    The full option text ALSO goes in the message body: Telegram truncates long
    button labels to a single narrow line ("Persiste…"), so the body is what
    keeps every option fully readable. The buttons are just the tap targets."""
    body = "\n".join([question or "Choose an option:", ""]
                     + [f"{i}. {o}" for i, o in enumerate(options, 1)])
    # ONE button per row: OpenClaw groups buttons within a single "buttons" block
    # into rows of 3 (TELEGRAM_INTERACTIVE_ROW_SIZE). Emitting a separate block
    # per button forces a full-width, one-per-line layout, so longer labels fit
    # before Telegram truncates them.
    pres = {"blocks": [
        {"type": "buttons", "buttons": [{"label": f"{i+1}. {o}"[:60], "value": f"ccsel:{i+1}"}]}
        for i, o in enumerate(options)]}
    r = subprocess.run(["openclaw", "message", "send", "--channel", "telegram",
                        "--target", CHAT_ID, *_thread_args(),
                        "--message", body[:TG_LIMIT],
                        "--presentation", json.dumps(pres), "--json"],
                       capture_output=True, text=True)
    try:
        mid = str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        mid = ""
    _oplog("SEND-BTNS", mid, body, r)
    return mid

def tg_remove_buttons(msg_id, note):
    """Edit the button message text; a text-only edit drops the inline keyboard
    (Telegram removes reply_markup when it isn't re-specified)."""
    if not (msg_id and CHAT_ID):
        return
    r = subprocess.run(["openclaw", "message", "edit", "--channel", "telegram",
                        "--target", CHAT_ID, *_thread_args(), "--message-id", str(msg_id),
                        "--message", note],
                       capture_output=True, text=True)
    _oplog("EDIT-BTNS", msg_id, note, r)

_RICH_CACHE = {"t": 0.0, "v": None}

def rich_enabled():
    """True when OpenClaw converts our markdown into Telegram rich blocks.

    This flips a core assumption of this file. Our fence/PNG table fallbacks exist
    ONLY because plain Telegram renders a table in a proportional font, so columns
    never line up and a phone wraps them into mush. With richMessages=true a
    markdown table becomes a native RichBlockTable -- but only if it reaches
    OpenClaw INTACT. Pre-mangling it here (fencing it, or replacing it with a PNG)
    hides the table from the converter, and we would keep shipping screenshots of
    something Telegram can now draw properly.

    Re-read on a short TTL so toggling the flag doesn't need a watcher restart --
    the watcher is long-lived and would otherwise hold the startup value forever.
    """
    now = time.time()
    if _RICH_CACHE["v"] is None or now - _RICH_CACHE["t"] > 30:
        try:
            path = os.environ.get("RELAY_CFG", os.path.expanduser("~/.openclaw/openclaw.json"))
            cfg = json.load(open(path))
            v = cfg.get("channels", {}).get("telegram", {}).get("richMessages") is True
        except Exception:
            v = False        # unreadable config -> assume plain; never lose a reply
        _RICH_CACHE.update(t=now, v=v)
    return _RICH_CACHE["v"]

def text_limit():
    """Per-message cap for TEXT. Captions are NOT rich (OpenClaw keeps them HTML,
    1024) so tg_send_media deliberately keeps using TG_LIMIT."""
    return TG_RICH_LIMIT if rich_enabled() else TG_LIMIT

def tg_send(text, silent=False):
    """Send a plain text message to the bound chat/topic. Returns the message id.

    `silent=True` (Telegram --silent) delivers without a push notification --
    used for the live progress message so the user is pinged only once, by the
    final answer."""
    cmd = ["openclaw", "message", "send", "--channel", "telegram",
           "--target", CHAT_ID, *_thread_args(),
           "--message", text[:text_limit()], "--json"]
    if silent:
        cmd.append("--silent")
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        mid = str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        m = re.search(r"Message ID:\s*(\d+)", r.stdout or "")
        mid = m.group(1) if m else ""
    _oplog("SEND" + ("-SILENT" if silent else ""), mid, text, r)
    return mid

def tg_send_media(path, caption="", document=True):
    """Send a local image/file as media. document=True (--force-document) keeps full
    resolution -- used for TUI screenshots where small terminal text must stay legible
    (a compressed Telegram photo blurs it). document=False sends an INLINE photo that
    renders in the chat and pinch-zooms -- used for rendered tables, whose larger font
    survives compression. Returns the message id."""
    cmd = ["openclaw", "message", "send", "--channel", "telegram",
           "--target", CHAT_ID, *_thread_args(), "--media", path, "--json"]
    if document:
        cmd.insert(-1, "--force-document")
    if caption:
        cmd += ["--message", caption[:TG_LIMIT]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        mid = str(json.loads(r.stdout).get("payload", {}).get("messageId", ""))
    except Exception:
        mid = ""
    _oplog("SENDMEDIA", mid, path, r)
    return mid

def tg_delete(msg_id):
    """Best-effort delete of a message (the live progress bubble)."""
    if not (msg_id and CHAT_ID):
        return
    r = subprocess.run(["openclaw", "message", "delete", "--channel", "telegram",
                        "--target", CHAT_ID, "--message-id", str(msg_id)],
                       capture_output=True, text=True)
    _oplog("DELETE", msg_id, "", r)

def tg_edit(msg_id, text):
    if not (msg_id and CHAT_ID):
        return
    r = subprocess.run(["openclaw", "message", "edit", "--channel", "telegram",
                        "--target", CHAT_ID, *_thread_args(), "--message-id", str(msg_id),
                        "--message", text[:text_limit()]],
                       capture_output=True, text=True)
    _oplog("EDIT", msg_id, text, r)

EDIT_SERVER = os.path.join(os.path.dirname(STATE_DIR), "relay-ws-edit-server.mjs")

class _WS:
    """Fast Telegram transport over the gateway websocket (one persistent Node
    helper, ~0.5s edits vs the ~2.8s CLI cold-start), so the live progress
    message can hold a real ~1s cadence. Falls back gracefully: if it can't
    connect, .ok is False and the caller uses the normal return path."""
    def __init__(self, target, thread):
        self.ok = False
        self._n = 0
        self._q = queue.Queue()
        try:
            self.proc = subprocess.Popen(
                ["node", EDIT_SERVER, str(target), str(thread or "")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        except Exception:
            self.proc = None
            return
        # Drain the helper's stdout on a thread so every read below can be bounded
        # by a deadline. readline() on a pipe has no timeout of its own, so the
        # `while time.time() < end` guards further down are decorative against the
        # case that actually happens: the helper starts but never answers, because
        # the gateway was mid-restart when it tried to connect. A direct readline
        # then parks the WATCHER forever -- not just the bubble -- and the topic
        # goes silent while its session keeps answering into the pane. Measured
        # 2026-08-24 on topic 53: wedged here 10h35m on 0.05s of CPU, replies
        # piling up on screen, nothing reaching Telegram.
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        self.ok = self._ready()
        if not self.ok:
            self._kill()        # an unusable helper is a leak; the caller falls back

    def _drain(self):
        try:
            for line in self.proc.stdout:
                self._q.put(line)
        except Exception:
            pass
        finally:
            self._q.put(None)   # EOF sentinel, so a reader never waits on a dead pipe

    def _line(self, end):
        """Next line from the helper, or None on EOF/timeout. Never waits past
        `end` -- that bound is the entire point of this indirection."""
        try:
            return self._q.get(timeout=max(0.0, end - time.time()))
        except queue.Empty:
            return None

    def _kill(self):
        try:
            self.proc.kill()
        except Exception:
            pass

    def _ready(self, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            line = self._line(end)
            if not line:
                return False
            try:
                m = json.loads(line)
            except Exception:
                continue
            if m.get("ready"):
                return True
            if m.get("error"):
                return False
        return False

    def send(self, text, silent=False):
        if not self.ok:
            return ""
        self._n += 1; rid = f"s{self._n}"
        try:
            self.proc.stdin.write(json.dumps({"op": "send", "text": text[:text_limit()],
                                              "silent": silent, "reqid": rid}) + "\n")
            self.proc.stdin.flush()
            end = time.time() + 8
            while time.time() < end:
                line = self._line(end)
                if not line:
                    break
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m.get("reqid") == rid:
                    return m.get("messageId") or ""
        except Exception:
            pass
        return ""

    def edit(self, mid, text):
        if not (self.ok and mid):
            return
        try:
            self.proc.stdin.write(json.dumps({"op": "edit", "mid": str(mid),
                                              "text": text[:text_limit()]}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def delete(self, mid):
        if not (self.ok and mid):
            return
        try:
            self.proc.stdin.write(json.dumps({"op": "delete", "mid": str(mid)}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def close(self):
        # The server DRAINS in-flight edits before exiting, so waiting for the process
        # to die makes this a real ordering barrier: every bubble edit has landed before
        # we return, and the final answer (sent right after) can never be overtaken by a
        # late edit. Timeout must exceed the server's 2s drain cap.
        try:
            self.proc.stdin.write(json.dumps({"op": "quit"}) + "\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=3)
        except Exception:
            try: self.proc.kill()
            except Exception: pass

def progress_snapshot(p, started, prompt=""):
    """Build a live 'thought process' view from the TUI pane while a turn runs:
    the spinner/status line plus the tail of the streaming output, chrome
    stripped, capped to Telegram's limit.

    `prompt` is the user's current message: when it's still visible in the pane
    (short turns) we trim everything up to and including its echoed line, so the
    stream never replays the user's own prompt or prior-turn text back at them.
    No-op once the prompt has scrolled off the top (long turns)."""
    lines = p.splitlines()
    needle = (prompt.strip().splitlines() or [""])[0][:60]
    if needle:
        cut = -1
        for i, l in enumerate(lines):
            if needle in l and not l.lstrip().startswith("⏺"):
                cut = i
        if cut >= 0:
            lines = lines[cut + 1:]
    # The footer chrome ("⏵⏵ bypass permissions… esc to interrupt", "? for
    # shortcuts") also matches the busy markers, so exclude it explicitly and
    # take the real spinner/token line ("✻ Cooked for 1m3s · ↓ 4.2k tokens").
    NOISE = re.compile(r"bypass permissions|shift\+tab|to cycle|for shortcuts|for agents", re.I)
    BORDER = re.compile(r"^[─▔━_│╭╮╰╯├┤┬┴┼┌┐└┘═╞╪╡╔╗╚╝║▕▏▎>·✻✶✢✽✳✺*\s]+$")
    # Claude's file/diff display rows are prefixed with a line number ("219 +  code",
    # "232  // ctx", bare "231"). In a progress bubble these are a wall of reflowed
    # code — collapse any run of them into a single ⋯ marker.
    LINENO = re.compile(r"^\d+(\s|$)")
    raw_status = ""
    for l in lines:
        if NOISE.search(l):
            continue
        if re.search(r"tokens|esc to interrupt|esc to cancel", l, re.I):
            raw_status = l.strip()
    # tidy the status: drop leading spinner glyph and the trailing "· esc to …"
    status = re.sub(r"^[✻✶✢✽✳✺·\s]+", "", raw_status)
    status = re.sub(r"\s*·?\s*esc to (interrupt|cancel).*$", "", status, flags=re.I).strip()
    body = []
    for l in lines:
        s = l.strip()
        if not s or BUSY.search(s) or READY.search(s) or NOISE.search(s) or s == raw_status:
            continue
        if re.search(r"tokens|esc to interrupt", s, re.I):
            continue
        if BORDER.match(s):                  # pure box-drawing / separator rows
            continue
        if LINENO.match(s):                  # code/diff dump row → collapse the run
            if body and body[-1] == "⋯":
                continue
            body.append("⋯")
            continue
        body.append(s)
    elapsed = int(time.time() - started)
    head = f"⏳ {status}" if status else f"⏳ working… ({elapsed}s)"
    tail = "\n".join(body[-30:])
    # Neutralise backticks: without the code-block wrapper an unbalanced one
    # (mid-render code) would swallow the rest into an inline code span.
    out = f"{head}\n\n{tail}".strip().replace("`", "'")
    return (out[: text_limit() - 1] or "✶ thinking…")

def raw_view(p, started):
    """Live progress = the REAL terminal: the last ~4000 chars of the actual TUI
    pane (chrome and all, 'the way it shows up in the terminal'), backticks
    neutralised, wrapped in a code block so it fits in one Telegram message."""
    s = p.rstrip().replace("`", "'")
    if not s.strip():
        return f"⏳ working… ({int(time.time()-started)}s)"
    s = s[-LIVE_WINDOW:]
    nl = s.find("\n")          # start on a clean line (drop a partial first line)
    if 0 <= nl < 200:
        s = s[nl + 1:]
    return "```\n" + s + "\n```"

def _slog(tag, mid, text, raw=None):
    """Append exactly what we push to Telegram (plus the raw TUI pane), so the
    rendered frames can be reviewed later and progress_snapshot() tuned against
    what the user actually saw. Off unless relay-work/DEBUG exists. Best-effort;
    never breaks the relay."""
    if not DEBUG:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STREAM_LOG, "a") as f:
            f.write(f"\n===== {time.strftime('%H:%M:%S')} {tag} mid={mid} len={len(text)} =====\n{text}\n")
            if raw is not None:
                f.write(f"----- raw pane -----\n{raw}\n----- end raw -----\n")
    except Exception:
        pass

class _Stream:
    """The live PROGRESS message: one silent Telegram message edited ~every 1s
    over the fast WS transport, showing the real terminal while the turn runs."""
    def __init__(self, prompt="", ws=None):
        self.started = time.time()
        self.last = 0.0
        self.id = None
        self.sent = None
        self.prompt = prompt
        self.ws = ws
        try:
            self.id = ws.send("✶ thinking…", silent=True) if ws else None
        except Exception:
            self.id = None

    def update_text(self, text):
        """Live bubble fed with the ANSWER ITSELF rather than a scraped pane.

        The API path has no terminal, but opencode's message grows while the turn
        runs (measured: 1761 chars readable at t+23s with status still busy), so the
        bubble can show the real reply forming instead of terminal chrome. Trimmed
        from the END: the interesting part of a partial answer is what just arrived.
        """
        # Render even with NO text yet. opencode emits nothing for the first ~20s of
        # a turn (tool calls, reasoning), so bailing on an empty body left the bubble
        # frozen at "thinking…" for the whole turn and then closed it -- which reads
        # as "the live bubble doesn't work". A ticking elapsed counter is the signal
        # that something is happening; the answer replaces it as soon as text exists.
        body = (text or "").strip()
        head = f"⏳ working… ({int(time.time() - self.started)}s)"
        snap = f"{head}\n\n{body[-LIVE_WINDOW:]}" if body else head
        if snap == self.sent:
            return
        self.sent = snap
        if self.ws and self.id:
            self.ws.edit(self.id, snap)

    def update(self, p):
        if not (self.id and self.ws):
            return
        now = time.time()
        # Flat 5s cadence: well under Telegram's per-message edit flood limit, so
        # the progress stream never goes stale (sustained 1s editing trips it).
        if now - self.last < 5.0:
            return
        snap = raw_view(p, self.started)  # real terminal, code-block, whole ~4000 chars
        if snap == self.sent:
            return
        self.last = now
        self.sent = snap
        try:
            self.ws.edit(self.id, snap)
        except Exception:
            pass

def tmux(*args, capture=False):
    cmd = ["tmux", *args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True).stdout
    subprocess.run(cmd, check=False)

def pane(scroll=0):
    # -J joins wrapped lines so long replies aren't chopped mid-sentence.
    args = ["capture-pane", "-t", SESSION, "-p", "-J"]
    if scroll:
        args += ["-S", f"-{scroll}"]
    return tmux(*args, capture=True)

def pane_color(scroll=0):
    # -ep keeps ANSI escapes: kimi renders THINKING grey/italic and the ANSWER
    # bright, so the reply parser needs color to drop reasoning from the answer.
    args = ["capture-pane", "-t", SESSION, "-ep", "-J"]
    if scroll:
        args += ["-S", f"-{scroll}"]
    return tmux(*args, capture=True)

# --- backend selection -------------------------------------------------------
# The relay drives `claude` by default. An ALT model can instead run a DIFFERENT
# CLI (currently `kimi` = Kimi Code, `cc model ik3`), whose TUI chrome differs in
# every anchor. restart_with_model() records the live backend per-session here so
# the long-lived watcher + per-message inject parse the right way (re-read each
# poll, since `cc model` can switch a running session mid-life).
BACKEND_FILE = os.path.join(STATE_DIR, f"backend-{SESSION}.json")

def _backend():
    try:
        return json.load(open(BACKEND_FILE))
    except Exception:
        return {"backend": "claude"}

def backend_name():
    return _backend().get("backend") or "claude"

def is_kimi():
    return backend_name() == "kimi"

def is_opencode():
    return backend_name() == "opencode"

def is_opencode_api():
    """opencode driven over its HTTP API instead of its TUI.

    Same agent, different transport. The TUI path has to parse a "▣ <agent> ·"
    footer, clip every line at the sidebar, skip "+ Thought:" headers, survive
    stderr writing over the screen, and live inside a 50-line pane with no
    scrollback -- and none of that is opencode misbehaving, it is the cost of
    reading a UI. The API reports turn state and returns whole messages."""
    return backend_name() == "opencode-api"

def is_codex():
    """codex driven headlessly via `codex exec`, with no terminal at all.

    Same reasoning as opencode-api, taken further: codex has a real
    non-interactive mode, so there is no pane to scrape and no TUI to keep
    alive. A turn is a detached process; `thread_id` is the durable per-folder
    conversation and the -o file is the finished answer."""
    return backend_name() == "codex"

_CODEX = None

def cx():
    """Lazy-load the codex helper so a broken/absent module can never stop the
    claude path from working (same contract as oc_api())."""
    global _CODEX
    if _CODEX is None:
        import importlib.util
        path = os.path.join(os.path.dirname(STATE_DIR), "relay-codex.py")
        spec = importlib.util.spec_from_file_location("relay_codex", path)
        _CODEX = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CODEX)
    return _CODEX

_OC_API = None

def oc_api():
    """Load the API helper lazily so a broken/absent module can never stop the
    claude path from working."""
    global _OC_API
    if _OC_API is None:
        import importlib.util
        path = os.path.join(os.path.dirname(STATE_DIR), "relay-opencode-api.py")
        spec = importlib.util.spec_from_file_location("relay_oc_api", path)
        _OC_API = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_OC_API)
    return _OC_API

# kimi TUI markers (empirically characterised, not guessed):
#   thinking bullet ● rendered grey+italic  -> ESC[38;2;136;136;136 (drop)
#   answer  bullet ●/• rendered bright        -> ESC[38;2;224;224;224 (keep)
#   user prompt echo prefixed ✨
#   busy = a moon-phase / braille spinner is animating on a "· Tip:" line
#   idle input bar carries the "context: N% (a/b)" gauge in the footer
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
KIMI_THINK_GREY = "38;2;136;136;136"
KIMI_MARK = "●"
KIMI_PROMPT_MARK = "✨"
KIMI_SPIN = re.compile(r"working\.\.\.|·\s*Tip:"
                       r"|[\U0001F311-\U0001F318]"            # 🌑..🌘 moon spinner
                       r"|[⠇⠋⠙⠸⠴⠦⠧⠏⡇]")  # braille spinner
KIMI_GAUGE = re.compile(r"context:\s*[\d.]+%\s*\(")

def _strip_ansi(s):
    return _ANSI.sub("", s)

def kimi_reply_lines(color_pane, prompt):
    """Extract kimi's ANSWER from a COLORED (-ep) pane, dropping grey-italic
    thinking. Start just after the echoed user prompt (✨ + needle); stop at the
    input box or the status footer. Proven against captured real panes."""
    lines = color_pane.splitlines()
    needle = (prompt.strip().splitlines() or [""])[0][:50]
    start = 0
    for i, ln in enumerate(lines):
        plain = _strip_ansi(ln)
        if KIMI_PROMPT_MARK in plain and (not needle or needle in plain):
            start = i + 1
    out = []
    for ln in lines[start:]:
        plain = _strip_ansi(ln).rstrip()
        s = plain.strip()
        if not s:
            continue
        if s.startswith("│ >") or s.startswith("> ") or s == "│ >":
            break
        if re.search(r"yolo\s+\S+\s+thinking:|context:\s*[\d.]+%", plain):
            break
        if KIMI_SPIN.search(plain):
            continue
        if re.search(r"ctrl\+o to expand|\(\d+ more lines?", plain):  # collapse hint
            continue
        if re.match(r"^[─-╿\s>│]+$", s):     # box-drawing / separators
            continue
        if KIMI_THINK_GREY in ln:                       # grey-italic reasoning
            continue
        s = s.lstrip("●• ").rstrip()          # strip ● / • bullets
        if s:
            out.append(s)
    return out

# "Working" states. "esc to interrupt" covers a normal turn, but a session that has
# fanned out sub-agents/workflows sits at "Waiting for N background agents to finish"
# with NO "esc to interrupt" and the normal input bar showing. Treating that as IDLE
# was a real silent-failure source: the watcher never set was_busy, so its idle-delivery
# opencode TUI markers, characterised from a real turn (2026-08-21, Ox Alpha Free):
#   ┃ gutter   carries the ECHOED USER PROMPT and the input box -- never the answer
#   + Thought: Nms   collapsed reasoning header (orange); no body while collapsed
#   <answer>         plain, indented, NO gutter glyph
#   ▣  Build · <model> · N.Ns   end-of-turn footer
# Unlike kimi, the split is STRUCTURAL, so the plain pane is enough -- the answer and
# the footer share a foreground colour (238;238;238), so a colour rule would have
# swallowed the footer.
# End-of-turn footer. The agent name varies (Build / General / any subagent), so
# match the marker and the separator only.
#
# NOT keyed on the trailing duration ("· 4.2s"), though that would otherwise
# distinguish a running subagent from a finished turn: _oc_content_width() clips
# each line at the sidebar boundary, and on a wide pane that clip lands BEFORE the
# duration. A completed turn then looks identical to a running one, so keying on it
# made finished turns undeliverable. See the subagent limitation in the README.
OC_TURN_END = re.compile(r"▣\s+\S+\s+·")
OC_THOUGHT = re.compile(r"^\s*[+-]\s*Thought:")

def _oc_content_width(lines):
    """Column where opencode's right-hand panel starts.

    The TUI paints a sidebar (Context / tokens / cost / LSP) on the right of the
    SAME text rows as the answer, so a naive line read returns "2+2 equals 4.
    ... $0.00 spent". Derive the boundary from the TUI itself rather than guessing
    a column: the input box's bottom border (╹▀▀▀...) spans exactly the content
    width. Falls back to the full line if that border isn't on screen."""
    for ln in lines:
        cols = [j for j, ch in enumerate(ln) if ch in "╹▀"]
        if len(cols) > 20:
            return max(cols) + 1
    return None

def opencode_reply_lines(plain_pane, prompt):
    """Extract opencode's ANSWER: the lines between the reasoning header and the
    end-of-turn footer. Anchored on the LAST footer so a pane holding several turns
    yields the newest one."""
    lines = plain_pane.splitlines()
    width = _oc_content_width(lines)
    if width:
        lines = [ln[:width] for ln in lines]
    end = None
    for i, ln in enumerate(lines):
        if OC_TURN_END.search(ln):
            end = i
    if end is None:
        return []
    # Walk back to the ECHOED PROMPT (the ┃ gutter), not to "+ Thought:".
    # With tool use opencode interleaves text, "→ tool" lines and thinking headers,
    # and the header often lands immediately before the footer -- anchoring on it
    # collapsed the range to nothing, so a healthy session delivered silence for the
    # rest of its life. The prompt is the only reliable start-of-turn marker.
    start = 0
    for j in range(end - 1, -1, -1):
        if lines[j].lstrip().startswith("┃"):
            start = j + 1
            break
    out = []
    for ln in lines[start:end]:
        t = ln.strip()
        if not t or t.startswith("┃"):
            continue
        if OC_THOUGHT.match(ln):            # "+ Thought: 19.2s"
            continue
        if t.startswith(("→", "$", "⎿")):   # tool invocation / shell echo / output
            continue
        out.append(t)
    return out

# path never fired and replies went undelivered (the session answered into the void),
# and slash commands got no busy feedback. Both states mean "a turn is in flight".
class _BackendRe:
    """A backend-aware matcher exposing .search(): the claude pattern ALWAYS applies;
    the kimi pattern applies ONLY in a kimi session. So a claude reply that happens to
    contain a kimi glyph (a moon emoji, a braille spinner, a 'context: N% (' string --
    all of which I might legitimately type in an answer) can NEVER be misread as busy /
    idle. For a claude session this is byte-identical to the original bare regex."""
    def __init__(self, claude_re, kimi_re, opencode_re=None):
        self._c, self._k, self._o = claude_re, kimi_re, opencode_re
    def search(self, s):
        hit = self._c.search(s)
        if hit:
            return hit
        alt = {"kimi": self._k, "opencode": self._o}.get(backend_name())
        return alt.search(s) if alt else None

BUSY_TAIL_LINES = 8   # footer + input box borders + the spinner line above it

class _TailRe(_BackendRe):
    """Like _BackendRe, but matches ONLY in the pane's live status region.

    A busy marker is chrome, not content -- except some of it is also printed INTO
    the transcript. "esc to interrupt" lives in the footer and vanishes the moment
    a turn ends, so scanning the whole pane was harmless for it. "Waiting for N
    background agents to finish" does not: it is emitted as transcript text and
    stays on screen as history long after the agent finished. Any pane still
    showing that line therefore read as permanently busy, and every `cc model` /
    slash command in that topic was refused with "Session is busy" against an idle
    session -- until the line happened to scroll off.

    Seen in the website topic 2026-08-05: the match was on line 13 of 50, four
    lines above "Agent 'Fable horizontal diagram build' finished", while the last
    five lines showed an empty input box. Measured against a genuinely busy pane,
    the live marker sits in the FOOTER (line 50 of 50), so the status region is a
    few lines deep and everything above it is history.

    Same fix protects the kimi spinner, whose glyphs can equally appear in an answer.
    """
    def search(self, s):
        tail = (s or "").rstrip().splitlines()[-BUSY_TAIL_LINES:]
        return super().search("\n".join(tail))

# claude "working" states unchanged; kimi busy = its moon/braille spinner animating.
BUSY = _TailRe(
    re.compile(r"esc to interrupt"
               r"|waiting for \d+ [a-z ]*(?:agents?|workflows?) to finish", re.I),
    re.compile(r"[\U0001F311-\U0001F318]|[⠇⠋⠙⠸⠴⠦⠧⠏⡇]"),  # moon / braille
    re.compile(r"esc interrupt"))                          # opencode
READY = _BackendRe(
    re.compile(r"for agents|for shortcuts"),
    re.compile(r"context:\s*[\d.]+%\s*\("),              # kimi idle/footer gauge
    # Either form of opencode's input bar: the hint text, OR the context gauge that
    # replaces it in agent modes ("General (3 of 3) 80.7K (8%)"). Matching only the
    # hint made a healthy session in General mode read as not-ready.
    re.compile(r"ctrl\+p commands|[\d.]+K \(\d+%\)"))       # opencode input bar
SURVEY = re.compile(r"How is Claude doing")         # periodic satisfaction popup
# The permission/hint footer is present whenever the normal input prompt is up
# (idle OR mid-turn). A full-screen overlay (/workflows, /config, a stray dialog)
# REPLACES that footer -- so its absence, on a stable non-menu pane, means a modal
# is blocking ALL keyboard input and a relay-bound topic is wedged behind it.
INPUTBAR = _BackendRe(
    re.compile(r"shift\+tab|bypass permissions|accept edits|plan mode|"
               r"for agents|for shortcuts|for commands", re.I),
    re.compile(r"context:\s*[\d.]+%\s*\("),           # kimi input-bar gauge
    re.compile(r"ctrl\+p commands|[\d.]+K \(\d+%\)"))    # opencode input bar

# --- menu detection ----------------------------------------------------------
OPT = re.compile(r'^\s*(❯)?\s*(\d+)\.\s+(.*\S)\s*$')
MENU_CURSOR = re.compile(r'^\s*❯\s*\d+\.\s')
MENU_FOOTER = re.compile(r"Esc to cancel|Enter to |to adjust|↑/↓|to select|use this session", re.I)

def parse_menu(text):
    """Return {'question','options':[...],'cursor':idx} ONLY for a REAL selection
    menu: a ❯ cursor in a cleanly-numbered (1..n) block of options, FOLLOWED by an
    interactive menu footer ("Enter to select / ↑↓ to navigate / Esc to cancel").

    The footer is what distinguishes a real picker from a prose numbered list, so
    requiring it lets us tolerate the description/separator/blank lines that
    AskUserQuestion interleaves BETWEEN options (a simple permission menu has none;
    AskUserQuestion puts a help line under every option). A prose "1. do X / 2. do
    Y" in an answer has no ❯ cursor AND no footer, so it is NEVER turned into
    buttons."""
    lines = text.splitlines()
    cur = next((i for i, l in enumerate(lines) if MENU_CURSOR.match(l)), None)
    if cur is None:
        return None
    # An interactive footer must appear at/below the cursor -> this is a picker.
    foot = next((i for i in range(cur, len(lines)) if MENU_FOOTER.search(lines[i])), None)
    if foot is None:
        return None
    # Walk up from the cursor (over interleaved description lines) to the "1." that
    # starts this option block; stop at a separator/prose boundary.
    top = None
    for i in range(cur, -1, -1):
        m = OPT.match(lines[i])
        if m and int(m.group(2)) == 1:
            top = i; break
        if re.match(r'^[─▔━_]{4,}\s*$', lines[i].strip()) or lines[i].strip().startswith('⏺'):
            break
    if top is None:
        return None
    # Collect the sequential 1..n numbered options between `top` and the footer,
    # skipping the non-option (description/separator/blank) lines between them.
    opts, cursor = [], 0
    for l in lines[top:foot]:
        m = OPT.match(l)
        if not m:
            continue
        if int(m.group(2)) != len(opts) + 1:    # numbering jumped -> end of menu
            break
        label = re.split(r'\s{2,}|·', m.group(3).strip())[0].strip()
        opts.append(label)
        if m.group(1):
            cursor = len(opts) - 1
    # Drop AskUserQuestion's trailing meta-affordances ("Type something…",
    # "Chat about this") -- they make no sense as tap targets. Keep them only if
    # removing them would leave fewer than 2 real choices.
    META = re.compile(r'^(type something|chat about this)', re.I)
    real = [o for o in opts if not META.match(o)]
    if len(real) >= 2:
        opts = real
        cursor = min(cursor, len(opts) - 1)
    if len(opts) < 2:
        return None
    # question = the non-empty lines just above the option block
    q, j = [], top - 1
    while j >= 0 and len(q) < 3:
        s = lines[j].strip()
        if not s:
            if q:
                break
            j -= 1; continue
        if re.match(r'^[─▔━_]{4,}$', s) or s.startswith('⏺'):
            break
        q.insert(0, s); j -= 1
    return {"question": " ".join(q).strip(), "options": opts, "cursor": cursor}

def format_menu(menu):
    lines = []
    if menu["question"]:
        lines.append(f"🔀 {menu['question']}")
    else:
        lines.append("🔀 Claude needs you to choose:")
    lines.append("")
    for i, o in enumerate(menu["options"], 1):
        lines.append(f"{i}. {o}")
    lines.append("")
    lines.append("Reply with the option number.")
    return "\n".join(lines)

def save_menu(menu, btn_msg_id=""):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"options": menu["options"], "btn_msg_id": btn_msg_id}, open(STATE, "w"))

def load_menu():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}

def clear_menu():
    try: os.remove(STATE)
    except FileNotFoundError: pass

def menu_open():
    return os.path.exists(STATE)

# --- waiting -----------------------------------------------------------------
def dismiss_interrupts():
    if SURVEY.search(pane()):
        tmux("send-keys", "-t", SESSION, "0")
        time.sleep(0.6)

def wait_settled(timeout=180, stable_needed=2, poll=0.6, on_progress=None):
    """Wait until the TUI settles. Returns ('menu', pane) | ('idle', pane).

    A menu is returned the INSTANT it's detected (with one quick re-check to skip
    mid-render frames) -- we do NOT wait for pane stability, because Claude's
    question menus have a blinking cursor so the pane never hashes the same twice
    (that was making menus time out and fall through to 'idle'). Only the idle
    state needs stability.
    """
    last, stable = None, 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        dismiss_interrupts()
        p = pane()
        if BUSY.search(p):
            last, stable = None, 0
            if on_progress:
                try:
                    on_progress(p)
                except Exception:
                    pass
            continue
        if parse_menu(p):
            time.sleep(0.3)
            if parse_menu(pane()):     # confirm it's a real, settled menu
                return "menu", pane()
            continue
        if READY.search(p):
            h = hashlib.md5(p.encode()).hexdigest()
            if h == last:
                stable += 1
                if stable >= stable_needed:
                    return "idle", p
            else:
                stable, last = 0, h
        else:
            last, stable = None, 0
    return "idle", pane()

# --- reply extraction --------------------------------------------------------
CHROME = re.compile(
    r"^\s*$|Claude Code v|Tips for getting started|Welcome back|What's new"
    r"|Auto mode is now|Plugins in|Added .claude|/release-notes|Claude Fable"
    r"|Opus 4.8 is here|Ask Claude to create|^[│╭╰─┌┐└┘▐▝▘▛▜█ ]+$|/effort"
    r"|^\s*[╭╰╮╯┃┏┓┗┛].*"                      # banner/panel rows (rounded/heavy corners)
    # Banner BODY only: a line whose ONLY bars are the two edges ("│ Welcome back │").
    # `│` used to be in the class above, which silently ate every DATA ROW of every
    # box-drawing table -- the border rows (├─┼─┤) start with different glyphs and
    # survived, so a scraped table arrived as a fence full of nothing but borders.
    # A real table row has >=3 bars (two edges + at least one divider), a banner has 2.
    r"|^\s*│[^│]*│\s*$"
    r"|~/.openclaw/workspace"                    # Claude Code session header path line
    r"|● high|● medium|● low|· /effort"          # status/footer bits
    r"|tmux detected|scroll with PgUp|set -g (mouse|focus)|focus-events"  # tmux hints
    r"|\? for shortcuts|Try \"|esc to interrupt|Worked for")

def _reply_lines(prompt):
    if is_kimi():
        return kimi_reply_lines(pane_color(scroll=4000), prompt)
    if is_opencode():
        return opencode_reply_lines(pane(scroll=4000), prompt)
    full = pane(scroll=4000).splitlines()
    box = len(full)
    for i in range(len(full) - 1, -1, -1):
        if full[i].lstrip().startswith("❯"):
            box = i; break
    region = full[:box]
    needle = (prompt.strip().splitlines() or [""])[0][:60]
    midx = -1
    for i, ln in enumerate(region):
        if needle and needle in ln and not ln.lstrip().startswith("⏺"):
            midx = i
    start = None
    if midx >= 0:
        for k in range(midx + 1, len(region)):
            if "⏺" in region[k]:
                start = k; break
        if start is None:
            start = midx + 1
    if start is None:
        for k in range(len(region)):
            if "⏺" in region[k]:
                start = k
        if start is None:
            start = 0
    footer = re.compile(r"/effort|\? for shortcuts|esc to interrupt|accept edits|^\s*─{8,}\s*$")
    out = []
    for ln in region[start:]:
        s = ln.rstrip()
        if out and (footer.search(s) or s.lstrip().startswith("❯")):
            break
        if CHROME.search(s) or "✻" in s:
            continue
        s = s.replace("⏺", "").strip()
        if s:
            out.append(s)
    return out

def extract_reply(prompt):
    return reflow(_reply_lines(prompt)).strip()

def extract_stream(prompt):
    # Non-reflowed: capture-pane -J already gives logical (unwrapped) lines, so
    # the joined text grows append-monotonically as Claude types -- only the last
    # line is volatile. That makes clean forward deltas reliable. Reflow is saved
    # for the authoritative final result.
    return "\n".join(_reply_lines(prompt)).strip()

def reflow(lines):
    try:
        width = int(tmux("display-message", "-p", "-t", SESSION, "#{pane_width}", capture=True).strip())
    except Exception:
        width = 200
    thr = max(60, width - 12)
    bullet = re.compile(r"^\s*([-*•‣◦]|\d+[.)]|```|#{1,6}\s)")
    merged = []
    for ln in lines:
        if (merged and len(merged[-1]) >= thr
                and merged[-1].rstrip()[-1:] not in ".!?:;"
                and ln and not bullet.match(ln)):
            merged[-1] = merged[-1].rstrip() + " " + ln.lstrip()
        else:
            merged.append(ln)
    return "\n".join(merged)

# --- queued-message control -------------------------------------------------
# Claude Code queues input typed while the model is ACTIVELY GENERATING (not while
# a tool/background shell runs -- then it just answers immediately, nothing queues).
# In that state the pane shows this hint, and Up pulls every queued message into the
# input box AND REMOVES IT FROM THE QUEUE (verified: after Up + clear, the messages
# never ran when the turn ended).
QUEUED_HINT = re.compile(r"Press up to edit queued messages", re.I)
_BORDER_LINE = re.compile(r"^\s*[─━]{20,}\s*$")

def input_box_text():
    """Text currently sitting in the TUI input box (the region between the last two
    box-border rules), with the prompt glyph stripped. Multi-line safe."""
    lines = pane().splitlines()
    borders = [i for i, l in enumerate(lines) if _BORDER_LINE.match(l)]
    if len(borders) < 2:
        return ""
    top, bottom = borders[-2], borders[-1]
    out = []
    for l in lines[top + 1:bottom]:
        out.append(re.sub(r"^\s*❯\s?", "", l).rstrip())
    return "\n".join(out).strip()

def clear_input_box():
    """Empty the input box WITHOUT pressing Escape -- Escape would interrupt a running
    turn, and unqueueing only ever happens mid-turn. C-u/C-k don't clear a multi-line
    buffer (verified: they leave the first line behind), so delete by backspace, sized
    to the actual content."""
    txt = input_box_text()
    n = min(len(txt) + 20, 4000)
    for _ in range(n):
        tmux("send-keys", "-t", SESSION, "BSpace")
    time.sleep(0.5)
    return txt

def unqueue_pending():
    """`cc unq` -- drop messages queued behind the running turn, so they never run.

    Telegram never tells a bot that a message was deleted (the Bot API has no
    deleted-message update for regular chats -- only Business accounts), so this is
    the supported way to take back something you queued."""
    if not QUEUED_HINT.search(pane()):
        deliver("📭 Nothing queued — there are no messages waiting behind this turn. "
                "(Input only queues while the model is actively generating.)")
        return
    tmux("send-keys", "-t", SESSION, "Up")      # pull queue into the input box
    time.sleep(0.8)
    dropped = clear_input_box()
    time.sleep(0.4)
    p = pane()
    still_queued = bool(QUEUED_HINT.search(p))
    leftover = input_box_text()
    if still_queued or leftover:
        deliver(f"⚠️ Tried to drop the queue but it isn't clean "
                f"(queued={'yes' if still_queued else 'no'}, "
                f"input={'not empty' if leftover else 'empty'}). Check the session.")
        return
    if dropped:
        items = [l.strip() for l in dropped.splitlines() if l.strip()]
        shown = "\n".join(f"• {l}" for l in items)
        deliver(f"🗑 Dropped {len(items)} queued message(s) — they will not run:\n{shown}")
    else:
        deliver("🗑 Queue cleared.")

def count_marker():
    mark = {"kimi": KIMI_MARK, "opencode": "▣"}.get(backend_name(), "⏺")
    return pane(scroll=4000).count(mark)

# --- actions -----------------------------------------------------------------
def send(prompt):
    dismiss_interrupts()
    state, _ = wait_settled(timeout=30)
    if state == "menu":
        # A stray menu is open (e.g. left over). Dismiss it so the command/prompt
        # we're about to type doesn't get typed INTO the menu's filter.
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)
        clear_menu()
    tmux("set-option", "-t", SESSION, "history-limit", "100000")
    tmux("clear-history", "-t", SESSION)
    tmux("send-keys", "-t", SESSION, "C-u")
    time.sleep(0.2)
    tmux("send-keys", "-t", SESSION, "-l", prompt)
    time.sleep(0.4)
    tmux("send-keys", "-t", SESSION, "Enter")
    for _ in range(6):
        time.sleep(0.5)
        if BUSY.search(pane()):
            break
    # TWO messages, kept separate, over the fast WS transport (~1s):
    #  - a live PROGRESS message mirroring the real terminal (last ~4000 chars);
    #  - a separate FINAL message with the clean answer, sent once at the end.
    ws = None
    if STREAM and CHAT_ID:
        w = _WS(CHAT_ID, THREAD_ID)
        if w.ok:
            ws = w
        else:
            w.close()
    stream = _Stream(prompt, ws) if ws else None
    state, p = wait_settled(on_progress=(stream.update if stream else None))
    if state == "menu":
        if ws: ws.close()
        return present_menu(parse_menu(p))   # native buttons for a real menu
    clear_menu()
    if stream and stream.id:
        try: ws.edit(stream.id, raw_view(p, stream.started))   # final terminal frame
        except Exception: pass
    reply = extract_reply(prompt) or "(done)"
    if ws:
        if stream and stream.id and len(reply) <= text_limit():
            ws.send(reply)      # the answer, as its OWN message (this one notifies)
            ws.close()
            return ""
        ws.close()              # too long -> fall through to OpenClaw's send
    return reply

def present_menu(menu):
    """Show a menu to the user: native Telegram buttons if we know the chat id,
    else a numbered text list. Persists menu state either way. Returns the text
    OpenClaw should send ('' when buttons were sent out-of-band)."""
    if CHAT_ID:
        mid = tg_buttons(menu["question"], menu["options"])
        save_menu(menu, btn_msg_id=mid)
        return ""   # buttons delivered out-of-band; suppress the text bubble
    save_menu(menu)
    return format_menu(menu)

def select(n):
    """Resolve a menu pick RACE-FREE: dismiss the TUI menu and answer Claude in
    plain text with the chosen option's label.

    Injecting arrow/number keystrokes into the live menu is unreliable (timing
    races -> wrong option / the default gets picked). But Claude asked the
    question, so it accepts the answer as words. We Escape the menu and send the
    label as a normal message, which is plain text delivery and never races.
    """
    saved = load_menu()
    state, p = wait_settled(timeout=12)
    menu = parse_menu(p)
    opts = menu["options"] if menu else saved.get("options", [])
    if not opts or n < 1 or n > len(opts):
        clear_menu()
        return ("⚠️ Couldn't read that menu — send your request again, or use "
                "`claude-attach` to answer in the live session.")
    label = opts[n - 1]
    btn_msg_id = saved.get("btn_msg_id", "")
    # Dismiss the TUI menu so the next message isn't typed into it, then answer.
    if menu:
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
    clear_menu()
    tg_remove_buttons(btn_msg_id, f"✓ {label}")
    return send(label)

def parse_selection(prompt):
    """A button tap arrives as 'callback_data: ccsel:N'; a typed reply as 'N'."""
    m = re.search(r'ccsel:(\d+)', prompt)
    if m:
        return int(m.group(1))
    s = prompt.strip().rstrip(".)")
    return int(s) if s.isdigit() else None

# --- persistent watcher model (RELAY_WATCH / relay-work/WATCH) ----------------
# Instead of watching the TUI only during the message that triggered a turn, one
# long-lived watcher per session tails the pane and delivers EVERY new assistant
# turn -- including turns that finish after a long wait and any output that shows
# up outside the request/response window. The per-message call then only INJECTS
# (types the prompt / resolves a menu tap) and returns "" so OpenClaw sends
# nothing; the watcher owns all delivery. This removes the old gap where a slow
# "I'll report back" reply was missed because nothing was watching anymore.

def _bound_peer_for_session():
    """(chat, thread) this session is BOUND to, straight from OpenClaw's config."""
    try:
        folder = folder_for_session()
        if not folder:
            return None
        cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
        agents = {a.get("id"): a for a in cfg.get("agents", {}).get("list", []) if a.get("id")}
        real = os.path.realpath(folder)
        for b in cfg.get("bindings", []):
            ws = (agents.get(b.get("agentId")) or {}).get("workspace")
            if ws and os.path.realpath(ws) == real:
                pid = b.get("match", {}).get("peer", {}).get("id", "")
                chat, _, th = pid.partition(":topic:")
                return chat, th
    except Exception:
        pass
    return None

def save_target(chat, thread):
    """Persist where the watcher should deliver (it has no inbound message).

    Guarded against writing someone else's chat. RELAY_CHAT_ID/RELAY_THREAD_ID come
    from the environment, so any process that inherits a DIFFERENT session's env and
    calls this -- a script run by hand from inside another bound session, which is
    exactly how it happened twice -- silently repoints this session's replies at that
    chat. The bound peer in openclaw.json is the authority; when the two disagree,
    keep the binding and drop the env value."""
    if not chat:
        return
    bound = _bound_peer_for_session()
    if bound and (str(chat), str(thread or "")) != (str(bound[0]), str(bound[1] or "")):
        _oplog("TARGET-REFUSED", "", f"env={chat}:{thread} bound={bound[0]}:{bound[1]}")
        chat, thread = bound[0], bound[1]
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        json.dump({"chat": chat, "thread": thread}, open(TARGET, "w"))
    except Exception:
        pass

def dedup_key(text):
    """Hash a reply for delivery dedup, normalizing whitespace first so a trivial
    pane re-render (different wrapping / trailing spaces) doesn't read as a new
    reply and get sent again."""
    return hashlib.md5(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()

def read_turndone():
    """(mtime, final_message) from the Stop-hook marker, or (None, None). The
    marker is written by relay-turn-done when Claude finishes a turn, giving the
    watcher a deterministic 'done' event + the exact reply text -- no pane scrape."""
    try:
        mt = os.path.getmtime(TURNDONE)
        msg = (json.load(open(TURNDONE)) or {}).get("message", "")
        return mt, msg
    except Exception:
        return None, None

def load_delivered():
    """Last reply hash we delivered, persisted so a RESTARTED watcher (gateway
    bounce, crash, manual relaunch) doesn't re-emit the reply already on screen."""
    try:
        return (open(DELIVERED).read().strip() or None)
    except Exception:
        return None

def save_delivered(h):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        open(DELIVERED, "w").write(h or "")
    except Exception:
        pass

def refresh_target():
    """Point CHAT_ID/THREAD_ID at the persisted per-session target."""
    global CHAT_ID, THREAD_ID
    try:
        t = json.load(open(TARGET))
        CHAT_ID = str(t.get("chat") or "")
        THREAD_ID = str(t.get("thread") or "")
    except Exception:
        pass

def write_last_prompt(p):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        open(LASTPROMPT, "w").write(p or "")
    except Exception:
        pass

def read_last_prompt():
    try:
        return open(LASTPROMPT).read()
    except Exception:
        return ""

def session_alive():
    return SESSION in tmux("list-sessions", "-F", "#{session_name}", capture=True)

def type_prompt(prompt):
    """Type a prompt into the TUI and submit it. No watching, no delivery.

    First Esc-peel any full-screen overlay (/workflows, /config, a stray
    dialog/menu): with no input bar on screen the typed text lands inside the
    overlay and wedges the whole topic. Esc one layer per pass until the input
    bar -- or a running turn -- is back, then type."""
    for _ in range(4):
        p = pane()
        if INPUTBAR.search(p) or BUSY.search(p):
            break
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
    tmux("set-option", "-t", SESSION, "history-limit", "100000")
    tmux("send-keys", "-t", SESSION, "C-u"); time.sleep(0.2)
    tmux("send-keys", "-t", SESSION, "-l", prompt); time.sleep(0.4)
    tmux("send-keys", "-t", SESSION, "Enter")
    # Confirm the Enter actually submitted. At a busy->idle render transition the
    # submit can be swallowed, leaving the text sitting on the "❯" input line
    # unsent (the whole topic then looks dead). If our prompt is still on the input
    # line after a beat -- and no turn is running -- re-send Enter once. Guarded by
    # `not BUSY` so an intentionally-queued slash command (typed behind a running
    # turn) is NOT force-submitted into that turn.
    snip = prompt.strip()[:12]
    for _ in range(3):
        time.sleep(0.4)
        p = pane()
        if not (snip and re.search(r"❯\s+.*" + re.escape(snip), p)):
            break  # input line cleared -> it submitted
        if BUSY.search(p):
            break  # a turn is running (queued on purpose) -> leave it
        tmux("send-keys", "-t", SESSION, "Enter")

# Table blocks (box-drawing OR markdown pipe tables) rely on a monospace font to keep
# columns aligned, but Telegram renders normal message text in a PROPORTIONAL font, so
# an ASCII/box table sent as plain text misaligns. Telegram only uses a fixed-width font
# INSIDE a ``` code block (OpenClaw renders our markdown -> Telegram HTML <pre>), so we
# wrap detected table blocks in a fence before sending. (This is also why the live
# progress bubble already looks right -- raw_view wraps the whole pane in ```.)
_BOXCH = "─━│┃┌┐└┘├┤┬┴┼╭╮╯╰═║╔╗╚╝╠╣╦╩╬▏▕▎▍▌▋▊▉█▔▁▂▃▄▅▆▇"
_BOXRE = re.compile("[" + re.escape(_BOXCH) + "]")
_FENCE = re.compile(r"^\s*```")
_MDSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_MDROW = re.compile(r"^\s*\|.*\|\s*$")

def _pad_md_table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    ncol = max(len(r) for r in cells)
    for r in cells:
        r += [""] * (ncol - len(r))
    sep = lambda c: bool(re.fullmatch(r":?-{2,}:?", c.strip()))
    widths = [0] * ncol
    for r in cells:
        if all(sep(c) or c == "" for c in r):
            continue
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    out = []
    for r in cells:
        if all(sep(c) or c == "" for c in r):
            out.append("|-" + "-|-".join("-" * w for w in widths) + "-|")
        else:
            out.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) + " |")
    return out

def _table_segments(text):
    """Split text into ('text', str) and ('table', [lines]) segments in order,
    fence-aware. A box-drawing run (>=2 lines) or a markdown pipe table is a 'table';
    everything else (incl. content inside an existing ``` fence) is 'text'."""
    lines = text.split("\n")
    segs, buf, i, in_fence = [], [], 0, False
    def flush():
        if buf:
            segs.append(("text", "\n".join(buf))); buf.clear()
    while i < len(lines):
        ln = lines[i]
        if _FENCE.match(ln):
            in_fence = not in_fence; buf.append(ln); i += 1; continue
        if in_fence:
            buf.append(ln); i += 1; continue
        if _BOXRE.search(ln):
            j = i
            while j < len(lines) and _BOXRE.search(lines[j]):
                j += 1
            if j - i >= 2:
                flush(); segs.append(("table", lines[i:j]))
            else:
                buf.extend(lines[i:j])
            i = j; continue
        if _MDROW.match(ln) and i + 1 < len(lines) and _MDSEP.match(lines[i + 1]):
            j = i
            while j < len(lines) and _MDROW.match(lines[j]):
                j += 1
            flush(); segs.append(("table", _pad_md_table(lines[i:j])))
            i = j; continue
        buf.append(ln); i += 1
    flush()
    return segs

def _box_to_md(lines):
    """Convert a box-drawing table (┌─┬─┐ │ a │ b │ └─┴─┘) into markdown rows.

    OpenClaw's converter only understands MARKDOWN. A box table is plain text to it,
    so passing one through in rich mode drops it into Telegram's proportional font
    and the columns collapse -- worse than the fence it used to get. Claude Code
    draws box tables constantly (they are what the TUI renders), so this is the
    common case, not an edge case.

    Returns markdown lines, or None if this doesn't look like a real grid -- the
    caller then falls back to fencing, which at least keeps it monospace."""
    rows = []
    for ln in lines:
        if "│" not in ln and "|" not in ln:
            continue                       # pure border row (├─┼─┤ / └─┴─┘)
        cells = [c.strip() for c in re.split(r"[│|]", ln)]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        # a separator drawn with │ at the edges, e.g. "│───│───│"
        if not cells or all(re.fullmatch(r"[─\-\s]*", c) for c in cells):
            continue
        rows.append([c.replace("|", "\\|") for c in cells])
    if len(rows) < 2:
        return None                        # a header with no body isn't worth converting
    width = max(len(r) for r in rows)
    if width < 2:
        return None
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return out

def render_reply(text):
    """Prepare a reply for delivery.

    Rich mode (richMessages on): a MARKDOWN table goes through untouched -- OpenClaw
    turns it into a native RichBlockTable, and fencing it would only hide it from the
    converter. A BOX-DRAWING table is converted to markdown first, because the
    converter reads markdown and nothing else: passed through as-is it would land in
    Telegram's proportional font with the columns collapsed. Claude Code draws box
    tables constantly, so that is the common path, not a corner.

    Flag off (or a box table we can't parse): fence it, which at least keeps it
    monospace. That is a degraded fallback, not a fix -- a wide one still wraps on a
    narrow screen. Prose, stray `|` and already-fenced content are untouched either way."""
    rich = rich_enabled()
    body = []
    for kind, payload in _table_segments(text):
        if kind == "text":
            body.append(payload)
            continue
        md = None
        if rich:
            md = payload if _MDROW.match(payload[0]) else _box_to_md(payload)
        body.append("\n".join(md) if md
                    else "```\n" + "\n".join(payload) + "\n```")
    return "\n".join(body).strip()

def _fence_safe_chunks(text, limit):
    """Split into <=limit pieces on line boundaries, keeping ``` fences balanced
    within each piece (a fence split across chunks would render as broken markup)."""
    chunks, cur, cur_len, open_fence = [], [], 0, False
    def flush():
        nonlocal cur, cur_len
        if not cur:
            return
        body = "\n".join(cur)
        if open_fence:
            body += "\n```"
        chunks.append(body)
        cur, cur_len = ([], 0)
    for line in text.split("\n"):
        add = len(line) + 1
        # while a fence is open, reserve 4 chars for the "\n```" we append on flush
        budget = limit - (4 if open_fence else 0)
        # long single line: hard-slice it (rare; e.g. a 4k-char no-newline blob)
        if add > limit:
            flush()
            for k in range(0, len(line), limit):
                chunks.append(line[k:k + limit])
            continue
        if cur_len + add > budget:
            reopen = open_fence
            flush()
            if reopen:
                cur = ["```"]; cur_len = 4; open_fence = True
        cur.append(line); cur_len += add
        if _FENCE.match(line):
            open_fence = not open_fence
    flush()
    return chunks or [text[:limit]]

def deliver(text):
    """Send a finished reply, split to fit Telegram's per-message cap.

    Returns True only if EVERY chunk got a message id back. The caller records the
    reply as delivered, and doing that after a failed send loses the message for
    good: the dedup guard then treats it as already sent and never retries. That
    happened for real -- a brew upgrade relinked ada-url, an older node could not
    load libada.3.dylib, and every `openclaw message send` failed with rc=-6 for
    ~20 minutes. The replies were generated, marked delivered, and never left."""
    if not text:
        return False
    ok = True
    for chunk in _fence_safe_chunks(render_reply(text), text_limit()):
        if not tg_send(chunk):
            ok = False
    return ok

def folder_for_session():
    """Reverse-lookup this session's bound folder from relay-codes.json
    (session name is cr-<md5(folder)[:10]>)."""
    codes_path = os.path.join(os.path.dirname(STATE_DIR), "relay-codes.json")
    try:
        codes = json.load(open(codes_path))
    except Exception:
        return None
    for f in codes.values():
        if "cr-" + hashlib.md5(f.encode()).hexdigest()[:10] == SESSION:
            return f
    return None

def settings_for_model(model):
    """Pick the --settings file for a model, and the real model id to pass.

    Convention: an ALT model routed to a non-Anthropic gateway gets its own
    `relay-claude-settings-<name>.json` next to the default one, carrying an `env`
    block (ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN) -- a settings-file `env`
    overrides shell env and, unlike a shell export, reliably reaches relay-spawned
    sessions. If that file exists we use it and take the real provider model id from
    its "model" key (e.g. `cc model kimi` -> kimi-k2-...); otherwise EVERY other model
    (opus/fable/sonnet/...) uses the default settings + subscription auth, untouched.
    Drop in a new `relay-claude-settings-<x>.json` and `cc model <x>` just works.

    Returns (settings_path, model_id_to_pass)."""
    base = os.path.dirname(STATE_DIR)
    alt = os.path.join(base, f"relay-claude-settings-{model.lower()}.json")
    if os.path.exists(alt):
        try:
            mid = json.load(open(alt)).get("model") or model
        except Exception:
            mid = model
        return alt, mid
    return os.path.join(base, "relay-claude-settings.json"), model

# Resolve the kimi binary to an ABSOLUTE path -- the gateway-spawned relay process
# gets a minimal PATH that often lacks /opt/homebrew/bin, so a bare "kimi" would
# not be found (same reason FREEZE is resolved absolutely above).
def _alt_bin(name, *fallbacks):
    return (shutil.which(name)
            or next((p for p in fallbacks if os.path.exists(p)), name))

KIMI_BIN = _alt_bin("kimi", "/opt/homebrew/bin/kimi", "/usr/local/bin/kimi")

# Registry of NATIVE alt CLIs the relay can drive in place of `claude`.
#   cmd   : launch template; {bin} and {model} are substituted
#   parser: which pane parser understands this TUI. A backend WITHOUT a parser is
#           declared but not usable -- launching one would put a foreign TUI on
#           screen that the scraper reads with claude's rules, which delivers
#           silence (exactly how ik3 broke when its markers were guessed rather
#           than characterised). backend_for_model() refuses those on purpose.
NATIVE_BACKENDS = {
    "kimi": {
        "bin": KIMI_BIN,
        "cmd": "{bin} -m {model} -c --yolo",
        "default_model": "kimi-code/k3",
        "parser": "kimi",
    },
    # opencode 1.18.15. Chrome characterised from a live pane 2026-08-21 (scratch
    # dir, unauthenticated -- enough to see every state transition except a real
    # answer):
    #   busy      "esc interrupt" + an animated block spinner (⬝⬝■■■■■■ -> ⬝⬝⬝⬝⬝⬝⬝⬝)
    #   input bar "ctrl+p commands", present in BOTH busy and idle
    #   idle      a context gauge in the footer, e.g. "13.8K (7%)"
    #   footer    "• OpenCode <version>"; input box drawn with ┃
    # Note "esc interrupt" has no "to": claude's r"esc to interrupt" does NOT match
    # it and vice versa, so the two backends' busy regexes cannot cross-fire.
    # API transport: no binary is driven in the pane at all, so there is no cmd and
    # no pane parser -- relay-opencode-api.py owns the whole conversation.
    "opencode-api": {
        "bin": _alt_bin("opencode", "/opt/homebrew/bin/opencode"),
        "cmd": "",
        "default_model": "x-preview-f-free",
        "parser": "api",
    },
    "opencode": {
        "bin": _alt_bin("opencode", "/opt/homebrew/bin/opencode"),
        "cmd": "{bin} -m {model} -c",
        "default_model": "",
        "busy": r"esc interrupt",
        "inputbar": r"ctrl\+p commands",
        "ready": r"[\d.]+K \(\d+%\)|ctrl\+p commands",
        # STILL MISSING: how an assistant reply is delimited on screen. That needs an
        # authenticated turn -- kimi's answer/thinking split turned out to be a COLOUR
        # difference invisible in plain capture, and guessing it is what made ik3
        # deliver silence. parser stays None (backend_for_model refuses) until then.
        "parser": "opencode",
    },
}

def backend_for_model(model):
    """If `cc model <model>` should run a NATIVE ALT CLI (not claude), return its
    backend config dict; else None (=claude). Convention: an ALT settings file
    `relay-claude-settings-<model>.json` with `"backend":"kimi"` declares it, e.g.
    `ik3` -> {"backend":"kimi","model":"kimi-code/k3","label":"K3"}."""
    base = os.path.dirname(STATE_DIR)
    alt = os.path.join(base, f"relay-claude-settings-{model.lower()}.json")
    try:
        cfg = json.load(open(alt))
    except Exception:
        return None
    spec = NATIVE_BACKENDS.get(cfg.get("backend"))
    if not spec:
        return None
    if not spec.get("parser"):
        # Declared but not characterised: refuse rather than launch a TUI whose
        # replies we cannot read.
        return None
    out = {"backend": cfg["backend"],
           "model": cfg.get("model") or spec["default_model"],
           "label": cfg.get("label") or model}
    if cfg.get("provider"):
        out["provider"] = cfg["provider"]
    return out

def _write_backend(cfg):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        json.dump(cfg, open(BACKEND_FILE, "w"))
    except Exception:
        pass

def restart_with_model(model):
    """Switch this session's model RELIABLY by relaunching `claude` with --model
    (+ --continue to keep context). The live /model command is gated on big cached
    conversations (a 're-read full history?' confirmation) so a one-shot `cc model X`
    silently reports 'Kept' -- relaunching bypasses that gate entirely."""
    folder = folder_for_session()
    if not folder:
        deliver(f"⚠️ Couldn't resolve this session's folder, so can't restart on {model}.")
        return
    # A model prefixed for a native ALT CLI (e.g. `ik3` -> kimi) launches that CLI
    # instead of `claude`; the backend marker tells the watcher/inject how to parse.
    kb = backend_for_model(model)
    if kb:
        _write_backend(kb)
        # Resolve through relay-alt-launch so a chat-initiated switch and a
        # folder-pinned default build the SAME command -- including the
        # directory-scoped resume. opencode's -c continues the last session
        # GLOBALLY, so a shared template here would resume another project's
        # conversation in that project's directory.
        spec = NATIVE_BACKENDS[kb["backend"]]
        cmd = ""
        try:
            r = subprocess.run(
                [sys.executable,
                 os.path.join(os.path.dirname(STATE_DIR), "relay-alt-launch"),
                 model, folder],
                capture_output=True, text=True, timeout=15)
            if "\t" in (r.stdout or ""):
                cmd = r.stdout.split("\t", 1)[1].strip()
        except Exception:
            cmd = ""
        if not cmd:      # resolver unavailable -> template, minus any resume flag
            cmd = spec["cmd"].format(bin=spec["bin"], model=shlex.quote(kb["model"]))
        expect = kb.get("label", model)
    else:
        _write_backend({"backend": "claude"})   # reset if switching back from kimi
        settings, alt_model = settings_for_model(model)
        # QUOTE the model: a 1M-context id carries brackets (`claude-opus-5[1m]`) and
        # tmux runs this through zsh, where an unquoted bracket is a glob -- it dies
        # "no matches found" and the session never launches at all.
        cmd = (f"claude --model {shlex.quote(alt_model)} --continue "
               f"--settings {shlex.quote(settings)} --dangerously-skip-permissions")
        expect = model
    tmux("kill-session", "-t", SESSION)
    time.sleep(0.5)
    tmux("new-session", "-d", "-s", SESSION, "-x", "200", "-y", "50", "-c", folder, cmd)

    # API mode has no TUI, so there is no chrome to wait for: the pane runs
    # `opencode serve`, which prints a log line and nothing else. Readiness is the
    # HTTP API answering. Waiting for READY chrome here is what produced
    # "Relaunched on oxa, but the TUI didn't confirm ready in 45s" on a switch that
    # had in fact worked. Also PIN the choice, or the next respawn silently reverts
    # to whatever the folder's default was.
    if kb and kb.get("backend") == "opencode-api":
        try:
            open(os.path.join(STATE_DIR, f"default-model-{SESSION}.txt"), "w").write(model)
        except Exception:
            pass
        api = oc_api()
        for _ in range(60):
            time.sleep(1)
            if api._alive(api.port_for(folder)):
                deliver(f"🔄 Restarted on **{kb.get('label', model)}** "
                        f"(opencode API, port {api.port_for(folder)}).")
                return
        deliver(f"⚠️ Relaunched on `{model}`, but the opencode server didn't answer "
                f"on port {api.port_for(folder)} within 60s.")
        return

    ready = False
    for _ in range(45):
        time.sleep(1)
        p = pane()
        if "trust this folder" in p:
            tmux("send-keys", "-t", SESSION, "Enter"); time.sleep(2); continue
        if "Resume from summary" in p:                       # big-session resume dialog
            tmux("send-keys", "-t", SESSION, "Enter"); time.sleep(2); continue
        if READY.search(p):
            ready = True; break
    if not ready:
        deliver(f"🔄 Relaunched on `{model}`, but the TUI didn't confirm ready in 45s; "
                "give it a moment or check the session.")
        return
    # Verify: read the actually-active model back from the TUI (claude: the /model
    # ✔ line; kimi: the footer), so a silent mismatch (model rejected) is surfaced.
    actual = current_model()
    exp = expect.lower()
    if actual and (exp in actual.lower() or actual.lower().split()[0].startswith(exp)
                   or exp.startswith(actual.lower().split()[0])):
        deliver(f"🔄 Restarted — confirmed now on **{actual}** (context kept).")
    elif actual:
        deliver(f"⚠️ Restarted, but the active model reads **{actual}**, not `{model}` "
                "as requested. It may have been rejected — check the session.")
    else:
        deliver(f"🔄 Restarted on `{model}` (context kept), but couldn't read back the "
                "active model to confirm.")

def current_model():
    """Read the currently-selected model from the /model picker: open it, capture the
    ✔ line, Esc WITHOUT changing anything. Returns a short label ('Opus 4.8', 'Fable
    5') or '' if it couldn't be read."""
    if is_kimi():
        # kimi has no gated /model dialog; the active model is in the footer
        # ("yolo  K3 thinking: max"). Read it back directly -- real, not requested.
        for line in pane().splitlines():
            m = re.search(r"yolo\s+(\S+)\s+thinking:", line)
            if m:
                return m.group(1)
        return _backend().get("label", "")
    tmux("send-keys", "-t", SESSION, "-l", "/model"); time.sleep(0.8)
    tmux("send-keys", "-t", SESSION, "Enter"); time.sleep(1.5)
    label = ""
    for line in pane().splitlines():
        if "✔" in line:
            after = line.split("✔", 1)[1].strip()          # "Opus 4.8 with 1M context · …"
            m = re.match(r"([A-Za-z]+ [\d.]+)", after)
            label = m.group(1) if m else after.split("·")[0].strip()[:24]
            break
    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)
    return label

# Resolve freeze to an ABSOLUTE path: the per-message relay process is spawned by
# the gateway with a minimal PATH that often lacks /opt/homebrew/bin, so a bare
# "freeze" subprocess call fails (FileNotFoundError) and screenshots silently fall
# back to text. shutil.which honours PATH when it works; the explicit paths cover
# the gateway case; bare "freeze" is the last-resort default for other installs.
FREEZE = (shutil.which("freeze")
          or next((p for p in ("/opt/homebrew/bin/freeze", "/usr/local/bin/freeze",
                               os.path.expanduser("~/bin/freeze")) if os.path.exists(p)),
                  "freeze"))

def screenshot_png():
    """Render the current TUI pane (ANSI colors and all) to a PNG via `freeze`.
    Returns the output path, or None if capture/render failed. This is how the
    relay surfaces what text can't -- full-screen overlays, colors, layout."""
    png = os.path.join(STATE_DIR, f"shot-{SESSION}.png")
    why = ""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        raw = tmux("capture-pane", "-ep", "-t", SESSION, capture=True)
        if not raw.strip():
            why = "empty capture"
        else:
            # Pipe the ANSI via STDIN, NOT as a file argument: given a file, freeze
            # tries to guess a source language and dies "Language Unknown" under the
            # gateway's minimal env (no TERM); from stdin it renders the terminal
            # colors directly and works regardless of environment. freeze writes its
            # errors to STDOUT, not stderr -- capture both.
            r = subprocess.run([FREEZE, "-o", png], input=raw,
                               capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(png):
                return png
            msg = ((r.stdout or "") + " " + (r.stderr or "")).split()
            why = f"freeze rc={r.returncode} ({FREEZE}): {' '.join(msg)[:200]}"
    except Exception as e:
        why = f"{type(e).__name__}: {e}"
    # Record WHY a screenshot fell back -- silent None reads as "no overlay" when it
    # may be a broken renderer/PATH. Best-effort, never breaks the relay.
    try:
        with open(os.path.join(STATE_DIR, "shot-debug.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {SESSION} screenshot fail: {why}\n")
    except Exception:
        pass
    return None

def send_screenshot():
    """Capture the live TUI as an image and send it as a photo/document."""
    png = screenshot_png()
    if png:
        tg_send_media(png, "🖥 TUI screenshot")
    else:
        deliver("⚠️ Couldn't render a screenshot (freeze/capture failed).")

def overlay_screenshot(open_cmd):
    """Open a full-screen TUI overlay (e.g. /workflows, /config), image it, then
    Esc to close. Returns the PNG path (or None). Captures FAST: the watcher's
    overlay-guard Escs a non-input-bar pane after ~3 polls (~3s), so we grab the
    frame well inside that window and close it ourselves. Only opens the overlay
    when the pane is at the input bar (not mid-turn / not already in a modal)."""
    if not INPUTBAR.search(pane()):
        return None
    tmux("send-keys", "-t", SESSION, "C-u"); time.sleep(0.2)
    tmux("send-keys", "-t", SESSION, "-l", open_cmd); time.sleep(0.3)
    tmux("send-keys", "-t", SESSION, "Enter")
    time.sleep(1.4)                       # let the panel render, inside the guard window
    png = screenshot_png()
    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)  # close the overlay
    return png

def workflow_status():
    """The /workflows viewer is interactive full-screen and can't render over the
    relay (it just auto-dismisses). Scrape the live per-workflow progress from the
    pane instead -- Claude Code keeps that status line on the normal screen while a
    background workflow runs -- and return it as a text snapshot."""
    rows, seen = [], set()
    for raw in pane().splitlines():
        s = raw.strip()
        if not s or s in seen:
            continue
        # Anchor each pattern to its leading TUI glyph so prose that merely
        # mentions "N/M agents done" or "/workflows" (e.g. this very chat in the
        # scrollback) can't be mistaken for a live status row.
        if (re.match(r"^[◯◉●▸▹‣]\s+\S", s)                              # per-workflow row
                or re.match(r"^[✻✶✢✽✳✺·]\s*Waiting for \d+\b.*workflow", s, re.I)  # waiting line
                or re.match(r"^⎿\s+Running in background\b.*/workflows", s, re.I)):  # bg note
            seen.add(s); rows.append(s)
    if not rows:
        return ("📋 No workflow is running right now.\n\n"
                "(The /workflows viewer is a full-screen TUI, so it can't be shown "
                "over the relay -- this is the live status instead. Re-send "
                "/workflows to refresh.)")
    return ("📋 Workflow status -- live scrape (the /workflows viewer can't render "
            "over the relay; re-send to refresh):\n\n" + "\n".join(rows[-15:]))

def inject(prompt):
    """Per-message path under the watcher model: type the prompt (or resolve a
    menu tap) into the TUI and return '' immediately. The watcher delivers the
    result, so this never blocks on the turn."""
    save_target(CHAT_ID, THREAD_ID)
    # API-backed opencode: POST the prompt and return. There is no pane to type
    # into, and prompt_async does not block on the turn, so the contract the
    # watcher expects ("" now, delivery later) is unchanged.
    if is_opencode_api() and not prompt.strip().startswith("/"):
        folder = folder_for_session()
        cfg = _backend()
        if folder:
            write_last_prompt(prompt)
            try:
                oc_api().send(folder, prompt,
                              cfg.get("provider") or "opencode",
                              cfg.get("model") or "x-preview-f-free")
            except Exception as e:
                deliver(f"⚠️ Couldn't reach the opencode server for this folder: {e}")
            return ""
    # codex: no pane, no typing. Start the turn detached and return; the watcher
    # polls is_busy()/last_reply() and delivers. `cc cancel` maps to killing the
    # process group, which is the only interrupt codex exec has.
    if is_codex():
        folder = folder_for_session()
        if not folder:
            deliver("\u26a0\ufe0f No folder is bound to this codex session.")
            return ""
        if prompt.strip().lower() in ("/cancel", "/interrupt", "/esc"):
            ok = cx().cancel(SESSION)
            deliver("\u270b Interrupted the codex turn." if ok
                    else "Nothing was running to interrupt.")
            return ""
        if cx().is_busy(SESSION):
            deliver("\u23f3 codex is still working on the previous turn. "
                    "`cc cancel` it, or wait for it to finish.")
            return ""
        write_last_prompt(prompt)
        try:
            cx().start(folder, SESSION, prompt, (_backend().get("model") or ""))
        except Exception as e:
            deliver(f"\u26a0\ufe0f Couldn't start codex for this folder: {e}")
        return ""
    # /workflows (and /workflow) can't open their full-screen viewer over the relay
    # -> answer with a scraped text snapshot of live workflow progress instead of
    # opening (and then auto-dismissing) the overlay.
    if re.fullmatch(r"/workflows?", prompt.strip(), re.I):
        # Image the actual /workflows panel (faithful, full fidelity); fall back to
        # the scraped text status if the pane is busy or the render fails.
        png = overlay_screenshot("/workflows")
        if png:
            tg_send_media(png, "🖥 /workflows")
        else:
            deliver(workflow_status())
        return ""
    # /screenshot (/ss, /shot): image of the live TUI -- the faithful way to see
    # full-screen overlays, colors and layout that text scraping can't carry.
    if re.fullmatch(r"/(screenshot|ss|shot)", prompt.strip(), re.I):
        send_screenshot()
        return ""
    # `cc model <name>` -> switch model by RELAUNCHING with --model (live /model is
    # gated on big cached sessions and silently "Kept"). Only a safe model token is
    # accepted here; anything else falls through to type /model normally. Bare /model
    # (no arg) also falls through -> opens the picker as before.
    mm = re.fullmatch(r"/model\s+([A-Za-z0-9._\[\]-]+)", prompt.strip(), re.I)
    if mm:
        model = mm.group(1)
        if BUSY.search(pane()):
            deliver(f"⏳ Session is busy. `cc cancel` the turn (or wait), then resend "
                    f"`cc model {model}` and I'll restart it on that model.")
        else:
            restart_with_model(model)
        return ""
    # `cc cancel` (-> /cancel) means "interrupt the running turn". Claude Code has NO
    # /cancel command, so typing it no-ops; interrupting is an Esc keystroke. Send Esc
    # directly (same as the /cancel plugin's relay-cancel.py). Must be BEFORE the
    # busy-warning below, else it'd be queued instead of interrupting.
    if prompt.strip().lower() in ("/cancel", "/interrupt", "/esc"):
        tmux("send-keys", "-t", SESSION, "Escape")
        deliver("✋ Interrupted the current turn (sent Esc).")
        return ""
    # `cc unq` -> drop messages queued behind the running turn. MUST be before the
    # busy-warning below: a queue only EXISTS while a turn is running, so the busy
    # path would queue this command itself instead of executing it.
    if prompt.strip().lower() in ("/unq", "/unqueue"):
        unqueue_pending()
        return ""
    # Busy-aware feedback for forwarded slash commands (/clear, /compact, /model, ...).
    # Typed while a turn is running, a slash command does NOT execute -- Claude Code
    # just queues it -- so `cc clear` silently no-ops ("I sent /clear but context is
    # still 99%"). Queue it (so it runs when the turn ends) but tell the user, and how
    # to run it now. A menu selection is a number, not a slash, so it's unaffected.
    if prompt.strip().startswith("/") and BUSY.search(pane()):
        cmd = prompt.strip()
        write_last_prompt(cmd)
        type_prompt(cmd)   # queues behind the running turn (runs when it finishes)
        deliver(f"⏳ Session is busy — a turn is running, so `{cmd}` can't run yet; "
                f"it's queued and will execute when the turn finishes.\n"
                f"To run it now, send `cc cancel` to interrupt the turn first.")
        return ""
    if menu_open():
        n = parse_selection(prompt)
        if n is not None:
            saved = load_menu()
            opts = saved.get("options", [])
            if opts and 1 <= n <= len(opts):
                label = opts[n - 1]
                if parse_menu(pane()):
                    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
                clear_menu()
                tg_remove_buttons(saved.get("btn_msg_id", ""), f"✓ {label}")
                write_last_prompt(label)
                type_prompt(label)
                return ""
            clear_menu()
            return "⚠️ Couldn't read that menu — send your request again."
        # not a selection while a menu is open -> cancel it, treat as a new msg
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
        clear_menu()
    write_last_prompt(prompt)
    type_prompt(prompt)
    return ""

def watch():
    """Long-lived: tail the pane, stream the active turn into a silent bubble,
    and deliver each settled turn's reply exactly once (hash-dedup). Survives
    long/slow turns and out-of-band output; exits when the session dies."""
    refresh_target()
    # Seed 'delivered' from the persisted hash first (survives watcher restarts),
    # falling back to whatever reply is already on screen, so we never resend a
    # reply that predates the watcher starting.
    delivered = load_delivered()
    if delivered is None and not BUSY.search(pane()):
        r0 = extract_reply(read_last_prompt())
        delivered = dedup_key(r0) if r0 else None
    # Seed the Stop-hook marker mtime so a stale marker isn't re-delivered on
    # start. hook_active flips on once we've ever seen one (the session's Claude
    # has the Stop hook); after that the pane-scrape path is only a slow safety
    # net for the rare 'silent tool stop' the Stop hook misses.
    # API mode: seed the dedup hash from the session's current last reply, or a
    # restarted watcher would immediately re-deliver the previous answer.
    if is_opencode_api() and delivered is None:
        try:
            _f = folder_for_session()
            _r = oc_api().last_reply(_f) if _f else ""
            if _r:
                delivered = dedup_key(_r)
        except Exception:
            pass
    last_done_mt, _seed = read_turndone()
    hook_active = last_done_mt is not None
    last_done_mt = last_done_mt or 0
    stream, menu_sig, was_busy, idle_stable, overlay_stable = None, None, False, 0, 0
    api_tick, stream_last_text = 0, ""
    while True:
        time.sleep(1.0)
        # API-backed opencode has no pane: turn state comes from /session/status
        # (the id is present while the turn runs, gone when it ends) and the answer
        # from /session/{id}/message -- whole, untruncated, no chrome to strip. This
        # branch deliberately skips session_alive(), the busy/ready regexes, the
        # menu and overlay guards and the Stop-hook marker: every one of those reads
        # a terminal that does not exist here.
        # codex: paneless, like opencode-api. Poll the detached turn, keep the
        # bubble fed from the event stream, deliver the -o answer once the
        # process exits. Placed BEFORE session_alive(): there is no tmux pane to
        # be alive, and reaching that check would end the watcher immediately.
        if is_codex():
            refresh_target()
            if not CHAT_ID:
                continue
            if cx().is_busy(SESSION):
                was_busy = True
                if stream is None and STREAM:
                    w = _WS(CHAT_ID, THREAD_ID)
                    stream = _Stream(read_last_prompt(), w if w.ok else None)
                if stream:
                    try:
                        stream.update_text(cx().live_text(SESSION))
                    except Exception:
                        pass
                continue
            if not was_busy:
                continue          # idle between turns: nothing to deliver
            reply = cx().last_reply(SESSION)
            if not reply:
                # A turn that produced no answer is a FAILURE, not silence. Say
                # so with codex's own stderr -- the alternative is a topic that
                # just goes quiet, which is the single most expensive failure
                # mode this relay has had.
                why = cx().turn_failed(SESSION)
                reply = (f"\u26a0\ufe0f codex ended the turn without an answer.\n\n{why}"
                         if why else
                         "\u26a0\ufe0f codex ended the turn without an answer.")
            cx().harvest_thread(SESSION)   # first turn's thread_id reaches disk here
            h = dedup_key(reply)
            if h and h != delivered:
                if stream and stream.ws:
                    stream.ws.close()
                if deliver(reply):
                    delivered = h
                    save_delivered(h)
            stream, was_busy = None, False
            continue
        if is_opencode_api():
            refresh_target()
            if not CHAT_ID:
                continue
            folder = folder_for_session()
            if not folder:
                continue
            try:
                api = oc_api()
                # The SSE reader belongs to the WATCHER: inject() is a per-message
                # process that exits immediately, so a thread started there would die
                # before a single delta arrived. Idempotent, and it reconnects itself.
                api.start_live(folder)
                busy = api.is_busy(folder)
            except Exception:
                continue
            if busy:
                # No explicit reset here: the reader already clears its buffer when a
                # new messageID appears, which is the real turn boundary. Resetting on
                # the first busy poll instead would race it and wipe deltas that had
                # already arrived.
                was_busy = True
                if stream is None and STREAM:
                    w = _WS(CHAT_ID, THREAD_ID)
                    stream = _Stream(read_last_prompt(), w if w.ok else None)
                if stream:
                    # Live text comes from the SSE stream, not from polling messages.
                    # Polling cannot work: on a measured 56s turn the message parts
                    # stayed [] for 52s and then appeared complete, so a poll-driven
                    # bubble could only ever show a counter. /event streams
                    # message.part.delta while the answer is generated.
                    try:
                        stream.update_text(oc_api().live_text(folder))
                    except Exception:
                        pass
                continue
            # Deliberately NOT gated on a busy->idle transition. A short turn can
            # finish inside one poll interval, so the busy window is never observed
            # and the answer would be dropped for good (measured: a 2s turn was
            # missed entirely). The API hands us the newest assistant message
            # directly, so compare it to what we already sent -- the dedup hash is
            # the real guard, and it is exact rather than a timing guess.
            was_busy = False
            try:
                reply = oc_api().last_reply(folder)
            except Exception:
                reply = ""
            h = dedup_key(reply) if reply else None
            if h and h != delivered:
                # Freeze the progress bubble BEFORE sending, so the final answer can
                # never be overtaken by a late edit landing under it.
                if stream and stream.ws:
                    stream.ws.close()
                stream = None
                if deliver(reply):
                    delivered = h
                    save_delivered(h)
            elif stream and stream.ws:
                stream.ws.close()
                stream = None
            continue
        if not session_alive():
            return
        refresh_target()
        if not CHAT_ID:
            continue
        dismiss_interrupts()
        # Deterministic delivery: the Stop hook wrote a fresh marker -> the turn
        # is genuinely done and the marker holds the exact final message. Deliver
        # it (dedup-guarded) and freeze the bubble. Beats the idle heuristic and
        # carries clean text with no pane-scrape artifacts.
        mt, msg = read_turndone()
        if mt and mt != last_done_mt:
            last_done_mt, hook_active = mt, True
            h = dedup_key(msg) if msg else None
            if h and h != delivered:
                if stream and stream.ws:
                    stream.ws.close()
                if deliver(msg):
                    delivered = h
                    save_delivered(h)
            stream, was_busy, idle_stable = None, False, 0
            continue
        p = pane()
        if BUSY.search(p):
            was_busy, idle_stable, menu_sig, overlay_stable = True, 0, None, 0
            if stream is None and STREAM:
                # Build the fast WS transport so the live bubble actually draws
                # (without a ws, _Stream.update is a no-op). Mirrors the sync path.
                w = _WS(CHAT_ID, THREAD_ID)
                stream = _Stream(read_last_prompt(), w if w.ok else None)
            if stream:
                stream.update(p)
            continue
        menu = parse_menu(p)
        if menu:
            sig = "|".join(menu["options"])
            if sig != menu_sig:
                # Freeze the progress bubble in place (don't delete it) and just
                # stop updating it; the question/menu posts as a new message below.
                if stream and stream.ws:
                    stream.ws.close()
                stream, menu_sig = None, sig
                present_menu(menu)      # buttons (notify) + save menu state
            was_busy, idle_stable, overlay_stable = False, 0, 0
            continue
        menu_sig = None
        # Wedge guard: a stable pane that's neither busy, nor a parseable menu, nor
        # showing the input bar = a full-screen overlay (/workflows, /config, a
        # dialog we can't button) blocking ALL input. Esc to peel one layer; the
        # next poll re-evaluates, so a menu hidden underneath then renders and gets
        # buttoned, and stacked overlays peel one layer per cycle. A MENU_FOOTER
        # means a picker is mid-render -> let parse_menu retry, don't Esc it away.
        if not INPUTBAR.search(p) and not MENU_FOOTER.search(p):
            overlay_stable += 1
            if overlay_stable >= 3:
                tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4)
                overlay_stable = 0
            continue
        overlay_stable = 0
        # Idle: only deliver once the turn has ACTUALLY run (was_busy) and the
        # pane has stayed idle for several polls. Without the was_busy gate the
        # watcher delivers in the dead windows where no reply is being produced --
        # right after a prompt is injected but before Claude responds (it grabs
        # the echoed envelope, or re-grabs the PREVIOUS reply) -- and a too-short
        # idle count delivers a brief between-tool-steps frame as if it were the
        # final answer. Both were seen as spurious extra messages.
        idle_stable += 1
        if stream:
            stream.update(p)
        # When the Stop hook is active it delivers above; here we only act as a
        # slow safety net (long idle) for the rare silent-stop it misses, so we
        # never race the marker. Without the hook, the normal short threshold.
        thresh = 12 if hook_active else 4
        if not (was_busy and idle_stable >= thresh):
            continue
        reply = extract_reply(read_last_prompt())
        h = dedup_key(reply) if reply else None
        if h and h != delivered:
            # Leave the progress bubble in the chat as a frozen record of the
            # turn; deliver the clean answer as a separate, new message below it.
            # The next turn opens a fresh bubble.
            if deliver(reply):
                delivered = h
                save_delivered(h)
        if stream and stream.ws:
            stream.ws.close()
        stream, was_busy = None, False

# --- native-streaming model (RELAY_JSONL / relay-work/JSONL) ------------------
# Emit Claude `stream-json` JSONL on stdout instead of sending to Telegram
# ourselves. OpenClaw parses the deltas and renders the live edits with its own
# fast (~1s, in-process) draft-stream loop, and uses our final `result` line as
# the authoritative reply. This retires the slow 2.8s-per-edit CLI path for the
# live stream. Requires the cliBackend configured output:jsonl + jsonlDialect.

def emit(obj):
    """Write one JSONL record to stdout and flush so OpenClaw streams it live."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def emit_delta(text):
    if text:
        emit({"type": "stream_event", "event": {"type": "content_block_delta",
              "delta": {"type": "text_delta", "text": text}}})

def emit_result(text):
    emit({"type": "result", "result": text})

def _jlog(msg):
    """Opt-in (relay-work/DEBUG) trace of what the JSONL stream emitted, so the
    delta cadence can be inspected against what the user actually saw."""
    if not DEBUG:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, f"jsonl-{SESSION}.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass

def send_jsonl(prompt):
    """Type the prompt, show one working indicator, then emit the final reply as
    a stream-json `result`. OpenClaw delivers it natively (no 2.8s CLI edit). We
    don't token-stream: a redrawing TUI can't map onto append-only deltas."""
    dismiss_interrupts()
    state, _ = wait_settled(timeout=30)
    if state == "menu":
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.4); clear_menu()
    type_prompt(prompt)
    for _ in range(6):
        time.sleep(0.5)
        if BUSY.search(pane()):
            break
    # We do NOT live-stream the reply text: Claude Code's TUI redraws
    # non-monotonically (tool/thinking blocks appear and collapse), but
    # stream-json deltas are append-only -- so scraped snapshots either repeat
    # (lenient) or never advance (strict). Instead we show one lightweight
    # working indicator and let OpenClaw render the authoritative `result` the
    # instant the turn settles: fast and clean, just not token-by-token.
    emit_delta("✶ working…")
    state, p = wait_settled()
    if state == "menu":
        menu = parse_menu(p); save_menu(menu)
        emit_result(format_menu(menu))      # text menu (native buttons TBD)
        _jlog("result=MENU")
        return
    clear_menu()
    final = extract_reply(prompt) or "(done)"
    emit_result(final)
    _jlog(f"result len={len(final)}")

def jsonl_main(prompt):
    if menu_open():
        n = parse_selection(prompt)
        if n is not None:
            saved = load_menu(); opts = saved.get("options", [])
            if opts and 1 <= n <= len(opts):
                label = opts[n - 1]
                if parse_menu(pane()):
                    tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
                clear_menu()
                send_jsonl(label); return
            clear_menu()
            emit_result("⚠️ Couldn't read that menu — send your request again.")
            return
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5); clear_menu()
    send_jsonl(prompt)

def main():
    args = [a for a in sys.argv[1:] if a != "--watch"]
    if "--watch" in sys.argv[1:]:
        watch(); return
    prompt = " ".join(args)
    if JSONL:
        jsonl_main(prompt); return
    if WATCH:
        print(inject(prompt)); return
    # Legacy synchronous path (default until the watcher is enabled).
    if menu_open():
        n = parse_selection(prompt)
        if n is not None:
            print(select(n)); return
        # not a selection while a menu is open -> cancel it, send as new message
        tmux("send-keys", "-t", SESSION, "Escape"); time.sleep(0.5)
        clear_menu()
    print(send(prompt))

if __name__ == "__main__":
    main()
