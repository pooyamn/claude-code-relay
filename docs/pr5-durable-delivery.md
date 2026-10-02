# PR 5 Durable delivery preparation and recovery

Local preparation dated 2026-10-02 supplies a protected action outbox, authenticated
MCP message enrollment and a guarded Codex steering adapter. It does not activate
native delivery, change either live bot, or establish target-PC acceptance.
Khadang remains the integration-test bot. HamalBot wiring, services, credentials
and the unrelated Codex protocol edits remain untouched.

## Delivery state and authority

`scripts/relay_core/outbox.py` persists the existing PR 1 message and external-action
contracts in a private SQLite ledger. Stable intent IDs, parameter digests,
provenance context, attempt IDs, exact adapter plans and outcome evidence survive
restart. The database uses full synchronous commits, a lifetime file lock and
directory fsync at creation. Recovery holds that lock before converting in-flight
attempts to unknown; it cannot run alongside another local ledger owner.

The protected driver commits a claim and its immutable plan before submission.
An identical claim replay returns `may_execute=False`; changing the attempt or
plan is denied. Receipt and terminal state commit in one transaction. A lost
acknowledgment or interrupted submit stays unknown until independent evidence
matches the intent, attempt and plan. Neither missing evidence nor restart is
permission to resubmit. A failed intent also cannot be reset; a separately
authorized replacement must retain its negative evidence.

| State | Meaning | Permitted next action |
| --- | --- | --- |
| Stored or held | No adapter attempt has begun; persistence is not queued model input | Revalidate the target and all authorization gates before a first claim |
| Delivering or submitted | Exact attempt is durable; adapter acceptance is not yet confirmed | Finish receipt persistence, or recover to unknown |
| Unknown | The effect may or may not have happened | Reconcile verified evidence; never blind retry |
| Confirmed | Exact input or external operation was accepted | Inspect the receipt; do not repeat the operation |
| Failed | Verified negative outcome is retained | Policy may authorize a new linked intent, not reset this one |

Decoding a plan, authorization reference or evidence envelope is not authentication.
Only trusted protected code may claim, submit, release a hold or reconcile an
outcome. Those methods are deliberately absent from worker RPC and MCP surfaces.
The outbox does not replace PR 3 owner approval or later admission/publication
checks, and does not execute arbitrary external actions. Its generic action
contract is preparation for separately authorized adapters. The local lock does
not fence another machine or establish a provider-side idempotency primitive.

## Authenticated MCP messages

`scripts/ccrelay_broker_mcp.py` exposes `send_message`, `message_status` and
`message_log` through the protected broker. The broker derives role, sender,
session and root from PR 2 kernel credentials and launcher bindings. It never
uses cwd, environment or a header claiming to be another agent.

Each caller chooses an opaque `intent_id` once and reuses the same ID and exact
arguments after an uncertain broker acknowledgment. The server scopes that ID
to the authenticated session. Transport request IDs remain separate from intent
IDs. Changed parameters with a reused intent ID are denied. Only the sender and
recipient can inspect a message. Logs use bounded cursor pages without cutting
message bodies; a body that cannot fit the protected frame is rejected explicitly.

Enrollment currently reports `held` with `runtime_delivery_gate_pending`, not
delivered or queued. Only explicit `steer` and `start` intent modes are accepted;
the latter still needs future admission and cannot be used as a steering fallback.
No native adapter runs from the broker entry point in this preparation.

Replies require a confirmed inbound parent visible to the caller and the same
admitted root. Unknown parent IDs cannot reset the existing three-hop guard.
Cross-root replies await PR 8's explicit inherited-root admission rather than
letting a worker mint its own root. New message chains remain possible: this hop
guard does **not** replace the root counters or three-handoff progress watchdog
planned in PRs 8 and 14.

The legacy `ccrelay_mcp.py` bus and its live configuration are unchanged. This
new protected client must be installed through a reviewed launch artifact before
it can enforce isolation on real sessions.

## Guarded steering

`scripts/relay_core/runtime_delivery.py` accepts an already initialized protected
RPC transport, trusted exact-session observations, compatibility evidence and an
authorization callback. It discovers no host socket, login or provider process.
The pure plan binds native thread, exact turn, runtime/tool/permission digests
and observation reference to the attempt.

