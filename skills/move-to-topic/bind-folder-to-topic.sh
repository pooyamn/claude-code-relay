#!/usr/bin/env bash
# bind-folder-to-topic.sh <folder> <topic name...>
#
# Sibling of move-to-topic.sh for the case it cannot serve: giving a DIFFERENT
# folder its own topic. move-to-topic forks the session it runs inside -- it can
# only ever target its own folder, via a worktree on a feature branch. When the
# work lives in a separate repo entirely (a website checkout, a sibling project),
# there is nothing to fork and no transcript worth transplanting.
#
# So this does the same last three steps and nothing else: register a relay code
# for the folder, create the topic, bind it, launch a FRESH session there (no
# --resume: there is no transplanted transcript, and --continue on an unrelated
# folder would pick up the wrong history), start its watcher, restart the gateway.
#
# The current session and folder are left completely untouched.
set -uo pipefail
SCRIPTS="$HOME/.openclaw/workspace/scripts"
RELAY_WORK="$SCRIPTS/relay-work"; CODES="$SCRIPTS/relay-codes.json"
die(){ echo "bind-folder-to-topic: $*" >&2; exit 1; }
CHAT_OVERRIDE=""
if [ "${1:-}" = "--chat" ]; then CHAT_OVERRIDE="${2:?--chat needs a chat id}"; shift 2; fi
[ "$#" -ge 2 ] || die "usage: bind-folder-to-topic.sh [--chat <chatId>] <folder> <topic name>"
TARGET="$1"; shift; NAME="$*"

# --- must be run from a relay-bound session (that is where the chat id lives) ---
[ -n "${TMUX:-}" ] || die "not inside a relay-bound session (no \$TMUX)."
KEY="$(tmux display-message -p '#S' 2>/dev/null || true)"
case "$KEY" in cr-[0-9a-f]*) : ;; *) die "not a relay session (session='$KEY').";; esac
# NO busy check here, deliberately. This script is copied from move-to-topic.sh,
# which refuses while the pane shows "esc to interrupt" because it commits WIP,
# switches branches and transplants the ACTIVE transcript -- all of which would
# corrupt a turn in flight. THIS script does none of that: it only READS
# target-$KEY.json for the chat id and leaves the invoking session untouched
# (see the header). Meanwhile an agent can only reach this script from inside a
# relay session, and a running tool call IS the busy state -- so the inherited
# check made the script unsatisfiable by its only real caller. The one piece
# that can genuinely disturb the invoking turn is the gateway restart, which
# now waits for the pane to go idle (bottom of file) instead.
# --- which group does the topic go in? ---
# Default: the chat THIS session answers into. That is the safe default but it is
# also a trap -- it makes the group implicit, so running from the wrong session
# creates the topic in the wrong group while every other check still passes.
# --chat makes it explicit, which is the only way to create a topic in a group
# you are not bound to. Overrides are validated hard: it must be a configured
# telegram group AND a -100 supergroup, because topic-create on a basic group
# silently upgrades it and changes its chat id (see SKILL.md pre-flight (a)).
if [ -n "$CHAT_OVERRIDE" ]; then
  CHAT="$CHAT_OVERRIDE"
  python3 - "$CHAT" <<'PY' || die "--chat rejected"
import json, os, sys
chat = sys.argv[1]
if not chat.startswith("-100"):
    sys.exit(f"bind-folder-to-topic: {chat} is not a -100 supergroup; topic-create "
             "would upgrade it and change its chat id. Refusing.")
cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
groups = cfg.get("channels", {}).get("telegram", {}).get("groups", {})
if chat not in groups:
    sys.exit(f"bind-folder-to-topic: {chat} is not a configured telegram group. "
             f"Known: {', '.join(k for k in groups if k != '*')}")
PY
  echo "bind-folder-to-topic: creating in OVERRIDDEN chat $CHAT (not this session's chat)" >&2
else
  TGT="$RELAY_WORK/target-$KEY.json"; [ -f "$TGT" ] || die "no target file $TGT"
  CHAT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("chat",""))' "$TGT")"
  [ -n "$CHAT" ] || die "no chat id in $TGT"
fi

# --- ONE FOLDER PER TOPIC, enforced here ---
# A relay session is keyed by FOLDER (cr-<md5(folder)>) and so is its reply target,
# while OpenClaw keys an agent by PEER. Bind two peers to one folder and they
# silently share ONE Claude conversation and ONE reply target: whichever topic
# spoke last receives the answer. That is not a config wart, it is two topics
# eating each other's replies, and it is invisible until someone notices an answer
# in the wrong place (Oracova PCBA, 2026-08-04). So a new topic ALWAYS gets its own
# folder: created here if missing, refused outright if already spoken for.
CREATED=""
if [ -d "$TARGET" ]; then
  TARGET="$(cd "$TARGET" && pwd -P)"
