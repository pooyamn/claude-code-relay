#!/usr/bin/env bash
# send-file.sh — zip the given file(s)/folder and send them to THIS session's
# bound Telegram chat via the OpenClaw gateway.
#
# Always zips: OpenClaw/Telegram block many raw file extensions (.hex, .exe, .sh,
# binaries...), but a .zip always gets through. Resolves the destination chat/topic
# automatically from the relay's per-session target file — no need to pass it.
#
# Usage:  send-file.sh <path> [more paths...]
#         SEND_CAPTION="here's the log" send-file.sh ./build.log
set -euo pipefail

OPENCLAW="$(command -v openclaw || echo /opt/homebrew/bin/openclaw)"
RELAY_WORK="$HOME/.openclaw/workspace/scripts/relay-work"

[ "$#" -ge 1 ] || { echo "usage: send-file.sh <path> [path...]" >&2; exit 2; }

# --- resolve this session's Telegram target (chat id + optional topic thread) ---
KEY="${CLAUDE_RELAY_SESSION:-$(tmux display-message -p '#S' 2>/dev/null || true)}"
TARGET="$RELAY_WORK/target-$KEY.json"
[ -f "$TARGET" ] || {
  echo "send-file: no relay target for session '$KEY' ($TARGET)." >&2
  echo "send-file: are you running inside a relay-bound Claude Code session?" >&2
  exit 1
}
CHAT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("chat",""))' "$TARGET")"
THREAD="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("thread",""))' "$TARGET")"
[ -n "$CHAT" ] || { echo "send-file: no chat id in $TARGET" >&2; exit 1; }

# --- validate inputs ---
for f in "$@"; do [ -e "$f" ] || { echo "send-file: not found: $f" >&2; exit 1; }; done

# --- always zip ---
# Write under media/outbound: OpenClaw only delivers media from allowlisted dirs
# (the workspace and ~/.openclaw/media/*), NOT from .openclaw/tmp or /tmp.
TS="$(date +%Y%m%d-%H%M%S)"
OUTDIR="$HOME/.openclaw/media/outbound"
mkdir -p "$OUTDIR"
if [ "$#" -eq 1 ]; then
  nm="$(basename "$1")"; ZIP="$OUTDIR/${nm%.*}-$TS.zip"
else
  ZIP="$OUTDIR/files-$TS.zip"
fi
rm -f "$ZIP"
if [ "$#" -eq 1 ] && [ -d "$1" ]; then
  ( cd "$(dirname "$1")" && zip -q -r "$ZIP" "$(basename "$1")" )   # keep folder structure
else
  zip -q -j "$ZIP" "$@"                                             # flat zip of files
fi

# --- send via the gateway ---
ARGS=(message send --channel telegram --target "$CHAT" --media "$ZIP" --force-document)
[ -n "$THREAD" ] && ARGS+=(--thread-id "$THREAD")
ARGS+=(--message "${SEND_CAPTION:-📦 $(basename "$ZIP")}" --json)

"$OPENCLAW" "${ARGS[@]}"
echo
echo "send-file: sent $(basename "$ZIP") ($(du -h "$ZIP" | cut -f1)) -> chat $CHAT${THREAD:+ topic $THREAD}" >&2
