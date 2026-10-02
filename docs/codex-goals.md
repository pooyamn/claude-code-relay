# Native Codex goal controls and rolling status

Prepared in repository code on 2026-10-02; not deployed to live watchers or bots.
The installed Codex CLI is 0.160.0. Its generated standard (not experimental)
schema includes `thread/goal/get`, `thread/goal/set`, `thread/goal/clear`,
`thread/goal/updated` and `thread/goal/cleared`. A separate read-only daemon
connection initialized and read the existing exact native thread's active goal;
it did not resume a thread, change a goal, interrupt work or start inference.
Schema generation is compatibility evidence, not live mutation acceptance.

## Commands and UI

| Command | Native action |
| --- | --- |
| `/goal <objective>` or `/goal set <objective>` | Set an explicit active goal |
| `/goal` or `/goal status` | Read native status |
| `/goal pause` | Update only status to paused |
| `/goal resume` | Update only status to active |
| `/goal clear` | Explicitly clear the native goal |

`cc goal …` and `/cc goal …` are aliases for gateways that intercept slash
commands. Objectives keep their case and are limited to 4000 characters. The
native thread must already exist; no new thread or model fallback is created.
Pause/resume omit objective and token budget, preserving native accounting.
Replacing an objective does not reset the target system's root budget/deadline.
These semantics follow the [native goal guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)
and [app-server contract](https://learn.chatgpt.com/docs/app-server).

The rolling message ends with, for example:

```text
Working (3m 12s)
Goal: active — Finish the DUT board mapping
```

The goal is native evidence, not a scraped user/model claim. Cross-thread events
are ignored, and delayed read/write replies cannot overwrite newer live
notifications. Missing/unsupported evidence is labeled unavailable. A compact,
redacted literal objective leaves room for the newest work and both footer
lines within 3900 rendered UTF-16 units. Controls amend the current bubble where
one exists; a control without a native turn receives an explicit command reply.
Completed-turn bubbles remain editable for goal changes without a second live
message. A completed turn and a completed goal are distinct.

## Mechanism and limits

`relay_codex_goal.py` supplies parsing, native goal validation/control and a
separate SQLite inbox. `relay_codex_bubble.py` extends the existing connection
wrapper, so the unrelated user-owned `relay-codex-proto.py` edits remain untouched.
The watcher uses its existing connection, not another thread writer. Commands
are intercepted before all prompt/JSONL paths and are processed separately from
the message queue. The legacy direct bot checks its authorized-owner list even
in wildcard-member chats; company-delegated controls remain disabled. The
OpenClaw entry path still depends on its existing trusted ingress ACL.

The inbox stores the exact native thread and command, commits `unknown` before
dispatch, and changes that row only on a classified result. Uncertain commands
are never eligible again; a new status request inspects native state and reports
held commands. An explicit subsequent user change is a new intent, not automatic
recovery of the old one. Native RPC has no relay idempotency key; a native read
does not prove which actor caused a matching state. A rebinding rejects the old
intent, and the connection rechecks the durable exact-thread pointer before RPC.

Goal pause is not `turn/interrupt` and does not prove running tools/descendants
have stopped. No current live goal was paused, resumed, replaced or cleared in
testing. Resume/set can cause native automatic continuation; their target-PC
activation must wait for pinned pre-turn admission, company-scoped authority,
root accounting, the three-active-session cap and 10% owner reserve gates.
These common-user Mac files do not establish those security boundaries. The
native read probe does not prove pause/continuation/stop behavior.

## Verification and recovery

Use only `scripts/tests/run_isolated.py --suite all`: copied-source OS sandbox,
synthetic native RPC/provider, no Telegram/network/credentials or model calls.
Focused tests cover parsing/aliases, status-only params, native clear, invalid
accounting, missing/complete goals, stale/foreign events, exact binding races,
unknown requests, owner-only routing, prompt/JSONL interception and the shared
one-message footer. Three actual scratch-process deaths exercise before-write,
accepted-write/lost-ACK and received-result/pre-ledger-commit boundaries; each
survives restart without another native mutation. The final clean staged-source
run passed all 327 core tests (including 30 goal tests) and all four legacy suites,
excluding the unrelated user-owned protocol edits. The earlier working-tree run
also passed. No live mutation/bot acceptance is inferred from those results.

New legacy state is `relay-work/codex-goals-<session>.sqlite`, schema/user-version
1. Preserve unknown rows and unsupported versions; do not clear a journal to
re-enable a mutation. Before any activation, register this component in the
full-system recovery inventory alongside native goal state/accounting, exact
thread/binding mappings and bubble receipts. Use a consistent SQLite backup
or quiesced copy, not a live main-file-only copy; native persisted state must be
handled according to the pinned runtime's backup contract. After restoration,
reconcile native state, unknown controls and grants before continuation.
Local in-memory bubble notices are not a durable Telegram receipt; the PR 6
protected sender/intake integration is still required.

Live activation requires an exclusive verified Khadang test route, owner-issued
controls with native/UI receipts, compatibility and pause/current-turn evidence,
protected target integration and clean-target restore acceptance. Do not start a
second poller, modify HamalBot wiring, restart the native daemon or use a bound
model session as a fixture. Rollback removes the adapter activation, not native
goals or command history; preserve the journal for inspection. This is scoped
preparation, not completion of PRs 6–9 or design acceptance test 15.
