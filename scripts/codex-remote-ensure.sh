#!/bin/zsh
# Ensure the codex app-server daemon (remote control) is running.
# `bootstrap` manages it with a pid-file backend, which nothing restarts at boot
# or after a crash; this is run by launchd at login and every 5 minutes.
# `start` is a no-op when the daemon is already up, so it never restarts it.
CODEX="${CODEX_BIN:-$(command -v codex || echo "$HOME/.local/bin/codex")}"
for i in {1..20}; do
  if $CODEX app-server daemon version 2>/dev/null | grep -q '"status":"running"'; then exit 0; fi
  echo "$(date '+%F %T') daemon not running, starting (attempt $i)"
  $CODEX remote-control start
  sleep 15
done
echo "$(date '+%F %T') daemon still not running after 20 attempts"; exit 1
