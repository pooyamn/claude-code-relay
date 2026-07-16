# Relay gotchas — mechanisms that cost an outage to learn

Every entry here was paid for with a real regression. Read before changing the
related area. The relay's failure mode is **silence** (dropped messages, unsubmitted
input, undelivered replies), so a broken change looks exactly like a quiet system.

## Working discipline (this is the part that actually mattered)

1. **Never use a live/bound folder as a test fixture.** A session is keyed by
   `cr-<md5(folder)>`, so a "throwaway" in a bound folder *is* that session. Using
   the hardware folder for a test collided with a real agent and destroyed a
   2,386-message context. Use a scratch dir that no code maps to.
2. **Read the mechanism before changing it, not after it breaks.** The provider-key
   disaster took 90 seconds of reading `dist/cli-backends-*.js` to explain — read
   *after* shipping. The answer is usually already on disk.
3. **Verify, then claim.** "Done/fixed/live" before checking makes the user the test
   suite. Reproduce under the **real** conditions, not your shell — the gateway's env
   is what finally explained `freeze: Language Unknown`.
4. **One destructive change at a time, with the rollback identified first**
   (`scripts/openclaw-restore-stable`, `~/.openclaw/backups/*.STABLE`).
5. **When the user says it's broken, believe them over your model.** Every pushback
   ("the buttons worked before", "limit is free", "it's not responding") was correct
   while a plausible theory said otherwise.

## Busy detection is not just "esc to interrupt"

A session that fanned out sub-agents sits at `Waiting for N background agents to
finish` (or `… dynamic workflow …`) with **no** `esc to interrupt` and the normal
input bar visible. Reading that as idle meant the watcher never set `was_busy`, its
idle-delivery path never fired, and **replies were never delivered** — the session
answered into the void. `BUSY` now matches both. Don't "simplify" it back.

## Model switching: relaunch, don't type `/model`

Live `/model <name>` is **gated** on a large cached conversation ("re-read the full
history?") and silently reports `Kept model as …` in either direction. Not a usage
cap. Reliable switch = relaunch `claude --model <name> --continue`; that's what
`cc model <name>` does (`restart_with_model`), then it reads the picker back to
confirm. Also: `/model` **rewrites the settings default**, so it flip-flops the pin —
keep `~/.claude/settings.json` and `relay-claude-settings.json` `"model"` in sync.

## Model-key prefix is routing, not a label

`<backend>/relay` — the part before `/` is how the gateway resolves the cliBackend.
Renaming to group the picker (`relay/<x>`) points routing at a nonexistent backend and
**silently drops every message**. Only a *registered* backend (`api.registerCliBackend`
with `modelProvider`) may declare a provider — see `provider-grouping-plan.md`.

## Transplanting a session to another folder (forks)

1. Pick the source transcript by `lastSessionId` in `~/.claude.json`, **not**
   newest-mtime (wrong file when a folder serves several chats or `/clear` rotated).
2. Rewrite each row's `cwd` to the new folder — claude associates transcripts by cwd.
3. First boot must be `claude --resume <sid>`; `--continue` rejects a transplant
   ("No conversation found") until the fork has its own activity.
4. Pre-write `relay-work/target-cr-<md5(newpath)>.json` and start the `crw-` watcher,
   or replies have nowhere to go.
5. The fork's `git add -A` sweeps OpenClaw's untracked seeds (BOOTSTRAP/AGENTS.md) into
   the branch; switching the parent to base then deletes them → the gateway hard-fails
   every message for that workspace with **WorkspaceVanishedError**. Restore the seeds
   untracked and `rm ~/.openclaw/workspace-attestations/<sha256-of-path>.attested`.

## Small ones that bit

- **zsh `:t`**: `"$CHAT:topic:$TID"` silently becomes `<chat>opic:<tid>` (`:t` = tail
  modifier). Always brace: `"${CHAT}:topic:${TID}"`.
- **`freeze` writes errors to STDOUT**, not stderr; and given a *file* arg it guesses a
  language and dies `Language Unknown` under the gateway's minimal env (no `TERM`).
  Pipe the ANSI via **stdin**, resolve `freeze` by absolute path.
- **Outbound media** only delivers from allowlisted dirs (`~/.openclaw/media/outbound`,
  the workspace) — never `/tmp`.
- **Topic create is not idempotent across fresh keys**: a timed-out call may have
  succeeded. Check before retrying or you get duplicate topics.
- **Overlays** (`/workflows`, `/config`) replace the input bar; the watcher Esc-peels
  them. Never keystroke-drive a picker — it races and mis-selects.
