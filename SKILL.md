---
name: "claude-code-relay"
description: "Bind Telegram groups to per-folder interactive Claude Code sessions on a Max subscription via OpenClaw: clean replies, slash commands, button menus."
metadata:
  type: integration
---

# Claude Code relay (subscription-billed)

Run **Claude Code on your Max/Pro subscription** through OpenClaw by driving the
**interactive `claude` TUI** in tmux, instead of `claude -p` (which after the
June 2026 split bills to a separate metered Agent-SDK pool). Each Telegram group
binds to one **project folder**; messages pipe to that folder's persistent Claude
session and replies come back as clean text.

## When to use

Setting up / operating a Telegram-group → Claude-Code bridge that stays on the
flat subscription. Handlers below (`/new-claude-code`, `/cc`, `/unbind-claude-code`,
`/claude-code-status`) should be answered by whatever agent receives them.

## Honest caveats (read first)

- **ToS-grey.** Automating the interactive client with no human watching each turn
  is the same signal Anthropic uses to move usage to the metered pool. It may be
  detected/blocked. Use deliberately.
- **Scraping, not an API.** Output is parsed from the terminal pane. Robust for
  normal replies, lists, code, prose, and selection menus; not bulletproof.
- **Per-group only.** Telegram route bindings have no topic dimension — one
  folder per group; different folder = different group.
- **Model switching:** `cc model sonnet` (direct arg). Tapping a `/model` picker
  button answers in text and does NOT switch the model.

## Install

1. Copy `scripts/` somewhere stable (e.g. `~/.openclaw/workspace/scripts`). They
   self-locate, so siblings + `relay-work/`, `relay-codes.json`,
   `relay-claude-settings.json` must sit together. `chmod +x` the executables.
2. Symlink remote-control onto PATH: `ln -sf <dir>/claude-attach ~/.local/bin/claude-attach`.
3. Enable native Telegram buttons in `~/.openclaw/openclaw.json`:
   `channels.telegram.capabilities.inlineButtons: "all"` then restart.
4. Optional global memory in bound sessions: set `autoMemoryDirectory` in
   `relay-claude-settings.json` to your Claude memory dir
   (`~/.claude/projects/<encoded-cwd>/memory`), or delete that line to skip.
   Needed because a folder that is its own git repo otherwise gets empty local memory.
5. BotFather → `/setprivacy` → **Disable** for the bot, so it receives ALL group
   messages, not just commands.
6. Add the handler block below to the workspace `AGENTS.md` so any session can bind.
7. Issue codes: add `"123456": "/abs/folder"` lines to `relay-codes.json`.

## Handlers (add to AGENTS.md)

`/new-claude-code <6-digit-code>` in a group → derive peer id from this
message's `chat_id` (part after `telegram:`), then run:
`python3 <dir>/bind-claude-code.py --peer="<peerId>" --code=<code> --restart`
(use the `=` form — group ids start with `-` and argparse treats a space-separated
value as a flag). The binder patches `openclaw.json` additively (backup +
schema-validate + auto-rollback + restart only if valid).

`/claude-code-status` → `python3 <dir>/claude-code-admin.py status`.

`/unbind-claude-code` in a bound group → `python3 <dir>/claude-code-admin.py
unbind --peer="<peerId>" --restart` (reverts the chat to the default agent).

## How a bound chat works

OpenClaw routes the group to a `claude-tui-<slug>` cliBackend = `claude-tui-backend-multi`:
1. Extracts the real user message from OpenClaw's composed prompt (`relay-extract-message.py`).
2. `cc <command>` / `/cc <command>` → forwards a slash command to the TUI
   (OpenClaw eats real slash commands before the backend).
3. `claude-relay-group` reuses (or spawns) the per-folder tmux session, keyed by
   folder md5; resumes history via `claude --continue`.
4. `claude-relay-send.py` types the message, waits for the turn, returns clean text.

## Menus → native Telegram buttons

When Claude shows a selection menu (its question tool, `/model` picker), the relay
posts native inline buttons (`openclaw message send --presentation` with
`blocks→buttons→{label,value}`; `value="ccsel:N"`). A tap returns to the agent as
text `callback_data: ccsel:N`. Selection is **race-free**: dismiss the menu and
answer Claude in plain text with the option label (keystroke injection into a live
menu picks the wrong option). Buttons are then removed via a text-only
`message edit` (drops the keyboard) showing `✓ <pick>`.

## Remote control

`claude-attach <code|folder|--list>` attaches to the live tmux Claude TUI for full
interactive control (slash commands, any menu, plan approvals). Detach: Ctrl-b
then d. Must run as the user who owns the tmux session (the gateway user).
