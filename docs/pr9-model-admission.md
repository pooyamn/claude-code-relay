# PR 9 Shared model admission preparation

The shared admission ledger is prepared offline. It joins model-attempt claims,
root turn charges, activity leases and account reservations in one transaction.
It preserves the approved three-active-session cap and 10% owner reserve. No
native runtime, subscription probe, worker endpoint or live scheduler is enabled;
PR 9 is not accepted until every real turn source passes its pre-turn boundary.

## Shared admission and task budgets

`model_admission.py` adds an explicitly initialized component to PR 8's protected
root/outbox database, rather than independent per-role counters. An authorized
controller enrolls immutable model intents bound to the current root, role,
execution, native session, runtime/adapter digests and provider/account/model.
Intake can retain work before execution is eligible. A stored intent grants no
model call; exact admission requires independently verified current source grants,
all-source activity/fencing and complete applicable quota windows.

One SQLite commit records the exact outbox attempt, account pacing, conservative
window allocations, retained activity lease and once-only root charge. A wait
records its reason, observation time, next eligibility and unchanged original
deadline without charging execution or incrementing the no-progress watchdog.
Ordinary turns preserve the root's diagnostic subset. Expected revisions and
fresh root/control/binding checks reject paused, revoked, changed or expired work.
An attempted/unknown intent never obtains another execution grant on replay.

## Activity leases and verified stops

Admission counts the union of retained leases and independently observed activity
from every source, not merely turns visible to Telegram. Another turn cannot
start in an occupied session, and a fourth active session waits. Idle sessions
are not charged a slot. The real observer must establish the held pre-turn fence,
including native-app and automatic goal continuations; a typed receipt or an
observer log after execution begins does not enforce that fence.

Restart changes retained active leases to held without freeing them. A terminal
outbox row, timeout, pause or missing process observation is not stop evidence.
Release requires current controller authority and independent all-tool quiescence
under a held launch fence, scoped to the exact admitted generation. The stop
receipt is retained. Releasing activity does not release PR 8's worktree custody
or erase its outstanding quota estimate. Waiting delegators need this proof too.

## Account pacing and owner capacity

Quota evidence is scoped to provider/account/model, observation source/time and
every applicable account or model pool. Each window has its allowance, used units
and reset time; each intent supplies a finite conservative estimate for every
window. The protected adapter must establish complete window/account provenance
and coverage of specific prior attempts. No live quota adapter or host-credential
discovery is implemented here.

Automation leaves the ceiling of 10% of each window's total allowance untouched,
not 10% of what happens to remain. Uncovered estimates from admitted attempts are
subtracted even after their activity ends; only verified provider coverage or a
verified new window removes that conservative overlap. Used quota plus retained
estimates may intentionally double-count until coverage is established. This is
not exact token accounting or a guarantee that a long turn cannot exceed its
estimate; real bounded checkpoints and outside-activity observation remain gates.

The minimum gap and observation ages require explicit approved policy values;
the examples leave them unset. Adaptive spacing also spreads estimated automated use
across the remaining window and increases when available capacity falls. All
roles sharing an account share its persisted last start and next eligible time.
Changing roles, messages or restarting cannot reset those values. Pacing indexes
are checked against their retained body/digest before use.

An independently verified Pouya-requested new turn may bypass automated spacing
and use his reserve, but not actual quota or the global activity cap. Autonomous
support needs an explicit action-scoped owner reserve grant. Real owner/company
attribution and priority dispatch remain unconnected; receipt booleans alone do
not authenticate a human. Steering an existing turn and stop/pause controls must
remain separate from new-turn pacing when the runtime driver is integrated.

Missing, stale, incomplete or mismatched quota holds work with a labeled reason;
an elapsed reset time requires a fresh provider observation rather than inventing
availability. The required bounded conservative fallback for missing telemetry
is still pending. No paid fallback, model change or purchase path exists.

## Planning and recovery

`ccrelay_admission.py --plan` reads only the disabled repository example and
reports unavailable runtime/probe/fence/grant/stop integration. Its three numerical
pacing/freshness values remain unset. Runtime commands are unavailable. The test
runner copies its source/template through explicit allowlists; none is installed.

Register `ccrelay.model_admission.v1` with the full-system recovery inventory.
Capture a consistent root/outbox SQLite cohort including `model_metadata`,
`model_accounts`, `model_attempts` and `model_waits`, all related outbox receipts,
root history, account/window provenance and authenticated runtime mappings.
Unknown component versions are refused before root recovery; a changed pacing
policy requires reviewed migration. Compatible readers must preserve held leases,
unknown attempts, pacing and estimates. An older reader that lacks the admission
boundary is not an authorized runtime. Joined encrypted clean-target restore is
still pending; these tables are not a complete disaster-recovery implementation.

## Verification and remaining gates

Twenty-four admission and two planner cases cover account sharing, adaptive gaps,
the combined three-session cap, per-window reserve, owner versus autonomous use,
stale/missing evidence, stop proofs, plan/source races, diagnostic reserves,
integrity and recovery. Two actual isolated process deaths straddle admission
commit: pre-commit rolls back the entire attempt/root/account/lease bundle;
post-commit preserves it as held/unknown without another execution grant. SQLite,
files, locks and deaths are real; all kernel/source/provider observations are
explicitly synthetic, not native or distinct-UID PC acceptance.

The clean staged-source milestone passed all 724 core tests in 181 serial sandbox
batches, the isolation probe and all four legacy suites. Candidate code ran only
inside the OS sandbox, without host home/credential/network access or increased
child timeouts; the unrelated user-owned protocol edits were excluded. The strict
staged secret scan passed. This is regression evidence, not live native admission.

Remaining integration includes protected owner/company grants, real all-source
native pre-turn controls and quiescence, compatible subscription/window adapters,
owner-priority dispatch, bounded missing-telemetry estimates, the passive status
bridge, joined diagnostic admission, durable capacity retries/shared cooldowns,
and encrypted target restore. Existing native sessions, bots, credentials and
services remain unchanged.
