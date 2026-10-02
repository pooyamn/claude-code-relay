# Agentic PC 20 PR implementation roadmap

Draft proposal dated 2026-10-01, based on [design v7](agentic-pc-design.md). These 20 PRs move the existing relay toward the design without replacing working native sessions or creating an always-running management hierarchy. This document plans work; it does not authorize live deployments, migrations, external actions or creation of GitHub PRs.

Build testable security and delivery foundations first. Introduce the builder with the session launcher, then prove publication and recovery before its first trusted end-to-end delivery. Keep the approved three-active-session cap, three-handoff watchdog and 10% owner reserve. Integrate evaluated memory/search/workflow components behind those controls, and finish with target-PC acceptance and staged migration.

## Execution status

Pouya requested sequential implementation for PC readiness and authorized committing and pushing verified changes. Repository publication is separate from deployment: no GitHub PRs, live deployments, credential changes or migration have been performed by this implementation run. Local implementation/test evidence is distinct from target-PC acceptance. Unrelated uncommitted edits and runtime/media files are excluded from this series.

PR 1 is locally implemented. PRs 2–5 code/template preparation is implemented, with target-OS acceptance and trusted owner-channel/runtime integration still pending; evidence and limits are recorded below. PR 6's outbound foundation, bounded format/media repair, receipt-bound owner-prompt bridge and current source-grant dispatch mechanism are prepared offline; real protected producer/context wiring and target integration remain pending. PRs 7–20 remain to be implemented, apart from separately requested early preparations noted below. Linux/WSL OS-boundary and integrated-system tests remain pending the appropriate isolated target environment; macOS conformance tests do not satisfy those gates.

## Existing code to extend

Design expansion (2026-10-02): [design v9](agentic-pc-design.md) also requires
human employees from different companies to use Khadang. Preserve the 20-PR
sequence, but extend contracts, protected identity/membership, intake, task
steering, approvals, retrieval/history and publication with company/project/topic
scope and actual human attribution. Pouya remains platform owner; employee
participation does not grant owner approval authority or his 10% reserve. The
existing local PR 1–5 preparation is not a completed multi-company boundary.
Revisit those contracts and demonstrate design acceptance test 14 before
enabling employee grants. Onboarding/delegation and topic trigger choices remain
pending; this requirement does not change live bot allowlists or bindings.

Native goals (requested 2026-10-02) extend PR 6's one-message status UI, PR 7's
pinned native adapters, PR 8's durable root ownership, PR 9's admission/pacing
and PR 19–20's recovery/target acceptance. Preserve the 20-PR sequence. The
legacy Mac code prepares explicit native goal commands, exact-thread intent
journaling and a compact goal footer without editing the user-owned protocol
launcher. It does not establish protected PC controls or admitted native
continuations. [Goal preparation evidence and activation gates](codex-goals.md);
design acceptance test 15 remains pending.

Native Telegram command menus (requested 2026-10-02) extend PR 6's configuration
and one-scheduler path, PR 7's pinned adapter capabilities, PR 9's control
admission and PR 19–20's recovery/target acceptance. Legacy repository code
prepares scoped registration, homogeneous tool menus, a labeled mixed-forum
union and current-topic `/help`; Telegram has no topic command scope. Explicit
commands are normalized, owner-gated and rechecked against the current backend,
never used to bypass company authority or send unsupported controls as model
text. [Prepared command discovery and activation limits](native-telegram-commands.md).
The live Khadang daemon and HamalBot wiring remain unchanged.

- Routing, Telegram formatting, session watchers, Codex observation and MCP messaging already exist in `scripts/`; do not plan their wholesale replacement.
- The legacy `scripts/ccrelayd.py` advances the Telegram offset before handling, and its per-topic queues are in memory. PR 4 prepares a separate protected durable intake for the target; native/media/action adapters are still required before cutover. The legacy live Mac deployment is not automatically converted.
- `scripts/ccrelay_mcp.py:128` derives the caller from cwd. It cannot establish reviewer/CTO authority under the target threat model.
- The legacy `scripts/relay_tg.py` still has direct sends and call-local rate-limit sleeps. PR 6 prepares a durable scheduler/receipt foundation separately; no live sender cutover is established.
- `history/history.py` already collects/searches transcripts; `history/backup.py` packages transcript increments and a search DB snapshot. Extend these into full-system recovery rather than duplicating them.
- `scripts/health_check.py` and `scripts/relay_triage.py` exist but are not a complete admitted support workflow. The current WSL kit assumes a common user/home and needs revision for the role-isolated design.
- The working tree includes unrelated Codex protocol edits. Preserve them and establish their test baseline before overlapping adapter work; do not label them shipped from this planning read.