else
  mkdir -p "$TARGET" || die "could not create $TARGET"
  TARGET="$(cd "$TARGET" && pwd -P)"
  # git init so the folder can later be forked with move-to-topic.sh -- but ONLY
  # if it isn't already inside a work tree. A subfolder of an existing repo is a
  # legitimate choice for a sub-project, and init'ing there would nest a second
  # repo inside the first (git sees an embedded repository, the parent can't
  # track it properly). Inside a work tree the parent's git already serves.
  git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || git -C "$TARGET" init -q >/dev/null 2>&1 || true
  CREATED=" (created)"
fi

NKEY="cr-$(printf '%s' "$TARGET" | md5 | cut -c1-10)"
tmux has-session -t "$NKEY" 2>/dev/null && die "$TARGET already has session $NKEY; it is already bound."
OWNER="$(python3 - "$TARGET" <<'PY'
import json, os, sys
target = sys.argv[1]
try:
    d = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
except Exception:
    sys.exit(0)
agents = {a.get("id"): a for a in d.get("agents", {}).get("list", []) if a.get("id")}
for b in d.get("bindings", []):
    aid = b.get("agentId")
    if (agents.get(aid) or {}).get("workspace") == target:
        print(f"{aid} <- {b.get('match', {}).get('peer', {}).get('id', '?')}")
        break
PY
)"
[ -n "$OWNER" ] && die "$TARGET is already bound to $OWNER. One folder per topic -- pick a new folder."

echo "bind-folder-to-topic: '$TARGET' -> new topic '$NAME'" >&2

# --- register a code for the folder (reuse one if it already exists) ---
WCODE="$(python3 - "$CODES" "$TARGET" <<'PY'
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
[ -n "$WCODE" ] || die "could not register a code for $TARGET"

mkparams(){ python3 - "$@" <<'PY'
import json,sys,time,random
p=dict(zip(sys.argv[2::2],sys.argv[3::2]))
print(json.dumps({"idempotencyKey":f"b2t-{int(time.time()*1000)}-{random.randint(10000,99999)}","action":sys.argv[1],"channel":"telegram","params":p}))
PY
}
CREATE="$(openclaw gateway call message.action --json --params "$(mkparams topic-create chatId "$CHAT" name "$NAME")" 2>&1)" || die "topic-create failed: $CREATE"
TID="$(printf '%s' "$CREATE" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("topicId",""))
except Exception: pass')"
[ -n "$TID" ] || die "no topicId in: $CREATE"
python3 "$SCRIPTS/bind-claude-code.py" --peer="$CHAT:topic:$TID" --code="$WCODE" --keep-parent >&2 || die "bind failed"

# --- launch a fresh session in the folder + its reply target + watcher ---
printf '{"chat": "%s", "thread": "%s"}\n' "$CHAT" "$TID" > "$RELAY_WORK/target-$NKEY.json"
SETTINGS="$SCRIPTS/relay-claude-settings.json"
tmux new-session -d -s "$NKEY" -x 200 -y 50 -c "$TARGET" \
  "claude --settings $SETTINGS --dangerously-skip-permissions"
for i in $(seq 1 45); do
  pane="$(tmux capture-pane -t "$NKEY" -p 2>/dev/null || true)"
  printf '%s' "$pane" | grep -q "trust this folder" && { tmux send-keys -t "$NKEY" Enter; sleep 2; }
  printf '%s' "$pane" | grep -qE "for agents|for shortcuts" && break
  sleep 1
done
WKEY="crw-${NKEY#cr-}"
if ! tmux has-session -t "$WKEY" 2>/dev/null; then
  tmux new-session -d -s "$WKEY" -c "$SCRIPTS" \
    "CLAUDE_RELAY_SESSION='$NKEY' RELAY_STREAM='1' exec python3 '$SCRIPTS/claude-relay-send.py' --watch"
fi
BR="$(git -C "$TARGET" branch --show-current 2>/dev/null || echo '(not a git repo)')"
openclaw gateway call message.action --json \
  --params "$(mkparams send to "$CHAT:topic:$TID" message "📁 Bound here — fresh session in $TARGET (branch $BR). No prior context carried over; say what you need.")" \
  >/dev/null 2>&1 || true

# Activate. The restart is the only step that can disturb the INVOKING session,
# so hold it until that pane is idle rather than guessing a delay: a fixed sleep
# either bounces the gateway mid-turn (crossing reply deliveries -- the exact
# failure this skill warns about) or stalls activation for no reason. Capped so
# a wedged turn can't defer it forever.
( for _ in $(seq 1 240); do
    tmux capture-pane -p -t "$KEY" 2>/dev/null | grep -q "esc to interrupt" || break
    sleep 2
  done
  sleep 3
  openclaw gateway restart ) >/dev/null 2>&1 &

cat <<EOF
✅ Bound new topic "$NAME" (id $TID).
• New topic -> $TARGET$CREATED (branch $BR) — fresh session $NKEY, watcher up, code $WCODE.
• This topic and folder — untouched.
Gateway restarts once this session's turn ends; then continue in "$NAME".
EOF
