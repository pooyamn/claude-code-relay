#!/usr/bin/env python3
"""Convert OpenClaw's Telegram relay bindings into ccrelayd's bindings file.

OpenClaw keys a binding as  bindings[].match.peer.id  ("-100..:topic:N" or a
bare chat id) -> agentId -> agents.list[].workspace (the folder). ccrelayd keeps
the same peer strings, so a topic stays bound to the same folder and therefore
the same cr-<md5(folder)> session, history and pins included.

Usage: export-openclaw-bindings.py [openclaw.json] > bindings.json
"""
import json
import os
import sys

src = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.openclaw/openclaw.json")
cfg = json.load(open(src))
agents = {a.get("id"): a.get("workspace") for a in cfg.get("agents", {}).get("list", [])}
out, skipped = {}, []
for b in cfg.get("bindings", []):
    m = b.get("match", {})
    peer = (m.get("peer") or {}).get("id")
    ws = agents.get(b.get("agentId"))
    if m.get("channel") != "telegram" or not peer or not ws:
        skipped.append(b.get("agentId"))
        continue
    out[str(peer)] = ws
json.dump(out, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
if skipped:
    sys.stderr.write(f"skipped (not a telegram folder binding): {skipped}\n")