These are repository observations, not a fresh audit of the live deployment. Prior-art evidence remains in the [survey](research/2026-10-01-prior-art.md), [GStack/GBrain evaluation](research/2026-10-01-gstack-gbrain-evaluation.md) and [AX/Paperclip evaluation](research/2026-10-01-ax-paperclip-evaluation.md).

## Rules for every PR

- Keep entry scripts thin and extract only the modules needed for that PR; a proposed `scripts/relay_core/` package can hold tested shared contracts. Avoid a preliminary framework rewrite.
- Include the mechanism, focused deterministic tests, a migration/dry-run path for affected state, and recovery/rollback instructions. Preserve incompatible old state for inspection; do not silently clear it.
- Start with fake providers, synthetic secrets, disposable repos/worktrees and a test bot when authorized. Candidate tests cannot access production credentials. Do not run concurrent builds into the same output directory.
- Pouya's test-bot direction: use Khadang for Telegram integration tests. Leave HamalBot's existing wiring untouched until he explicitly authorizes a change, including credentials, bindings, polling ownership, hooks and services. Verify the configured bot identity before live tests; never infer test authorization from a token/config filename. Inspect the existing Khadang test poller before starting any polling so a second poller cannot compete for its token. This testing permission does not authorize a production-bot cutover.
- Existing Mac sessions and the remote-control daemon remain untouched. No installer silently enables units, changes schedules, copies a shared credential home, or restarts the daemon.
- Schema changes register their backup/restore requirements from PR 1. Every component enabled later must join the recovery package and repeat the relevant restore tests before use.
- Deploy only through the protected policy: routine changes need review/tests/Jev clearance; protected changes and security flags need Pouya's exact-version decision. If any required gate cannot run, deployment waits; a merge or a passing unit test alone is not permission to deploy.
- Until admission, publication and recovery are proven for an enabled capability, keep it in an isolated test environment. There is no autonomous delegation during the foundational PRs.

## PR 1 State contracts and isolated regression harness

Depends on: none.

Define versioned root-task, role/session, execution, message, external-action, approval and component-snapshot contracts. Distinguish requested/observed state and `submitted`/confirmed/unknown outcomes. Add fault-injection fixtures for process death, ambiguous acknowledgments, duplicated events and concurrent writers. Reuse the current relay tests and capture a baseline without live services. Record intended changes as contracts, not claims about the running system.

Done when: synthetic fixtures exercise the contracts and crash points; every state type has an upgrade/recovery rule; tests run without production network, home directories or credentials.

Local implementation (2026-10-01): `scripts/relay_core/contracts.py` supplies eight strict v1 record kinds, immutable canonical encoding, exact intent digests, revision-checked transitions, per-kind recovery rules and fail-closed legacy/future schema handling. These validate records, not authenticated authority; broker, durable runtime storage and production adapters are later work. The test-only SQLite ledger/provider fixtures demonstrate crash boundaries, duplicate-intent rejection, uncertain-outcome reconciliation and competing-writer fencing. They are explicitly not the live persistence implementation.

Run `/usr/bin/python3 scripts/tests/run_isolated.py` on this Mac. The runner copies an allowlist of source into scratch storage, constructs a clean environment with synthetic configuration, and verifies OS filesystem/socket restrictions before tests. Initial sandbox startup failures were traced to missing root-directory/entropy read permissions; only those required reads were added. There is no unsandboxed fallback. Linux uses a bubblewrap command contract but its actual execution still needs target validation.

Baseline investigation found a hard-coded live path in `relay-alt-launch` and outdated table assertions. The launcher now locates sibling configuration portably. Regression coverage preserves OpenClaw's existing scrolling-table behavior and direct-bot native tables; the new native-table case reproduced and fixed a list-versus-string `TypeError` in `render_reply`. Only repository files changed, not live scripts. All four legacy suites and 36 new contract/fault/isolation tests pass; this is not an integration guarantee. Unknown schemas retain original bytes for explicit reviewed migration; no existing runtime files are auto-converted. Rollback of this preparation requires restoring only its reviewed code artifact, with no live state migration to undo.

