# Native Telegram command menus

Prepared in repository code on 2026-10-02. This feature registers the relay's
implemented controls as Telegram bot commands and adapts discovery to the bound
session types. It has not been activated on the live Khadang daemon. HamalBot
wiring, native sessions, credentials, bindings and allowlists are unchanged.

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

Actual bot-menu rendering, native control effects, language overrides and live
Khadang activation remain unverified. No menu test is evidence of a completed
PC integration, safe goal continuation or company authorization boundary.
