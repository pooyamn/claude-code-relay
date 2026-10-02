#!/usr/bin/env python3
"""ccrelay MCP server: lets a Claude Code or Codex session message other sessions.

Stdio MCP (JSON-RPC 2.0, one JSON object per line), stdlib only. Both tools
spawn it with the session's working directory as cwd, so the CALLER is the
relay session whose bound folder contains that cwd. A session cannot pick its
own sender name: identity comes from where it runs, not from an argument.

Tools
  list_sessions()                        sessions you can message
  send_message(to, text, reply_to?)      deliver now; returns id and state
  message_log(limit?)                    recent inter-session messages

Delivery
  Claude: one JSON line on the target's inbox socket, /tmp/cc-socks/<pid>.sock
          (format verified 2026-10-01; target needs crossSessionInbound=accept).
  Codex:  `codex queue --thread <thread-id> --message <text>` via the daemon.

Every message is appended to relay-work/bus.jsonl with its delivery state and
mirrored to the Telegram bus topic configured in ~/.config/ccrelay/bus.json.
"""
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid

D = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(D, "relay-work")
CODES = os.path.join(D, "relay-codes.json")
BUS = os.path.join(WORK, "bus.jsonl")
BUS_CFG = os.path.expanduser("~/.config/ccrelay/bus.json")
HOP_LIMIT = 3
CODEX = os.environ.get("RELAY_CODEX_BIN") or "codex"


# --- sessions ---------------------------------------------------------------
def _key(folder):
    return "cr-" + hashlib.md5(folder.encode()).hexdigest()[:10]


def _folders():
    try:
        return sorted(set(json.load(open(CODES)).values()))
    except Exception:
        return []


def _name(folder):
    """Friendly session name: the folder's last two path parts when the last
    one alone is ambiguous across bindings (e.g. ccrelay-test/claude)."""
    base = os.path.basename(folder.rstrip("/"))
    clash = [f for f in _folders() if os.path.basename(f.rstrip("/")) == base]
    if len(clash) > 1:
        return "/".join(folder.rstrip("/").split("/")[-2:])
    return base


def _backend(key):
    try:
        return json.load(open(os.path.join(WORK, f"backend-{key}.json"))).get("backend") or "claude"
    except Exception:
        return "claude"


