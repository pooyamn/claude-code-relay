#!/usr/bin/env python3
"""Remove dead Telegram->Claude-relay bindings and the config they left behind.

Every `newcc` bind writes FOUR coupled entries: a binding, an agents.list entry,
a models entry, and a cliBackend. Nothing ever removes them, so the config
accumulates bindings pointing at chats that no longer exist and backends nothing
routes to. A dead binding is not inert: it keeps a stale agent id alive, which
shows up in session keys and log records, and it makes the real cause of a silent
group ("which of these three agents owns this folder?") much harder to see.

Reaped only on EVIDENCE, in three certain classes:

  MISSING_FOLDER  the agent's workspace no longer exists on disk. Nothing can run.
  MIGRATED_PEER   the peer is a basic-group id (no `-100` prefix) whose traffic
                  STOPS and is immediately followed by a supergroup id starting
                  up. That is Telegram's group->supergroup upgrade fingerprint:
                  the old id becomes permanently unreachable, and the gateway
                  drops `migrate_to_chat_id`, so nothing rebinds itself.
  ORPHAN_CONFIG   models / cliBackends / agents.list entries no binding references.

Reported but NEVER auto-removed, because the fix is a human decision:

  FOLDER_COLLISION  two or more live bindings share one workspace. The relay keys
                    a session by FOLDER (`cr-<md5(folder)>`) while OpenClaw keys an
                    agent by PEER, so those peers silently share ONE Claude
                    conversation and ONE reply target -- last inbound wins, and
                    answers surface in whichever topic spoke most recently.

Dry-run by default. `--apply` writes, after a backup, and rolls back if the
result fails `openclaw config validate`.
"""
import argparse, glob, hashlib, json, os, re, shutil, subprocess, sys, time

CFG = os.environ.get("RELAY_CFG", os.path.expanduser("~/.openclaw/openclaw.json"))
MSGLOG = os.environ.get("RELAY_MSGLOG", os.path.expanduser("~/.openclaw/logs/messages.jsonl"))
RELAY_WORK = os.path.expanduser("~/.openclaw/workspace/scripts/relay-work")

# A basic group upgraded to a supergroup within this window of its last message.
# Telegram issues the new id at the moment of upgrade; the old chat goes silent
# for good. Wide enough to absorb a quiet gap, narrow enough that two unrelated
# groups days apart are never paired.
MIGRATE_WINDOW_S = 6 * 3600


def peer_chat(peer):
    """`-100123:topic:5` -> `-100123`. Bare ids pass through."""
    return str(peer).split(":topic:", 1)[0]


def is_supergroup(chat):
    return str(chat).startswith("-100")


