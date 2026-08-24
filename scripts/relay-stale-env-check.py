#!/usr/bin/env python3
"""Detect relay TUI processes running on STALE environment.

Root cause this guards against (2026-08-24): the schematic-pipeline-lab session was
launched BEFORE the OpenRouter proxy existed, so its captured ANTHROPIC_BASE_URL still
pointed straight at openrouter.ai with one key. When that key's daily quota died the
session 429'd forever while the whole key pool sat idle -- invisible, because direct
traffic never shows up in the proxy log. Claude Code reads env ONCE at launch; editing
settings files can never reach a running process.

Detection is time-correlated, because a socket snapshot lies both ways (a healthy
session is BETWEEN proxy connections whenever idle; telemetry keeps remote :443 sockets
open). A session is flagged only when, across a sampling window:

  - its transcript GREW        -> real turns completed, so API calls really happened
  - it NEVER held a connection to the configured local proxy port
  - it DID hold remote :443    -> those calls went somewhere else

That combination has exactly one explanation: captured env predates the config change.
Restarting fixes it (sessions resume via --continue/--resume); we notify instead of
killing so an in-flight turn is never interrupted silently.
"""
import json
import os
import re
import subprocess
import time

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(SCRIPTS, "relay-work")
LOG = os.path.join(STATE, "stale-env.log")
SEEN = os.path.join(STATE, "stale-env-reported.json")
NOTIFY_TO = os.environ.get("OR_NOTIFY_TO", "-1003550185469:topic:816")

SAMPLES, GAP_S = 10, 5          # ~50s window


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def notify(text):
    try:
        subprocess.Popen(
            ["openclaw", "message", "send", "--channel", "telegram",
             "--target", NOTIFY_TO.split(":topic:")[0],
             *(["--thread-id", NOTIFY_TO.split(":topic:")[1]] if ":topic:" in NOTIFY_TO else []),
             "--message", text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        log(f"NOTIFY FAILED: {e}")


def candidates():
    """pid -> (settings path, transcript path) for interactive claude TUIs on OUR settings."""
    out = {}
    try:
        raw = subprocess.run(["ps", "ax", "-o", "pid=,tty=,command="],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return out
    for line in raw.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*--settings\s+(\S+))", line)
        if not m:
            continue
        pid, tty, _cmd, settings = m.groups()
        if not os.path.basename(settings).startswith("relay-claude-settings"):
            continue
        if tty.startswith("?"):          # want terminal-attached TUIs, not headless runs
            continue
        base = ""
        try:
            base = json.load(open(settings)).get("env", {}).get("ANTHROPIC_BASE_URL", "")
        except Exception:
            pass
        if "127.0.0.1" not in base and "localhost" not in base:
            continue                     # genuinely direct config: nothing to compare
        # cwd -> newest transcript, the ground truth that turns are happening
        cwd = ""
        try:
            lsof = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                                  capture_output=True, text=True, timeout=30).stdout
            cwd = next((l[1:] for l in lsof.splitlines() if l.startswith("n/")), "")
        except Exception:
            pass
        enc = cwd.replace("/", "-").replace(".", "-")
        proj = os.path.expanduser(f"~/.claude/projects/{enc}")
        transcript = ""
        if os.path.isdir(proj):
            files = [os.path.join(proj, f) for f in os.listdir(proj) if f.endswith(".jsonl")]
            if files:
                transcript = max(files, key=os.path.getmtime)
        out[pid] = {"tty": tty, "base": base, "transcript": transcript,
                    "port": re.sub(r".*:", "", base.rstrip("/"))}
    return out


def main():
    cands = {pid: c for pid, c in candidates().items() if c["port"] and c["transcript"]}
    if not cands:
        return

    def size(pid):
        try:
            return os.path.getsize(cands[pid]["transcript"])
        except Exception:
            return None

    t0 = {pid: size(pid) for pid in cands}
    saw_proxy = {pid: False for pid in cands}
    saw_remote = {pid: False for pid in cands}

    for i in range(SAMPLES):
        if i:
            time.sleep(GAP_S)
        for pid, c in list(cands.items()):
            try:
                conns = subprocess.run(["lsof", "-nP", "-p", pid], capture_output=True,
                                       text=True, timeout=30).stdout
            except Exception:
                continue
            if f"->127.0.0.1:{c['port']}" in conns or f":{c['port']}->127.0.0.1:{c['port']}" in conns \
               or re.search(rf"127\.0\.0\.1:\d+->127\.0\.0\.1:{c['port']}\b", conns):
                saw_proxy[pid] = True
            if re.search(r"->\[[0-9a-f:]+\]:443\s+\(ESTABLISHED\)", conns) or \
               re.search(r"->\d+\.\d+\.\d+\.\d+:443\s+\(ESTABLISHED\)", conns):
                saw_remote[pid] = True

    try:
        reported = set(json.load(open(SEEN)))
    except Exception:
        reported = set()

    stale = []
    for pid, c in sorted(cands.items()):
        grew = size(pid) not in (None, t0[pid])
        if grew and not saw_proxy[pid] and saw_remote[pid]:
            stale.append((pid, c))
            log(f"STALE pid={pid} tty={c['tty']} wants={c['base']} transcript grew "
                f"{t0[pid]}->{size(pid)} with no :{c['port']} conn in {SAMPLES} samples")

    fresh = [(p, c) for p, c in stale if p not in reported]
    if fresh:
        names = ", ".join(f"pid {p} ({c['tty']})" for p, c in fresh)
        notify(f"🕵️ Stale relay session(s) detected: {names}. They launched before a "
               f"config change and their API calls bypass the local proxy. Ask me to "
               f"restart them — sessions resume where they were.")
    try:
        json.dump(sorted(set(reported) | {p for p, _ in stale}), open(SEEN, "w"))
    except Exception:
        pass


if __name__ == "__main__":
    main()
