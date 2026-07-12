#!/usr/bin/env bash
# move-to-topic.sh — from inside a relay-bound Claude Code session, create a NEW
# Telegram topic in the SAME group and bind it to THIS session's folder. Because a
# relay session is keyed by folder (not topic), the new topic reaches the SAME
# session with full context (continues via --continue). The old topic stays bound
# too (harmless fallback); replies auto-follow to wherever you last messaged.
#
# Usage: move-to-topic.sh <new topic name...>
set -uo pipefail

SCRIPTS="$HOME/.openclaw/workspace/scripts"
RELAY_WORK="$SCRIPTS/relay-work"
CODES="$SCRIPTS/relay-codes.json"

die(){ echo "move-to-topic: $*" >&2; exit 1; }
[ "$#" -ge 1 ] || die "usage: move-to-topic.sh <new topic name>"
NAME="$*"

# --- must be inside a relay-bound session (same guard as send-file) ---
[ -n "${TMUX:-}" ] || die "not inside a relay-bound session (no \$TMUX)."
KEY="$(tmux display-message -p '#S' 2>/dev/null || true)"
case "$KEY" in cr-[0-9a-f]*) : ;; *) die "not a relay session (session='$KEY').";; esac

# --- resolve THIS session's folder + code (reverse md5 over relay-codes.json) ---
FC="$(python3 - "$CODES" "$KEY" <<'PY'
import json,sys,hashlib
codes=json.load(open(sys.argv[1])); key=sys.argv[2]
for c,f in codes.items():
    if "cr-"+hashlib.md5(f.encode()).hexdigest()[:10]==key:
        print(c+"\t"+f); break
PY
)"
CODE="${FC%%$'\t'*}"; FOLDER="${FC#*$'\t'}"
[ -n "$FC" ] && [ -n "$FOLDER" ] || die "couldn't resolve folder/code for $KEY"

# --- this session's group chat + current topic ---
TGT="$RELAY_WORK/target-$KEY.json"
[ -f "$TGT" ] || die "no target file $TGT"
CHAT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("chat",""))' "$TGT")"
[ -n "$CHAT" ] || die "no chat id in $TGT"

# --- create the new topic (build params in python to avoid JSON-escaping issues) ---
mkparams(){ python3 - "$@" <<'PY'
import json,sys,time,random
action=sys.argv[1]
p=dict(zip(sys.argv[2::2], sys.argv[3::2]))
ik=f"m2t-{int(time.time()*1000)}-{random.randint(10000,99999)}"
print(json.dumps({"idempotencyKey":ik,"action":action,"channel":"telegram","params":p}))
PY
}
CREATE="$(openclaw gateway call message.action --json \
  --params "$(mkparams topic-create chatId "$CHAT" name "$NAME")" 2>&1)" \
  || die "topic-create failed: $CREATE"
TID="$(printf '%s' "$CREATE" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("topicId",""))
except Exception: pass')"
[ -n "$TID" ] || die "no topicId in create response: $CREATE"

# --- bind the new topic to the SAME folder (same session -> context preserved) ---
BIND="$(python3 "$SCRIPTS/bind-claude-code.py" --peer="$CHAT:topic:$TID" --code="$CODE" --keep-parent 2>&1)" \
  || die "bind failed: $BIND"

# --- greet the new topic so it isn't empty ---
openclaw gateway call message.action --json \
  --params "$(mkparams send to "$CHAT:topic:$TID" message "🔀 Moved here — same Claude Code session and folder ($FOLDER), full context preserved. Send your next message here to continue.")" \
  >/dev/null 2>&1 || true

# --- activate: defer the gateway restart so this reply flushes to the user first ---
( sleep 12; openclaw gateway restart ) >/dev/null 2>&1 &

cat <<EOF
✅ Created topic "$NAME" (id $TID) and bound it to this session's folder:
   $FOLDER
Same session -> full context preserved (continues via --continue).
Activating now (gateway restart in ~12s). When it's back, continue in the "$NAME"
topic. The old topic stays bound as a fallback; /unbind it there if you want it gone.
EOF