## PR 2 Protected identities and authenticated action broker

Depends on: PR 1.

Add target-WSL provisioning templates for `relay`, isolated worker roles, reviewer/CTO/support and protected component identities. Protect homes, credentials, runtime sockets, policy and worktrees. Introduce a broker authenticating peer UID and trusted session bindings; the stdio MCP client submits scoped requests rather than reading shared privileged state or choosing its identity through cwd. Unregistered sessions and empty allowlists fail closed. Revise the unsafe common-home assumptions in the migration kit without running it.

Done when: different role UIDs cannot read or attach to each other's state, spoof a privileged role, rewrite mappings or submit a privileged request by changing directory. A reviewed bootstrap can register only its permitted role/session.

Local preparation (2026-10-01): `relay_core/identity.py`, `bindings.py` and `broker_wire.py` plus thin Linux broker/stdio-client entry scripts implement explicit policy ceilings, kernel peer/per-message credential requirements, root-controlled cgroup/process-generation bindings, private immutable SQLite registration/revocation and fail-closed schemas. Only authenticated introspection is enabled; authorization of a role is not permission to execute an external operation without the later gates. The WSL kit supplies isolated identity/home/component templates and a read-only collision/group planner. Legacy shared-home setup/bulk-copy paths now exit before performing any change. No live service, native login or configuration was altered.

Verification, component snapshot requirements, migration and rollback are in [the PR 2 evidence/runbook](pr2-identity-broker.md). All four legacy suites and 64 core tests pass. Mac isolated tests exercise synthetic kernel/permission observations, protocol/descriptor/slow-fragment rejection and actual SQLite persistence; they are not distinct-UID Linux/WSL acceptance. The target OS/security and native-runtime topology gates remain pending and no PR 2 capability is trusted for live use yet.

## PR 3 Owner authorization and protected deployment

Depends on: PRs 1 and 2.

Persist owner-authenticated, single-use approvals bound to action parameters and candidate digests. Build the protected deployer, deterministic protected-change classification, masked Jev screening contract and audit trail. Install immutable artifacts; test candidates without live router secrets. Distinguish triage rule fallback from deployment screening: unavailable/uncertain security clearance never becomes automatic authorization. Use owner-approved bootstrap artifacts until the reviewer/publication path is available in PR 11.

Done when: forged approval text, replay, altered artifacts and modified screening/deployer policy cannot authorize execution. Protected changes always wait for exact-version owner approval; routine deployment remains disabled until its later gates exist.

Local preparation: `owner_gate.py` and a thin Linux ingress persist owner/channel/prompt-bound decisions, revocation, single-use approval consumption and durable attempts in private SQLite. `artifacts.py` verifies complete sealed content-addressed trees, classifies changes under installed protected policy and supplies owner-approved bootstrap pointer activation/reconciliation without executing candidates or restarting services. `screening.py` supplies the pure masked Jev report contract; no live provider or automated clearance is connected. Credentialed code is protected regardless of filename; the later routine lane isolates presentation work from bot credentials rather than requiring owner review of every relay change.

All four legacy suites and 101 core tests pass, including actual scratch-process deaths around attempt/pointer/receipt boundaries. [The PR 3 evidence and recovery runbook](pr3-owner-deployment.md) records remaining WSL, trusted Khadang intake/receipt/UI and screener-provenance gates. Examples and service templates remain disabled/inert. No live bot, credential, service or state migration changed. Root bootstrap enrollment is not an owner decision; routine activation remains unavailable until PR 11's independent gates and PR 15's runtime proof.

## PR 4 Durable inbound intake and poller ownership

Depends on: PRs 1 and 2.

Persist and fsync Telegram updates before advancing offsets. Store deduplication IDs, routing decisions, media/callback references and dispatch state; reconcile disk/DB commits and recover interrupted intake. Add singleton poller ownership, sustained-409 fail-fast behavior and event-loop liveness detection. Stop/pause and owner steering enter a durable high-priority control path instead of waiting behind a topic's model-work queue.

