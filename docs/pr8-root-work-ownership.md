# PR 8 Root budgets and work ownership preparation

PR 8's protected ledger is prepared offline, not activated. It preserves root
budgets, assessed progress and exclusive resource custody across sessions and
recovery. It does not admit a model turn, launch a worker or establish that real
writers stopped. PR 7's target-native gates, protected controller integration,
real evidence verifiers and PR 9's all-source admission remain prerequisites.

## Root budgets and inherited identity

`scripts/relay_core/work_ownership.py` reuses the strict root-task contract and
private SQLite/lifetime-lock mechanism. A permitted kernel-authenticated role
controller enrolls an accountable owner, acceptance criteria, explicit finite
turn/delegation/diagnostic limits and a future checkpoint deadline. Workers cannot
create roots. The approved initial watchdog threshold is three; its configurable
value is pinned separately to each root's enrollment history. Reusing a root ID
cannot alter criteria, limits or threshold, or clear counters.

Charging derives the root, session and execution from current authenticated
bindings, not cwd, message text or a requested replacement root. Multiple sessions
under one admitted root share its counters. A stable operation ID charges once;
replay retains the receipt without granting another execution. A diagnostic
attempt consumes both the root's diagnostic allocation and a turn. Charges are
conservative attempt accounting, not measured token usage or subscription quota.
Ordinary turns cannot consume the remaining diagnostic subset of the total budget.
Production limits are still owner choices; numerical fixtures are not defaults.

A mandatory protected millisecond clock and persisted high-water mark reject
clock regression and expired deadlines. Pausing, new message chains, native goal
replacement, provider switching and recovery do not extend deadlines or replenish
budgets. The trusted launcher must preserve the same admitted root when creating
children; neither this ledger nor a worker can rebind an existing session.

## Completed results and verified progress

Delegation charging and result assessment are separate. A send, acknowledgment or
in-flight wait does not increment the no-progress watchdog. The protected assessor
must attest to a completed delegation result bound to its original budget charge
and current root. One charge receives one durable assessment; repeated ACKs or
fresh assessment IDs cannot count it again. Three assessed results without verified
progress hold the root under the initial policy.

Progress needs a mandatory protected verifier's exact-scope receipt. It must
inspect task-relevant evidence against criteria and prior checkpoints, including
failed experiments that genuinely narrow the problem. A dictionary or changed
artifact hash alone does not establish relevance. Accepted result digests are
retained; renaming the same accepted result cannot reset the progress window.
Genuinely new verified evidence resets only the no-progress counter, never usage,
limits or deadline. A held root remains held until authorized control permits
continuation; exhausted budgets or expired deadlines do not gain exceptions.

Root/work completion requires independently verified acceptance evidence. The
diagnosis guard below prepares bounded proposals and passive report intents;
actual evidence readers, operation monitoring and delivery remain pending.

## Bounded diagnosis and passive reports

`task_diagnosis.py` prepares one durable proposal per independently observed
material state of the same root. Criteria, verified evidence, work custody,
blocker/wait facts and owner intent participate in the fingerprint. Poll IDs,
budget bookkeeping and a recovery hold of the same writer do not mint another
diagnosis. The mandatory protected observer must establish task relevance and
real operation waits; a typed receipt or changed hash alone is not that proof.

Proposal and passive report enrollment share the root's outbox transaction.
Stored proposals reserve finite diagnostic capacity without incrementing executed
turns. Quota or pacing waits do not spend a turn or count as progress. After
mandatory admission, the exact outbox claim atomically charges one root turn and
one diagnosis and records the attempted report. Exact attempt replay grants no
execution; ambiguous submission remains unknown and is never automatically retried.
The real activity/quota/pacing scheduler is unavailable, so no model is dispatched.

Owner desired state and its control epoch are separate from a watchdog/recovery
hold. Pausing an already-held root is recorded and blocks old proposals. Explicit
running intent does not remove its task hold, reset counters or revive an old
control epoch. Before an attempt or applying a confirmed result, the guard
revalidates current material, binding, owner intent and original deadline. A
result scope check is necessary but does not authorize repairs or publication.

A verified wait before expiry starts no model and produces no stall report.
Deadline exhaustion, a missing target or unavailable diagnostic capacity produce
coalesced passive report intents rather than delegation. These intents are not
sent messages. A historical/logical session reference for a missing target grants
no sender authority: PR 6's protected producer must provide current source and
owner/company grants. Actual report routing and current result enforcement remain
integration gates. Unsubmitted stale reservations are retained conservatively;
there is no automatic cancellation or rearming policy.

## Work custody and fencing

The controller enrolls immutable work criteria, dependencies, assignee role and
resource identity. Dependencies must refer to earlier items in the same root;
unverified completion blocks checkout. Current authenticated root/role/execution
bindings, expected revision and ready state are checked in one transaction.
Competing claims yield one owner, and exact-run replay is idempotent without
granting a second launch. Fencing tokens increase globally across resource claims;
an allocator that regresses behind retained tokens is refused before recovery.
The work-custody API is `checkout`; the inherited `claim` API is the outbox's
submission boundary, allowing the diagnosis guard to join attempt accounting.

