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
5. **Tests need enforced isolation, not only mocks.** Run
   `python3 scripts/tests/run_isolated.py`: it copies source to scratch and denies
   host home/credential and network access before testing. The old helper tests
   write sibling state/config files, and the old alt launcher read a hard-coded
   live directory even in a copied fixture. Its path now follows its own script.
   Linux sandbox execution still requires target validation; no unsafe fallback.
6. **When the user says it's broken, believe them over your model.** Every pushback
   ("the buttons worked before", "limit is free", "it's not responding") was correct
   while a plausible theory said otherwise.

## Busy detection is not just "esc to interrupt"

A session that fanned out sub-agents sits at `Waiting for N background agents to
finish` (or `… dynamic workflow …`) with **no** `esc to interrupt` and the normal
input bar visible. Reading that as idle meant the watcher never set `was_busy`, its
idle-delivery path never fired, and **replies were never delivered** — the session
answered into the void. `BUSY` now matches both. Don't "simplify" it back.

## Codex bubbles need item history and exact event scope

On 2026-10-02, DUT topic 53 missed the MCU-routing commentary and the PB15
question visible in the native app. The native history contains that question
at 06:47 PDT as an `agentMessage` with `delivery: "async"`. The old adapter kept
only its newest message, ignored the question marker, and posted text only
when the turn ended. A later comment overwrote the question. Tools were shown
only after completion and reduced to labels such as "running a command";
resume responses containing an active turn's prior items were ignored.

The outbound log also records a software-review reply in DUT topic 53 at
06:40:43. Its native source is a different review thread. The old notification
parser had no thread or turn filter, so foreign item/completion events could
replace the DUT message or clear its busy state. Reject unscoped, foreign and
stale-turn events before changing any connection or display state.

`relay_codex_bubble.py` retains user messages (including native-app prompts
and steering), assistant messages, asynchronous questions and visible
tool actions in native item order. Starts and completions amend the same item;
resume snapshots restore prior activity. Tool output and private reasoning are
not published. Following the owner's final presentation choice, live delivery
uses one acknowledged text-message ID, continually amended with the newest
part of that history. `Working (elapsed)` stays at the bottom; a terminal turn
amends the same bubble with its terminal state. The tail is budgeted against
rendered HTML in UTF-16, including emoji, escaping, balanced code fences and
the footer. Full history is retained in the native records rather than emitted
as a growing set of live continuation messages. The full-history multipage
renderer remains available for explicit recovery, not the default live view.
Media still attaches separately without duplicating final prose.

Cumulative content cannot use the disposable edit path: that path drops edits
while its helper is in a cooldown. The new edit path requires a matching
positive acknowledgment. A pending send/edit is persisted before the effect;
an absent acknowledgment holds newer operations for reconciliation instead of
marking the text delivered or making a blind replacement send. A gateway
response can arrive after the foreground eight-second wait: the transport now
keeps the same request in flight and polls its late acknowledgment, without a
second send/edit. On restart, the sole watcher may reconcile an exact persisted
same-ID/same-payload edit before admitting newer content. Unknown sends are
still held rather than replayed. A held update is **not** proof that Telegram
received it. The complete native history remains the source for recovery;
full protected scheduler integration is still pending.

The [official app-server reference](https://learn.chatgpt.com/docs/app-server)
documents agent-message phases, authoritative completed items and user-input
requests. Local isolated tests cover the screenshot-shaped regression, active
tool display, event isolation, same-ID edits, single-message rolling limits,
elapsed footer, late acknowledgments and restart reconciliation. Live bot acceptance is a separate gate;
these tests do not establish it or authorize changing bot wiring.

The owner subsequently authorized activation specifically for DUT topic 53.
Khadang (`TheKhadangBot`, test topic 5) accepted one canary message (ID 98),
two cumulative edits and a same-ID restart/no-change edit. No model turn was
started. On 2026-10-02 at 07:23 PDT only the DUT watcher was restarted with
the patched live files; its connection uses the existing native daemon and
thread. Bot credentials, topic bindings and the native Codex process were not
changed. A recoverable backup of the three replaced files is under
`relay-work/dut-bubble-backup.cgCfOX` in the live scripts directory.

The reported prompt "Have you updated the source? Pushed?" is present in DUT's
native history at 07:03:57 PDT (relay input) and 07:19:06 PDT (app input).
Do not replay it as a supposed lost input: it was processed, and native replies
exist. At inspection the old DUT watcher had no daemon connection while idle;
the updated watcher stays subscribed to the bound native thread.

The real app-started "Push it" turn ended at 07:22 PDT, before activation, and
had no Telegram delivery record. It was recovered from native item history into
DUT message 4755, with a positive same-ID edit acknowledgment. Its source and
schematic push was **not** repeated, and no model turn was started. The watcher
then resumed that recorded bubble and acknowledged another same-ID edit. This
establishes real-content delivery through the existing DUT gateway, separately
from the Khadang canary.

The owner also requested the fix in Ai Dispatch topic 816, then changed the
presentation to one rolling message. Its watcher was activated separately,
preserving the native model turn. Seven continuation messages created during
the initial full-history rollout (13445–13451) were deleted only after positive
acknowledgments; the complete activity remains in native history. Message 13444
was retained and acknowledged with the bounded tail and elapsed footer.
Khadang accepted two further same-ID edits of message 98 exercising that rolling
view, with no additional message or model turn. Bot wiring and credentials
remain unchanged; only the two explicitly requested watchers were restarted.
The subsequent live DUT turn is tracked in message 4757 on the same native
thread. After the rolling-view activation both live routes retained one message
ID with no pending edit in their durable state. Isolated verification ended
with all four legacy suites and 279 core tests passing.

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
