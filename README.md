# claude-code-relay

Run **Claude Code from Telegram, on your Max/Pro subscription** — not the metered API.

An [OpenClaw](https://github.com/openclaw/openclaw) skill that binds a Telegram group to a dedicated, persistent **Claude Code** session in a project folder. You chat in the group; Claude Code works in the folder and replies back, with clean text, slash commands, and tappable menus.

## Why this exists

As of the June 2026 split, headless Claude Code (`claude -p` / the Agent SDK) bills to a **separate metered pool**, not your flat subscription. The only thing that still draws on the subscription is the **interactive `claude` client**.

So this skill drives the *interactive* TUI in a `tmux` session and relays it to Telegram. You get Claude Code automation that stays on the plan you already pay for.

## What you get

- **Per-folder sessions.** Each Telegram group binds to one project folder. Messages pipe to that folder's persistent Claude Code session; replies come back clean.
- **Durable + resumable.** The session survives restarts and reboots; it resumes the same conversation via `claude --continue`.
- **Live-streamed replies.** A turn streams into one Telegram message, edited in place ~every 2s with Claude's progress, then finalized with the clean answer (set `RELAY_STREAM=0` to disable). Replies over Telegram's 4096-char cap fall back to a normal chunked send.
- **Self-serve binding, LLM-free.** `/newcc <code>` binds a group *or a single forum topic*; `/unbind` and `/ccstatus` manage it. These run as **pre-agent** OpenClaw commands (the `cc-relay-commands` plugin), so they never spend a Claude turn and work even on a topic that isn't bound yet.
- **Slash commands.** `cc model sonnet`, `cc clear`, `cc compact` — forward any Claude Code slash command into the session.
- **Native button menus.** When Claude asks a multiple-choice question (or you open `/model`), the bot posts real tappable Telegram buttons; your tap is delivered as the answer, and the buttons collapse to `✓ <pick>`.
- **Remote control.** `claude-attach <code>` drops you into the live TUI for anything interactive.
- **Global memory + skills.** Bound sessions keep your Claude memory and skills.

## How it works

```
Telegram msg ─▶ OpenClaw
                  │
                  ├─▶ cc-relay-commands plugin  (PRE-AGENT, no LLM)
                  │     matches /newcc /unbind /ccstatus, runs the admin
                  │     script, replies, and short-circuits the agent.
                  │     Works on bound OR unbound chats/topics.
                  │
                  └─▶ cliBackend (claude-tui-backend-multi)   [bound chats only]
                        │  extracts your message, handles `cc`, finds chat id
                        ▼
                 claude-relay-group   ── per-folder tmux session (claude --continue)
                        ▼
                 claude-relay-send.py ── types prompt, scrapes the reply,
                                          turns menus into Telegram buttons
```

The admin commands (`/newcc`, `/unbind`, `/ccstatus`) are intercepted by the plugin **before any agent runs**, so the very first bind on a fresh topic is deterministic and LLM-free. Everything else (your actual prompts) flows to the bound folder's session.

Output is read from the terminal pane (there is no API for the interactive client), so the parser is built to be robust: it joins wrapped lines, anchors on Claude's reply marker, rejoins soft-wrapped prose, and strips TUI chrome.

## Install

Quick path — run the installer from the repo root:

```bash
./install.sh
```

It copies `scripts/` to `~/.openclaw/workspace/scripts` (override with `CC_RELAY_DIR`), `chmod +x`'s the executables, puts `claude-attach` on PATH, installs + enables the `cc-relay-commands` plugin (the pre-agent command hook), enables native Telegram buttons, and prints the remaining manual steps. Re-running is safe (idempotent).

Then finish the manual bits the installer can't do for you:

1. **Bot privacy off:** BotFather → `/setprivacy` → Disable, so the bot sees every group message (not just commands).
2. **Restart the gateway:** `openclaw gateway restart` (loads the plugin and applies the button capability).
3. **Issue codes:** add `"123456": "/abs/path/to/folder"` entries to `scripts/relay-codes.json`.
4. **(Optional) Global memory:** set `autoMemoryDirectory` in `relay-claude-settings.json` to your Claude memory dir, or delete that line to skip.

Then in any Telegram group or forum topic, type `/newcc <code>` to bind it.

### How binding is wired

The `cc-relay-commands` plugin registers `/newcc`, `/unbind`, `/ccstatus` as **pre-agent** OpenClaw commands. Each shells out to the deterministic admin scripts — no LLM in the loop, so binding works even before a topic is bound:

```
/newcc <code>   → bind-claude-code.py --peer="<peer>" --code=<code> --restart
/unbind         → claude-code-admin.py unbind --peer="<peer>" --restart
/ccstatus       → claude-code-admin.py status
```

`<peer>` is derived from the inbound message (`<chatId>` for a whole group, `<chatId>:topic:<N>` for a single forum topic). The binder patches `openclaw.json` additively: backup → schema-validate → auto-rollback → restart only if valid. It can't strand your gateway.

> No-plugin fallback: if you can't run a plugin, the same three commands can be wired as `AGENTS.md` handlers instead, but then the *first* bind on an unbound topic passes through the agent once.

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
- **Per-group or per-topic.** Bind a whole group (`/newcc` posts the group peer) or a single forum topic (the peer carries `:topic:<N>`). A group-level binding catches every topic in that group, so for a multi-project forum bind each topic explicitly.
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
| `scripts/openclaw-newcc-plugin/` | OpenClaw plugin: pre-agent `/newcc` `/unbind` `/ccstatus` |
| `install.sh` | one-shot installer (copy scripts, install plugin, enable buttons) |

## Tests

Pure unit/routing tests, no tmux/Telegram/network required:

```bash
bash scripts/tests/run_tests.sh
```

- `test_extract.py` — message extraction across real OpenClaw prompt shapes (context block, `Current message:` + reply, first-message, legacy envelopes).
- `test_backend.sh` — backend routing: `/cc` → `/model` forwarding, numeric chat id + topic thread split, message extraction. Uses a stub for the TUI hop (`RELAY_GROUP_CMD`).
- `test_send_helpers.py` — `progress_snapshot` (the live streamed view), menu parsing, thread addressing.

## License

MIT
