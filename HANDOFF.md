# HANDOFF — claude-code-relay

Context handoff from a Claude Code session (2026-07-16). Read this before acting.
The previous agent's conversation history does NOT carry over; this file is the transfer.

## What this project is

`claude-code-relay` drives **interactive** Claude Code TUI sessions in `tmux` and relays
them to Telegram via OpenClaw. It exists for one reason: as of the June 2026 split,
headless `claude -p` bills to a **metered pool**, while only the **interactive client**
draws on the flat Max subscription. So the relay screen-scrapes a real TUI instead of
calling an API.

Everything ugly in this repo (tmux, scraping, busy-detection, Stop hooks) is downstream
of that one constraint. Kimi Code does NOT have this constraint — it bills flat-rate even
headless (`kimi -p`), so a Kimi backend needs none of this machinery.

## Two-copy architecture (read this before editing anything)

- **LIVE** (what actually runs): `/Users/pouya/.openclaw/workspace/scripts/`
- **REPO** (git): `/Users/pouya/.openclaw/workspace/claude-code-relay/scripts/`

They are separate copies. Port changes by **logical edit, not file copy** — the live copy
carries annotations the repo doesn't.

## Key facts that cost outages to learn

See `docs/GOTCHAS.md` for the full list. The load-bearing ones:

- **Session keying:** tmux session = `cr-$(md5(WORKDIR)[:10])`, watcher = `crw-${KEY#cr-}`.
  A "throwaway" session launched in a bound folder **IS** that folder's real session.
  This destroyed a live 2,386-message context once. Never test on a bound folder.
- **Model-key routing:** OpenClaw model keys are `<backend>/relay`. The part **before**
  the `/` is how the gateway resolves the cliBackend — it is NOT a display label.
  Renaming to `relay/<x>` silently drops ALL messages to bound topics.
- **`/model` is gated** on large cached conversations ("re-read full history?"), so a
  one-shot `/model X` silently reports "Kept model as …". The reliable switch is a
  **relaunch**: `claude --model <name> --continue`.
- **`--continue` picks newest transcript**, so an empty test session can hijack a resume.
  Use `lastSessionId`; transplanted transcripts need `--resume`, not `--continue`.
- **The relay fails silently.** "No error" is never evidence it worked. Verify, then claim.
- **zsh `:t` modifier:** `"$CHAT:topic:$TID"` silently becomes `<chat>opic:<tid>`.
  Always brace: `"${CHAT}:topic:${TID}"`.
- **Outbound media** only delivers from allowlisted dirs (`~/.openclaw/media/outbound`,
  the workspace) — never `/tmp`.

## Working discipline (the user asked for this explicitly)

The user's standing feedback, after a run of regressions: *"Why every time you do
something there is a regression?"* The causes were always the same three:

1. Acting on assumption instead of verifying the mechanism first.
2. Testing on live/bound resources.
3. Claiming done before checking.

So: read the mechanism before changing it; one destructive change at a time with the
rollback identified; **believe the user over your own model of the system.**

## Current state (2026-07-16)

- Panic button exists: `scripts/openclaw-restore-stable` reverts to the blessed
  `~/.openclaw/backups/openclaw.json.STABLE`.
- Provider-grouping is **inert by design** — see `docs/provider-grouping-plan.md`. The
  legitimate path is `api.registerCliBackend` with `modelProvider`. A previous naive
  attempt broke all routing and was reverted (`b93bacd`).
- `cc model <name>` = restart-based switch + read-back verification.

## Kimi as an ALT model (RESOLVED — working, verified 2026-07-16)

**Claude Code runs on Kimi directly. No proxy, no shim, no `kimi` CLI in the loop.**

The key fact: **Moonshot's platform API and Kimi Code's coding gateway are different
products with different auth.** Aiming a Kimi Code key at Moonshot's platform gives a
misleading `401 Invalid Authentication` that looks like a bad key. It isn't — it's the
wrong service.

- **Working endpoint:** `https://api.kimi.com/coding/v1` — **natively Anthropic-shaped**.
  Returns real `msg_…` / `type: message` / content blocks. Both `x-api-key` and
  `Authorization: Bearer` authenticate. Found by grepping base URLs out of the CLI binary.
- **Does NOT work:** `api.moonshot.ai/anthropic/v1/messages` and `api.moonshot.cn/...`
  (platform API, wants a platform key), and `kimi server` (`/v1/messages` → **404**; it is
  an **agent-level** server — `{websocket, file_upload, fs_query, mcp, tasks, terminal}` —
  not a model-level one).
- **Do not build a `kimi -p` → Anthropic shim.** Claude Code needs a *model* endpoint: it
  sends tool definitions and expects `tool_use` blocks. `kimi -p` is an *agent* with its
  own prompt/tools/loop — it ignores those definitions and returns prose, so Claude's
  agentic loop dies. Agent-inside-an-agent. This was investigated and rejected.
- **Models** (`GET /coding/v1/models`): `kimi-for-coding` (K2.7, ctx 262144),
  `kimi-for-coding-highspeed`, `k3` (K3, ctx 262144).

### How it is wired

`settings_for_model()` in `claude-relay-send.py` is generic: `cc model <name>` looks for
`relay-claude-settings-<name>.json` and, if present, uses it + the `model` inside it.
Otherwise it falls back to the default settings + subscription auth, **untouched**.

So adding an ALT model is just adding a settings file. Live files (with the real key):

- `scripts/relay-claude-settings-kimi.json` → `kimi-for-coding`
- `scripts/relay-claude-settings-k3.json` → `k3`

Verified: `cc model kimi` → `kimi-for-coding`; `cc model k3` → `k3`; **default → Claude
Opus 4.8 on the subscription, with no `env` override.** The isolation is the whole point —
do not add an `env` block to the default settings file.

### Rules

- **The key is a secret.** Live ALT settings carry it; `workspace/.gitignore` has
  `scripts/relay-claude-settings-*.json` so `git add -A` can't sweep it in (the default
  `relay-claude-settings.json` has no dash-suffix and is deliberately NOT matched).
  **Repo copies must stay `REPLACE_WITH_…` placeholders — never commit the key.**
- **`ANTHROPIC_BASE_URL` disables Remote Control + voice dictation** (they need a claude.ai
  identity) and takes precedence over the saved Max login while set. Expected, not a bug.
- Kimi ALT sessions do **not** draw on the Max subscription; they bill the Kimi plan.

## Kimi CLI specifics (only if you ever use `kimi` itself — not needed for the above)

- Global instructions: `$KIMI_CODE_HOME/AGENTS.md`, else `~/.kimi-code/AGENTS.md`.
  **Kimi does NOT read `CLAUDE.md` at runtime** — it is only a `kimi migrate` source.
- Project instructions: `<project root>/AGENTS.md` (native), `.kimi-code/AGENTS.md`.
- Kimi treats `AGENTS.md` as *reference data, not a privileged instruction channel*.
- Config: `~/.kimi-code/config.toml`; auth via `kimi login` (device-code, user-only).
- `kimi migrate` imports `~/.claude/CLAUDE.md` + `~/.claude/skills/` → `~/.kimi-code/`.
- Note: Claude's **auto-memory** (`autoMemoryDirectory`) is Claude-specific and has no
  Kimi equivalent — `AGENTS.md` is static text, not a self-writing memory.

## Open / pending

- Latent landmine: `BOOTSTRAP.md` is missing from `workspace/hardware` while an
  attestation exists → a WorkspaceVanished failure waiting to happen. Flagged, untouched.
- `media/outbound` has ~299 files and no retention sweep.
