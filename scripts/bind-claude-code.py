#!/usr/bin/env python3
import os as _os
BASE = _os.environ.get("RELAY_DIR") or _os.path.dirname(_os.path.abspath(__file__))
"""Bind a Telegram group/topic to a per-folder Claude TUI relay agent.

Called when the user types `/new-claude-code <code>` IN the target chat: the
caller (Jamshid) supplies the peer id from the inbound message metadata, so no
manual chat-id wrangling. Patches ~/.openclaw/openclaw.json additively (backup
first, JSON validated). A gateway restart is required after (printed, not auto).

Usage: bind-claude-code.py --peer "<chatId|chatId:topic:N>" --code <6digits>
"""
import json, os, sys, argparse, shutil, time, subprocess

CFG = os.environ.get("RELAY_CFG", os.path.expanduser("~/.openclaw/openclaw.json"))
REG = "" + BASE + "/relay-codes.json"
WRAPPER = "" + BASE + "/claude-tui-backend-multi"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peer", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--restart", action="store_true", help="restart gateway if config validates")
    a = ap.parse_args()

    reg = json.load(open(REG))
    folder = reg.get(a.code)
    if not folder:
        print(f"ERROR: unknown code {a.code}", file=sys.stderr); sys.exit(2)
    if not os.path.isdir(folder):
        print(f"ERROR: folder missing: {folder}", file=sys.stderr); sys.exit(2)
    slug = os.path.basename(folder.rstrip("/"))
    backend = f"claude-tui-{slug}"
    model = f"{backend}/relay"
    agent_id = f"claude-{slug}"

    bak = f"{CFG}.bak-bind-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CFG, bak)
    d = json.load(open(CFG))

    ag = d.setdefault("agents", {})
    defs = ag.setdefault("defaults", {})
    # 1) backend
    defs.setdefault("cliBackends", {})[backend] = {
        "command": WRAPPER, "args": [folder],
        "input": "arg", "output": "text", "sessionMode": "none",
    }
    # 2) model allowlist entry (must bind to the cliBackend via agentRuntime.id)
    defs.setdefault("models", {})[model] = {"agentRuntime": {"id": backend}}
    # 3) agents.list: ensure default 'main' + this relay agent
    lst = ag.setdefault("list", [])
    if not any(x.get("id") == "main" for x in lst):
        lst.insert(0, {"id": "main", "default": True})
    lst[:] = [x for x in lst if x.get("id") != agent_id]
    lst.append({
        "id": agent_id, "model": model, "workspace": folder,
        "contextInjection": "never",  # raw pipe: no bootstrap/system-prompt injection
    })
    # 4) binding (replace any existing for same peer)
    binds = d.setdefault("bindings", [])
    binds[:] = [b for b in binds if not (
        b.get("match", {}).get("peer", {}).get("id") == a.peer
        and b.get("match", {}).get("channel") == "telegram")]
    binds.append({"agentId": agent_id, "match": {
        "channel": "telegram", "peer": {"kind": "group", "id": a.peer}}})

    # write, then validate against the OpenClaw schema; roll back if invalid
    txt = json.dumps(d, indent=2)
    json.loads(txt)
    open(CFG, "w").write(txt)
    only_live = (CFG == os.path.expanduser("~/.openclaw/openclaw.json"))
    if only_live:
        r = subprocess.run(["openclaw", "config", "validate", "--json"],
                           capture_output=True, text=True)
        ok = '"valid":true' in r.stdout.replace(" ", "")
        if not ok:
            shutil.copy2(bak, CFG)   # ROLLBACK
            print("ERROR: config invalid, rolled back. Details:", file=sys.stderr)
            print(r.stdout or r.stderr, file=sys.stderr)
            sys.exit(3)
    print(f"OK bound peer={a.peer} -> agent={agent_id} folder={folder}")
    print(f"backup={bak}")
    if a.restart and only_live:
        rr = subprocess.run(["openclaw", "gateway", "restart"],
                            capture_output=True, text=True)
        print("restart:", (rr.stdout or rr.stderr).strip().splitlines()[-1] if (rr.stdout or rr.stderr).strip() else "(done)")
    else:
        print("RESTART REQUIRED: openclaw gateway restart")

if __name__ == "__main__":
    main()