Done when: crash at each intake boundary loses no durably accepted message and cannot duplicate logical dispatch. Only one poller owns a token, and empty/invalid owner authorization admits nobody.

Local preparation (2026-10-02): `intake.py`, `polling.py` and a thin target entry persist original response bytes, deduplicated updates, frozen routes/media/callback references, per-batch acknowledgment cursors and atomic prioritized logical dispatches. Restart observes pending remote updates before any saved high offset; random lower IDs do not reset history. Protected host-wide bot locks, pinned `getMe`/webhook checks, persistent conflict/cooldown state and an independent actual-cycle watchdog provide the local ownership/liveness mechanism. They never execute a model, download media, send a reply, steal a webhook or change HamalBot wiring. The repository legacy empty-owner allowlist check also now fails closed; its live copy was not updated.

All four legacy suites and 142 core tests pass, including real scratch-process deaths, concurrent materializers and cross-process locks. [The PR 4 evidence and recovery runbook](pr4-durable-intake.md) distinguishes logical readiness from runtime delivery and local locks from cross-machine ownership. Examples/services stay disabled/inert and no live bot was polled. Real WSL isolation/storage and authorized exclusive Khadang integration remain pending; PRs 5–6 must connect guarded effects, receipts and owner UI before any complete phone-control cutover.

## PR 5 Durable action outbox and guarded runtime delivery

Depends on: PRs 1 through 4.

Give messages and external actions stable intent IDs, attempt IDs and parameter fingerprints. Persist submit/receipt/unknown states before and after adapter calls; reconcile uncertain outcomes using evidence instead of blind retry. Route MCP delivery through the broker and retain the existing hop guard. For Pouya's messages to an active session, prefer steering with the exact expected turn ID, honoring his steering preference; an inactive session has no turn to steer. If an active-turn steer is unsupported or races completion, retain the message and report the state rather than silently changing it into queued follow-up. A new turn still needs admission.

Done when: duplicated sends, process crashes and missing acknowledgments do not repeat a confirmed action; unresolved non-idempotent actions remain unknown. Stale-turn steering cannot land in a different turn. Persistence may buffer intake, but is not presented as a queued model interaction.

Local preparation (2026-10-02): `relay_core/outbox.py`, `messaging.py` and `runtime_delivery.py` implement a private durable intent/attempt/plan/evidence ledger, kernel-authenticated held MCP enrollment, participant-scoped paginated logs, confirmed-parent hop checks and a no-fallback exact-turn Codex steering adapter. Actual process deaths at eight storage/submission/receipt boundaries and a non-idempotent fake provider test recovery without uncertain resubmission. The protected broker can store/inspect messages but does not invoke native or external adapters. [PR 5 evidence and recovery](pr5-durable-delivery.md) records remaining Telegram owner-ingress, Claude/pinned native transport, inherited-root/admission, reconciliation and target-OS gates; input acceptance is not completed work. Legacy live wiring and unrelated protocol edits remain unchanged.

## PR 6 One Telegram scheduler and reply receipts

Depends on: PRs 4 and 5.

Move every send/edit/media/bus/status/approval path behind a durable outbound scheduler. Prioritize approvals/alerts, final replies and then passive traffic; persist per-operation cooldowns and coalesce expendable status without dropping content. Watchers advance reply cursors only after all required chunks have confirmed receipts, tied to their exact submission/turn. Preserve rich tables, attachments, voice and mirrored app turns.

Done when: simulated floods, partial chunk delivery, rate limits and restarts preserve content and reply offsets. Ambiguous Telegram acknowledgments remain visible; no claim of universal exactly-once delivery is made where the remote service supplies no such primitive.

Local foundation: `telegram_scheduler.py`, `telegram_outbound.py` and `telegram_producers.py` prepare one private durable queue, atomic ordered reply bundles, priority/pacing, bounded negative-evidence flood replacements, sealed original response/attempt bindings and receipt-bound stream offsets. Rich tables, classic code, immutable uploads, voice, media groups and full captions use the common protected producer gateway in offline tests. `telegram_repair.py` adds one pre-enrolled, exactly authorized format/media alternative per rejected operation, retaining source/negative evidence, confirmed siblings and the shared retry budget. Fourteen original and fourteen additional repair process-death boundaries test persistence against a non-idempotent fake provider. Queue/bundle/policy v2 rejects and preserves older state for explicit migration. `ccrelay_outbound.py --plan` and disabled examples perform no live I/O. [PR 6 evidence and remaining gates](pr6-telegram-outbound.md) records pinned rejection characterization and protected runtime authorization, authenticated producer and owner-prompt integration, exclusive Khadang/WSL proof, complete component backup and live cutover work. The prepared scheduler has not replaced any legacy sender or HamalBot wiring; PR 6 remains in preparation.

