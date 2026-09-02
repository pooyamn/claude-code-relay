#!/usr/bin/env python3
"""Codex backend for the per-folder relay: `codex exec` driven headlessly.

Why this shape rather than a TUI in tmux, like the claude/kimi/opencode paths:
codex ships a real non-interactive mode with everything the relay needs, so
there is nothing to gain from scraping a terminal. Measured on codex-cli
0.151.0:

  codex exec <prompt>                --json -o <file> -C <dir>    -> new thread
  codex exec resume <tid> <prompt>   --json -o <file>             -> same thread

  {"type":"thread.started","thread_id":"01a0..."}      <- the durable id
  {"type":"turn.started"}
  {"type":"item.started"}                              <- a tool call began
  {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
  {"type":"item.completed","item":{"type":"command_execution",...}}
  {"type":"turn.completed","usage":{...}}

`thread_id` gives us folder -> conversation the way `--resume <sid>` does for
claude, and `-o` writes the final answer to a file, which is the same
deterministic turn-completion signal the Stop hook provides on the claude path.
No busy-regex, no chrome parsing, no 50-line pane with no scrollback.

Two flags that are not optional here:
  --skip-git-repo-check   a bound folder is not always a git repo
  < /dev/null             without it codex waits on inherited stdin and logs
                          "Reading additional input from stdin..." forever

The turn runs DETACHED (start_new_session) because the caller is a per-message
process that exits as soon as it has queued the prompt; a child in its process
group would die with it and the turn would vanish mid-flight. The watcher polls
is_busy()/last_reply() and delivers, exactly as it does for opencode-api.
"""
import json
import os
import re
import signal
import subprocess
import time

D = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(D, "relay-work")
CODEX = os.environ.get("RELAY_CODEX_BIN", "/opt/homebrew/bin/codex")


def _cfg():
    """Permissions/model for the codex backend, from relay-claude-settings-cx.json.

    Kept in the settings file rather than hardcoded here so the trust posture is
    visible and reversible in one place -- the same file `cc model cx` already
    resolves the token through."""
    try:
        return json.load(open(os.path.join(D, "relay-claude-settings-cx.json")))
    except Exception:
        return {}


def _perm_args(cfg, resume=False):
    """Compose the permission flags. Default posture is ALLOW EVERYTHING, which
    matches --dangerously-skip-permissions on the claude path: nobody is at the
    keyboard to answer an approval prompt, so a prompt is just a hung turn.

    -s danger-full-access is redundant while bypass_approvals is on (the bypass
    already disables the sandbox) but is emitted anyway, so dropping the bypass
    alone does not silently re-sandbox every command.

    `codex exec resume` accepts a STRICTLY SMALLER flag set than `codex exec`:
    -s/--sandbox, --add-dir, -C, -p and --color are all rejected there with
    "unexpected argument", which kills the turn before the model is reached (the
    relay then delivers nothing and the topic looks dead -- codex-cli 0.152.1,
    topic 816, 2026-09-01). Both survivors have a -c config-override spelling,
    so on the resume path emit those instead of dropping the posture."""
    args = []
    if cfg.get("bypass_approvals", True):
        args.append("--dangerously-bypass-approvals-and-sandbox")
    sandbox = cfg.get("sandbox", "danger-full-access")
    if resume:
        args += ["-c", 'sandbox_mode=%s' % json.dumps(sandbox)]
    else:
        args += ["-s", sandbox]
    if cfg.get("bypass_hook_trust", True):
        args.append("--dangerously-bypass-hook-trust")
    if cfg.get("inherit_env", True):
        # Without this codex hands spawned commands a scrubbed environment, so
        # anything relying on PATH/tokens from the relay's shell fails in ways
        # that look like the tool being broken rather than the env being empty.
        args += ["-c", "shell_environment_policy.inherit=all"]
    add_dirs = cfg.get("add_dirs") or []
    if add_dirs:
        if resume:
            args += ["-c", "sandbox_workspace_write.writable_roots=" + json.dumps(add_dirs)]
        else:
            for d in add_dirs:
                args += ["--add-dir", d]
    for extra in cfg.get("extra_args") or []:
        args.append(extra)
    return args


def _p(key, name):
    return os.path.join(STATE, f"codex-{name}-{key}")


def thread_path(key):   return _p(key, "thread") + ".txt"
def events_path(key):   return _p(key, "events") + ".jsonl"
def last_path(key):     return _p(key, "last") + ".txt"
def pid_path(key):      return _p(key, "pid") + ".txt"
def err_path(key):      return _p(key, "err") + ".log"


def read_thread(key):
    """The folder's durable codex thread, or '' before the first turn."""
    try:
        t = open(thread_path(key)).read().strip()
        return t if re.fullmatch(r"[0-9a-fA-F-]{16,}", t) else ""
    except Exception:
        return ""


def _save_thread(key, tid):
    try:
        os.makedirs(STATE, exist_ok=True)
        open(thread_path(key), "w").write(tid)
    except Exception:
        pass


def harvest_thread(key):
    """Pull thread_id out of this turn's events and persist it.

    Called after every turn, not just the first: `codex exec resume` re-emits
    thread.started with the same id, so this is idempotent, and it is the only
    way a first turn's id ever reaches disk."""
    try:
        with open(events_path(key)) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") == "thread.started" and d.get("thread_id"):
                    _save_thread(key, d["thread_id"])
                    return d["thread_id"]
    except Exception:
        pass
    return read_thread(key)


_TERMINAL = ("turn.completed", "turn.failed", "error")