def load_traffic():
    """{chat_id: (first_ts, last_ts)} from the message log, seconds since epoch.

    Only records whose sessionKey carries the peer are trusted: the logger
    plugin's own chatId field is derived by a loose `-\\d{7,}` regex that can
    match digits inside an AGENT id (agent `claude-hardware-0310143aba` logs
    chatId `-0310143`), so reading it here would invent chats that never existed.
    """
    span = {}
    try:
        fh = open(MSGLOG, errors="replace")
    except OSError:
        return span
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
                ts = time.mktime(time.strptime(row["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            m = re.search(r":(?:group|direct):(-?\d+)", str(row.get("sessionKey", "")))
            if not m:
                continue
            chat = m.group(1)
            lo, hi = span.get(chat, (ts, ts))
            span[chat] = (min(lo, ts), max(hi, ts))
    return span


def migrated(chat, span):
    """True if `chat` is a basic group whose traffic ends where a supergroup's begins."""
    if is_supergroup(chat) or chat not in span:
        return None
    last = span[chat][1]
    for other, (first, _) in span.items():
        if other == chat or not is_supergroup(other):
            continue
        if 0 <= first - last <= MIGRATE_WINDOW_S:
            return other
    return None


def collect(d):
    """Cross-reference bindings against agents/models/backends. Returns findings."""
    ag = d.get("agents", {})
    defs = ag.setdefault("defaults", {})
    agents = {a.get("id"): a for a in ag.get("list", []) if a.get("id")}
    binds = d.get("bindings", [])
    span = load_traffic()

    dead, keep = [], []
    for b in binds:
        aid = b.get("agentId")
        peer = b.get("match", {}).get("peer", {}).get("id", "")
        folder = (agents.get(aid) or {}).get("workspace", "")
        chat = peer_chat(peer)
        if folder and not os.path.isdir(folder):
            dead.append((b, aid, peer, folder, "MISSING_FOLDER", f"workspace gone: {folder}"))
            continue
        new = migrated(chat, span)
        if new:
            dead.append((b, aid, peer, folder, "MIGRATED_PEER",
                         f"basic group {chat} upgraded to {new}; old id unreachable"))
            continue
        keep.append((b, aid, peer, folder))

    # Collisions are computed over SURVIVORS only -- reaping a migrated twin often
    # resolves the collision by itself, and flagging it beforehand is just noise.
    byfolder = {}
    for b, aid, peer, folder in keep:
        if folder:
            byfolder.setdefault(folder, []).append((aid, peer))
    collisions = {f: v for f, v in byfolder.items() if len(v) > 1}

    live_agents = {aid for _, aid, _, _ in keep}
    orphans = {"models": [], "cliBackends": [], "agents.list": []}
    live_models, live_backends = set(), set()
    for aid in live_agents:
        model = (agents.get(aid) or {}).get("model", "")
        if model:
            live_models.add(model)
            live_backends.add(model.split("/", 1)[0])
    for m in list(defs.get("models", {})):
        # Only relay models are ours to reap; provider models (anthropic/..., kimi-cli/...)
        # are user-selectable and must survive having no binding.
        if m.startswith("claude-tui-") and m not in live_models:
            orphans["models"].append(m)
    for c in list(defs.get("cliBackends", {})):
        if c.startswith("claude-tui-") and c not in live_backends:
            orphans["cliBackends"].append(c)
    for aid in list(agents):
        if aid.startswith("claude-") and aid not in live_agents:
            orphans["agents.list"].append(aid)

    return dead, collisions, orphans, keep


def apply(d, dead, orphans, keep):
    ag = d["agents"]; defs = ag["defaults"]
    doomed_agents = {aid for _, aid, _, _, _, _ in dead} | set(orphans["agents.list"])
    d["bindings"] = [b for b in d.get("bindings", []) if b.get("agentId") not in doomed_agents]
    ag["list"] = [a for a in ag.get("list", []) if a.get("id") not in doomed_agents]
    for m in orphans["models"]:
        defs.get("models", {}).pop(m, None)
    for c in orphans["cliBackends"]:
        defs.get("cliBackends", {}).pop(c, None)

    # Reply-target files are keyed by FOLDER, so only drop one when no surviving
    # binding still uses that folder -- otherwise we blind a live session.
    survivors = {folder for _, _, _, folder in keep if folder}
    removed = []
    for _, _, _, folder, _, _ in dead:
        if not folder or folder in survivors:
            continue
        key = "cr-" + hashlib.md5(folder.encode()).hexdigest()[:10]
        for p in glob.glob(os.path.join(RELAY_WORK, f"*-{key}.json")):
            try:
                os.remove(p); removed.append(os.path.basename(p))
            except OSError:
                pass
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--quiet", action="store_true", help="print nothing when there is nothing to do")
    a = ap.parse_args()

    d = json.load(open(CFG))
    dead, collisions, orphans, keep = collect(d)
    n_orphans = sum(len(v) for v in orphans.values())

    if not dead and not n_orphans and not collisions:
        if not a.quiet:
            print("No dead bindings. Config is clean.")
        return 0

    # Stamp only when there is something to say, so the unattended sweep's log
    # stays empty on a clean config instead of growing a line every run.
    if a.quiet:
        print(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    for _, aid, peer, folder, why, detail in dead:
        print(f"DEAD  {why:<14} {aid}  peer={peer}\n      {detail}")
    for kind, items in orphans.items():
        for it in items:
            print(f"DEAD  ORPHAN_CONFIG  {kind}: {it}")
    for folder, owners in collisions.items():
        print(f"WARN  FOLDER_COLLISION  {folder}")
        for aid, peer in owners:
            print(f"      {aid}  peer={peer}")
        print("      -> these peers SHARE one Claude session and one reply target "
              "(last inbound wins). Give each peer its own folder/worktree. Not auto-fixed.")

    if not a.apply:
        print(f"\nDry run. {len(dead)} dead binding(s), {n_orphans} orphan entr(ies). "
              f"Re-run with --apply to remove.")
        return 0

    # A collision alone is a report, not an edit. Bailing here keeps the periodic
    # sweep from writing a backup file every run for as long as one goes unfixed.
    if not dead and not n_orphans:
        print("\nNothing to remove (collisions are reported only).")
        return 0

    bak = f"{CFG}.bak-reap-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CFG, bak)
    removed = apply(d, dead, orphans, keep)
    open(CFG, "w").write(json.dumps(d, indent=2))

    if CFG == os.path.expanduser("~/.openclaw/openclaw.json"):
        r = subprocess.run(["openclaw", "config", "validate", "--json"],
                           capture_output=True, text=True)
        if '"valid":true' not in r.stdout.replace(" ", ""):
            shutil.copy2(bak, CFG)
            print("ERROR: config invalid, rolled back. Details:", file=sys.stderr)
            print(r.stdout or r.stderr, file=sys.stderr)
            return 3

    print(f"\nRemoved {len(dead)} binding(s), {n_orphans} orphan entr(ies)"
          + (f", {len(removed)} relay-work file(s): {', '.join(removed)}" if removed else ""))
    print(f"backup={bak}")
    if dead or n_orphans:
        print("RESTART REQUIRED: openclaw gateway restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