A SQLite unique index enforces one retained writer lease per resource across
work items. The resource ID must come from a protected inventory mapping actual
worktrees/artifacts and aliases; this module does not resolve filesystem aliases
or prove native resource provenance. Custody is distinct from accountable root
ownership and PR 9's activity slots. A current custody token is not permission to
execute tools, publish or consume model capacity.

Completing work, cancelling a root, revoking a binding, timing out or restarting
does not free its writer lease. Release requires the mandatory protected verifier
to establish all old writers/descendants stopped or quiesced under a held launch
fence, bound to that exact generation and work revision. Typed receipts alone do
not supply that physical guarantee. Current control and revision are rechecked
after verification. A new claim receives a new token; stale, revoked or recovered
claims cannot validate their former fence. Broker/publication/tool adapters must
enforce these checks and all-source fences before target activation.

## Read only planning and activation gates

`scripts/ccrelay_work.py --plan` reads inert repository examples and reports missing
task-limit configuration, real evidence/writer verifiers and admission. It creates
no state and makes no native/network call. Runtime `--run`, `--claim` and `--release`
commands are unavailable. The disabled single-owner example and private broker
directory template have not been installed. Company boundaries and employee
grants still require the design's protected context/authority integration.
Diagnosis activation, material verification and the passive report bridge are
explicitly reported unavailable.

The test runner copies the planner and its example through explicit source
allowlists. It still denies host homes, credentials and network, with no
unsandboxed fallback or increased child timeout. A Python 3.9 annotation import
failure was corrected with postponed annotations, preserving the harness runtime.

## Recovery migration and rollback

Register `ccrelay.work_ownership.v1` as a required protected recovery component.
Capture a consistent SQLite backup/WAL with all root/work records, enrollment
thresholds, clock/fence allocators, budget-charge receipts, completed assessments,
accepted result identities and revision histories. Capture actual evidence,
resource mappings, dirty worktrees and authenticated bindings with the same cohort;
references in this database do not themselves back up those files or identities.
Include owner-control proofs and the existing outbox's diagnosis/report intents,
material observations, capacity reservations, attempts and outcome receipts.

Recovery retains budgets, deadlines, pending ownership and all historical receipts.
Active roots and open roots with writers become held; owned work becomes held but
keeps its resource lease. No native call, automatic retry, deadline extension or
lease expiry occurs. A post-commit lost ACK cannot charge or claim again. Before a
new writer, revalidate current authority and independent all-writer quiescence.
An old confirmed result is historical evidence, not current execution permission.

Unknown component versions, changed policy, regressed fence allocation and an
accepted-result index that differs from immutable history preserve
the database for reviewed migration. This guard adds no SQL schema or new state
database. Historical enrollment proofs without explicit owner intent remain
readable but mean unknown, not permission to execute; a current controller must
establish intent explicitly. Older readers may reject the new proof fields, so
retain state and use a compatible reader rather than rewriting history to permit
a downgrade. Existing relay state is neither imported nor rewritten. Rollback does
not release leases or erase counters. Joined encrypted capture and clean-machine
restoration remain PRs 12–13 gates, not an implemented full-system backup.

## Verification and remaining work

Nineteen ownership cases and two planner cases cover shared budgets, exact charge
replay, root spoofing/revocation, watchdog assessments, repeated evidence,
dependencies, completion without release, resource contention, current fencing,
clock regression, recovery and schema/allocator refusal. Three actual process
deaths cover pre-claim commit, post-claim commit and post-charge commit. A separate
process is refused by the live component's actual lifetime lock. SQLite, files,
locks and process deaths are real; kernel, evidence, clock and writer observations
are explicitly synthetic, not distinct-UID WSL/native acceptance.

Seventeen additional diagnosis cases cover material deduplication, stale result
scope, owner pause while already held, unavailable/revoked targets, verified waits,
deadlines, legacy owner intent and quota/pacing admission races. Four actual
scratch-process deaths surround reservation and attempt commits: a pre-commit
death rolls back the bundle; a post-commit death preserves the same intent and
once-only accounting without granting another execution. Material and admission
receipts in these tests are synthetic, not real task/provider observations.

The diagnosis preparation passed 324 focused root/work, diagnosis, contract,
identity, outbox, artifact, isolation and native/transport checks from a clean
staged-source export in 81 serial sandbox batches. The subsequent
[PR 9 milestone](pr9-model-admission.md) passed all 724 core tests and all four
legacy suites. These results do not establish target/native acceptance.

PR 8 remains in preparation. Real protected root creation/inherited dispatch,
resource inventory and writer fences, criteria/result provenance, diagnostic
material/wait readers and passive delivery, external-action/publication fencing,
company context,
PR 9 admission and joined target restore still need integration. No live bot,
native session, credential, service or scheduler changed.