def _turn_ended(key):
    """True once the event stream carries a terminal event.

    This, not the pid, is the authoritative signal. os.kill(pid, 0) SUCCEEDS on
    a zombie, so any caller that is itself the spawning process sees a finished
    turn as eternally busy -- measured: a turn that completed in 4s reported
    busy for the full 180s poll. The watcher happens to be a different process,
    which would have hidden this until something else polled from the parent."""
    try:
        with open(events_path(key)) as f:
            for line in f:
                try:
                    t = json.loads(line).get("type")
                except Exception:
                    continue
                if t in _TERMINAL:
                    return True
    except Exception:
        pass
    return False


def _pid_alive(key):
    try:
        pid = int(open(pid_path(key)).read().strip())
    except Exception:
        return False
    try:
        os.waitpid(pid, os.WNOHANG)   # reap it if we are the parent
    except Exception:
        pass
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    # A zombie answers signal 0; only a real state check separates the two.
    try:
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                            capture_output=True, text=True, timeout=10).stdout.strip()
        return bool(st) and not st.startswith("Z")
    except Exception:
        return True


def is_busy(key):
    """True while this folder's codex turn is still running.

    Process exit -- not the terminal event -- is the completion signal, because
    codex emits turn.completed BEFORE it writes the -o file. Gating on the event
    raced the file and delivered an EMPTY answer for a turn that had genuinely
    succeeded (measured: reply '' on a turn whose -o landed a moment later).
    Once _pid_alive() stopped counting zombies as running, the pid became both
    correct and race-free: codex writes the answer, then exits."""
    return _pid_alive(key)


def cancel(key):
    """Interrupt the running turn (the `cc cancel` equivalent for codex)."""
    try:
        pid = int(open(pid_path(key)).read().strip())
    except Exception:
        return False
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), sig)
        except Exception:
            try:
                os.kill(pid, sig)
            except Exception:
                return False
        time.sleep(1.5)
        if not is_busy(key):
            return True
    return not is_busy(key)


def start(folder, key, prompt, model=""):
    """Spawn a detached turn. Returns immediately; the watcher delivers."""
    os.makedirs(STATE, exist_ok=True)
    for p in (events_path(key), last_path(key), pid_path(key)):
        try:
            os.remove(p)          # a stale file would be delivered as this turn's answer
        except OSError:
            pass

    tid = read_thread(key)
    base = [CODEX, "exec"]
    if tid:
        # NOTE: `exec resume` rejects -C ("unexpected argument"), so the working
        # directory has to come from the process, not a flag. cwd= below covers
        # both shapes, and -C is only added on the new-thread path.
        base += ["resume", tid, prompt]
    else:
        base += [prompt, "-C", folder]
    cfg = _cfg()
    model = model or cfg.get("model", "")
    if model:
        base += ["-m", model]
    cmd = base + ["--json",
                  "-o", last_path(key),
                  "--skip-git-repo-check"] + _perm_args(cfg, resume=bool(tid))

    ev = open(events_path(key), "w")
    er = open(err_path(key), "a")
    dn = open(os.devnull, "r")
    proc = subprocess.Popen(cmd, cwd=folder, stdin=dn, stdout=ev, stderr=er,
                            start_new_session=True)
    try:
        open(pid_path(key), "w").write(str(proc.pid))
    except Exception:
        pass
    return proc.pid


def last_reply(key):
    """The finished turn's answer, or '' if it has not landed yet."""
    try:
        return open(last_path(key)).read().strip()
    except Exception:
        return ""


_ITEM_LABEL = {
    "command_execution": "running a command",
    "file_change": "editing files",
    "mcp_tool_call": "calling a tool",
    "web_search": "searching the web",
    "reasoning": "thinking",
    "todo_list": "planning",
}


def live_text(key):
    """A progress summary for the live bubble, built from the event stream.

    Deliberately a SUMMARY, not a transcript: codex emits whole items rather
    than token deltas, so there is no partial answer to stream. Showing what it
    is doing and the newest agent message is the honest version of progress
    here -- inventing a fake typing effect from completed items would only
    misrepresent the pace."""
    steps, msg, err = [], "", ""
    try:
        with open(events_path(key)) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                if t == "item.completed":
                    it = d.get("item") or {}
                    k = it.get("type")
                    if k == "agent_message":
                        msg = (it.get("text") or "").strip()
                    elif k in _ITEM_LABEL:
                        steps.append(_ITEM_LABEL[k])
                elif t == "error" or (t or "").endswith(".failed"):
                    err = json.dumps(d)[:200]
    except Exception:
        return ""
    out = []
    if steps:
        # collapse runs so "running a command" x12 does not fill the bubble
        counts, last = [], None
        for s in steps:
            if s == last:
                counts[-1][1] += 1
            else:
                counts.append([s, 1]); last = s
        out.append(" · ".join(f"{s}{f' x{n}' if n > 1 else ''}" for s, n in counts[-4:]))
    if msg:
        out.append(msg)
    if err:
        out.append(f"⚠️ {err}")
    return "\n\n".join(out)


def turn_failed(key):
    """Non-empty when the turn died without producing an answer.

    codex exits non-zero on auth failure, a bad thread id, or a killed turn, and
    an empty -o file is indistinguishable from 'still thinking' unless we look
    at stderr. Returning the reason lets the caller say something true instead
    of leaving the topic silent -- the failure mode that has cost the most time
    on every other backend here."""
    if is_busy(key) or last_reply(key):
        return ""
    try:
        tail = open(err_path(key)).read().strip().splitlines()[-4:]
    except Exception:
        tail = []
    tail = [l for l in tail if l.strip() and "Reading additional input" not in l]
    return "\n".join(tail)[:400]
