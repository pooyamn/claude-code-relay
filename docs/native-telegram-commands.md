# Native Telegram command menus

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
