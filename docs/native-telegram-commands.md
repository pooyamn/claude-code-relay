# Native Telegram command menus

## Topic typing: receipt and active work

The PC router now sends a topic-specific typing pulse immediately after a
durably claimed input passes human authorization and resolves to its mapped
session. This happens before model/dispatch locks or attachment downloads, for
both Claude and Codex. Unauthorized senders/controls, unmapped topics, synthetic
deployment inputs and service events do not produce receipt pulses.

An independent two-second activity loop renews typing only for actual busy,
Working sessions that are neither held nor disconnected. Idle, completed,
stopped and waiting-for-owner sessions are not renewed. An active goal alone
does not keep typing alive. Goal pause does not interrupt a current tool/turn;
typing follows that actual work until it stops. This loop is independent of
slow bubble edits, final-message sends and the native dispatch lock.

Typing uses `sendChatAction` with the exact chat and `message_thread_id` (omitted
for non-forum topic0). Telegram clears it on bot messages and otherwise expires
it within about five seconds, so a stopped session can briefly retain the last
pulse. [Telegram chat-action behavior](https://core.telegram.org/bots/api#sendchataction).

One-second burst coalescing, eight-request concurrency bound, a two-second
per-request deadline and Telegram `retry_after` cooldown keep this cosmetic
signal bounded. Failures never block native delivery, hold a session, create a
durable action/unknown record or automatically retry an incoming message.
Typing acknowledges the bridge or active work, not model acceptance or proof of
progress. The rolling code-block bubble and separate final messages are unchanged.
Bubble creation already sets `disable_notification:true` (send without sound),
including non-forum destinations; updates amend the same message. Separate final
answers omit that flag and retain normal notifying delivery, subject to the
user's Telegram notification settings.
[Telegram silent message parameter](https://core.telegram.org/bots/api#sendmessage).
Sanitized `receiptTyping` status counters record attempts, confirmations,
failures, suppressions and the last confirmed destination/time—never input text,
credentials or URL-bearing errors.

Deployed on the PC as generation `3000aa7f68e14bb093b6fe0a86d51496` on
October 4: 1,025 Linux and 1,028 sealed Windows fixture checks passed. Real
Telegram typing API calls succeeded for DUT53 and CC816; the live router's
confirmed activity count increased from26 to51 to102, with zero typing failures.
All12 routes and seven exact-ID Claude sessions recovered. Phone rendering has
not been independently observed. Deployment/recovery evidence is in
[the migration record](mac-to-pc-migration.md#topic-receipt-and-working-typing-october-4-at-721-am-pdt).

## Current PC Khadang model switching — 2026-10-04

The protected PC router restores **only** the requested legacy model syntax:
`cc model opus`, `cc model sonnet`, `cc model haiku` select native Claude;
`cc model cx` returns to native Codex. Explicit native Claude/GPT catalog IDs
are supported. `cc model` lists the current native catalog. Other legacy `cc`
commands and the old button picker are not restored by this change.

Cross-tool switches require an idle source with no pending approval/question,
active Codex goal or uncertain delivery. Pause `/goal`, then finish or `/cancel`
the running turn; goal pause alone does not stop it. No automatic interruption
or pause is performed. Unsupported selectors never become model prompts.

Both provider IDs are retained in protected per-topic slots. A first switch
creates an exact reserved counterpart; subsequent switches resume its saved ID.
The topic address and worktree never move. A bounded handoff carries recent
owner requests, the last completed answer/progress, goal snapshot, Git HEAD,
dirty/untracked file names and diff summary. This is not a full history clone.
Pending approvals and authority for old external actions are not transferred.

Codex receives the handoff through native `thread/inject_items`, without a paid
work turn. Claude receives it through an acknowledged native send-now message:
acknowledge readiness, then wait for the next owner request without doing project
work. The topic binding and committed switch receipt change atomically only
after handoff delivery is confirmed. Incomplete/unknown switches hold their
exact destination for inspection; no replacement conversation or replay.
Legacy Claude model changes relaunch the same ID with `--model`, rather than
relying on a live setting that can retain the previous cached model.

This paired launcher covers the nine activated **Linux** topic workspaces,
including DUT and CC relay. Windows LG has no reviewed Claude launcher and
refuses cross-tool switching. Existing native `/model` and other supported
controls remain; the older Mac deployment sections below are historical.

During an active Codex goal, authoritative `agentMessage` completions with
`phase=final_answer` enter a separate durable, notifying final-answer outbox.
They no longer wait for the goal or whole turn to end. Commentary/tools remain
in the one rolling code-block bubble with Working timer/goal footer; final prose
is a normal formatted message. Repeated item IDs, concurrent flushes and restart
receipts cannot resend confirmed answers. Unknown acknowledgments hold instead
of duplicating a message; explicit Telegram throttles can retry the rejected part.
The native item/turn distinction follows the
[official app-server lifecycle](https://learn.chatgpt.com/docs/app-server).

Deployed generation `0bc81f90bf4e4494a07d2d36b979271e`: 924 PC Linux fixture
checks, **927 actual Windows fixture checks**, and 25 Python bridge tests passed.
A candidate-bound real Claude test delivered a fixed canary, verified tool UID
1000, and resumed the same UUID in an independent native generation with its
marker/context intact. Live routing was not changed by that canary. Fresh
installed OS/credential checks followed; all ten routes/five Claude connections
and the exact active controller turn/goal were observed after restart. An actual
owner-issued cross-tool command and the next live goal-final notification remain
to be observed; fixtures/native canaries are not claimed as those human receipts.

## Legacy tool-switch alias regression — 2026-10-03

DUT topic 53 received `cc model opus` at 07:57:03; outbound message 4778
confirmed the command was incorrectly rejected as an unknown Codex model.
The native picker intercepted the normalized `/model opus` before the older
backend-switch path could run. This was command dispatch, not lost delivery or
an unavailable Anthropic model.

Recognized Claude names (`opus`, `sonnet`, `haiku`, and explicit `claude-…` IDs)
now retain their cross-tool switch meaning in Codex topics; `cx` retains the
switch back to Codex. Within Claude, Claude names still select its model.
Native Codex catalog IDs still use settings update/readback on the existing
thread. Unknown or retired IDs never trigger a backend switch. Both aliases and
`/backend` refuse an active turn or an unavailable idle-status read. `/backend`
remains the unambiguous tool selector.

The failed command is not automatically replayed. A tool switch preserves the
stored conversations, but does not transfer Codex history into Claude; the
existing unfinished-work handoff gate remains separate. Activation replaces only
the model-control helper loaded by fresh per-message senders; it does not need a
watcher/native-daemon restart, bot credential change, or binding change.

Activated in the shared Mac sender installation at 09:26 PDT. Installed helper
SHA-256 is `cac50c056ccbdd16c286b17bbb8e21748a7703e1953f753303965ba2e3e1c52d`,
byte-identical to the tested source. A private before-copy is under
`~/.config/ccrelay/dut-model-alias-backup.E2C7j8`. Readback verified the same
DUT watcher PID, sender, folder registry, backend/pin, target, native thread
and gateway configuration. Khadang's PC installation and Hamal wiring were
not changed. Six new regression tests join the existing command/model tests:
38 focused core tests and all four legacy suites passed in the OS sandbox;
the strict secret scan passed. The actual next owner-issued switch and native
Claude model confirmation remain unobserved; no live tool switch or inference
was performed as a test.

## Model controls and retired providers — 2026-10-02 follow-up

Pouya requested new commands, proper Codex model selection, and retirement of
Kimi Code and Ox Alpha on both Khadang and the Jamshid/HamalAIBot installation.
This supersedes the earlier deployment's shared-script preservation restriction
for these specific model controls and retired profiles.

`/model` now opens native Telegram model buttons. In Codex topics, the catalog
comes from `model/list` and current settings from the exact bound native thread.
`/model <id> [effort]` and `/effort <level>` use `thread/settings/update`, then
read back the model and reasoning level before confirming. They neither restart
the tool nor create a replacement conversation or inference turn. `/effort`
lists the selected model's supported reasoning levels. `/backend` explicitly
switches between Claude Code and Codex. Existing `cc model …` / `cc effort …`
aliases reach the same control on Jamshid, whose bare `/model` is an OpenClaw
command. Claude model changes retain their existing native relaunch path.

Picker receipts are bound to the native thread, destination, session, nonce and
expiry. Foreign/stale buttons fail closed; Khadang verifies owner authority for
button taps and text-shaped callbacks. An ambiguous settings acknowledgment is
reported as unconfirmed and never automatically replayed.

Both live sender installations include these logical edits. Khadang's router
was replaced after confirming its old poller stopped; native daemons and session
watchers were retained. Telegram readback confirmed all twelve member commands,
including the new `backend` and `effort` entries. Kimi's three OpenClaw model
entries and CLI backend were removed with schema validation. Kimi/Ox settings
and obsolete launch pins were archived privately; native histories remain.
Recovery copies are under `~/.config/ccrelay/model-controls-backup-20261002`.
Do not commit that directory: it contains private pre-change configuration.

The reviewed source passed 409 isolated core tests and all four legacy suites.
A disposable unbound ephemeral native thread verified model/effort mutation and
readback without inference, and was unsubscribed afterward. An additional run
against the concurrently edited working tree encountered unrelated untracked
snapshot-test failures; those files were excluded from this release. OpenClaw's
`models list` also fails in `applyAnthropicSonnet5Cost` with the original and
updated configs; this pre-existing catalog bug is independent of the native
Codex picker. Phone rendering still requires a human observation.

## Earlier activation

Activated on the legacy Mac Khadang test router on 2026-10-02, after Pouya
authorized testing and deployment. Telegram confirmed registration and readback
of the implemented controls, with discovery adapted to the bound session types.
This is not protected PC deployment. HamalBot wiring and installed shared
scripts, credentials, bindings and allowlists are unchanged.

## Session commands

Both tools expose `/help`, `/model <name>` and `/cancel`. Claude topics also
expose `/clear`, `/compact` and `/unq`; Codex topics expose `/goal` with its
objective, status, pause, resume and clear arguments. Owners also see `/newcc`,
`/unbind` and `/ccstatus`. Existing `cc …` and `/cc …` aliases remain usable.
An explicit command addressed to this bot is normalized before routing;
`/clear@OtherBot` and other foreign-addressed commands are ignored.

The menu lists implemented relay controls, not every native CLI command.
Codex's native CLI `/clear` starts a fresh chat, while `/goal clear` removes its
goal. Native CLI `/clear` and `/compact` are not yet wired to this relay's
app-server adapter; they return an explicit unsupported-control message rather
than entering a model prompt. Preserve their native-controller requirement in
PR 7; do not fake either operation. [Official OpenAI command documentation](https://learn.chatgpt.com/docs/developer-commands?surface=cli).

## Chats and forum topics

Telegram supports chat and chat-member command scopes, but no forum-topic
command scope. A homogeneous chat gets its tool's menu. A forum with both tools
gets a stable union with `[Claude]` and `[Codex]` descriptions. Do not switch the
whole forum's menu to whichever topic was used most recently. `/help` reads the
current topic's binding and shows only its tool's controls, without invoking a
model. [Telegram command scopes](https://core.telegram.org/bots/api#botcommandscope).

Group-wide scopes show only help; owner-specific chat-member scopes contain
controls. Owner private chats use a chat scope. Menus are discovery, not
authorization: receiving a command still checks the actual allowed human,
current binding and backend. Wildcard chat membership does not grant control.
Forwarded, via-bot and sender-chat controls cannot act as an owner. Company
employee grants and protected PC control authority remain separate gates.

Bindings and backend markers are reread during daemon poll cycles; the `cx` pin
uses the launcher's existing precedence. Missing/corrupt markers mean unverified,
not Claude. Run planning/registration from the reviewed installed artifact that
owns the session's `relay-work`; a repository preview with no runtime markers
must not be treated as evidence of live session types. Changes schedule a coalesced menu plan
on a separate worker in the existing daemon, not another poller. Menu network
calls do not block inbound steering/stop handling. Execution rechecks the
backend, so stale discovery cannot turn an unsupported control into a prompt.

## Registration and activation

`relay_bot_commands.py` prepares exact scopes and performs
`getMyCommands` → merge → `setMyCommands` → readback. It retains unrelated
commands at each scope and never changes global/default/admin menus or
webhooks. A missing/lost acknowledgment is reported as unconfirmed; the next
pass reads state before deciding whether another configuration write is needed.
Method-local rate-limit sleeps are disabled for discovery. [Telegram command
registration](https://core.telegram.org/bots/api#setmycommands).

The existing config can opt into automatic refresh with
`"command_menu_bot": "TheKhadangBot"`, after the reviewed adapters have been
activated. The daemon verifies its `getMe` username before menu writes. Inspect
and merge existing config; do not replace it or create another daemon.

Read-only planning does not load a token, contact Telegram, write state or start
a session:

```sh
python3 scripts/ccrelayd.py --config <existing-config> --command-menu-plan
```

After verified activation, one-shot registration requires the exact bot identity
and does not poll or start a session:

```sh
python3 scripts/ccrelayd.py --config <existing-config> --sync-command-menu --expect-bot TheKhadangBot
```

Only publish commands whose live handlers are installed and verified. Do not
advertise goal continuation as ready before its compatibility/admission gates.
Use the exclusive Khadang test route, never HamalBot. The current common-user
Mac helper is not PR 6's protected configuration outbox or PR 7–9's admitted
control plane; integrate menu configuration behind those gates for the PC.

Language-specific and administrator menus may override the written scopes.
Telegram cannot enumerate every previously configured scope/language. This
implementation leaves those unrelated scopes intact. Retired bindings seen in
the same daemon run are replaced with help-only menus; after restart, stale
removed-chat/member scopes may need explicit reviewed cleanup. These are UI
limits, not exceptions to handler authorization or binding checks.

## Verification

Run `scripts/tests/run_isolated.py --suite all`, never a live session as a
fixture. Synthetic Bot API tests cover homogeneous/mixed menus, backend
changes, owner/private/public scopes, preserved unrelated commands, missing
acknowledgments, wrong-bot rejection and retired scopes. Joined routing tests
cover addressed commands, aliases, direct owner authority, contextual help,
backend rechecks, JSONL bypass and nonblocking discovery. CLI tests prove
planning needs no token/network and registration does not poll or infer.

The final clean staged-source run passed all 376 core tests, including 23
command-menu/routing tests, and all four legacy suites. It excluded the existing
user-owned protocol edits. The strict staged secret scan passed; a read-only
repository preview against the existing test config performed no token/network
access or state mutations; it read only configuration, bindings and backend markers.

## Khadang deployment and recovery

The missing live menu was a deployment gap: the running router still loaded the
old shared installation, its config lacked `command_menu_bot`, and Telegram
returned empty default, group, chat, administrator and owner-member menus.
Pushing repository code did not install it into that running process.

The reviewed release is `/Users/pouya/.config/ccrelay/khadang-release.JgVvNO`,
with launcher changes from commit `9406f3a`. Its router and sender load the new
menu/goal/bubble modules. `claude-relay-group` now resolves helpers from its own
release, rather than escaping to hardcoded shared scripts. Three new sandbox
tests exercise release-local Codex routing, including paths with spaces. The
final clean staged-source suite passed 400 core tests and all four legacy suites;
the strict staged secret scan passed. The initial launcher fixtures failed
because their PATH omitted macOS's `/sbin/md5`; correcting the fixture PATH
retained the existing hash/key mechanism and passed both real shell checks.

Only the `ccrelayd-test` router and the watchers for Claude topic 2 and Codex
topic 5 in the Khadang test forum were replaced. The old poller was verified
gone before the new one started. The native Codex daemon, the Claude TUI and
all other watchers stayed running. The release uses the existing private runtime
state/code registry and model settings; templates are retained as `.repo-example`
files. The installed protocol helper was copied unchanged into the release,
preserving the user-owned edits without committing them. Existing shared
scripts and OpenClaw configuration hashes remained unchanged.

The test config retains its original token-file path, bindings, state and owner
allowlist, adding only `"command_menu_bot": "TheKhadangBot"`. Its before-copy
is `test.before.json` inside the release. Telegram verified the exact bot, the
help-only chat menu and all ten owner-member commands. Pouya's group membership
was verified; owner-member English and Persian scopes returned no override.
The running router refreshes discovery automatically without another poller.
Typing `/` in a topic exposes command suggestions; `/help` is topic-specific.
A separate native `thread/goal/get` read matched the existing Codex test thread
and validated the returned goal with no mutation or model inference.
Two silent activation notices received exact-topic Telegram acknowledgments:
message 149 in Claude topic 2 and message 150 in Codex topic 5. These confirm
bot-message routes, not a human command, native mutation or phone rendering.

For a reviewed restart, use this release's `scripts/ccrelayd.py` with the existing
`~/.config/ccrelay/test.json`, and launch the two test watchers from the same
release. First inspect running processes, queued work and the current config;
never start a competing poller or restart the native daemon. Menu-only readback
or reconciliation uses the one-shot command above from this release, not an
uninstalled repository preview.

Rollback is a scoped return of the test router/watchers to their previous shared
scripts after verifying the replacement processes have stopped. Preserve the
runtime state, bindings, native threads, bubble receipts and goal SQLite journal,
including unknown controls. Merge the before-config rather than overwriting
subsequent edits. Registered commands must be reconciled with the handlers
actually installed; returning to the old router is not evidence that its new
goal/help handlers work. Do not touch HamalBot or reset native goals to roll back.

Actual phone rendering and end-to-end human command effects still need receipts;
native goal mutations were not exercised against an existing task. Other
language/menu overrides cannot be globally enumerated. PC role isolation,
admission, company authority and full clean-machine recovery remain unverified.
Menu registration and a native status read do not establish those boundaries.
