#!/usr/bin/env python3
"""Platform health check: plain code, no model. Finds problems and, with
--report, files them as issues (deduplicated) so the support agent is woken
only when something is actually wrong.

  health_check.py            dry run: print findings
  health_check.py --report   file new findings with ccrelay report_issue
  health_check.py --bench    also check the bench Mac for wedged USB drives

Each check reads only what is new since the previous run (state file), so a
problem is reported once, not every 15 minutes.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(D, "relay-work")
STATE = os.path.expanduser("~/.config/ccrelay/health-state.json")
DEDUP_HOURS = 6


def sh(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return 127, str(e)


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"offsets": {}, "reported": {}}


def new_lines(state, path):
    """Lines appended to `path` since the last run (inode-aware)."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    ino, off = state["offsets"].get(path, [None, 0])
    if ino != st.st_ino or off > st.st_size:
        off = max(0, st.st_size - 200_000) if ino is None else 0   # first run: recent tail only
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    end = data.rfind(b"\n") + 1
    state["offsets"][path] = [st.st_ino, off + end]
    return data[:end].decode("utf-8", "replace").splitlines()


def check_ops(state):
    out = []
    for l in new_lines(state, os.path.join(WORK, "msg-ops.log")):
        bad = (" rc=" in l and " rc=0 " not in l) or " ERR=" in l or "TARGET-REFUSED" in l
        if bad:
            out.append(l[:240])
    if out:
        return [("bug", f"Telegram send/edit failures ({len(out)} since last check)", "\n".join(out[-15:]))]
    return []


def check_bus(state):
    bad = []
    for l in new_lines(state, os.path.join(WORK, "bus.jsonl")):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("state") in ("failed", "refused"):
            bad.append(f"{r.get('ts')} {r.get('from')}->{r.get('to')} {r.get('state')}: {r.get('error') or r.get('text', '')[:100]}")
    if bad:
        return [("bug", f"Inter-session messages not delivered ({len(bad)})", "\n".join(bad[-15:]))]
    return []


def check_watchers():
    """Every live relay session (cr-*) needs its watcher (crw-*), and every
    codex topic needs one even without a pane."""
    rc, out = sh(["tmux", "ls", "-F", "#S"])
    names = set(out.split()) if rc == 0 else set()
    missing = []
    for n in names:
        if n.startswith("cr-") and f"crw-{n[3:]}" not in names:
            missing.append(n)
    for f in os.listdir(WORK):
        if f.startswith("backend-cr-") and f.endswith(".json"):
            key = f[len("backend-"):-5]
            try:
                if json.load(open(os.path.join(WORK, f))).get("backend") == "codex" \
                        and os.path.exists(os.path.join(WORK, f"codex-thread-{key}.txt")) \
                        and f"crw-{key[3:]}" not in names:
                    missing.append(f"{key} (codex)")
            except Exception:
                pass
    if missing:
        return [("bug", f"Relay watchers missing for {len(missing)} session(s)", "\n".join(sorted(missing)))]
    return []


def check_codex_daemon():
    rc, out = sh(["codex", "app-server", "daemon", "version"])
    if rc != 0 or '"status":"running"' not in out.replace(" ", ""):
        return [("bug", "Codex remote-control daemon not running", out[-400:])]
    return []


def check_disk():
    u = shutil.disk_usage(os.path.expanduser("~"))
    if u.free / u.total < 0.10:
        return [("bug", f"Disk nearly full ({u.free / 1e9:.0f} GB free)", f"total {u.total / 1e9:.0f} GB")]
    return []


def check_bench():
    """A FAT drive that stops answering (the DAPLink probe's virtual drive)
    freezes Finder and LaunchServices on the bench Mac. Probe each mounted
    msdos volume with a bounded listing."""
    rc, out = sh(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "bench",
                  "for m in $(mount | awk '/msdos|fskit/{print $3}'); do "
                  "( ls \"$m\" >/dev/null 2>&1 & p=$!; sleep 4; kill -0 $p 2>/dev/null && echo HUNG $m || echo OK $m ); done"],
                 timeout=40)
    if rc != 0 and "HUNG" not in out:
        return [("bug", "Bench Mac unreachable over ssh", out[-300:])]
    hung = [l for l in out.splitlines() if l.startswith("HUNG")]
    if hung:
        return [("bug", "Bench: USB drive not responding (Finder will hang)", "\n".join(hung))]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--bench", action="store_true")
    a = ap.parse_args()
    state = load_state()
    findings = check_ops(state) + check_bus(state) + check_watchers() + check_codex_daemon() + check_disk()
    if a.bench:
        findings += check_bench()
    now = time.time()
    state["reported"] = {k: t for k, t in state["reported"].items() if now - t < DEDUP_HOURS * 3600}
    filed = []
    for kind, title, details in findings:
        sig = hashlib.md5(title.split(" (")[0].encode()).hexdigest()[:12]
        fresh = sig not in state["reported"]
        print(f"{'NEW ' if fresh else 'seen'} {title}\n    " + details.replace("\n", "\n    ")[:600])
        if a.report and fresh:
            sys.path.insert(0, D)
            import ccrelay_mcp
            r = ccrelay_mcp.report_issue(kind, title, details, reporter="health-check")
            filed.append(r.get("id"))
            state["reported"][sig] = now
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, "w"))
    if not findings:
        print("healthy")
    if filed:
        print("filed:", ", ".join(filed))


if __name__ == "__main__":
    main()
