#!/usr/bin/env bash
# send-file.sh — send file(s)/folder(s) to THIS session's bound Telegram chat via
# the OpenClaw gateway. Sends RAW when the gateway will accept the file as-is, and
# falls back to a zip when it won't.
#
# Why not always zip (the old behaviour): the gateway accepts host-local media that
# it can buffer-verify as "images, audio, video, PDF, Office documents, archives, and
# validated plain-text documents". Everything else is refused as `unknown`. That is a
# CONTENT sniff, not an extension blocklist -- so a PDF, a log or a screenshot never
# needed wrapping, and zipping them cost the real filename, inline image preview, and
# an unzip step on the phone. Measured 2026-08-07: .txt sent raw, PDF sent raw,
# .hex refused as unknown.
#
# So: try raw, and zip only what actually needs it. The zip fallback is automatic and
# also covers any type this script's sniff gets wrong -- a raw refusal must never mean
# an undelivered file.
#
# Usage:  send-file.sh <path> [more paths...]
#         SEND_CAPTION="here's the log"  send-file.sh ./build.log
#         SEND_ZIP=1                     send-file.sh ./a.pdf ./b.pdf   # force one zip
#         SEND_PHOTO=1                   send-file.sh ./shot.png        # inline preview
#
# Images go as DOCUMENTS by default. Telegram re-encodes an inline photo (that is
# what --force-document exists to avoid), and these are usually schematics, plots or
# TUI screenshots where the detail that gets crushed is the whole point of sending
# it. SEND_PHOTO=1 opts back into the compressed inline preview when the picture is
# meant to be glanced at rather than read.
set -uo pipefail

OPENCLAW="$(command -v openclaw || echo /opt/homebrew/bin/openclaw)"
RELAY_WORK="$HOME/.openclaw/workspace/scripts/relay-work"
OUTDIR="$HOME/.openclaw/media/outbound"

[ "$#" -ge 1 ] || { echo "usage: send-file.sh <path> [path...]" >&2; exit 2; }

# --- resolve THIS session's Telegram target; refuse unless we are clearly inside a
# relay-bound CC session ---
# CRITICAL: only ask tmux for the session name when actually attached to a tmux
# client ($TMUX set). A bare `tmux display-message` from a NON-tmux context (e.g. an
# OpenClaw agent session) returns the most-recent tmux session -- a cr-* relay
# session -- which misroutes the file to that session's bound chat. That was the bug.
KEY=""
if [ -n "${TMUX:-}" ]; then
  KEY="$(tmux display-message -p '#S' 2>/dev/null || true)"
fi
case "$KEY" in
  cr-[0-9a-f]*) : ;;   # a real relay session name (cr-<md5[:10]>)
  *)
    echo "send-file: not inside a relay-bound Claude Code session (session='${KEY:-none}')." >&2
    echo "send-file: refusing, so the file can't be delivered to the wrong chat." >&2
    echo "send-file: if you are an OpenClaw agent, send with your OWN native media send" >&2
    echo "           (the message tool's media/mediaUrl/path fields), not this relay skill." >&2
    exit 3
    ;;
esac
TARGET="$RELAY_WORK/target-$KEY.json"
[ -f "$TARGET" ] || {
  echo "send-file: no relay target for session '$KEY' ($TARGET)." >&2
  echo "send-file: this session isn't bound; refusing rather than guessing a chat." >&2
  exit 1
}
CHAT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("chat",""))' "$TARGET")"
THREAD="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("thread",""))' "$TARGET")"
[ -n "$CHAT" ] || { echo "send-file: no chat id in $TARGET" >&2; exit 1; }

for f in "$@"; do [ -e "$f" ] || { echo "send-file: not found: $f" >&2; exit 1; }; done
mkdir -p "$OUTDIR"
TS="$(date +%Y%m%d-%H%M%S)"

# --- send one already-staged file -------------------------------------------------
# $1 path (must be under an allowed dir)  $2 caption  $3 "photo"|"doc"
send_one() {
  local path="$1" cap="$2" mode="$3"
  local args=(message send --channel telegram --target "$CHAT" --media "$path")
  [ "$mode" = doc ] && args+=(--force-document)
  [ -n "$THREAD" ] && args+=(--thread-id "$THREAD")
  args+=(--message "$cap" --json)
  "$OPENCLAW" "${args[@]}" 2>&1
}