OpenAI documents `turn/steer` with an `expectedTurnId` that must match the active
turn; a successful response returns the accepted turn ID. This is the remote
guard used here, not a claim inferred from local busy status.
[Official OpenAI app-server documentation](https://learn.chatgpt.com/docs/app-server#steer-an-active-turn).

Unsupported steering, absent readiness or a changed turn retains the unsubmitted
intent on hold. A timeout, malformed acknowledgment, mismatched request/turn or
provider error after submission remains unknown. Version-specific errors are
not promoted to definite negative evidence without characterization. No branch
calls `turn/start`, queue, resume, fork or fresh-thread creation. A steer that
loses the completion race therefore cannot land in a different turn.

Confirmation means **input accepted**, not task completed or verified progress.
An inactive session has no turn to steer. Its first turn requires an explicitly
admitted start, not reinterpretation of an already submitted steering intent.
Pouya's active-turn steering preference remains the intended owner policy;
connecting the durable Telegram dispatch to this adapter is still gated.

## Local evidence

Run the copied-source OS sandbox, not legacy tests against live state:

```sh
python3 scripts/tests/run_isolated.py
```

The new fixtures use invented identities, session observations and a deliberately
non-idempotent fake provider: every call records another effect, even if it repeats
the same request ID. Tests cover deduplication, changed intent rejection, attempt
uniqueness, terminal receipt immutability, exact evidence binding, participant
visibility, pagination, three-hop enforcement, stale/unsupported steering,
authorization denial and acknowledgment loss. Actual separate-process lock
contention and process death exercise storage before/after commit, claim
before/after commit, submission, adapter effect and receipt before/after commit.
Restart neither loses a committed intent nor repeats an uncertain/confirmed
effect in those tested traces. Death before a claim commit rolls back and permits
a first attempt; death after claim but before effect remains unknown, not retried.

The macOS OS sandbox excludes host credentials, production state and network.
Only scratch-path protection checks and kernel/native observations are substituted
for fixtures. SQLite commits, fsync, file locks, separate processes and crashes
are real. These tests are not Linux distinct-UID, native-provider or Telegram
acceptance. The fake provider's receipt lookup demonstrates reconciliation; it
does not prove that real Codex exposes sufficient evidence after a lost reply.

## Recovery and remaining gates

Preserve an incompatible or damaged database and its WAL for inspection. Unknown
schema/policy, changed indexes, context, plan or evidence stops access; there is
no empty-database fallback or silent migration. A consistent snapshot API uses
SQLite backup into a new private file and fsyncs it and its parent. PRs 12 and 13
must include the outbox, receipts and protected policies in full encrypted
recovery, restore paused and reconcile before releasing work.

Before enabling this capability, the remaining sequence is:

1. PR 6 records outbound owner/status/approval delivery with the shared Telegram
   scheduler. A returned local result is not proof that Pouya received an alert.
2. PR 7 supplies pinned initialized no-auto-retry native transports, authenticated
   exact-session observations, role-isolated visibility and Claude conformance.
   Installed runtime versions must prove their own input acceptance and error
   semantics; unsupported acknowledgments remain unknown, not fabricated success.
3. PRs 8 and 9 supply inherited-root checkout, finite counters, all-source
   admission, pacing and the 10% owner reserve. The owner-ingress bridge must verify
   the private PR 4 dispatch source and exact route, choose active-turn steering
   before a claim, preserve dispatch identity, and report holds/unknown outcomes.
   Neither body text nor a worker-provided dispatch envelope may assert ownership.
4. Real native loss-of-ack recovery must demonstrate authoritative evidence or
   retain unknown for owner reconciliation. PR 10 preserves these intents and
   attempts across switching; PR 11 gates publication/external operations.
5. The clean-machine restore and target-PC acceptance drills must pass before a
   separately authorized cutover. Inspect Khadang's existing poller first; do not
   run another poller or change HamalBot to obtain a test result.

No unit test or commit enables an adapter, starts a paid/model turn, migrates
legacy state or authorizes deployment. Keep the reviewed preparation commit and
compatible state together; do not roll older code over a newer ledger schema.
