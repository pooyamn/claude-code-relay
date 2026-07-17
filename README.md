# claude-code-relay

Run **Claude Code from Telegram, on your Max/Pro subscription** — not the metered API.

An [OpenClaw](https://github.com/openclaw/openclaw) skill that binds a Telegram group to a dedicated, persistent **Claude Code** session in a project folder. You chat in the group; Claude Code works in the folder and replies back, with clean text, slash commands, and tappable menus.

## Why this exists

As of the June 2026 split, headless Claude Code (`claude -p` / the Agent SDK) bills to a **separate metered pool**, not your flat subscription. The only thing that still draws on the subscription is the **interactive `claude` client**.

So this skill drives the *interactive* TUI in a `tmux` session and relays it to Telegram. You get Claude Code automation that stays on the plan you already pay for.

## What you get

- **Per-folder sessions.** Each Telegram group binds to one project folder. Messages pipe to that folder's persistent Claude Code session; replies come back clean.
- **Durable + resumable.** The session survives restarts and reboots; it resumes the same conversation via `claude --continue`.
- **Live-streamed replies, one ping.** While a turn runs, progress streams into a **silent** Telegram message (edited in place, starting ~every 1.5s and backing off on long turns to stay under Telegram's edit-rate limit) — no notification spam. When the turn finishes, that progress bubble is **frozen in place** as a record and the clean answer is sent as a **fresh, notifying** message, so you're pinged exactly once: when the reply is ready. (Set `RELAY_STREAM=0` to disable streaming; replies over Telegram's 4096-char cap fall back to a normal chunked send.)
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
- **Model switching:** use `cc model <name>`. It **relaunches the session** with `--model <name> --continue` (context kept) and reads the model back to confirm — a live `/model` is gated on large cached conversations and silently reports "Kept model as …". Tapping a `/model` picker button does **not** switch the model.
### ALT models (Kimi / K3)

`cc model <name>` looks for `scripts/relay-claude-settings-<name>.json`. If it exists, that
model is launched with those settings; **every other model keeps the default settings and
your subscription auth, untouched.** Adding an ALT model is just adding a file.

Shipped templates route to Kimi Code's **natively Anthropic-compatible** gateway
(`https://api.kimi.com/coding`) — no proxy needed:

| file | `cc model …` | model |
|---|---|---|
| `relay-claude-settings-kimi.json` | `cc model kimi` | `kimi-for-coding` (K2.7, 262k ctx) |
| `relay-claude-settings-k3.json` | `cc model k3` | `k3` (K3, 262k ctx) |

Fill in `ANTHROPIC_AUTH_TOKEN` with a **Kimi Code** key (`sk-kimi-…`). Note this is *not* a
Moonshot platform key — `api.moonshot.ai` rejects it with a misleading
`401 Invalid Authentication`. They are different products.

Two caveats: an ALT model bills that provider, **not** your Max subscription; and setting
`ANTHROPIC_BASE_URL` **disables Remote Control and voice dictation** (both need a claude.ai
identity). Keep the key out of git — `relay-claude-settings-*.json` should be gitignored.

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
| `scripts/relay-claude-settings-<name>.json` | optional ALT-model settings (e.g. `kimi`, `k3`) — routes that model to another gateway |
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

## Gotchas

Before changing the relay, read [docs/GOTCHAS.md](docs/GOTCHAS.md) — the mechanisms
that cost an outage to learn (busy states, model switching, model-key routing, session
transplants) plus the working discipline. The relay fails *silently*, so assumptions are
expensive here.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the version history.

## License

MIT
