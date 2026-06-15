#!/usr/bin/env bash
# Tests claude-tui-backend-multi routing WITHOUT launching a TUI: a stub stands
# in for claude-relay-group (via RELAY_GROUP_CMD) and echoes the folder, the
# final PROMPT, and the exported RELAY_CHAT_ID / RELAY_THREAD_ID.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCRIPTS="$(dirname "$DIR")"
BACKEND="$SCRIPTS/claude-tui-backend-multi"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

STUB="$TMP/stub"; cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
echo "FOLDER=$1"
echo "PROMPT=$2"
echo "RELAY_CHAT_ID=$RELAY_CHAT_ID"
echo "RELAY_THREAD_ID=$RELAY_THREAD_ID"
EOF
chmod +x "$STUB"

fails=0
check() { if [ "$2" = "$3" ]; then echo "[ok  ] $1"; else echo "[FAIL] $1: expected [$2] got [$3]"; fails=$((fails+1)); fi; }

run() {  # <bound_peer> <current_message>  -> sets global OUT
  local peer="$1" msg="$2"
  local prompt="Conversation info (untrusted metadata):
\`\`\`json
{ \"chat_id\": \"telegram:-1003550185469:topic:816\", \"topic_id\": \"816\", \"sender_id\": \"110123423\" }
\`\`\`

Conversation context (untrusted, chronological, selected for current message):
#100 Sun PDT Pouya M: an earlier message

$msg"
  OUT="$(RELAY_GROUP_CMD="$STUB" bash "$BACKEND" "$TMP/folder" "$peer" "$prompt" 2>&1)"
}
get() { printf '%s\n' "$OUT" | grep "^$1=" | head -1 | cut -d= -f2-; }

# 1) /cc forwarding converts to a TUI slash command
run "-1003550185469:topic:816" "/cc model"
check "/cc model -> /model"                 "/model"          "$(get PROMPT)"
check "RELAY_CHAT_ID numeric (topic split)" "-1003550185469"  "$(get RELAY_CHAT_ID)"
check "RELAY_THREAD_ID = topic"             "816"             "$(get RELAY_THREAD_ID)"

# 2) cc with an arg
run "-1003550185469:topic:816" "cc model sonnet"
check "cc model sonnet -> /model sonnet"    "/model sonnet"   "$(get PROMPT)"

# 3) a normal message passes through unchanged (and is extracted from the prompt)
run "-1003550185469:topic:816" "what files changed?"
check "plain message extracted + unchanged" "what files changed?" "$(get PROMPT)"

# 4) non-forum chat (no topic_id) -> empty thread id, numeric chat
OUT="$(RELAY_GROUP_CMD="$STUB" bash "$BACKEND" "$TMP/folder" "-4884" "Conversation info (untrusted metadata):
\`\`\`json
{ \"chat_id\": \"telegram:-4884\", \"sender_id\": \"110123423\" }
\`\`\`

hi there" 2>&1)"
check "non-forum -> numeric chat"           "-4884"           "$(get RELAY_CHAT_ID)"
check "non-forum -> empty thread"           ""                "$(get RELAY_THREAD_ID)"
check "non-forum -> message extracted"      "hi there"        "$(get PROMPT)"

echo
if [ "$fails" -eq 0 ]; then echo "backend: all passed"; else echo "backend: $fails failed"; fi
exit $fails
