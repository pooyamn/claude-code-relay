# Changelog

All notable changes to **claude-code-relay** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versions are date-tagged.

## [0.8.0] — 2026-07-18

### Added
- **`cc model ik3` — native Kimi Code backend.** Drives the **`kimi` binary** in tmux
  instead of `claude` (`i` = native), using kimi's own OAuth + `config.toml`. Kimi bills
  flat-rate, so headless/metered concerns don't apply. Declared by
  `relay-claude-settings-ik3.json` (`{"backend":"kimi",...}`) — no secret in it, so it is
  safe in git. Implemented as an **isolated** branch: a per-session
  `backend-<session>.json` marker selects kimi parsing, and the claude path is unchanged.
  Kimi's thinking is split from its answer **by colour** (grey-italic reasoning vs bright
  answer, both bulleted `●`), characterised from real panes rather than assumed.
- **`CLAUDE_CODE_MAX_CONTEXT_TOKENS` on the k3 template**, so an upgraded 1M plan is
  actually usable. Claude Code defaults an unknown model to a 200k window regardless of
  plan; this raises it without disabling auto-compact (it only applies to model ids that
  don't start with `claude-`).

### Fixed
- **Live progress bubble could land AFTER the final reply.** Bubble edits are
  fire-and-forget, and the WS edit server's `quit` handler called `process.exit(0)`
  immediately — orphaning an in-flight edit that Telegram then applied after the answer.
  `quit` now drains pending edits (2s cap) and `close()` waits for it, making close a real
  ordering barrier. Also explains the "bubble frozen, nothing happening" reports: the same
  Telegram flood-pause that drops edits.
- **`ik3` silently killed comms on a bound topic.** `claude-relay-group`'s liveness probe
  only matched claude chrome, so a healthy kimi session read as dead and was replaced by
  claude — while the backend marker still said kimi, so the watcher scraped a claude pane
  with the kimi parser and delivered nothing. The probe now accepts kimi's input-bar gauge,
  and every claude (re)launch path resets the marker.
- **Watcher Esc'd kimi's screen**, so a kimi turn never reached delivery: the overlay/wedge
  guard treated kimi's normal input bar as a full-screen overlay.
- **Kimi busy/idle patterns are now backend-gated.** They were merged into the shared
  BUSY/READY/INPUTBAR regexes on the assumption they could never appear in a claude pane —
  wrong, since a claude *reply* can legitimately contain a moon emoji, a braille glyph, or
  a `context: N% (` string. They now apply only in a kimi session.

### Changed
- **Corrects 0.7.0's endpoint claim.** Kimi Code keys (`sk-kimi-…`) do **not** authenticate
  against `api.moonshot.ai` — the Moonshot *platform* API and the Kimi Code *coding gateway*
  are different products, and the platform returns a misleading `401 Invalid Authentication`
  for a perfectly valid key. The working, natively Anthropic-compatible endpoint is
  **`https://api.kimi.com/coding`**; the shipped templates use it.

## [0.7.0] — 2026-07-16

### Added
- **Per-model settings routing — `cc model kimi` runs on Kimi, everything else stays on
  the subscription.** `settings_for_model()` looks for `relay-claude-settings-<name>.json`
  next to the default; if present the restart uses that file and takes the real provider
  model id from its `model` key, otherwise every other model uses the default settings
  untouched. Drop in a new `relay-claude-settings-<x>.json` and `cc model <x>` works with
  no code change.
- **Kimi needs no proxy.** Probed empirically: `https://api.moonshot.ai/anthropic/v1/messages`
  returns an Anthropic-shaped `invalid_authentication_error` (401) — it speaks the Messages
  API natively; `/v1/messages` 404s. So routing is just an `env` block
  (`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`) in the kimi settings file — a settings
  `env` overrides shell env and reliably reaches relay-spawned sessions.

### Notes
- `ANTHROPIC_BASE_URL`/`AUTH_TOKEN` **disable Remote Control + voice dictation** (they need
  a claude.ai identity) and take precedence over the saved Max login while set — which is
  why the routing is scoped strictly to the alt-model settings file, leaving subscription
  sessions untouched.
- Local `relay-claude-settings-*.json` may hold a provider key; the repo ships only a
  `REPLACE_WITH_*` template.

## [0.6.0] — 2026-07-15

### Added
- **`cc model <name>` reliably switches the model by relaunching the session.** The
  live `/model` command is gated on large cached conversations (a "re-read the full
  history?" confirmation), so a one-shot `cc model X` silently reported "Kept model as
  …" — the switch never took, in either direction. The relay now intercepts
  `cc model <name>`: it relaunches `claude --model <name> --continue` (folder
  auto-resolved from the session name; keeps full context, handles trust +
  resume-from-summary dialogs) and confirms. Bare `cc model` still opens the picker;
  only a safe model token triggers the restart; a busy session is asked to finish/cancel
  first, and it **reads back the active model after restart** and confirms it (warns
  on mismatch). Verified opus↔fable on a throwaway session.
## [0.5.1] — 2026-07-11

### Fixed
- **Pruned orphaned relay backends** left behind by unbinds (each an agents-list entry
  + model + cliBackend that no binding referenced) — they cluttered the model picker.

### Reverted
- **Single `relay/` provider grouping — DO NOT do this.** The model key's provider
  prefix (before `/`) is not just a picker label: the gateway resolves a relay's
  cliBackend from it. Renaming `claude-tui-<x>/relay` to `relay/<x>` pointed routing at
  a nonexistent backend and **silently dropped messages** to bound topics. Reverted to
  `<backend>/relay`; the constraint is now documented in `bind-claude-code.py`. Picker
  tidiness needs a different mechanism (e.g. a display-label field, if OpenClaw grows one).


## [0.5.0] — 2026-07-11

### Added
- **`move-to-topic` skill — worktree fork.** Say "move/fork this to a new topic": the
  session suggests names (buttons), then it creates a new Telegram topic and backs it
  with a **git worktree** so the fork is an INDEPENDENT session (own folder = own
  `cr-<hash>`) that `--continue`s the current conversation with full context, while the
  current topic stays alive on the base branch. Flow: commit WIP on the feature branch,
  switch the current folder to `main`, add `.worktrees/<branch>`, copy the transcript
  into the fork's project dir, create+bind the new topic, defer a gateway restart.
  Refuses cleanly if the folder isn't a git repo on a feature branch.


## [0.4.3] — 2026-07-11

### Fixed
- **`cc` prefix is now case-insensitive.** Phone keyboards auto-capitalize the first
  word, so "cc model" became "Cc model", which the case-sensitive prefix match missed
  — the command silently fell through to Claude as plain text. Now "Cc"/"CC"/"cc" (and
  the "/cc" forms) all convert; the rest of the line keeps its original case.
- **`cc cancel` now actually interrupts.** It used to convert to `/cancel` and *type*
  it into the TUI, but Claude Code has no `/cancel` command, so it no-op'd.
  `cc cancel` / `cc interrupt` now send an Esc keystroke to the session (like the
  `/cancel` plugin command), and confirm with "✋ Interrupted the current turn". Handled
  before the busy-warning so it interrupts instead of queuing.

## [0.4.2] — 2026-07-11

### Added
- **Busy-aware feedback for `cc` slash commands.** A forwarded slash command
  (`cc clear`, `cc compact`, `cc model …`) typed while a turn is running does NOT
  execute — Claude Code just queues it — so `cc clear` looked broken ("I sent it but
  context is still 99%"). The relay now detects a running turn, still queues the
  command (so it runs when the turn finishes), and replies immediately: *"session is
  busy, `/clear` is queued and will run when the turn finishes; send `cc cancel` to
  run it now."* Menu selections (a number) and normal messages are unaffected.

## [0.4.1] — 2026-07-09

### Fixed
- **`send-file` misrouted to the wrong chat from non-relay contexts.** When an OpenClaw
  agent session (no `$TMUX`) invoked the skill, `tmux display-message -p '#S'` returned
  the *most-recent* tmux session — a `cr-*` relay session — so the file was zipped and
  delivered to that session's bound chat instead of the caller's. The script now only
  consults tmux when actually attached to a client (`$TMUX` set) and the session is a
  real `cr-<hash>` with a target file; otherwise it **refuses** (exit 3) rather than
  guess, so an OpenClaw agent falls back to its own native media send. SKILL.md also now
  says to send only the files the user named (don't zip a whole folder unless asked).

## [0.4.0] — 2026-06-29

### Added
- **`send-file` skill** (`skills/send-file/`) — when you ask a bound session to send/share
  a file, it delivers it to your Telegram chat via the OpenClaw gateway. It **always
  zips first** because OpenClaw/Telegram block many raw extensions (`.hex`, `.exe`,
  `.sh`, binaries); a `.zip` always gets through. The destination chat/topic is resolved
  automatically from the relay's per-session target file — no chat id to pass. Outbound
  zips are written under `~/.openclaw/media/outbound/` (the gateway only delivers media
  from allowlisted dirs, not `/tmp`).

## [0.3.1] — 2026-06-28

### Changed
- **Inbound files arrive as an on-disk link, not inlined content.** OpenClaw already
  saves every attachment under `~/.openclaw/media/inbound/`; the relay's message
  extractor now rewrites the bulky payload — a fully inlined document body, or a
  vision *Description* for images — into a single compact link (`📎 /abs/path (size)`).
  A 177 KB firmware hex (or an 833 KB PDF) no longer floods the prompt; Claude opens
  the file on demand with `Read`. Plain-text messages are untouched, and the bare
  `<media:…>` marker is stripped even when it rides inline on the sender line.

## [0.3.0] — 2026-06-26

### Added
- **`/screenshot`** (aliases `/ss`, `/shot`) — sends an image of the live TUI:
  full-screen overlays, colours, and layout that text scraping can't carry. Rendered
  with [`freeze`](https://github.com/charmbracelet/freeze) and delivered as a sharp
  document (uncompressed, so small terminal text stays legible).
- **`/workflows`** — sends a screenshot of the *real* workflows panel (opens it,
  captures it inside the overlay-guard window, then `Esc`-closes it); falls back to a
  scraped text status if the pane is busy or rendering fails.
- **Remote Control at startup** — relay sessions auto-connect to claude.ai Remote
  Control via `"remoteControlAtStartup": true`, so phone push + remote steering work
  without running `/remote-control` by hand. Requires Claude Code ≥ 2.1.119.

### Fixed
- **Overlay wedge.** Full-screen overlays (`/workflows`, `/config`, stacked dialogs)
  replace the input bar, so the TUI accepted no keystrokes while one was up — a queued
  message typed *into* the overlay and froze the bound topic. The watcher now
  self-heals (Esc-peels overlays one layer per poll) and `type_prompt` pre-clears them
  before typing; real AskUserQuestion menus are never dismissed.
- **Screenshots silently falling back to text.** `freeze`, given the ANSI capture as a
  file argument, died `Language Unknown` under the gateway's minimal env (no `TERM`).
  Now piped via stdin so it renders regardless of environment; `freeze` is also
  resolved by absolute path, and render failures are logged instead of swallowed.

## [0.2.1] — 2026-06-21

### Changed
- Live progress bubble renders the raw terminal (code block, ~4000 chars) for faithful
  colours and alignment, after trialling a chrome-stripped reflow.

## [0.2.0] — 2026-06-20

### Added
- **Deterministic turn-end delivery** via a Claude Code `Stop` hook — replaces
  idle-window guessing; the exact final message is delivered once, on a marker.
- **AskUserQuestion → native Telegram buttons** — real selection menus become tappable
  buttons; your tap is delivered back into the TUI as the answer.

### Changed
- The live progress bubble is **frozen in place** at turn end (not deleted); the final
  answer is sent as a fresh message and the next turn opens a new bubble.

### Fixed
- Duplicate reply delivery on watcher restart (hash-dedup, persisted across restarts).
- Live bubble not drawing — pass the WS transport to the stream and pin the watcher's
  cwd; resolve the device-identity module dynamically.

## [0.1.1] — 2026-06-15

### Added
- Live terminal progress over a fast WebSocket edit transport; separate final message;
  `/cancel`.

### Removed
- `/stop` alias (collided with OpenClaw's built-in abort trigger).

## [0.1.0] — 2026-06-14

### Added
- Initial release: per-folder, durable, resumable **Claude Code** sessions driven in
  `tmux` and relayed to Telegram on the Max/Pro subscription.
- Persistent watcher model; native JSONL streaming; silent live-stream with a single
  final ping.
- Pre-agent command plugin (`/newcc`, `/unbind`, `/ccstatus`) — LLM-free binding.
- Robust message extraction + test suite.
