# PR 9 Shared model admission preparation

The shared admission ledger is prepared offline. It joins model-attempt claims,
root turn charges, activity leases and account reservations in one transaction.
It also retains owner-first dispatch offers, capacity waits, shared cooldowns and
once-only replacement proposals in that database. It preserves the approved three-active-session cap
and 10% owner reserve. No native runtime, subscription probe, worker endpoint or
live scheduler is enabled;
PR 9 is not accepted until every real turn source passes its pre-turn boundary.

## Shared admission and task budgets

`model_admission.py` adds an explicitly initialized component to PR 8's protected
root/outbox database, rather than independent per-role counters. An authorized
controller enrolls immutable model intents bound to the current root, role,
execution, native session, runtime/adapter digests and provider/account/model.
Intake can retain work before execution is eligible. A stored intent grants no
model call; exact admission requires independently verified current source grants,
all-source activity/fencing and complete applicable quota windows. The explicitly
enrolled estimate path below may use a retained verified baseline and independently
bounded usage when current telemetry is missing; it does not invent an allowance.

One SQLite commit records the exact outbox attempt, account pacing, conservative
window allocations, retained activity lease and once-only root charge. A wait
records its reason, observation time, next eligibility and unchanged original
deadline without charging execution or incrementing the no-progress watchdog.
Ordinary turns preserve the root's diagnostic subset. Expected revisions and
fresh root/control/binding checks reject paused, revoked, changed or expired work.
An attempted/unknown intent never obtains another execution grant on replay.

## Joined diagnostic admission

`TaskDiagnoses` can use `ModelAdmission` only on the exact same protected ledger.
Preparation pins explicit provider/account/model, native identity, runtime/adapter,
source and per-window estimates into the original diagnostic intent's sealed
context. Repeated preparation cannot change that metadata or create another
intent for the same material state. Older proposals without these fields are
held for reviewed integration, not silently converted into fresh model work.

The original diagnosis passes the common source, activity, quota, pacing and
cooldown gates. Current material, owner-control epoch, binding and deadline are
rechecked before execution. One commit advances its existing outbox attempt,
reserves account/window capacity and an activity lease, charges one turn and one
diagnosis, and enrolls its passive attempted report. Waits spend neither counter.
The root stays held; diagnosis/input acceptance is not recovered task progress,
and stop evidence is still required before releasing the activity lease.

When the shared admission component exists, the standalone diagnostic-receipt
callback cannot authorize a new attempt. Automatic diagnoses cannot claim the
fresh-owner-request pacing/reserve bypass; only a separately verified action grant
permits reserve use. This prepares the transaction bridge, not real task readers,
diagnostic prompt/native dispatch, result application or report delivery. Those
protected producer/runtime paths remain required before activation.

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
and coverage of specific prior attempts. The PC read-only observer below is not
connected to these admission receipts; no host-credential discovery is implemented.

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
attribution and the live priority driver remain unconnected; receipt booleans alone do
not authenticate a human. Steering an existing turn and stop/pause controls must
remain separate from new-turn pacing when the runtime driver is integrated.

Without the explicitly enrolled estimate path, missing or stale quota holds work
with a labeled reason. Incomplete, mismatched or changed stale observations cannot
be relabeled as outages to bypass negative evidence. An elapsed reset time requires
a fresh provider observation rather than inventing availability. No paid fallback,
model change or purchase path exists.

### PC read-only native observer (2026-10-03)

