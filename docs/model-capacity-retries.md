# Model capacity retry policy and integration gates

Pouya requested automatic retries when a model is temporarily at capacity on
2026-10-02. The design assigns execution to PR 9's shared admission scheduler,
using PR 7's pinned native adapters. Local preparation provides pure policy and
a durable journal joined to shared admission; automatic live retrying is not yet
enabled. Neither Khadang nor HamalBot wiring, services or credentials changed.

## Prepared policy

`scripts/relay_core/capacity_retry.py` keeps one versioned state for a pinned
work/root, provider/account/model, native session, runtime/adapter and operation
mode. A protected adapter supplies classified failure and evidence references.
The words “at capacity,” a decoded JSON object or an arbitrary 429/5xx do not
authenticate that evidence or prove that input was rejected.

The policy schedules a nonblocking wait only for temporary capacity with proven
unaccepted input, or a reconciled terminal failure explicitly handled as a
checkpoint continuation. It honors the provider minimum wait, uses increasing
locally capped backoff with bounded jitter, and limits retries and total elapsed
time within the original root deadline. All numerical policy values are mandatory
inputs; test values are invented, not production defaults. The current record
format supports up to 50 retained automatic retries, a technical storage bound
and not a recommended retry budget.

Duplicate failure evidence cannot change a wait or reset counters. Changed
evidence under the same ID is denied. A due timer yields one stable replacement
proposal, bound to its root and negative evidence. A following failure must name
that exact requested intent. Restoring a serialized requested state retains the
proposal for reconciliation and does not emit it again. Cancellation retains
history; changed scope/policy and backward clock movement fail closed.

Unknown acceptance, quota/authentication/other errors and a native runtime already
retrying remain held. Steering preserves the exact expected turn. A partly
executed failed turn cannot be retried as fresh input; continuation requires
verified checkpoint and external-action reconciliation. No model, tool, session,
subscription or paid fallback is silently substituted.

## Durable journal and shared cooldowns

`capacity_journal.py` stores one job across an original admitted intent and its
replacements in the existing protected root/outbox database. The failure capture
time, original deadline, policy, negative delivery evidence and native-retry
observations survive restart. Duplicate observations cannot reset the first failure
time or retry allowance. The failure, wait, account/model cooldown and passive
report intent commit together; a due proposal and its exact outbox link also
commit together before any attempt can execute.

Every replacement requires fresh shared admission. The original activity lease
remains occupied until independently verified stop evidence permits release;
root budgets, quota, pacing, current source grants and the 10% owner reserve still
apply. An automatic retry is not a new Pouya request and cannot inherit the
original request's reserve bypass. Cancellation is rechecked after observation,
and a stored proposal cannot execute after its elapsed deadline. Account-wide
provider waits apply across roles and models; model-specific waits spare an
unaffected model. Cancellation does not erase a provider cooldown.

The journal prepares fresh-input replacements only when exact negative evidence
proves rejection and no native retry is pending. Steering and checkpoint
continuation still require their own pinned native adapters; they must not be
converted to new input. The journal makes no provider/model call and sends no
Telegram message. Passive report intents await PR 6's protected producer and
current owner/company binding. A confirmed replacement-input receipt reports
acceptance, not task completion or verified tool quiescence.

## Evidence and limits

Eighteen tests in `scripts/tests/test_core_capacity_retry.py` cover backoff, jitter,
provider minimums, retry and elapsed bounds, original deadlines, deduplicated
evidence, cancellation, scope/policy drift, native retry deferral, stale-operation
constraints and serialization. They run inside the copied-source OS sandbox:

```sh
python3 scripts/tests/run_isolated.py
```

The pure policy module performs no provider call, blocking sleep, state-file
write, admission grant or live error classification. Its serialization tests are
not process-death evidence. The separate journal tests use real isolated SQLite
transactions and scratch-process deaths around failure and proposal commits;
source, provider and stop observations are explicitly synthetic. This does not
establish native replay semantics, protected PC authority or PR 9 acceptance.

Eighteen additional journal cases passed within 386 clean-staged focused checks
in 97 serial sandbox batches. Four actual process deaths straddle failure and
proposal commits. The cases cover shared cooldowns, exact rejection, original
stop/admission requirements, reserve misuse, cancellation races, exhausted
allowances, elapsed deadlines, corruption and revocation. A final-clock
regression reproduced an expired retry receiving an execution grant; the final
admission recheck now denies it without charging a turn or retaining a new lease.
These fixtures perform no live provider, bot or native-session operation.

OpenAI's API guidance distinguishes overload from quota errors, treats a provider
wait as a minimum, and recommends bounded backoff/jitter and accounting for SDK
retries. [Official OpenAI retry guidance](https://developers.openai.com/api/docs/guides/rate-limits#error-mitigation).
Anthropic documents temporary overload separately from rate/spend limits and
notes that errors can occur after streaming begins. [Official Anthropic errors](https://platform.claude.com/docs/en/api/errors).
These are API-level patterns, not proof of the installed Codex/Claude native
runtime's error codes, acceptance or replay semantics. The local ccbot survey
also has an overload fixture and preserves structured Codex error information;
that prior art is not runtime conformance or a reason to trust agent-editable
transcripts as privileged failure evidence.

## Required integration

PR 7 must establish protected error/acceptance observations, exact session/turn
identity, provider wait parsing and ownership/accounting of native retries. The
prepared journal joins durable cooldowns, counters and proposals to one shared
admission database; real native dispatch and recovery integration remain required.
Disable nested SDK/native retries or charge their verified attempts to the same
budget; do not add an independent loop around an already-retrying native turn.

Every actual attempt passes fresh cancellation/pause checks, target/turn/adapter
validation, approval and inherited-root limits, the three-active-session ceiling,
shared cooldown/quota checks and the 10% owner reserve. Waiting is not verified
progress and grants no execution slot or extra budget. Release a slot only after
the original writer/tools are proven stopped or quiesced. PR 6 coalesces passive
wait/next attempt/recovered notifications and reports exhausted limits or a
threatened deadline without waking management models. Keep unknown external
effects for PR 5 reconciliation, never repeat them to rebuild context.

## Recovery inventory

Register `ccrelay.capacity_journal.v1` in the full-system inventory. Back up
`capacity_metadata`, `capacity_jobs`, `capacity_failures` and `capacity_cooldowns`
as part of a consistent root/outbox/admission SQLite cohort, including linked
replacement and passive-report intents, negative receipts, original policy,
authenticated runtime mappings and captured source evidence. A main-file-only
copy of a live WAL database is insufficient. Unknown versions and changed
policies require reviewed migration; neither restoration nor an older reader may
reset retry history, silently release held leases or replay unknown attempts.
Encrypted restoration onto a clean target remains an integration gate.
