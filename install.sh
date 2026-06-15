#!/usr/bin/env bash
# Installer for claude-code-relay.
# Idempotent: copies the relay scripts to a stable dir, puts claude-attach on
# PATH, installs + enables the pre-agent command plugin, and enables native
# Telegram buttons (backup + validate + rollback, never strands the gateway).
#
#   ./install.sh                       # installs to ~/.openclaw/workspace/scripts
#   CC_RELAY_DIR=/some/dir ./install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEST="${CC_RELAY_DIR:-$HOME/.openclaw/workspace/scripts}"
CFG="${RELAY_CFG:-$HOME/.openclaw/openclaw.json}"
BIN="$HOME/.local/bin"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!  \033[0m %s\n' "$*"; }

command -v openclaw >/dev/null || { echo "openclaw CLI not found on PATH" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found on PATH" >&2; exit 1; }

# 1. Copy scripts (preserve an existing relay-codes.json — it holds your codes).
say "Copying scripts → $DEST"
mkdir -p "$DEST"
SAVED_CODES=""
[ -f "$DEST/relay-codes.json" ] && SAVED_CODES="$(cat "$DEST/relay-codes.json")"
cp -R "$REPO/scripts/." "$DEST/"
if [ -n "$SAVED_CODES" ]; then
  printf '%s' "$SAVED_CODES" > "$DEST/relay-codes.json"
  say "Kept your existing relay-codes.json"
fi
chmod +x "$DEST"/claude-attach "$DEST"/claude-relay-group "$DEST"/claude-tui-backend-multi 2>/dev/null || true

# 2. Put claude-attach on PATH.
say "Linking claude-attach → $BIN"
mkdir -p "$BIN"
ln -sf "$DEST/claude-attach" "$BIN/claude-attach"
case ":$PATH:" in *":$BIN:"*) :;; *) warn "$BIN is not on PATH — add it to use claude-attach";; esac

# 3. Install + enable the pre-agent command plugin.
PLUGIN="$DEST/openclaw-newcc-plugin"
OPENCLAW_PKG="$(npm root -g 2>/dev/null)/openclaw"
if [ -d "$OPENCLAW_PKG" ]; then
  say "Linking plugin SDK"
  mkdir -p "$PLUGIN/node_modules"
  ln -sfn "$OPENCLAW_PKG" "$PLUGIN/node_modules/openclaw"
else
  warn "Could not locate the global openclaw package for the SDK symlink; the plugin import may fail to resolve."
fi
say "Installing + enabling cc-relay-commands plugin"
openclaw plugins install --link "$PLUGIN" --force >/dev/null 2>&1 || openclaw plugins install --link "$PLUGIN" >/dev/null
openclaw plugins enable cc-relay-commands >/dev/null

# 4. Enable native Telegram inline buttons (safe: backup → validate → rollback).
say "Enabling Telegram inline buttons"
python3 - "$CFG" <<'PY'
import json, sys, os, shutil, subprocess, time
cfg = sys.argv[1]
d = json.load(open(cfg))
caps = d.setdefault("channels", {}).setdefault("telegram", {}).setdefault("capabilities", {})
if caps.get("inlineButtons") == "all":
    print("   inlineButtons already 'all'"); raise SystemExit
bak = f"{cfg}.bak-install-{time.strftime('%Y%m%d-%H%M%S')}"
shutil.copy2(cfg, bak)
caps["inlineButtons"] = "all"
open(cfg, "w").write(json.dumps(d, indent=2))
r = subprocess.run(["openclaw", "config", "validate", "--json"], capture_output=True, text=True)
if '"valid":true' not in r.stdout.replace(" ", ""):
    shutil.copy2(bak, cfg)
    print("   config validation failed, rolled back — set inlineButtons manually"); raise SystemExit(1)
print(f"   set inlineButtons='all' (backup {os.path.basename(bak)})")
PY

cat <<EOF

$(say "Done. Remaining manual steps:")
  1. BotFather → /setprivacy → Disable (so the bot sees all group messages)
  2. openclaw gateway restart        (loads the plugin + button capability)
  3. Add codes to $DEST/relay-codes.json  ("123456": "/abs/path/to/folder")
  4. In a Telegram group/topic: /newcc <code>
EOF
