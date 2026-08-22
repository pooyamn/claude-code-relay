#!/usr/bin/env python3
"""OpenCode backend over its HTTP API instead of scraping the TUI.

The tmux path drives opencode's terminal UI and reads answers off the screen. That
cost, in one evening: parsing the "▣ <agent> ·" footer, clipping each line at the
sidebar boundary, a "+ Thought:" header that collapsed the answer range to nothing,
stderr writing over the UI, replies truncated by a 50-line pane with no scrollback,
and sessions wedged forever by a resumed subagent turn. None of that is opencode
misbehaving -- it is what screen-scraping a UI costs.

opencode ships a real HTTP API, so use it:

    POST /session                      create (or reuse the folder's newest)
    POST /session/{id}/prompt_async    send, returns immediately
    GET  /session/status               map of RUNNING sessions -> busy/idle
    GET  /session/{id}/message         full messages, no truncation

Turn completion is /session/status: the id is present while the turn runs and gone
when it finishes. That is a real state from the server, not a guess about chrome.

One server per bound folder, on the same derived port the TUI used, so a session
keeps its address across restarts. Bound to 127.0.0.1; remote access goes through a
tunnel, never a public listener.
"""
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(SCRIPTS, "relay-work")
PORT_BASE, PORT_SPAN = 4100, 700
_TIMEOUT = 90


# --- server ------------------------------------------------------------------

def _free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def port_for(folder):
    """Stable per-folder port, so a restart keeps the same address."""
    h = int(hashlib.md5(os.path.abspath(folder).encode()).hexdigest()[:8], 16)
    start = PORT_BASE + (h % PORT_SPAN)
    for i in range(PORT_SPAN):
        p = PORT_BASE + ((start - PORT_BASE + i) % PORT_SPAN)
        if not _free(p) and _alive(p):
            return p          # already OUR server: reuse it
        if _free(p):
            return p
    return start


def _alive(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/config", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True           # 401 from a password-protected server still means up
    except Exception:
        return False


def ensure_server(folder, wait=45):
    """Start `opencode serve` for this folder if it isn't already up. Returns base URL.

    cwd matters: opencode resolves the PROJECT from the server's working directory,
    and sessions are listed per project. Starting it anywhere else silently yields a
    server that cannot see this folder's sessions.
    """
    port = port_for(folder)
    if _alive(port):
        return f"http://127.0.0.1:{port}"
    log = os.path.join(STATE, f"opencode-stderr-{key_for(folder)}.log")
    os.makedirs(STATE, exist_ok=True)
    with open(log, "a") as fh:
        subprocess.Popen(
            ["opencode", "serve", "--port", str(port), "--hostname", "127.0.0.1"],
            cwd=folder, stdout=fh, stderr=fh, start_new_session=True)
    for _ in range(wait):
        if _alive(port):
            break
        time.sleep(1)
    return f"http://127.0.0.1:{port}"


def key_for(folder):
    return "cr-" + hashlib.md5(os.path.abspath(folder).encode()).hexdigest()[:10]


# --- http --------------------------------------------------------------------

def call(base, path, body=None, method=None, timeout=_TIMEOUT):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(raw) if raw else None


# --- sessions ----------------------------------------------------------------

def _sid_path(folder):
    return os.path.join(STATE, f"opencode-session-{key_for(folder)}.txt")


def session_for(folder, base, title="relay"):
    """The session this folder talks to: remembered, else newest for the directory,
    else a fresh one. Directory-scoped on purpose -- opencode's `-c` continues the
    most recent session GLOBALLY, which once resumed another project's conversation
    in that project's cwd."""
    p = _sid_path(folder)
    try:
        sid = open(p).read().strip()
        if sid:
            call(base, f"/session/{sid}", timeout=15)   # 404s if it is gone
            return sid
    except Exception:
        pass
    real = os.path.realpath(folder)
    try:
        for s in sorted(call(base, "/session", timeout=20) or [],
                        key=lambda x: (x.get("time") or {}).get("updated", 0), reverse=True):
            if os.path.realpath(s.get("directory") or "") == real:
                sid = s["id"]
                break
        else:
            sid = call(base, "/session", {"title": title})["id"]
    except Exception:
        sid = call(base, "/session", {"title": title})["id"]
    try:
        open(p, "w").write(sid)
    except Exception:
        pass
    return sid


# --- the two operations the relay needs --------------------------------------

def send(folder, text, provider, model):
    """Fire the prompt and return at once; the watcher collects the answer."""
    base = ensure_server(folder)
    sid = session_for(folder, base)
    call(base, f"/session/{sid}/prompt_async", {
        "model": {"providerID": provider, "modelID": model},
        "parts": [{"type": "text", "text": text}],
    })
    return sid


def is_busy(folder):
    base = f"http://127.0.0.1:{port_for(folder)}"
    try:
        sid = open(_sid_path(folder)).read().strip()
        return sid in (call(base, "/session/status", timeout=15) or {})
    except Exception:
        return False


def last_reply(folder):
    """Text of the newest assistant message. Whole thing -- no pane, no truncation."""
    base = f"http://127.0.0.1:{port_for(folder)}"
    try:
        sid = open(_sid_path(folder)).read().strip()
        msgs = call(base, f"/session/{sid}/message", timeout=30) or []
    except Exception:
        return ""
    for m in reversed(msgs):
        info = m.get("info") or m
        if info.get("role") != "assistant":
            continue
        parts = m.get("parts") or []
        out = []
        for part in parts:
            # text only: tool calls and reasoning are chrome for our purposes, and
            # leaking them is how a "$ mkdir ..." line once got delivered as a reply.
            if part.get("type") == "text" and part.get("text"):
                out.append(part["text"])
        return "\n".join(out).strip()
    return ""