Owner-prompt preparation: `owner_prompts.py` joins deterministic exact-action text, ordered approval bundles and sealed complete delivery evidence to the PR 3 gate's protected ingress. Only the actual final button-bearing message may bind; enrollment or delivery never makes an owner decision. A kernel-ingress-only `read_prompt` operation preserves exact nonces and existing receipts. Seven actual scratch-process deaths exercise separate send/gate commits, including a committed bind with lost ACK, without resending or granting approval. Real source/grant enforcement, gate/client/transport characterization and live WSL/Khadang acceptance remain pending. Company employees do not inherit platform-owner approval authority; v8 onboarding/context isolation must precede grants.

Additional PR 6 preparation: `telegram_authority.py` retains exact-manifest grants
and issuance/revocation/explicit renewal history in a private component. Mandatory
typed current permission checks precede claim and the guarded adapter's sole
request, after upload assembly. Denied unattempted content stays held without
discarding confirmed siblings or blocking unrelated work; claimed uncertainty
never replays. Four actual process-death cases preserve grants/attempts/cursors.
The disabled config is v2 with a separate source directory. Real kernel-native,
root/company/context and split-UID bridges, exclusive Khadang/WSL acceptance and
full-component recovery remain pending; this does not complete PR 6.

## PR 7 Native session registry and role launcher

Depends on: PRs 2, 5 and 6.

Implement the desired/observed registry with exact Claude/Codex IDs, pinned adapter capabilities and independently verified resume. Add worktree creation/reuse, generated role/repo instructions, reviewed skill references, strict launch manifests and readiness conditions. Enforce WSL CPU/RAM/process profiles including detached children. Make builder/reviewer/support available now, with CEO/CTO profiles on demand; run a manually requested builder fixture task early. Choose a proven role-isolated runtime/subscription topology and preserve native app access; do not assume a shared socket or copied login home is safe. Normalize evidenced temporary-capacity, quota, authentication, terminal-turn and unknown-submission outcomes from pinned adapters; establish native retry ownership/counts and provider wait semantics rather than matching error prose. Keep automated turns disabled pending PR 9.

Done when: exact-ID resume and app visibility work for both tools under isolated identities; failed setup, unsupported controls and failed stop acknowledgment cannot masquerade as readiness or successful pause. No fresh-thread or default-profile fallback hides failure. Document the pre-turn control surface PR 9 will enforce.

## PR 8 Root tasks and atomic work ownership

Depends on: PRs 1, 2 and 7.

Add root-task ownership, acceptance criteria, finite inherited budgets/deadlines, progress/evidence records and dependency gates. Atomically check out work items by expected state, assignee and execution ID. Separate accountable ownership from execution leases and activity slots; add artifact leases and broker fencing. Prove old writers/descendants are stopped or quiesced before transferring a worktree. Define bounded diagnostic allowance inside the root budget. Agents cannot mint a replacement root to reset limits.

Done when: two competing checkouts yield one owner; same-run replay is idempotent; terminal DB rows cannot release a surviving writer. Children, tool switches and new message chains retain root counters and pending actions. Numerical policies remain explicit owner choices, not invented defaults.

## PR 9 Global admission and subscription pacing

Depends on: PRs 5, 7 and 8.

Enforce admission before model execution for native-app, Telegram, MCP, recovery, curation and support sources. Limit active turns/tools to three; waiting delegators release activity slots without leaving writers or losing ownership. Add one durable provider/account scheduler, bounded privileged quota probes, timestamped/source-labeled windows, in-flight reservations and a configurable minimum gap. Reserve 10% of every applicable allowance for Pouya, with explicit authorization required for autonomous use of it. Account for outside activity conservatively; never enable paid fallback.