The owner-only Windows adapter adds `/limits`, using the documented
[`account/read` and `account/rateLimits/read` protocol](https://learn.chatgpt.com/docs/app-server).
Compatibility is pinned to native Codex 0.160.0 and checked against its generated
schema, not an internal socket or an assumed token allowance. Three read-only
RPCs bracket usage with the active managed ChatGPT account; no token/email is
used as identity, no login refresh is requested and no model turn, quota reset,
credit redemption, account change or paid fallback is available in this path.

`NativeQuota.cs` retains every reported bucket and primary/secondary window,
validates percentages/reset metadata, deduplicates the historical alias, rejects
conflicting aliases and account IDs, and preserves unknown windows/permissions.
Native account IDs are hashed; emails, credentials, origins, credit balances and
upsell text are not persisted. Account binding is verified only if the active
native routing ID and backend usage account ID are both present and agree.
Absent identity is explicitly unverified, not an admission grant.

Account-wide notifications are handled before thread routing. Sparse quota or
account-change events invalidate the catalog; they cannot restore old windows
or nullable spend permission. Revision guards prevent a delayed full read from
overwriting this invalidation. `/limits` always requests a fresh full snapshot,
amends the existing bubble, displays observation/reset times in UTC, and leaves
the current turn, tool history and goal alone. The network read does not hold
the session dispatch lock, so owner steering/interrupt/status can continue.
Failure stays a read failure, not an unknown external action or held session.

This is **observation, not 10% reserve enforcement**. The display says so.
Provider percentages do not prove bounded future turn cost, covered outstanding
attempts, complete model/pool applicability, Claude quota, outside consumption or
an all-source pre-turn fence. Those gates, approved pacing/estimate parameters
and integration with the existing common admission ledger remain required
before autonomous/company work. A native goal continuation cannot be fenced
retroactively by its `turn/started` notification.

The observer stores only sanitized metadata beside the router ledger and status
file. A restored observation is historical evidence: startup does not load it
as fresh availability. Consistent daily recovery still needs the complete
router/account/admission cohort and fresh provider/account verification.

136 joined/offline checks pass locally, including the existing routing/goals
suite and 59 new quota checks: malformed and missing data, account changes,
alias conflicts, permission denial, sparse/delayed races, denied foreign input,
same-bubble rendering, and an interrupt RPC acknowledged while a quota read waits
(not a claim that tools stopped).
Fixtures use no credentials, provider network or model inference. Actual PC
quota/Windows/deployment evidence is recorded separately in
[`pc-router/deployment-status.json`](../pc-router/deployment-status.json).

## Bounded quota estimates

`quota_estimates.py` joins the common admission ledger. Its policy explicitly
sets maximum baseline age, usage-proof age, starts per applicable window and a
minimum gap. Examples leave those values unconfigured; test numbers are not
owner-approved runtime defaults. Enrollment pins the estimate policy into the
composite admission digest. Runtime activation remains disabled.

Fallback requires a retained verified provider/account/model observation covering
every requested window, before its actual reset and within the configured baseline
age. A protected reader must establish a fresh upper bound on consumption not
covered by retained reservations, from that exact baseline, under the all-source
launch fence. Unknown outside use, missing baseline or proof, account/window
mismatch and expired evidence hold the original intent without spending a turn.
There is no cold-start guessed quota or synthetic window reset.

Admission adds the bounded unreserved consumption to the verified used amount,
then subtracts uncovered attempt reservations and the existing 10% reserve.
Every applicable window and model pool still gates execution. Fresh known
exhaustion uses normal quota admission, not fallback; a later outage cannot lower
the retained negative baseline. Estimated quota is labeled `conservative_estimate`
and retains both the provider's original timestamp and the usage-proof timestamp.
It never replaces or refreshes the provider baseline in account state.

The finite estimate-start count applies to owner requests too. All sessions and
models sharing an account/window use the same retained history; fresh observation
of the same window, role changes, releases and restart cannot replenish it.
Actual fresh provider telemetry can permit normal starts independently of that
fallback count. It does not erase estimate history. Estimates use shared pacing,
with their explicit minimum gap, and retain the ordinary root/cap/source gates.
Waits do not spend execution budget or count as no-progress handoffs.

The usage bound and baseline are reread after priority evaluation; changes deny
execution. Their ages are also checked at the final admission clock, closing a
reproduced expiry race. One commit stores the estimate receipt/history with the
original outbox attempt, root charge, account reservation and activity lease.
Missing estimate history is detected against retained model attempts rather than
resetting the counter. Post-commit recovery holds activity and never grants that
attempt again.

This prepares the guarded transaction path, not a real all-source usage ceiling.
Typed test receipts are synthetic. Protected external-usage readers, compatible
provider provenance, explicit approved policy and real pre-turn fencing remain
activation gates. Where consumption cannot be bounded, the system must keep the
task held and report uncertainty; a start-count limit alone cannot guarantee the
owner's reserve.

## Durable owner-first dispatch offers

`model_dispatch.py` enrolls bounded offers in the same protected database. An
offer pins the original intent, attempt, plan, revision, target and model request;
it reserves no model capacity or root turn. Exact repeats retain their original
sequence. A full pending queue retains the unoffered intent rather than dropping
work. The pending bound requires explicit policy; fixture values are not runtime
defaults. Original deadlines and cancellation remain effective during waits.

Once the component is enrolled, an unoffered direct model claim is refused.
Among currently eligible offers, independently verified owner requests precede
automation; each class keeps sequence order. Priority is reread through the
protected source verifier, not taken from a stored owner flag. Known busy,
stopped, expired, cooldown-held or freshly quota-exhausted offers do not block
otherwise runnable work. Unverifiable previously owner-requested work retains
a labeled hold on automation rather than granting execution or discarding it.
Missing quota is not treated as proof of available capacity.

The common admission path still enforces quota, reserve, pacing, root budgets,
current authority and the three-active-session cap. It rechecks the current
source grant after examining other offers, closing a reproduced revocation race.
The offer becomes attempted in the same commit as its original outbox attempt,
root charge, account reservation and activity lease. Recovery cannot grant that
attempt again. Cancellation holds only unattempted work; it does not interrupt
running tools or release activity. Steering, pause and stop need their separate
runtime control paths.

Enrollment pins a composite pacing/dispatch policy digest, preventing a
pacing-only admission checksum from authorizing new attempts against the enrolled
state. Sequence/history and supported metadata are validated without resetting
them. Signed compatible runtime deployment remains necessary; this does not prove
that every historical reader understands the new component.

This is the offline priority boundary, not a polling loop, native dispatcher or
human authentication mechanism. Protected producers, current source-grant readers
and the live driver remain unconnected. Comparing another diagnostic offer
requires its current same-ledger diagnosis guard; without that guard it remains
unverified, not silently admitted.

## Capacity retries and shared admission

`capacity_journal.py` retains one original job, captured failure time, exact
negative receipt, finite retry allowance and original deadline across replacement
intents. Failure/wait/cooldown/report and proposal/outbox commits are atomic.
Account-wide cooldowns apply across models; model cooldowns apply across roles
using that model. A provider minimum longer than local backoff is not shortened.
Duplicate evidence, restart or changed role cannot replenish retry limits.

Stored replacements grant no execution. Shared admission rechecks the exact
requested proposal, current negative/no-native-retry evidence, cancellation and
deadline before charging a turn. They need fresh source approval, quota/reserve
capacity and verified stop evidence for any retained activity lease. The original
owner-request flag cannot make an automatic retry a fresh owner request.

Unknown input acceptance, native retries and partly executed failed turns remain
held rather than replayed. Fresh-input journal preparation is not steering or
checkpoint-continuation support; both native paths remain required. Passive
report intents are stored, not delivered. A recovered input-acceptance notice
does not mean task completion. [Retry evidence and recovery](model-capacity-retries.md).

## Planning and recovery

`ccrelay_admission.py --plan` reads only the disabled repository example and
reports unavailable runtime/probe/fence/grant/stop integration. Its three numerical
pacing/freshness values remain unset. Owner-priority activation and dispatch policy
configuration are also explicitly false. Runtime commands are unavailable. The test
runner copies its source/template through explicit allowlists; none is installed.
Quota-estimate activation, policy configuration and real usage-bound verification
are also reported as unavailable.

Register `ccrelay.model_admission.v1` with the full-system recovery inventory.
Capture a consistent root/outbox SQLite cohort including `model_metadata`,
`model_accounts`, `model_attempts` and `model_waits`, plus the
`ccrelay.capacity_journal.v1` metadata/jobs/failures/cooldowns, linked replacement
and report intents, all related outbox receipts, root history, account/window
provenance and authenticated runtime mappings. Unknown component versions are
refused before root recovery; changed pacing or retry policies require reviewed
migration. Compatible readers must preserve held leases, unknown attempts,
cooldowns, retry history, pacing and estimates. An older reader that lacks the
admission boundary is not an authorized runtime. Include sealed diagnostic model
requests and original diagnostic/report intents in the same cohort; there is no
separate diagnostic quota store. Joined encrypted clean-target restore is
still pending; these tables are not a complete disaster-recovery implementation.

Include `ccrelay.model_dispatch.v1` metadata and all offers, their retained
sequence, pinned plans, initial source proofs, original intent links and the
composite admission policy digest in that same consistent cohort. Preserve
cancelled/attempted history and held model attempts. There is no separate dispatch
database, and restoring an offer never proves execution or tool quiescence.

Include `ccrelay.quota_estimates.v1` metadata and complete attempt history in
the same cohort, with labeled estimate receipts, verified provider baselines,
usage proofs, window/reset identities and the composite policy digest. Restore
cannot replenish per-window estimate-start counts or refresh baseline timestamps;
real usage must be reverified before another estimated turn.

## Verification and remaining gates

Twenty-four admission and two planner cases cover account sharing, adaptive gaps,
the combined three-session cap, per-window reserve, owner versus autonomous use,
stale/missing evidence, stop proofs, plan/source races, diagnostic reserves,
integrity and recovery. Two actual isolated process deaths straddle admission
commit: pre-commit rolls back the entire attempt/root/account/lease bundle;
post-commit preserves it as held/unknown without another execution grant. SQLite,
files, locks and deaths are real; all kernel/source/provider observations are
explicitly synthetic, not native or distinct-UID PC acceptance.

The preceding shared-admission milestone (`c75bfe4`) passed all 724 core tests
in 181 serial sandbox batches, the isolation probe and all four legacy suites. Candidate code ran only
inside the OS sandbox, without host home/credential/network access or increased
child timeouts; the unrelated user-owned protocol edits were excluded. The strict
staged secret scan passed. This is regression evidence, not live native admission.

The subsequent capacity-journal preparation passed 386 clean-staged focused
root/diagnosis/admission/retry/native/storage checks in 97 serial sandbox batches,
including 18 new journal cases and four actual failure/proposal commit deaths.
Cancellation during a quota probe and elapsed expiry at the final admission clock
cannot obtain another attempt or root charge. This is a focused regression run,
not a new full-suite milestone; all source/provider observations remain synthetic.

The joined diagnostic preparation adds 16 cases covering the same-ledger boundary,
once-only counters/leases, finite diagnostic allowance, metadata/plan drift,
standalone bypass refusal, shared cap/pacing/cooldowns, missing quota, owner
reserve, stop evidence and material/control races. Two actual process deaths
straddle the common commit: all diagnosis/outbox/account/slot changes roll back
before commit or survive together as held/unknown afterward, without replay.
The clean staged-source run passed all 758 core tests in 190 serial sandbox
batches, the isolation probe and all four legacy suites. The strict staged secret
scan passed at the joined-diagnosis milestone (`6223bb9`). These observations remain synthetic and do not establish real native
dispatch, protected PC fencing or target acceptance.

Sixteen owner-priority cases cover durable order, duplicate offers, direct-claim
bypass refusal, bounded pending work, cancellation, busy/quota-blocked owners,
current source rechecks and the unchanged activity cap. Four actual isolated
process deaths straddle offer and common-admission commits: pre-commit changes
roll back; post-commit history and held attempts survive without another grant.
Owner arrival during a quota observation is seen before automation commits, and
revocation during either quota observation or another offer's priority read
cannot grant execution. All owner/source/provider observations remain synthetic.
The clean staged-source run passed 418 focused root/diagnosis/admission/retry/
native/storage checks in 105 serial sandbox batches, without host home,
credentials, network access or increased child timeouts. This is focused
regression evidence, not a replacement for the historical full-suite runs or
target acceptance.

Twenty quota-estimate cases cover absent/stale/expired baselines, every applicable
window, bounded outside usage, reserve preservation, shared gap/start limits,
owner requests, model changes, fresh negative evidence, replay and missing
history. Usage changes during priority evaluation and proof expiry at the final
clock cannot grant execution. Two actual isolated process deaths straddle the
common attempt commit: estimate history and the original root/account/slot/outbox
bundle roll back or survive together, without replenishing counts or replaying
the attempt. The clean staged-source run passed all 794 core tests in 199 serial
sandbox batches, the isolation probe and all four legacy suites, without host
home/credentials/network access or increased child timeouts. The strict staged
secret scan passed. Quota, usage and source facts remain synthetic; this is not
native-provider or target-PC acceptance.

Remaining integration includes protected owner/company grants, real all-source
native pre-turn controls and quiescence, compatible subscription/window adapters,
the protected priority producer/driver and explicit pending policy, real usage ceilings and approved estimate policy, the passive status
bridge, protected diagnostic producers/current result application, real capacity/native-retry classification,
steering and checkpoint-continuation adapters, and encrypted target restore.
Existing native sessions, bots, credentials and services remain unchanged.
