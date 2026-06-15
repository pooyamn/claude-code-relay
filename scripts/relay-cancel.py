#!/usr/bin/env python3
"""Interrupt the current Claude turn in a bound relay session -- a Telegram
replacement for pressing Esc in the TUI. Sends an Escape keystroke straight to
the per-folder tmux session, so it works even while a turn is mid-flight (it's
invoked from the pre-agent plugin, not the serialized backend).

Usage: relay-cancel.py --peer "<chatId|chatId:topic:N>"
"""
import json, os, sys, argparse, hashlib, shlex, subprocess

CFG = os.environ.get("RELAY_CFG", os.path.expanduser("~/.openclaw/openclaw.json"))


def folder_for_peer(peer):
    """Map a Telegram peer to its bound project folder via openclaw.json. Falls
    back to the parent group binding when standing in an unbound topic."""
    d = json.load(open(CFG))
    binds = d.get("bindings", [])
    agents = {a.get("id"): a for a in d.get("agents", {}).get("list", [])}

    def lookup(p):
        for b in binds:
            mt = b.get("match", {})
            if (mt.get("channel") == "telegram"
                    and mt.get("peer", {}).get("id") == p):
                return agents.get(b.get("agentId"), {}).get("workspace")
        return None

    return lookup(peer) or (lookup(peer.split(":topic:")[0]) if ":topic:" in peer else None)


def tmux_key(folder):
    # Match claude-relay-group exactly: KEY=cr-<first10 of md5(`cd folder && pwd`)>.
    wd = subprocess.run(["bash", "-lc", f"cd {shlex.quote(folder)} && pwd"],
                        capture_output=True, text=True).stdout.strip() or folder
    return "cr-" + hashlib.md5(wd.encode()).hexdigest()[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peer", required=True)
    a = ap.parse_args()
    folder = folder_for_peer(a.peer)
    if not folder:
        print("Nothing to cancel: this chat isn't bound to a Claude relay.")
        return
    key = tmux_key(folder)
    if subprocess.run(["tmux", "has-session", "-t", key],
                      capture_output=True).returncode != 0:
        print("Nothing to cancel: no live session.")
        return
    subprocess.run(["tmux", "send-keys", "-t", key, "Escape"], capture_output=True)
    print("🛑 Interrupted — sent Esc to Claude's current turn.")


if __name__ == "__main__":
    main()