# The gateway only reads media from allowlisted dirs (the workspace and
# ~/.openclaw/media/*); /tmp is refused outright. Copy anything else in, keeping the
# real filename so the user receives "sheet-1-core.pdf", not a timestamped archive.
stage() {
  local src="$1"
  case "$src" in
    "$HOME/.openclaw/workspace/"*|"$HOME/.openclaw/media/"*) printf '%s' "$src"; return ;;
  esac
  local dst="$OUTDIR/$(basename "$src")"
  cp -f "$src" "$dst" 2>/dev/null && printf '%s' "$dst" || printf '%s' "$src"
}

# Mirror of the gateway's accepted classes. Deliberately conservative: a wrong "yes"
# only costs one failed attempt (we then zip), a wrong "no" costs a needless zip.
raw_ok() {
  local mime; mime="$(file -b --mime-type "$1" 2>/dev/null)"
  case "$mime" in
    image/*|audio/*|video/*|text/*) return 0 ;;
    application/pdf|application/zip|application/gzip|application/x-tar|application/x-7z-compressed|application/x-bzip2) return 0 ;;
    application/msword|application/vnd.openxmlformats-officedocument.*|application/vnd.ms-*|application/vnd.oasis.opendocument.*) return 0 ;;
    *) return 1 ;;
  esac
}
is_image() { case "$(file -b --mime-type "$1" 2>/dev/null)" in image/*) return 0 ;; *) return 1 ;; esac; }

zip_and_send() {   # $@ = paths to archive together
  local zip
  if [ "$#" -eq 1 ]; then
    local nm; nm="$(basename "$1")"; zip="$OUTDIR/${nm%.*}-$TS.zip"
  else
    zip="$OUTDIR/files-$TS.zip"
  fi
  rm -f "$zip"
  if [ "$#" -eq 1 ] && [ -d "$1" ]; then
    ( cd "$(dirname "$1")" && zip -q -r "$zip" "$(basename "$1")" )   # keep structure
  else
    zip -q -j "$zip" "$@"
  fi
  local out; out="$(send_one "$zip" "${SEND_CAPTION:-📦 $(basename "$zip")}" doc)"
  if printf '%s' "$out" | grep -q "Error"; then
    echo "send-file: FAILED to send $(basename "$zip")" >&2; printf '%s\n' "$out" >&2; return 1
  fi
  echo "send-file: sent $(basename "$zip") ($(du -h "$zip" | cut -f1), zipped) -> chat $CHAT${THREAD:+ topic $THREAD}" >&2
}

# --- decide per input -------------------------------------------------------------
# Folders and unknown binaries are collected and zipped together; everything the
# gateway accepts goes raw, one message each, keeping its own name and (for images)
# an inline preview instead of a download.
NEEDS_ZIP=(); RAW=()
if [ "${SEND_ZIP:-0}" = "1" ]; then
  NEEDS_ZIP=("$@")
else
  for f in "$@"; do
    if [ -d "$f" ] || ! raw_ok "$f"; then NEEDS_ZIP+=("$f"); else RAW+=("$f"); fi
  done
fi

rc=0
for f in "${RAW[@]:-}"; do
  [ -n "$f" ] || continue
  staged="$(stage "$f")"
  mode=doc
  { [ "${SEND_PHOTO:-0}" = "1" ] && is_image "$staged"; } && mode=photo
  out="$(send_one "$staged" "${SEND_CAPTION:-$(basename "$f")}" "$mode")"
  if printf '%s' "$out" | grep -q "Error"; then
    # The gateway refused it despite our sniff -- zip that one file rather than lose it.
    echo "send-file: raw send refused for $(basename "$f"), falling back to zip" >&2
    zip_and_send "$f" || rc=1
  else
    echo "send-file: sent $(basename "$f") ($(du -h "$f" | cut -f1), raw${mode:+, $mode}) -> chat $CHAT${THREAD:+ topic $THREAD}" >&2
  fi
done

if [ "${#NEEDS_ZIP[@]}" -gt 0 ] && [ -n "${NEEDS_ZIP[0]:-}" ]; then
  zip_and_send "${NEEDS_ZIP[@]}" || rc=1
fi
exit $rc
