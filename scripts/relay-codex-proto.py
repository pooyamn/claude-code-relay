#!/usr/bin/env python3
"""Codex over the app-server protocol: a live connection per topic.

Replaces the one-shot `codex exec` path. Three things only this shape can do,
each of them a defect in the exec backend rather than a nice-to-have:

1. VISIBILITY. `codex exec` threads are stamped source="exec", and thread/list
   -- which is exactly what the ChatGPT app renders -- filters those out. A
   thread created or forked over the protocol gets source="vscode" and appears.
   Measured 2026-09-05: thread/list returned precisely the 6 threads the app
   showed, and not one was source="exec"; DUT's real thread was readable by
   thread/read the whole time yet absent from the list.

2. STEERING. A message arriving mid-turn used to be REFUSED ("codex is still
   working on the previous turn"), which is both useless to the user and the
   reason the live bubble looked dead: the refusal posts a new message under the
   bubble while the bubble itself keeps being edited above it. turn/steer feeds
   the text into the running turn instead, which is what the user meant.

3. INTERRUPT. Cancel was SIGINT/SIGTERM/SIGKILL to a process group -- the turn
   died with no record. turn/interrupt ends it cleanly inside the thread.

Connection ownership: the WATCHER holds it. A thread only exists inside the
connection that started or resumed it (a second process asking for it gets
"thread not found"), and the per-message inject() process exits as soon as it
has queued the prompt -- so inject can only ever append to a queue file, and the
watcher drains it. That split is forced by the protocol, not a design taste.
"""
import json
import os
import subprocess
import threading
import time

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_ws import UnixWS, DAEMON_SOCK  # noqa: E402

D = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(D, "relay-work")
CODEX = os.environ.get("RELAY_CODEX_BIN", "/opt/homebrew/bin/codex")


def _p(key, name, ext):
    return os.path.join(STATE, f"codex-{name}-{key}{ext}")


def thread_path(key):  return _p(key, "thread", ".txt")
def queue_path(key):   return _p(key, "queue", ".jsonl")
def log_path(key):     return _p(key, "proto", ".log")


def enqueue(key, text=None, cmd=None):
    """Called from the per-message process. Append; the watcher decides whether
    this becomes a new turn, a steer, or an interrupt -- it is the only one
    holding the connection, so it is the only one that can decide."""
    os.makedirs(STATE, exist_ok=True)
    with open(queue_path(key), "a") as f:
        f.write(json.dumps({"text": text, "cmd": cmd, "ts": time.time()}) + "\n")


def peek(key):
    """Read the queue WITHOUT consuming it."""
    try:
        with open(queue_path(key)) as f:
            lines = f.read().splitlines()
    except Exception:
        return []
    out = []
    for l in lines:
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("cmd") or d.get("text"):
            out.append(d)
    return out


def drop(key, n):
    """Discard the first n queued entries, keeping anything that arrived since.

    Deliberately split from peek(): draining first and sending afterwards LOSES
    the message whenever the send cannot happen -- which is exactly the case
    that matters, a thread whose writer lock is held by the ChatGPT app while it
    works. A queued message must survive until it has actually been handed over."""
    p = queue_path(key)
    try:
        with open(p) as f:
            lines = f.read().splitlines()
    except Exception:
        return
    rest = lines[n:]
    try:
        if rest:
            with open(p, "w") as f:
                f.write("\n".join(rest) + "\n")
        else:
            os.remove(p)
    except Exception:
        pass


def drain(key):
    """Take everything queued, atomically enough for one reader."""
    p = queue_path(key)
    try:
        with open(p) as f:
            lines = f.read().splitlines()
        os.remove(p)
    except Exception:
        return []
    out = []
    for l in lines:
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("cmd") or d.get("text"):
            out.append(d)
    return out


def read_thread(key):
    try:
        return open(thread_path(key)).read().strip()
    except Exception:
        return ""


def save_thread(key, tid):
    try:
        os.makedirs(STATE, exist_ok=True)
        open(thread_path(key), "w").write(tid)
    except Exception:
        pass


# The protocol spells item types in camelCase ("agentMessage",
# "commandExecution"), while `codex exec --json` uses snake_case
# ("agent_message", "command_execution"). Same events, different wire format --
# reusing the exec spellings here silently matched nothing, so the bubble stayed
# empty and the final answer never landed. Accept both.
_ITEM_LABEL = {
    "commandExecution": "running a command", "command_execution": "running a command",
    "fileChange": "editing files",           "file_change": "editing files",
    "mcpToolCall": "calling a tool",         "mcp_tool_call": "calling a tool",
    "webSearch": "searching the web",        "web_search": "searching the web",
    "reasoning": "thinking",
    "todoList": "planning",                  "todo_list": "planning",
}
_AGENT_MSG = ("agentMessage", "agent_message")


