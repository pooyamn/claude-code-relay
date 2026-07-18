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
  `kimi-for-coding-highspeed` (262144), `k3` (now **ctx 1048576 / 1M** on the upgraded plan).

### Context window: the wedge trap and the 1M override (verified 2026-07-17)

The plan's context cap and **Claude Code's assumed window are two different limits**, and
mismatches between them are what wedge a session.

- Claude Code sizes its auto-compact threshold to the window it *thinks* the model has.
  For a non-Anthropic model it isn't in the registry, so it defaults to **200k**
  (confirmed via `/context`: a fresh k3 session showed `25.4k/200k`).
- **How the wedge happened once:** a session ran 395 msgs on `claude-fable-5` (1M window),
  grew past 256k, then `cc model k3` dropped that oversized conversation onto k3's *old*
  256k plan cap → every request 401'd, and `/compact` couldn't run (it sends the whole
  conversation, the exact thing that's too big). Only a relaunch escapes.
- **Override (found by disassembling the resolver `rFc`):**
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS=<n>` sets the window for any model whose id does **not**
  start with `claude-`, *without* disabling auto-compact. (There is a second, higher-prio
  branch that also reads this var but only when `DISABLE_COMPACT` is set — not the one we
  use.) The `!startsWith("claude-")` guard means it can never affect opus/fable/sonnet.
- **What is wired:** `relay-claude-settings-k3.json` carries
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000`. Verified on a scratch folder: `/context` shows
  `25.4k/1m`, auto-compact still on (triggers ~920k, safely under the 1M hard cap).
- **`kimi-for-coding` deliberately has NO override** — its plan cap is 256k, and Claude
  Code's default 200k is already under it, so it is safe and never wedges. Do not add the
  1M override to it; that would re-create the trap.

Rule of thumb: `CLAUDE_CODE_MAX_CONTEXT_TOKENS` must stay **below the model's plan cap**,
and auto-compact then keeps you clear of even that. Never set it above the cap.

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

## Native Kimi backend — `cc model ik3` (added 2026-07-18, tested)

Two ways to run Kimi now exist, and they are DIFFERENT:
- `cc model kimi` / `cc model k3` — **claude** pointed at Kimi's Anthropic-compatible
  gateway (the ALT-settings section above). Still the `claude` binary.
- `cc model ik3` — **native Kimi Code** (`i` = native): the relay drives the **`kimi`
  binary** in tmux instead of `claude`. Uses Kimi's OAuth login + `~/.kimi-code/config.toml`.

### How it works (isolated backend branch in `claude-relay-send.py`)

The scraper is deeply `claude`-coupled (reply marker `⏺`, ready `for agents`, busy
`esc to interrupt`, input cursor `❯`). Kimi's TUI differs in EVERY one of those. Rather
than thread a flag through claude's working code, kimi is an **isolated additive branch**
— the claude path is byte-for-byte unchanged (verified: full test suite passes clean).

Mechanism:
- `backend-<session>.json` records the live backend per session (`restart_with_model`
  writes it; re-read each poll so a mid-life `cc model` switch is seen). `is_kimi()` reads it.
- `BUSY`/`READY` were **extended**, not branched: kimi's moon/braille spinner and
  `context: N% (a/b)` gauge can NEVER appear in a claude pane, so merging those alternations
  leaves all ~12 claude call sites semantically identical while making busy/idle work for
  kimi. (Do NOT add `working...` text to BUSY — it can appear in a kimi answer and would
  wedge delivery; spinner glyphs are the safe signal.)
- Only extraction is branched: `_reply_lines` → `kimi_reply_lines(pane_color(...), prompt)`,
  `count_marker` → counts `●`, `current_model` → reads the footer `yolo <M> thinking:`.
- **Thinking vs answer split is by COLOR** (empirically characterised, NOT guessed): kimi
  renders thinking grey-italic `ESC[38;2;136;136;136m` and the answer bright
  `ESC[38;2;224;224;224m`, both with a `●` bullet. `kimi_reply_lines` captures with
  `capture-pane -ep` (color) and drops the grey lines. Proven on real bullet/prose/code
  answers.
- Launch: `kimi -m kimi-code/k3 -c --yolo` (no `--settings`, no trust dialog; `-c`=continue,
  `--yolo`=auto-approve). `KIMI_BIN` resolved to an absolute path (gateway PATH is minimal).
- Declared by `relay-claude-settings-ik3.json` = `{"backend":"kimi","model":"kimi-code/k3",
  "label":"K3"}`. **No secret in it** (kimi uses its own OAuth), so it is safe in git.
  `backend_for_model()` reads it; any `relay-claude-settings-<x>.json` with `"backend":"kimi"`
  adds a new native model for free.

### Gotchas specific to ik3
- Kimi's model alias is namespaced: **`kimi-code/k3`**, not bare `k3` (bare → "not configured").
- `--prompt` (headless) rejects `--yolo`; the TUI path uses `--yolo` fine.
- Kimi's config `max_context_size` starts at 262144 but the footer shows the true **1.0M**
  after it connects to the gateway (native kimi picks up the upgraded plan on its own).
- Native kimi does NOT carry your claude auto-memory or claude skills (different tool).

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