Add automatic temporary-capacity retries with provider-directed minimum waits, increasing backoff and bounded jitter, finite retries/elapsed time, shared account/model cooldowns and passive wait/recovery/exhaustion reporting. Persist exact failure evidence, retry counters, original deadlines and stable replacement proposals before acting. Re-admit every actual attempt under the same root/cap/quota/reserve gates. Unknown delivery is reconciled, not replayed; a terminal partly executed turn resumes only from a verified checkpoint with external outcomes reconciled. Native retries cannot multiply an outer loop, and a steering retry cannot become a new turn. Cancellation and owner controls stay responsive. Retry policy values remain explicit owner choices.

Done when: a fourth turn cannot start through any source; one account's roles cannot reserve the same capacity independently. Missing/stale telemetry is labeled and bounded; known exhaustion holds automation. Owner steering/stop remain responsive, and pace waits neither consume execution budget nor pretend to be progress. Native-app pre-turn enforcement must be demonstrated, not inferred from observer logs.

Capacity acceptance: overload retries preserve the task and resume safely after the verified wait; restart cannot reset retry limits or duplicate a replacement intent. Quota/authentication/unknown outcomes, canceled or stale-turn work and exhausted deadlines do not auto-retry. A provider wait longer than the local cap is honored or held, not shortened. Prove no replay of completed tools/external actions and no independent per-role retry storm.

Local early preparation (2026-10-02, requested separately by Pouya): `relay_core/capacity_retry.py` supplies a pure versioned retry-policy state machine with typed normalized evidence, bounded backoff/jitter, deadline checks, deduplication, cancellation, native-retry deferral and stable one-time proposals. Eighteen isolated tests verify policy and serialized-state behavior. It does not persist state or call a model by itself; PR 9 remains unimplemented until the durable shared scheduler, atomic proposal/outbox linkage and admission gates are integrated. [Capacity retry scope and evidence](model-capacity-retries.md) records these limits.

## PR 10 Verified tool switch and interrupted recovery

Depends on: PRs 5, 7, 8 and 9.

Implement a durable switch state machine with dirty/untracked snapshots, task context, running operations, provider/tool/permission fingerprints, publications, approvals and pending-action evidence. Quiesce old writers and verify context loaded in the destination tool on the same worktree. Independently validate session/active-turn identity before same-tool delta resume. Report incomplete handoffs as relay bugs through the existing issue path; admitted support can repair and revalidate, or the switch stays pending with owner notification.

Done when: Claude → Codex → Claude preserves unfinished work and action identities. Crashes before/after checkpoints and changed contracts recover without a second writer, silent fresh conversation or action replay. Support repair never grants extra privilege or quota.

## PR 11 Publication and independent merge gates

Depends on: PRs 2, 3, 5, 7, 8 and 9.

Add brokered `publish`, fresh publication branches, one open publication per session, the scoped GitHub App interface and reviewer-only SHA-bound verdicts. Require authenticated CTO merge requests and serialize merges by repository. Resolve the proposed independent build/test gate against the current merge target; model review is not its substitute. Preserve later dirty/committed work during post-merge rebase, recording conflicts rather than discarding it. Low-risk review exceptions require an explicit protected policy; default to independent review.

Done when: builder cannot self-approve, push directly or merge; changing candidate/base invalidates stale gates. Two merges serialize and current-target tests run in isolated build dirs. Fake GitHub fixtures prove the mechanism before any authorized live integration.

## PR 12 Full system daily encrypted backups

Depends on: PRs 1, 2, 3, 5, 7, 8 and 9.

Extend the existing packager to cover all system records, role state, instructions/skills, dirty/untracked work, ledgers, histories, component stores, configuration and pinned deployment versions. Use consistent component snapshots, path/exclusion/digest manifests, verified off-machine uploads and capture-time freshness alerts at the approved 24-hour bound. Preserve incremental bases and restore-critical records during retention; pruning must respect pinned/resumable sessions. Require separate owner-controlled key custody and restricted credential recovery or owner re-login.

Done when: synthetic packages decrypt and verify; interrupted capture/upload cannot advance success cursors or trigger unsafe pruning. A package reconstructs more than conversations, and an incomplete/missing component is not declared a complete backup. Choose storage credentials/key custody before live scheduling; quiet backups run without model calls.

## PR 13 Clean machine restoration and action reconciliation

