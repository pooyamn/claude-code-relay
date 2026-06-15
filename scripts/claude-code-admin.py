#!/usr/bin/env python3
import os as _os
BASE = _os.environ.get("RELAY_DIR") or _os.path.dirname(_os.path.abspath(__file__))
"""Manage Claude-code relay bindings: status + unbind.

Companion to bind-claude-code.py. Same safety model: backup, schema-validate,
auto-rollback, restart only when valid.

  claude-code-admin.py status
  claude-code-admin.py unbind --peer "<chatId>" [--restart]
"""
import json, os, sys, argparse, shutil, time, subprocess

CFG = os.environ.get("RELAY_CFG", os.path.expanduser("~/.openclaw/openclaw.json"))
REG = "" + BASE + "/relay-codes.json"

def load_cfg(): return json.load(open(CFG))

def status():
    d = load_cfg()
    reg = json.load(open(REG))
    folder_by_path = {v: k for k, v in reg.items()}
    binds = d.get("bindings", [])
    relay = [b for b in binds if str(b.get("agentId", "")).startswith("claude-")]
    if not relay:
        print("No Claude-code relay bindings.");
    for b in relay:
        peer = b.get("match", {}).get("peer", {}).get("id", "?")
        aid = b.get("agentId")
        ag = next((a for a in d.get("agents", {}).get("list", []) if a.get("id") == aid), {})
        wsp = ag.get("workspace", "?")
        code = folder_by_path.get(wsp, "-")
        print(f"peer={peer}  agent={aid}  folder={wsp}  code={code}")
    print("\nAvailable codes:")
    for c, f in reg.items():
        print(f"  {c} -> {f}")

def unbind(peer, restart):
    bak = f"{CFG}.bak-unbind-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CFG, bak)
    d = load_cfg()
    binds = d.get("bindings", [])
    before = len(binds)
    removed = [b for b in binds
               if b.get("match", {}).get("peer", {}).get("id") == peer
               and b.get("match", {}).get("channel") == "telegram"]
    binds[:] = [b for b in binds if b not in removed]
    if not removed:
        print(f"No binding found for peer={peer}"); return
    # Leave the backend/model/agent definitions in place (harmless, reusable);
    # only the binding is removed so the chat reverts to the default agent.
    txt = json.dumps(d, indent=2); json.loads(txt)
    open(CFG, "w").write(txt)
    only_live = (CFG == os.path.expanduser("~/.openclaw/openclaw.json"))
    if only_live:
        r = subprocess.run(["openclaw", "config", "validate", "--json"],
                           capture_output=True, text=True)
        if '"valid":true' not in r.stdout.replace(" ", ""):
            shutil.copy2(bak, CFG)
            print("ERROR: config invalid, rolled back.", file=sys.stderr)
            print(r.stdout or r.stderr, file=sys.stderr); sys.exit(3)
    print(f"OK unbound peer={peer} (removed {len(removed)} binding(s)). backup={bak}")
    if restart and only_live:
        # Detached + delayed (see bind-claude-code.py): survive being run from
        # inside the relay backend so the reply is delivered before reload.
        subprocess.Popen(["sh", "-c", "sleep 2; openclaw gateway restart >/dev/null 2>&1"],
                         start_new_session=True)
        print("restart: scheduled (gateway reloading in ~2s)")
    else:
        print("RESTART REQUIRED: openclaw gateway restart")

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    u = sub.add_parser("unbind")
    u.add_argument("--peer", required=True)
    u.add_argument("--restart", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status": status()
    elif a.cmd == "unbind": unbind(a.peer, a.restart)

if __name__ == "__main__":
    main()