class Conn:
    """One app-server connection and one open thread.

    The connection goes to the remote-control DAEMON whenever it is up, so the
    relay and the ChatGPT app are two clients of ONE server sharing one writer.
    Spawning a private `codex app-server` instead made the relay a second writer
    process: whichever side opened the thread first took the lock and the other
    was refused -- the app showed "Another Codex session is using this task"
    for the length of every relayed turn (2026-09-29, topic 427), and the relay
    was blocked whenever the app merely had the thread open. Measured over the
    daemon: two clients both thread/resume the same thread, one runs a turn,
    the other streams it live, and the lock stays with the daemon throughout.

    A private stdio app-server is used only when the daemon socket is not
    reachable -- then no app session exists to conflict with."""

    def __init__(self, key, folder, cfg=None):
        self.key, self.folder, self.cfg = key, folder, (cfg or {})
        self.proc = None
        self.ws = None             # set when attached through the daemon
        self.tid = ""
        self.turn_id = ""
        self.busy = False
        self.steps = []
        self.message = ""          # newest completed agent message
        self.delta = ""            # partial text streaming in right now
        self.final = ""            # set when the turn completes
        self.error = ""
        self._cancelled_turn = ""
        self._id = 0
        self._replies = {}
        self._lock = threading.Lock()

    # --- plumbing ---------------------------------------------------------
    def _log(self, msg):
        try:
            with open(log_path(self.key), "a") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def _send(self, method, params, want_id=True):
        with self._lock:
            self._id += 1
            i = self._id
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if want_id:
            msg["id"] = i
        try:
            if self.ws is not None:
                self.ws.write(json.dumps(msg))
            else:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
        except Exception as e:
            self._log(f"send failed {method}: {e}")
            return None
        return i

    def _wait(self, rid, secs=60):
        end = time.time() + secs
        while time.time() < end:
            with self._lock:
                if rid in self._replies:
                    return self._replies.pop(rid)
            time.sleep(0.05)
        return None

    def _reader(self):
        for line in (self.ws if self.ws is not None else self.proc.stdout):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if "id" in d and ("result" in d or "error" in d):
                with self._lock:
                    self._replies[d["id"]] = d
                continue
            self._on_notify(d)

    def _on_notify(self, d):
        m, p = d.get("method"), (d.get("params") or {})
        if m == "turn/started":
            # turn/started carries the id under params.turn.id, not params.turnId.
            self.turn_id = (p.get("turn") or {}).get("id") or p.get("turnId") or ""
            self.busy = True
            self.delta = ""
        elif m == "turn/completed":
            if p.get("turnId") == self._cancelled_turn or \
               (p.get("turn") or {}).get("id") == self._cancelled_turn:
                self.message = self.delta = ""      # cancelled: deliver nothing
            else:
                self.final = self.message or self.delta
            self.busy = False
        elif m == "turn/failed":
            self.error = json.dumps(p)[:300]
            self.busy = False
        elif m == "item/agentMessage/delta":
            # Token-level streaming. This is what makes the bubble genuinely
            # live: the exec backend only ever saw whole completed items, so the
            # bubble sat still for the length of a step and read as dead.
            self.delta += p.get("delta") or ""
        elif m in ("item/started", "item/completed",
                   "thread/realtime/item/started", "thread/realtime/item/completed"):
            it = p.get("item") or {}
            k = it.get("type")
            if k in _AGENT_MSG:
                txt = (it.get("text") or "").strip()
                if not txt:
                    # completed items carry the text in content[] on this wire
                    txt = "".join(c.get("text") or "" for c in (it.get("content") or [])
                                  if isinstance(c, dict)).strip()
                if txt:
                    self.message, self.delta = txt, ""
            elif k in _ITEM_LABEL and m.endswith("completed"):
                self.steps.append(_ITEM_LABEL[k])
        elif m == "error":
            self.error = json.dumps(p)[:300]

    # --- lifecycle --------------------------------------------------------
    def alive(self):
        if self.ws is not None:
            return not self.ws.closed
        return self.proc is not None and self.proc.poll() is None

    def open(self):
        """Connect (daemon first), initialize, and attach to this folder's thread."""
        if self.alive():
            return True
        self.ws = self.proc = None
        try:
            self.ws = UnixWS(DAEMON_SOCK)
        except Exception as e:
            self._log(f"daemon unreachable ({e}); using a private app-server")
            self.ws = None
        if self.ws is None:
            try:
                self.proc = subprocess.Popen(
                    [CODEX, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, bufsize=1)
            except Exception as e:
                self._log(f"spawn failed: {e}")
                return False
        threading.Thread(target=self._reader, daemon=True).start()
        rid = self._send("initialize", {"clientInfo": {
            "name": "claude-code-relay", "version": "0.1", "title": "relay"}})
        if not self._wait(rid, 30):
            self._log("initialize timed out")
            self.close()
            return False
        if self._attach():
            return True
        # A FAILED open must not leave its app-server running. The caller drops
        # the Conn reference on failure, so nothing else can ever reap it, and a
        # watcher retrying a lock-blocked thread every 5s spawned one process per
        # attempt: ~50 orphaned `codex app-server` processes accumulated in half
        # an hour before this was noticed.
        self.close()
        return False

    def _policy(self):
        # Same allow-everything posture as the exec path. NOTE the spelling
        # differs per method: fork/resume take the sandbox as a plain enum
        # ("danger-full-access"), and passing the object form there is rejected
        # outright ("unknown variant `type`").
        return {"approvalPolicy": "never",
                "sandbox": self.cfg.get("sandbox", "danger-full-access")}

    def _attach(self):
        tid = read_thread(self.key)
        if tid:
            # A lock from a previous connection can outlive the process that
            # held it, so a single failed resume is not proof the thread is
            # unusable. Starting a fresh thread here costs the topic its whole
            # history, which is far worse than waiting -- so retry before ever
            # falling through.
            for attempt in range(6):
                rid = self._send("thread/resume", dict(
                    threadId=tid, cwd=self.folder, **self._policy()))
                r = self._wait(rid, 60)
                if r and "result" in r:
                    self.tid = tid
                    return True
                why = json.dumps(r)[:200] if r else "timeout"
                if "active writer" not in why:
                    self._log(f"resume failed for {tid}: {why}")
                    break
                # Give a real handover a chance first: if the app is mid-turn the
                # lock is doing its job and waiting is correct. From the third
                # attempt on, an IDLE thread whose lock is held by the daemon is
                # a lock that outlived its work, and waiting for the user to
                # close a thread in an app is not a recovery strategy.
                # Never on the daemon transport: there the daemon's lock IS our
                # lock, and "active writer" means a private app-server elsewhere
                # (an old-code watcher) is mid-turn -- waiting is correct.
                if self.ws is None and attempt >= 2 and self._lock_holder_is_daemon(tid) \
                        and self._thread_idle(tid):
                    if self._reclaim_lock(tid):
                        time.sleep(1)
                        continue
                self._log(f"resume blocked by a writer lock "
                          f"(attempt {attempt + 1}/6): {why}")
                time.sleep(5)
            else:
                self._log(f"resume still blocked after 6 attempts; NOT starting a "
                          f"new thread -- refusing to abandon {tid}")
                return False
        rid = self._send("thread/start", dict(cwd=self.folder, **self._policy()))
        r = self._wait(rid, 60)
        if not (r and "result" in r):
            self._log(f"thread/start failed: {json.dumps(r)[:200] if r else 'timeout'}")
            return False
        self.tid = r["result"]["thread"]["id"]
        save_thread(self.key, self.tid)
        return True

    # --- writer-lock recovery ---------------------------------------------
    LOCK_DIR = os.path.expanduser("~/.codex/thread-writer-locks")

    def _lock_path(self, tid):
        return os.path.join(self.LOCK_DIR, f"{tid}.lock")

    def _lock_holder_is_daemon(self, tid):
        """True when the remote-control daemon holds this thread's writer lock.

        Only the daemon is reclaimable: it takes the lock for any thread the
        ChatGPT app has merely OPEN and keeps it while the thread sits idle, so
        "held" says nothing about whether work is happening. Another relay
        connection holding it is a different matter and must be left alone."""
        try:
            out = subprocess.run(["lsof", "-t", self._lock_path(tid)],
                                 capture_output=True, text=True, timeout=10).stdout.split()
        except Exception:
            return False
        for pid in out:
            try:
                cmd = subprocess.run(["ps", "-o", "command=", "-p", pid],
                                     capture_output=True, text=True, timeout=10).stdout
            except Exception:
                continue
            if "app-server" in cmd and "--remote-control" in cmd:
                return True
        return False

    def _thread_idle(self, tid):
        """Ask the store whether a turn is actually running on this thread.

        Reclaiming a lock while the app is mid-turn would put two writers on one
        thread, so idleness is the precondition -- not a guess from the fact that
        the lock is held."""
        rid = self._send("thread/read", {"threadId": tid})
        r = self._wait(rid, 25)
        try:
            st = (r["result"]["thread"].get("status") or {}).get("type", "")
        except Exception:
            return False
        # notLoaded = not even open; idle = open, no turn running.
        return st in ("notLoaded", "idle")

    def _reclaim_lock(self, tid):
        """Unlink the lock path so the next open() creates a fresh inode.

        This is a RECLAIM, not a handshake: the daemon keeps its descriptor on
        the old inode, so for as long as it holds that thread open both sides
        believe they own the writer. It is done only when the thread is idle and
        the holder is the daemon, which is the case where the lock outlived the
        work it was protecting -- the alternative is a topic that stays silent
        until the user happens to close a thread in the app."""
        try:
            os.unlink(self._lock_path(tid))
            self._log(f"reclaimed idle writer lock for {tid} (held by the Codex app)")
            return True
        except Exception as e:
            self._log(f"lock reclaim failed for {tid}: {e}")
            return False

    def set_name(self, name):
        if not (self.tid and name):
            return False
        rid = self._send("thread/name/set", {"threadId": self.tid, "name": name[:80]})
        r = self._wait(rid, 20)
        return bool(r and "result" in r)

    def current_name(self):
        rid = self._send("thread/read", {"threadId": self.tid})
        r = self._wait(rid, 20)
        try:
            return (r["result"]["thread"].get("name") or "").strip()
        except Exception:
            return ""

    def set_name_if_unset(self, name):
        """Name a thread only when it has none -- never overwrite a title the
        user chose in the app."""
        if not self.tid:
            return False
        if self.current_name():
            return True
        return self.set_name(name)

    def close(self):
        """Shut down so the thread's WRITER LOCK is released.

        SIGKILL leaves the lock held: the next connection's thread/resume gets
        "thread <id> already has an active writer", falls through to
        thread/start, and the topic silently continues in a NEW empty thread --
        history intact on disk but no longer the one the relay writes to. That
        is the same divergence that made DUT look idle in the app while a turn
        ran in Telegram, so it is worth an orderly exit.

        On the daemon transport this only drops our connection: the daemon keeps
        the thread (and its lock) for the app, which is the point."""
        if self.ws is not None:
            self.ws.close()
            return
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=8)
            return
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass

    # --- turns ------------------------------------------------------------
    def send(self, text):
        """Start a turn, or STEER the running one. Never refuse the message."""
        if not self.alive() and not self.open():
            return False
        if self.busy and self.turn_id:
            rid = self._send("turn/steer", {
                "threadId": self.tid, "expectedTurnId": self.turn_id,
                "input": [{"type": "text", "text": text}]})
            r = self._wait(rid, 30)
            if r and "result" in r:
                self._log(f"steered turn {self.turn_id}")
                return "steered"
            # A steer can lose the race with turn completion; fall through and
            # start a fresh turn rather than dropping what the user typed.
            self._log(f"steer rejected, starting a turn instead: "
                      f"{json.dumps(r)[:160] if r else 'timeout'}")
        self.steps, self.message, self.delta = [], "", ""
        self.final, self.error = "", ""
        self.busy = True                      # optimistic: turn/started confirms
        rid = self._send("turn/start", {
            "threadId": self.tid, "input": [{"type": "text", "text": text}]})
        r = self._wait(rid, 30)
        if r and "error" in r:
            self.busy = False
            self.error = json.dumps(r["error"])[:300]
            return False
        return "started"

    def interrupt(self):
        """Cancel the running turn AND discard its partial output.

        Without the discard, codex still emits turn/completed for the killed
        turn, take_final() hands back whatever had streamed so far, and the
        relay posts it as the answer -- so a cancel produced a confirmation
        immediately followed by "I'll run the 90-second sleep now." as if the
        turn had succeeded. Cancelling means the user does not want that text."""
        if not (self.busy and self.turn_id):
            return False
        rid = self._send("turn/interrupt", {"threadId": self.tid, "turnId": self.turn_id})
        r = self._wait(rid, 20)
        self.busy = False
        self.message = self.delta = self.final = self.error = ""
        self._cancelled_turn = self.turn_id
        return bool(r and "result" in r)

    def live_text(self):
        """Progress for the bubble: what it is doing, plus the newest message."""
        out = []
        if self.steps:
            counts, last = [], None
            for s in self.steps:
                if s == last:
                    counts[-1][1] += 1
                else:
                    counts.append([s, 1]); last = s
            out.append(" · ".join(f"{s}{f' x{n}' if n > 1 else ''}"
                                  for s, n in counts[-4:]))
        live = self.message or self.delta      # streamed text before it completes
        if live:
            out.append(live)
        return "\n\n".join(out)

    def take_final(self):
        """The finished answer, once. Empty while a turn is still running."""
        if self.busy:
            return ""
        if self.final:
            f, self.final = self.final, ""
            return f
        if self.error:
            e, self.error = self.error, ""
            return f"⚠️ codex turn failed.\n\n{e}"
        return ""