Depends on: PRs 5, 7, 8, 9, 11 and 12.

Build a restore command/runbook that reconstructs identities, permissions, compatible binaries/configuration, repos/worktrees, exact session mappings and operational state on a clean WSL machine. Restore initially paused; revalidate permissions and approvals, reconcile external outcomes and rebuild derived indexes before admitted resume. Preserve newer externally completed actions even when absent from the snapshot. Add component restore hooks for later memory/search services.

Done when: a drill using separately recovered key material works without the source PC and makes no real external calls. Record restored/missing data, backup age and recovery time; prove an unknown action is not reissued merely because a stale snapshot lacks its receipt.

## PR 14 Evidence progress watchdog and passive incidents

Depends on: PRs 5, 7, 8, 9 and 10.

Extend existing deterministic health checks and issue intake with verified milestones, delegation cycles, budgets/deadlines and explicit operation/approval/quota waits. Keep the initial trigger of three completed handoffs without verified progress. Persist material diagnosis fingerprints including evidence revisions; suppress unchanged model reviews and revalidate before applying results. Assign one bounded same-root diagnosis, not recursive management work. Jev triage sees masked evidence and has its existing rules fallback; security screening still follows PR 3.

Done when: cross-chain loops trip once and fresh status/artifact churn cannot reset progress. A genuine failed experiment can count when it narrows the problem; builds and legitimate waits are not false loops. Stale diagnoses fail safely, quiet checks start no agent, and Pouya gets silent/coalesced findings and resolutions.

## PR 15 Reviewed support rollout and first builder delivery

Depends on: PRs 3, 6 and 9 through 14.

Connect support fixes to independent publication, Jev/deployment gates, immutable canary artifacts, round-trip checks and rollback that preserves state. Add independent router liveness observation without a second Telegram poller or bypass sender. Complete the first scoped builder → other-tool reviewer → on-demand CTO publication with evidence and recovery coverage. Add the passive status board, owner pause/resume/stop controls and up-to-three weekly CTO improvement proposals under the same admission/budget rules.

Done when: a routine safe support change can deploy without owner review on every change, while protected changes/security flags cannot. Failed canaries restore the compatible artifact/state without restarting the live Codex daemon. The first builder task is completed with measured coordination cost, not only handoffs. Trust only capabilities whose target-runtime gates have passed.

## PR 16 Evidence based memory and nightly reconciliation

Depends on: PRs 2, 3, 7, 8, 9, 12 and 14.

Implement stable fact IDs, authenticated proposal provenance, scope/evidence/validity/status fields and explicitly linked supersession. Serialize canonical curation by scope, preserve corrections/disputes and generate indexes; company/privileged instruction changes retain owner authority. Reconcile affected facts at completion/new evidence and add nightly deterministic scans with model work only for changed/flagged records. Deliver Pouya a silent digest including automatically resolved inconsistencies.

Done when: newer unsupported facts cannot replace verified knowledge; cross-role or false owner attribution grants no authority. Competing proposals preserve history, repeated conflicts coalesce, and a quiet night costs no model turn. Register memory/audit state with the tested backup/restore path.

## PR 17 Protected GBrain projection and retrieval

Depends on: PRs 2, 3, 5, 9, 12, 13 and 16.

Integrate the evaluated pinned GBrain revision behind a protected local service and authenticated broker. Canonical files remain authoritative; project stable IDs/revisions through a durable replay outbox and enforce source/operation grants. Workers can query scoped facts and submit proposals, not directly administer or supersede canonical memory. Start keyless, retain withdrawals/disputes and reject hidden cloud/model jobs. Include consistent full-store snapshots and controlled schema migrations.

Done when: canonical update → projection → scoped retrieval → correction/withdrawal → restart → restore works on WSL. Worker access cannot widen grants/read backend state; similarity cannot establish a correction; stale replay cannot resurrect a withdrawn fact. Repeat component restore/security tests before enabling retrieval.

## PR 18 Scoped local knowledge and history search

Depends on: PRs 2, 9, 12, 13, 16 and 17.

