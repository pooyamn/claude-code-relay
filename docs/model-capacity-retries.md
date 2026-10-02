# Model capacity retry policy and integration gates

Pouya requested automatic retries when a model is temporarily at capacity on
2026-10-02. The design assigns execution to PR 9's shared admission scheduler,
using PR 7's pinned native adapters. Local preparation provides tested pure policy
code; automatic live retrying is not yet enabled. Neither Khadang nor HamalBot
wiring, services or credentials changed.

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

## Evidence and limits

Eighteen tests in `scripts/tests/test_core_capacity_retry.py` cover backoff, jitter,
provider minimums, retry and elapsed bounds, original deadlines, deduplicated
evidence, cancellation, scope/policy drift, native retry deferral, stale-operation
constraints and serialization. They run inside the copied-source OS sandbox:

```sh
python3 scripts/tests/run_isolated.py
```

This module performs no provider call, blocking sleep, state-file write, admission
grant or live error classification. Serialization tests are not a process-death
or durable-transaction proof. The actual shared scheduler must atomically persist
waits and proposals before acting, retain the proposal/outbox link across crashes,
and join full backup/paused restore. PR 9 must demonstrate those tests; this
preparation does not mark that PR implemented.

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
identity, provider wait parsing and ownership/accounting of native retries. PR 9
must use one durable provider/account scheduler with model-scoped cooldowns,
persist policy/counters/deadlines and atomically consume each replacement proposal.
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
