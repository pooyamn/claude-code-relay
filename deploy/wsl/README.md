# Moving the relay to WSL2 (no OpenClaw)

ccrelayd replaces OpenClaw for the relay: it polls the bot, routes each
chat/topic to its bound folder, and calls the same backend. Everything else
(tmux sessions, watchers, codex over the remote-control daemon) is unchanged.

## What stops working

Only OpenClaw's own assistant: DMs with the bot, unbound groups, heartbeats and
its cron jobs (nightly mail digest, grand-plan watcher, anthropic-auth-sync).
Bound topics keep working.

## Before you start

- The Windows PC must reach the bench Mac (same LAN or Tailscale). The Mac VM is
  reached through it (`ProxyJump`, see `pull-from-mac.sh`), and `ssh bench`
  needs a new `HostName`: `192.168.64.1` exists only from inside the Mac's VM network.
- Decide the bot: keep the current one (its token from `~/.openclaw/openclaw.json`,
  `channels.telegram.botToken`) so every chat stays as it is, or move to a new one
  and re-add it to each group. Only ONE program may poll a bot token at a time.

## Steps

1. **Windows:** `wsl --install -d Ubuntu-24.04`, then in elevated PowerShell run
   `keep-wsl-alive.ps1` (boot task + no idle timeout + no sleep).
2. **WSL, as root:** `sudo bash setup-wsl.sh root`, then in PowerShell
   `wsl --shutdown` and reopen (systemd and the `pouya` user with home
   `/Users/pouya` take effect).
3. **WSL, as pouya:** `bash setup-wsl.sh user`, then log in by hand:
   `claude`, `codex login`, `gh auth login`.
4. **Copy the data** (Mac stays live): add the `oldvm` ssh alias, then
   `bash pull-from-mac.sh oldvm`. Fix `Host bench` in `~/.ssh/config`.
5. **Config:** copy `prod.json.example` to `~/.config/ccrelay/prod.json`, fill
   in your user id and the open chats (today: `-1004395661179`), and put
   `CCRELAY_BOT_TOKEN=<token>` in `~/.config/ccrelay/env-prod` (chmod 600).
6. **Cutover** (about 15 min):
   1. Wait until no relay turn is running.
   2. On the Mac: stop and disable the OpenClaw gateway
      (`launchctl bootout gui/$(id -u)/ai.openclaw.gateway`), so it stops polling.
   3. `bash pull-from-mac.sh oldvm --final`
   4. `bash setup-wsl.sh enable`
   5. Pair the ChatGPT app with the new machine: `codex remote-control pair`.
   6. Send one message in every bound topic; each must resume its existing
      session (same history), not start a new one.
7. **Rollback** for a week: stop `ccrelayd` on WSL, start the gateway on the Mac.

## Files

| File | Purpose |
|---|---|
| `setup-wsl.sh` | packages, user, wsl.conf, claude/codex/gh, whisper.cpp, services |
| `pull-from-mac.sh` | rsync of workspace, `.claude`, `.codex`, ssh, ccrelay config |
| `export-openclaw-bindings.py` | OpenClaw bindings to ccrelayd's bindings file |
| `systemd/` | ccrelayd, openrouter proxy, codex-daemon and stale-env timers |
| `keep-wsl-alive.ps1` | keeps the distro running on Windows |