Wire QMD Markdown search, GBrain fact retrieval and the existing history database through one scope-aware query broker. Keep separate corpus responsibilities; add chunking/local embeddings, bounded context packing, source/revision/dispute labels, relevance evaluation including Farsi queries and measured hybrid ranking. Test any local reranker before enabling it. Protect collector/index stores and keep raw secrets out of searchable/model-visible results. Retain verbatim encrypted histories independently of search truncation.

Done when: authorized queries return useful cited evidence without cross-role leakage or treating retrieved text as instructions. Collector replay does not duplicate records, indexes rebuild after restore, and local-model work introduces no paid/API fallback. Compare retrieval quality before/after ranking changes rather than assuming more components help.

## PR 19 Adapted GStack methods for existing roles

Depends on: PRs 7, 9, 11, 14 and 16 through 18.

Vendor/adapt reviewed pinned engineering-plan review, risk review, investigation and QA methods as existing CTO/reviewer/support/builder skills. Keep review read-only and findings bound to the exact candidate; fixes go back to the builder and invalidate old approval. Additional opinions are admitted native sessions, not direct CLI subprocesses. Use isolated QA profiles/fixtures, controlled publication and no automatic telemetry, cookie extraction or upgrades.

Done when: one engineering review, one independent code review, one investigation and one QA workflow produce inspectable useful evidence within cap/reserve/root limits. Workflow assets cannot push, approve, install privileged code or reach the owner's logged-in browser. Measure overhead before expanding methods.

## PR 20 Target PC acceptance and staged migration

Depends on: PRs 1 through 19.

Finish reviewed WSL boot/unit templates with validated role isolation and dry-run-first configuration merging. Run all [design acceptance tests](agentic-pc-design.md#13a-acceptance-tests-and-metrics), including unfinished switching, unknown delivery, impersonation, clean restore, contradiction handling, loops, all-source admission, shared quota pacing, component isolation and launch/resource failures. Add weekly metrics for completed work, owner interventions, coordination quota, verified milestones, recovery and quota deferrals. Perform a canary then one-role-at-a-time migration with owner-authorized cutover, one poller per token and recorded rollback checkpoints.

Done when: target-runtime evidence is attached for every enabled capability, compatible restore/rollback is demonstrated and the builder/reviewer/support path works from Telegram and native apps. No step kills/restarts the existing Mac daemon or touches the bench/VPN. Do not run the old common-user migration instructions unchanged. Code readiness and approval of an actual cutover are distinct.

## Milestones and open decisions

PR 7 gives an isolated builder session doing a manually requested fixture task, with reviewer/support identities available. PR 15 gives the first trusted end-to-end delivery after core security, admission, publication and recovery demonstrations. PRs 16–19 add memory correctness, retrieval and selected workflow methods. PR 20 proves the integrated target system and supplies the controlled migration procedure. These are acceptance gates, not promised calendar dates.

Resolve the following when their PR reaches implementation; no unanswered choice is silently approved by this roadmap:

- Before PR 2 target validation: development host/VM versus target PC, and access to a suitable disposable WSL environment.
- Before PR 7 approval: subscription authentication plus native-app/daemon topology that actually respects role isolation and supports pre-turn mediation. A failed feasibility experiment reports the mechanism and requires a new compliant approach, not loss of app access or an observer-only substitute.
- Before PRs 8–9 autonomous use: finite numerical budgets/checkpoint deadlines, diagnostic allocation, initial pacing gap, capacity retry/backoff/elapsed bounds and verified account-specific quota/error adapters. The already-approved three-session cap, three-handoff trigger and 10% reserve stay unchanged.
- Before PR 11 publication: independent current-merge-target test suite and any explicit low-risk review policy. This roadmap proposes an independent automated gate; it does not erase the design's pending decision.
- Before PRs 12–13 scheduling/trust: off-machine destination access, separate key custody and owner login/bootstrap recovery path.
- Paperclip production adoption remains optional and pending. Its checkout/watchdog/native-runtime patterns are already reflected above; AX is not a deployment dependency. Any optional Paperclip prototype uses synthetic state, authenticated owner access, disabled telemetry and a relay adapter. Adopt only after continuity/isolation/admission/restore proof and owner decision, without a second operational authority. A substantial production integration needs an explicitly revised PR scope rather than being hidden inside this series.

Every later PR extends the tested component manifests and reruns affected recovery/security checks. Approval, quota and backup failures cannot be waived just to finish the twentieth PR.
