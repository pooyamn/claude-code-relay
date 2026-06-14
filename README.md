# claude-code-relay

Run **Claude Code from Telegram, on your Max/Pro subscription** — not the metered API.

An [OpenClaw](https://github.com/openclaw/openclaw) skill that binds a Telegram group to a dedicated, persistent **Claude Code** session in a project folder. You chat in the group; Claude Code works in the folder and replies back, with clean text, slash commands, and tappable menus.

## Why this exists

As of the June 2026 split, headless Claude Code (`claude -p` / the Agent SDK) bills to a **separate metered pool**, not your flat subscription. The only thing that still draws on the subscription is the **interactive `claude` client**.

So this skill drives the *interactive* TUI in a `tmux` session and relays it to Telegram. You get Claude Code automation that stays on the plan you already pay for.

## What you get

- **Per-folder sessions.** Each Telegram group binds to one project folder. Messages pipe to that folder's persistent Claude Code session; replies come back clean.
- **Durable + resumable.** The session survives restarts and reboots; it resumes the same conversation via `claude --continue`.
- **Self-serve binding.** `/new-claude-code <code>` in a group binds it (no chat-id wrangling).
- **Slash commands.** `cc model sonnet`, `cc clear`, `cc compact` — forward any Claude Code slash command into the session.
- **Native button menus.** When Claude asks a multiple-choice question (or you open `/model`), the bot posts real tappable Telegram buttons; your tap is delivered as the answer, and the buttons collapse to `✓ <pick>`.
- **Remote control.** `claude-attach <code>` drops you into the live TUI for anything interactive.
- **Global memory + skills.** Bound sessions keep your Claude memory and skills.

## How it works

```
Telegram group ──▶ OpenClaw ──▶ cliBackend (claude-tui-backend-multi)
                                   │  extracts your message, handles `cc`, finds chat id
                                   ▼
                          claude-relay-group   ── per-folder tmux session (claude --continue)
                                   ▼
                          claude-relay-send.py ── types prompt, scrapes the reply,
                                                   turns menus into Telegram buttons
```

Output is read from the terminal pane (there is no API for the interactive client), so the parser is built to be robust: it joins wrapped lines, anchors on Claude's reply marker, rejoins soft-wrapped prose, and strips TUI chrome.

## Install

1. **Copy `scripts/`** somewhere stable, e.g. `~/.openclaw/workspace/scripts`. They self-locate, so the scripts, `relay-codes.json`, and `relay-claude-settings.json` must sit together. `chmod +x` the executables.
2. **Put `claude-attach` on PATH:** `ln -sf <dir>/claude-attach ~/.local/bin/claude-attach`.
3. **Enable native buttons** in `~/.openclaw/openclaw.json`: set `channels.telegram.capabilities.inlineButtons` to `"all"`, then restart the gateway.
4. **(Optional) Global memory:** set `autoMemoryDirectory` in `relay-claude-settings.json` to your Claude memory dir, or delete that line to skip.
5. **Bot privacy off:** BotFather → `/setprivacy` → Disable, so the bot sees every group message (not just commands).
6. **Add the handlers** (below) to your OpenClaw agent's `AGENTS.md` so any session can bind.
7. **Issue codes:** add `"123456": "/abs/path/to/folder"` entries to `relay-codes.json`.

### AGENTS.md handlers

```
/new-claude-code <6-digit-code>   (in the target group)
  → peer id = part after "telegram:" in the inbound chat_id
  → python3 <dir>/bind-claude-code.py --peer="<peerId>" --code=<code> --restart

/claude-code-status               → python3 <dir>/claude-code-admin.py status
/unbind-claude-code  (in a bound group)
  → python3 <dir>/claude-code-admin.py unbind --peer="<peerId>" --restart
```

The binder patches `openclaw.json` additively: backup → schema-validate → auto-rollback → restart only if valid. It can't strand your gateway.

## Usage

| In the group | Result |
|---|---|
| any message | piped to Claude Code, clean reply |
| `cc model sonnet` | runs `/model sonnet` in the session |
| `cc clear` | runs `/clear` |
| Claude asks a question | tappable buttons appear; tap to answer |
| `claude-attach 123456` (terminal) | attach to the live TUI |

## Honest caveats

- **Terms of service.** Automating the interactive client with no human watching each turn is the same signal Anthropic uses to move usage to the metered pool. It may be detected or blocked. Use deliberately and at your own risk.
- **It's screen-scraping, not an API.** Robust for normal replies, lists, code, prose, and selection menus — but not bulletproof. `claude-attach` is the reliable fallback for fiddly interactive sequences.
- **Per-group only.** Telegram route bindings have no topic dimension: one folder per group.
- **Model switching:** use `cc model sonnet` (direct). Tapping a `/model` button answers in text and does **not** switch the model.
- **Privacy:** a bound session carries your global Claude memory and can read the host filesystem via its tools. Only add other people to a bound group if you're comfortable with that.

## Files

| File | Role |
|---|---|
| `scripts/bind-claude-code.py` | bind a group → folder (safe config patcher) |
| `scripts/claude-code-admin.py` | `status` / `unbind` |
| `scripts/claude-tui-backend-multi` | cliBackend entry: chat-id + message extract, `cc` |
| `scripts/claude-relay-group` | per-folder tmux session lifecycle + resume |
| `scripts/claude-relay-send.py` | drive the TUI, scrape replies, menus → buttons |
| `scripts/relay-extract-message.py` | pull the current message from OpenClaw's composed prompt |
| `scripts/claude-attach` | attach to the live TUI |
| `scripts/relay-codes.json` | `{ "code": "/abs/folder" }` registry |
| `scripts/relay-claude-settings.json` | Claude `--settings` (auto-memory dir) |

## License

MIT
