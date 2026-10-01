#!/usr/bin/env bash
# Run ON WSL as pouya: copy the relay's data from the Mac VM with rsync over ssh.
#
#   bash pull-from-mac.sh <ssh-host>            # full copy (run while still live)
#   bash pull-from-mac.sh <ssh-host> --final    # cutover: only the fast-changing state
#
# <ssh-host> is an ~/.ssh/config alias for the Mac VM. The VM sits on the Mac's
# private VM network (192.168.64.x), so from Windows it is reached THROUGH the
# bench Mac, e.g.:
#   Host oldvm
#     HostName 192.168.64.<vm>
#     User pouya
#     ProxyJump oracova@<bench Mac LAN or Tailscale address>
#
# Skipped on purpose: node_modules/.venv/__pycache__ (built for macOS arm64,
# rebuilt here), ~/.codex/packages (macOS codex binaries) and the codex daemon's
# runtime files (pids, sockets, locks belong to the old machine).
set -euo pipefail
SRC="${1:?ssh host alias for the Mac VM}"
FINAL="${2:-}"
R=(rsync -aH --info=progress2 --partial)
X=(--exclude node_modules --exclude .venv --exclude __pycache__ --exclude .DS_Store)

if [ "$FINAL" = "--final" ]; then
  # Small, fast-moving state only: sessions, pins, transcripts.
  "${R[@]}" "$SRC:.openclaw/workspace/scripts/relay-work/" ~/.openclaw/workspace/scripts/relay-work/
  "${R[@]}" "$SRC:.claude/projects/" ~/.claude/projects/
  "${R[@]}" "$SRC:.claude/sessions/" ~/.claude/sessions/ || true
  "${R[@]}" "$SRC:.claude.json" ~/.claude.json
  "${R[@]}" "$SRC:.codex/sessions/" ~/.codex/sessions/
  "${R[@]}" "$SRC:.codex/archived_sessions/" ~/.codex/archived_sessions/
  # thread index/history live in SQLite: copy each db WITH its -wal/-shm, after
  # codex on the Mac is idle, or the copy can miss the newest threads.
  "${R[@]}" "$SRC:.codex/*.sqlite*" "$SRC:.codex/session_index.jsonl" "$SRC:.codex/history.jsonl" ~/.codex/
  exit 0
fi

mkdir -p ~/.openclaw ~/.codex ~/.ssh
"${R[@]}" "${X[@]}" "$SRC:.openclaw/workspace/" ~/.openclaw/workspace/
"${R[@]}" "$SRC:.openclaw/whisper-models/" ~/.openclaw/whisper-models/
"${R[@]}" "${X[@]}" --exclude 'shell-snapshots' "$SRC:.claude/" ~/.claude/
"${R[@]}" "$SRC:.claude.json" ~/.claude.json
"${R[@]}" --exclude packages --exclude app-server-daemon --exclude app-server-control \
  --exclude thread-writer-locks --exclude 'tmp' --exclude ipc \
  --exclude installation_id "$SRC:.codex/" ~/.codex/
# installation_id is left behind on purpose: it identifies THIS machine to
# remote control, and two machines sharing one would fight over the pairing.
"${R[@]}" "$SRC:.ssh/" ~/.ssh/ && chmod 700 ~/.ssh && chmod 600 ~/.ssh/* 2>/dev/null || true
"${R[@]}" "$SRC:.gitconfig" ~/.gitconfig || true
"${R[@]}" "$SRC:.config/ccrelay/" ~/.config/ccrelay/
# The bindings, converted from OpenClaw's config on the Mac side.
ssh "$SRC" 'python3 ~/.openclaw/workspace/claude-code-relay/deploy/wsl/export-openclaw-bindings.py' \
  > ~/.config/ccrelay/bindings-prod.json
echo "copied. bindings: $(python3 -c 'import json,os;print(len(json.load(open(os.path.expanduser("~/.config/ccrelay/bindings-prod.json")))))')"
