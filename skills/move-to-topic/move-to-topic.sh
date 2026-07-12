#!/usr/bin/env bash
# move-to-topic.sh — FORK the current relay-bound session into a NEW Telegram topic
# backed by a git WORKTREE: an INDEPENDENT session (own folder = own cr-<hash>) that
# resumes the current conversation with full context, while the current topic stays
# alive on the base branch.
#
# Flow (Option-B fork): commit WIP -> switch main folder to base branch -> nested
# worktree on the feature branch -> copy the ACTIVE transcript (lastSessionId, not
# newest-mtime) + rewrite its cwd rows -> create topic + bind -> PRE-LAUNCH the fork
# session with `claude --resume <sid>` (--continue rejects a transplanted file) ->
# write its reply target + start its watcher -> deferred gateway restart.
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
tmux capture-pane -p -t "$KEY" 2>/dev/null | grep -q "esc to interrupt" && die "session is busy; try again when idle."

# --- resolve folder + code + chat ---
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

# --- git preconditions ---
git -C "$FOLDER" rev-parse --git-dir >/dev/null 2>&1 || die "$FOLDER is not a git repo."
BRANCH="$(git -C "$FOLDER" branch --show-current)"
[ -n "$BRANCH" ] || die "detached HEAD in $FOLDER; checkout a branch first."
BASE=main; git -C "$FOLDER" rev-parse --verify -q main >/dev/null 2>&1 || BASE=master
[ "$BRANCH" != "$BASE" ] || die "already on '$BASE'; nothing to fork (switch to a feature branch first)."
WT="$FOLDER/.worktrees/$BRANCH"
[ -e "$WT" ] && die "worktree already exists: $WT"

echo "move-to-topic: forking '$BRANCH' -> worktree; '$FOLDER' stays on '$BASE'" >&2

# --- 1-3) commit WIP, switch to base, add worktree ---
if [ -n "$(git -C "$FOLDER" status --porcelain)" ]; then
  git -C "$FOLDER" add -A
  git -C "$FOLDER" commit -q -m "wip: checkpoint before topic fork ($NAME)" || die "WIP commit failed"
fi
git -C "$FOLDER" switch "$BASE" 2>/dev/null || die "couldn't switch $FOLDER to $BASE"
grep -qxF '.worktrees/' "$FOLDER/.gitignore" 2>/dev/null || echo '.worktrees/' >> "$FOLDER/.gitignore"
git -C "$FOLDER" add .gitignore >/dev/null 2>&1 && git -C "$FOLDER" commit -q -m "chore: ignore .worktrees" >/dev/null 2>&1 || true
git -C "$FOLDER" worktree add "$WT" "$BRANCH" >&2 || die "worktree add failed"

# --- 4) transplant the ACTIVE transcript ---
# lastSessionId from ~/.claude.json is the conversation the session is LIVE on;
# newest-mtime picks the wrong file when a folder serves several chats or /clear
# rotated sessions (learned the hard way). Rewrite top-level cwd rows or claude
# will not associate the file with the worktree.
enc(){ python3 -c "import sys;print(sys.argv[1].replace('/','-').replace('.','-'))" "$1"; }
SRCDIR="$HOME/.claude/projects/$(enc "$FOLDER")"
DSTDIR="$HOME/.claude/projects/$(enc "$WT")"
SID="$(python3 - "$FOLDER" <<'PY'
import json,sys,os
try:
    d=json.load(open(os.path.expanduser("~/.claude.json")))
    print(d.get("projects",{}).get(sys.argv[1],{}).get("lastSessionId","") or "")
except Exception: print("")
PY
)"
SRC=""
[ -n "$SID" ] && [ -f "$SRCDIR/$SID.jsonl" ] && SRC="$SRCDIR/$SID.jsonl"
[ -z "$SRC" ] && { SRC="$(ls -t "$SRCDIR"/*.jsonl 2>/dev/null | head -1)"; SID="$(basename "${SRC%.jsonl}")"; }
[ -n "$SRC" ] || die "no transcript found in $SRCDIR"
mkdir -p "$DSTDIR"; cp "$SRC" "$DSTDIR/"
python3 - "$DSTDIR/$SID.jsonl" "$FOLDER" "$WT" <<'PY'
import json,sys
p,old,new=sys.argv[1:4]
out=[]
for line in open(p):
    line=line.rstrip("\n")
    if not line.strip(): continue
    try:
        row=json.loads(line)
        if row.get("cwd")==old:
            row["cwd"]=new; line=json.dumps(row,ensure_ascii=False,separators=(",",":"))
    except Exception: pass
    out.append(line)
open(p,"w").write("\n".join(out)+"\n")
PY

# --- 5) register code, create topic, bind ---
WCODE="$(python3 - "$CODES" "$WT" <<'PY'
import json,sys,random
p,wt=sys.argv[1],sys.argv[2]; codes=json.load(open(p))
for c,f in codes.items():
    if f==wt: print(c); break
else:
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

# --- 6) PRE-LAUNCH the fork session (resume) + reply target + watcher ---
# `claude --continue` refuses a transplanted transcript until the fork has real
# activity of its own, so first boot must be `--resume <sid>`. Pre-launching also
# means the first user message just injects into a ready TUI.
NKEY="cr-$(printf '%s' "$WT" | md5 | cut -c1-10)"
printf '{"chat": "%s", "thread": "%s"}\n' "$CHAT" "$TID" > "$RELAY_WORK/target-$NKEY.json"
SETTINGS="$SCRIPTS/relay-claude-settings.json"
tmux kill-session -t "$NKEY" 2>/dev/null || true
tmux new-session -d -s "$NKEY" -x 200 -y 50 -c "$WT" \
  "claude --resume $SID --settings $SETTINGS --dangerously-skip-permissions"
for i in $(seq 1 45); do
  pane="$(tmux capture-pane -t "$NKEY" -p 2>/dev/null || true)"
  printf '%s' "$pane" | grep -q "trust this folder" && { tmux send-keys -t "$NKEY" Enter; sleep 2; }
  # big-session resume dialog: take the recommended "Resume from summary"
  printf '%s' "$pane" | grep -q "Resume from summary" && { tmux send-keys -t "$NKEY" Enter; sleep 2; }
  printf '%s' "$pane" | grep -qE "for agents|for shortcuts" && break
  sleep 1
done
WKEY="crw-${NKEY#cr-}"
if ! tmux has-session -t "$WKEY" 2>/dev/null; then
  tmux new-session -d -s "$WKEY" -c "$SCRIPTS" \
    "CLAUDE_RELAY_SESSION='$NKEY' RELAY_STREAM='1' exec python3 '$SCRIPTS/claude-relay-send.py' --watch"
fi
openclaw gateway call message.action --json \
  --params "$(mkparams send to "$CHAT:topic:$TID" message "🔱 Forked here — independent session on branch '$BRANCH' (worktree), resumed with this conversation's context. The old topic stays on '$BASE'.")" \
  >/dev/null 2>&1 || true

# --- 7) activate (deferred so this reply flushes first) ---
( sleep 12; openclaw gateway restart ) >/dev/null 2>&1 &

cat <<EOF
✅ Forked to new topic "$NAME" (id $TID).
• New topic  -> $WT (branch $BRANCH) — independent session $NKEY, resumed from $SID, watcher up.
• This topic -> $FOLDER (now on $BASE) — stays alive.
Gateway restarts in ~12s; then continue in "$NAME".
EOF
