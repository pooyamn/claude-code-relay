#!/usr/bin/env bash
# move-to-topic.sh — FORK the current relay-bound session into a NEW Telegram topic
# backed by a git WORKTREE, so the fork is an INDEPENDENT session (its own folder =
# its own cr-<hash>) that continues the current conversation with full context, while
# the current topic stays alive on the base branch.
#
# What it does (Option-B fork), for a git repo currently on a feature branch:
#   1. commit any WIP on the feature branch (checkpoint),
#   2. switch the main folder to the base branch (main/master),
#   3. add a nested worktree .worktrees/<branch> on the feature branch,
#   4. copy the current Claude transcript into the worktree's project dir (--continue),
#   5. create a new topic + bind it to the worktree, then defer a gateway restart.
# The CURRENT topic stays bound to the main folder (now on base).
#
# Usage: move-to-topic.sh <new topic name...>
set -uo pipefail
SCRIPTS="$HOME/.openclaw/workspace/scripts"
RELAY_WORK="$SCRIPTS/relay-work"; CODES="$SCRIPTS/relay-codes.json"
die(){ echo "move-to-topic: $*" >&2; exit 1; }
[ "$#" -ge 1 ] || die "usage: move-to-topic.sh <new topic name>"
NAME="$*"

# --- must be a relay-bound session ---
[ -n "${TMUX:-}" ] || die "not inside a relay-bound session (no \$TMUX)."
KEY="$(tmux display-message -p '#S' 2>/dev/null || true)"
case "$KEY" in cr-[0-9a-f]*) : ;; *) die "not a relay session (session='$KEY').";; esac
# don't do git surgery under a running turn
tmux capture-pane -p -t "$KEY" 2>/dev/null | grep -q "esc to interrupt" && die "session is busy; try again when idle."

# --- resolve this session's folder + code + chat ---
FC="$(python3 - "$CODES" "$KEY" <<'PY'
import json,sys,hashlib
codes=json.load(open(sys.argv[1])); key=sys.argv[2]
for c,f in codes.items():
    if "cr-"+hashlib.md5(f.encode()).hexdigest()[:10]==key: print(c+"\t"+f); break
PY
)"
CODE="${FC%%$'\t'*}"; FOLDER="${FC#*$'\t'}"
[ -n "$FC" ] && [ -n "$FOLDER" ] || die "couldn't resolve folder/code for $KEY"
TGT="$RELAY_WORK/target-$KEY.json"; [ -f "$TGT" ] || die "no target file $TGT"
CHAT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("chat",""))' "$TGT")"
[ -n "$CHAT" ] || die "no chat id in $TGT"

# --- git preconditions: must be a repo on a feature branch ---
git -C "$FOLDER" rev-parse --git-dir >/dev/null 2>&1 || die "$FOLDER is not a git repo; can't create a worktree fork."
BRANCH="$(git -C "$FOLDER" branch --show-current)"
[ -n "$BRANCH" ] || die "detached HEAD in $FOLDER; checkout a branch first."
BASE=main; git -C "$FOLDER" rev-parse --verify -q main >/dev/null 2>&1 || BASE=master
[ "$BRANCH" != "$BASE" ] || die "already on '$BASE'; nothing to fork (make/switch to a feature branch first)."
WT="$FOLDER/.worktrees/$BRANCH"
[ -e "$WT" ] && die "worktree already exists: $WT"

echo "move-to-topic: forking '$BRANCH' -> worktree, base '$BASE', current folder $FOLDER" >&2

# --- 1) commit WIP on the feature branch ---
if [ -n "$(git -C "$FOLDER" status --porcelain)" ]; then
  git -C "$FOLDER" add -A
  git -C "$FOLDER" commit -q -m "wip: checkpoint before topic fork ($NAME)" || die "WIP commit failed"
fi
# --- 2) switch main folder to base, ignore the worktrees dir ---
git -C "$FOLDER" switch "$BASE" 2>/dev/null || die "couldn't switch $FOLDER to $BASE"
grep -qxF '.worktrees/' "$FOLDER/.gitignore" 2>/dev/null || echo '.worktrees/' >> "$FOLDER/.gitignore"
git -C "$FOLDER" add .gitignore >/dev/null 2>&1 && git -C "$FOLDER" commit -q -m "chore: ignore .worktrees" >/dev/null 2>&1 || true
# --- 3) add the nested worktree on the feature branch ---
git -C "$FOLDER" worktree add "$WT" "$BRANCH" 2>&1 | tail -1 >&2 || die "worktree add failed"

# --- 4) copy the current transcript so the fork --continues with context ---
enc(){ python3 -c "import sys;print(sys.argv[1].replace('/','-').replace('.','-'))" "$1"; }
SRCDIR="$HOME/.claude/projects/$(enc "$FOLDER")"
DSTDIR="$HOME/.claude/projects/$(enc "$WT")"
LATEST="$(ls -t "$SRCDIR"/*.jsonl 2>/dev/null | head -1)"
if [ -n "$LATEST" ]; then mkdir -p "$DSTDIR"; cp "$LATEST" "$DSTDIR/"; fi

# --- 5) register worktree code, create topic, bind ---
WCODE="$(python3 - "$CODES" "$WT" <<'PY'
import json,sys,random
p,wt=sys.argv[1],sys.argv[2]; codes=json.load(open(p))
for c,f in codes.items():
    if f==wt: print(c); break
else:
    import random
    while True:
        c=str(random.randint(100000,999999))
        if c not in codes: break
    codes[c]=wt; json.dump(codes,open(p,'w'),indent=2); print(c)
PY
)"
mkparams(){ python3 - "$@" <<'PY'
import json,sys,time,random
p=dict(zip(sys.argv[2::2],sys.argv[3::2]))
print(json.dumps({"idempotencyKey":f"m2t-{int(time.time()*1000)}-{random.randint(10000,99999)}","action":sys.argv[1],"channel":"telegram","params":p}))
PY
}
CREATE="$(openclaw gateway call message.action --json --params "$(mkparams topic-create chatId "$CHAT" name "$NAME")" 2>&1)" || die "topic-create failed: $CREATE"
TID="$(printf '%s' "$CREATE" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("topicId",""))
except Exception: pass')"
[ -n "$TID" ] || die "no topicId in: $CREATE"
python3 "$SCRIPTS/bind-claude-code.py" --peer="$CHAT:topic:$TID" --code="$WCODE" --keep-parent >&2 || die "bind failed"
openclaw gateway call message.action --json --params "$(mkparams send to "$CHAT:topic:$TID" message "🔱 Forked here — independent session on branch '$BRANCH' (worktree), continuing with full context. This topic's own thread; the old topic stays on '$BASE'.")" >/dev/null 2>&1 || true

# --- 6) activate (deferred so this reply flushes first) ---
( sleep 12; openclaw gateway restart ) >/dev/null 2>&1 &

cat <<EOF
✅ Forked to a new topic "$NAME" (id $TID).
• New topic  -> worktree $WT  (branch $BRANCH, your WIP committed) — INDEPENDENT session, context copied.
• This topic -> $FOLDER  (now on $BASE) — stays alive.
Activating (gateway restart in ~12s). Then continue in the "$NAME" topic.
EOF