def _claude_socket(key):
    """The inbox socket of the Claude process running in tmux session `key`."""
    r = subprocess.run(["tmux", "display-message", "-p", "-t", key, "#{pane_pid}"],
                       capture_output=True, text=True)
    pane = r.stdout.strip()
    if r.returncode or not pane:
        return None
    # Claude can sit several levels below the pane (shell -> wrapper -> claude),
    # so walk every descendant, not just direct children.
    # Not pgrep: on macOS it silently omits the caller's own ancestors, which
    # hid the Claude process whenever this server ran inside that session.
    kids = {}
    for row in subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                              text=True).stdout.splitlines():
        parts = row.split()
        if len(parts) == 2:
            kids.setdefault(parts[1], []).append(parts[0])
    pids, todo = [], [pane]
    while todo:
        p = todo.pop()
        pids.append(p)
        todo += kids.get(p, [])
    for pid in pids:
        for base in ("/tmp/cc-socks", f"/tmp/cc-socks-{os.getuid()}",
                     os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"), "cc-socks")):
            p = os.path.join(base, f"{pid}.sock")
            if os.path.exists(p):
                return p
    return None


def _codex_thread(key):
    try:
        return open(os.path.join(WORK, f"codex-thread-{key}.txt")).read().strip()
    except Exception:
        return ""


def sessions():
    out = []
    for f in _folders():
        k = _key(f)
        tool = _backend(k)
        if tool == "codex":
            tid = _codex_thread(k)
            out.append(dict(name=_name(f), key=k, tool="codex", folder=f,
                            reachable=bool(tid), address=tid))
        else:
            sock = _claude_socket(k)
            out.append(dict(name=_name(f), key=k, tool="claude", folder=f,
                            reachable=bool(sock), address=sock))
    return out


def caller():
    """The session this server runs for: the bound folder containing cwd."""
    cwd = os.path.realpath(os.getcwd())
    best = None
    for f in _folders():
        rf = os.path.realpath(f)
        if cwd == rf or cwd.startswith(rf + "/"):
            if best is None or len(rf) > len(os.path.realpath(best)):
                best = f
    return best


def resolve(to):
    to = (to or "").strip()
    for s in sessions():
        if to in (s["name"], s["key"], os.path.basename(s["folder"].rstrip("/"))):
            return s
    return None


# --- bus --------------------------------------------------------------------
def bus_append(rec):
    os.makedirs(WORK, exist_ok=True)
    with open(BUS, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def bus_read():
    try:
        with open(BUS) as f:
            return [json.loads(l) for l in f if l.strip()]
    except Exception:
        return []


def hop_of(reply_to):
    if not reply_to:
        return 1
    for r in reversed(bus_read()):
        if r.get("id") == reply_to:
            return int(r.get("hop", 1)) + 1
    return 1


def bus_telegram(rec):
    """Mirror one line to the Telegram bus topic. Best effort: the log is the record."""
    try:
        cfg = json.load(open(BUS_CFG))
        sys.path.insert(0, D)
        import relay_tg
        bot = relay_tg.Bot(relay_tg.load_token(cfg["env"]))
        mark = {"delivered": "", "failed": " ⚠️ not delivered"}.get(rec["state"], "")
        first = rec["text"].strip().split("\n", 1)[0]
        more = "" if first == rec["text"].strip() else " …"
        relay_tg.send_text(bot, cfg["chat"], cfg.get("thread"),
                           f"**{rec['from']} → {rec['to']}** · hop {rec['hop']}{mark}\n{first[:600]}{more}",
                           silent=True)
    except Exception as e:
        print(f"bus telegram: {e}", file=sys.stderr)


# --- delivery ---------------------------------------------------------------
def deliver_claude(sock, body):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(sock)
    s.sendall((json.dumps({"type": "user", "message": {"role": "user", "content": body}})
               + "\n").encode())
    s.shutdown(socket.SHUT_WR)
    s.close()


def deliver_codex(thread, body):
    r = subprocess.run([CODEX, "queue", "--thread", thread, "--message", body],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:])


def send_message(to, text, reply_to=None):
    me = caller()
    if not me:
        return {"ok": False, "error": "this session is not a bound relay session"}
    sender = _name(me)
    target = resolve(to)
    if not target:
        return {"ok": False, "error": f"no session named {to!r}; call list_sessions"}
    if target["folder"] == me:
        return {"ok": False, "error": "that is this session"}
    hop = hop_of(reply_to)
    if hop > HOP_LIMIT:
        rec = dict(id=uuid.uuid4().hex[:8], ts=time.strftime("%Y-%m-%dT%H:%M:%S"), hop=hop,
                   to=target["name"], text=text, state="refused", reply_to=reply_to)
        rec["from"] = sender
        bus_append(rec)
        bus_telegram({**rec, "state": "failed", "text": f"[hop limit {HOP_LIMIT} reached] " + text})
        return {"ok": False, "error": f"hop limit {HOP_LIMIT} reached; ask Pouya instead"}
    mid = uuid.uuid4().hex[:8]
    header = f"[from {sender} · hop {hop} · id {mid}]"
    tail = (f"\n\n(Reply with the ccrelay send_message tool, to=\"{sender}\", "
            f"reply_to=\"{mid}\". Do not reply in this chat.)")
    body = f"{header} {text}{tail}"
    state, err = "delivered", None
    try:
        if not target["reachable"]:
            raise RuntimeError("target session is not running")
        if target["tool"] == "codex":
            deliver_codex(target["address"], body)
        else:
            deliver_claude(target["address"], body)
    except Exception as e:
        state, err = "failed", str(e)
    rec = {"id": mid, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": sender,
           "to": target["name"], "hop": hop, "reply_to": reply_to, "text": text,
           "state": state, "error": err}
    bus_append(rec)
    bus_telegram(rec)
    return {"ok": state == "delivered", "id": mid, "state": state, "error": err}


# --- MCP plumbing -----------------------------------------------------------
TOOLS = [
    {"name": "list_sessions",
     "description": "List the other agent sessions you can message, with their tool and whether they are reachable.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "send_message",
     "description": ("Send a short message to another session. It arrives in that session as a new "
                     "input; do not wait for a reply, it will arrive in your own session later. "
                     "Pass reply_to with the id from the message you are answering."),
     "inputSchema": {"type": "object", "required": ["to", "text"], "properties": {
         "to": {"type": "string", "description": "session name from list_sessions"},
         "text": {"type": "string"},
         "reply_to": {"type": "string", "description": "id of the message you are answering"}}}},
    {"name": "message_log",
     "description": "Show recent inter-session messages.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
]


def call_tool(name, args):
    if name == "list_sessions":
        me = caller()
        rows = [{k: s[k] for k in ("name", "tool", "reachable")}
                for s in sessions() if s["folder"] != me]
        return {"you": _name(me) if me else None, "sessions": rows}
    if name == "send_message":
        return send_message(args.get("to"), args.get("text", ""), args.get("reply_to"))
    if name == "message_log":
        n = int(args.get("limit") or 20)
        return bus_read()[-n:]
    raise ValueError(f"unknown tool {name}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        rid, method = req.get("id"), req.get("method")
        if rid is None:
            continue                                   # notification
        try:
            if method == "initialize":
                ver = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
                res = {"protocolVersion": ver, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "ccrelay", "version": "0.1"}}
            elif method == "tools/list":
                res = {"tools": TOOLS}
            elif method == "tools/call":
                p = req.get("params") or {}
                out = call_tool(p.get("name"), p.get("arguments") or {})
                res = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                       "isError": isinstance(out, dict) and out.get("ok") is False}
            elif method == "ping":
                res = {}
            else:
                raise ValueError(f"method not found: {method}")
            msg = {"jsonrpc": "2.0", "id": rid, "result": res}
        except Exception as e:
            msg = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
