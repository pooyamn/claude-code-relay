# PR 7 Native session and launch preparation

The private native-session registry is prepared and tested offline. It preserves
exact Claude/Codex conversation mappings, separates desired state from observed
state and rejects stale observations after an owner control request or changed
binding. It does not launch or resume sessions, prove native readiness, admit
model turns or complete PR 7. It supplies a dependency for PR 6's still-pending
protected producer/source wiring; PR 6 acceptance remains unfinished.

## Prepared mapping and observation mechanism

`relay_core/native_sessions.py` extends the protected delivery ledger's lifetime
lock, SQLite transactions, fsync and schema validation. Native mappings and their
revision history live in a separate private database, not the Telegram queue or
worker home. Broker policy and existing launcher bindings supply role, root and
execution identity; changing cwd or supplying a UID/role header cannot enroll a
session. The controller peer must originate from authenticated kernel ingress.
No worker RPC has been added for this component.

Enrollment fixes the local session ID, role/root/execution binding, provider,
exact native conversation ID, worktree, expected runtime/tool/permission hashes
and required capabilities. A role may have multiple sessions; one provider's
conversation cannot silently acquire two local mappings. Repeating the original
enrollment returns current state rather than resetting later observations or
owner requests. Replacing a native ID, root, worktree or contract requires the
later reviewed transfer/migration protocol, not ordinary re-enrollment.

`desired()` persists a request only. It invalidates the old observation and any
pending probe, but does not send a native control or claim that pause/stop
succeeded. A fresh running observation while pause is requested remains
observed-running, desired-paused and not ready. Unsupported controls or a failed
stop acknowledgment cannot be substituted with an idle thread.

`refresh()` first checks the current controller/binding and commits an unknown,
not-ready record with a unique probe. The mandatory trusted observer runs outside
the SQLite transaction, so an owner pause or a newer probe can proceed while a
transport read is outstanding. Its result must match the exact native identity,
worktree, binding, pinned contracts and required capabilities. A final revision,
probe and current-binding check prevents a late callback from overriding newer
state or revocation. Observer errors retain the native ID and last known turn for
reconciliation without preserving readiness.

`cached()` returns historical claims, not current authority. `NativeObservation`
is a typed trusted-adapter boundary, not an authentication primitive: constructing
or decoding that object does not prove its facts. The installed observer must
independently verify the real transport, runtime process generation/UID, exact
conversation, worktree, permissions and lifecycle evidence. Those native/OS
bridges are not implemented by this registry, and its records alone must never
grant source delivery, publication, owner approval or execution admission.

## Codex contract boundary

Official OpenAI documentation distinguishes `thread.id` from the live session-tree
root `thread.sessionId`; the recorded conversation ID is the former. `thread/read`
reads without resuming or subscribing and exposes runtime status. `thread/resume`
reopens the recorded thread; its acknowledgment alone is not our independent
readiness or app-visibility proof. The later pinned adapter must observe the exact
ID and current contracts after resume, and must not fall back to start/fork when
resume fails. [Codex App Server](https://learn.chatgpt.com/docs/app-server).

The generic registry also supports Claude mappings, but does not infer Claude's
transport or lifecycle semantics from Codex. Native goal capability is Codex-only.
Neither these normalized fixtures nor the separate legacy Mac goal/menu rollout
establish isolated native transports, provider entitlement, app visibility or
pre-turn enforcement on the PC.

## Read only target preparation

Run `/usr/bin/python3 scripts/ccrelay_native.py --plan` to inspect inert examples.
It reads no credentials, creates no state and makes no native/network calls.
`--run`, `--resume` and `--goal` are not runtime entry points. The config requires
both activation and automated turns to remain disabled; it cannot silently enable
company access or default unsafe paths into a usable configuration.

`native-config.json.example` identifies broker-owned private state under
`/var/lib/ccrelay-broker/native`; the repository tmpfiles template adds that
directory beneath the existing private broker directory. Neither template has
been installed. Builder/reviewer/support/CEO/CTO entries are role profiles, not
active sessions or automatic management work. The builder still needs the later
reviewed launcher and a manually requested fixture task under admission.

## Recovery migration and rollback

Restart or database-snapshot restore clears cached readiness and pending probes,
retaining exact native IDs, last known turns, desired state, immutable enrollment,
expected contracts and revision history. No native call is made during recovery.
Do not reset mappings or create a fresh conversation to make resume pass.
Unknown component/record schemas and changed broker policies preserve original
bytes and require reviewed migration before recovery can mutate them.

The database snapshot contains the local mapping/history tables, not native
transcripts, launch artifacts, worktrees, broker bindings or credentials. PR 12
must capture those components consistently with policy/version hashes; PR 13 must
restore initially paused and reconcile current identities and external outcomes.
A restored binding or capability tuple is not current permission. Keep company
membership/context and source grants in their protected components, not a cached
native ready flag.

No existing registry has been imported or live state migrated. Rollback of this
preparation concerns the repository artifact only. After activation, retain
compatible component state and quiesce real writers before artifact changes;
neither revocation nor a terminal record proves that a detached writer stopped.

## Prepared launch bundles

`native_launch.py` creates a content-addressed candidate through the existing
private `ArtifactStore`. It does not grant approval, launch, resume, create a Git
worktree, write instructions into one, link skills, install a service or admit a
turn. No worker RPC or new live entry point is exposed. The specification requires
automation disabled and platform-owner scope; employee/company grants remain
subject to the existing acceptance test 14 gate.

The strict specification records requested role/session/root/execution IDs and
checks role UID and policy digest against the supplied installed broker policy.
It fixes provider and exact native conversation ID, or an explicit null for a
requested new session; compilation never replaces an existing ID with null. It
also pins baseline commit, role-scoped branch, create/reuse choice, owned paths,
runtime/version/adapter and capability hashes, native/MCP configuration artifacts
and explicit CPU/RAM/process settings with a referenced measurement artifact.
Identity fields and paths are requests, not authenticated kernel observations.

Worktree and common Git-directory paths must be under the same role's private
home. Worktrees from different UIDs cannot safely share writable Git metadata;
the eventual launcher must independently verify ownership, topology and stopped
or quiescent writers. It must perform Git operations under the intended worker
identity, not execute worker-controlled hooks/configuration as a privileged
broker. This compiler performs no Git operations or workspace checkout/reset.
Git documents that linked worktrees share repository data except per-worktree
files. Our role-private common-directory requirement is a security inference
from that sharing, not a claim that Git authenticates roles. [Git worktrees](https://git-scm.com/docs/git-worktree).

Role and repository instruction bytes are read from verified sealed artifacts,
retained separately and combined in that order. Codex's candidate file is
`AGENTS.override.md`; Claude's is `CLAUDE.md`, whose native loading still requires
its own adapter proof. Missing, empty, invalid UTF-8 or oversized instructions
fail rather than being silently truncated. Official OpenAI documentation says
Codex discovers instructions at run startup and prefers an override at each
scope, subject to a configured byte limit. Generated bytes alone cannot prove
they were loaded. [Codex instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Every selected skill's entire sealed artifact is retained, including license
notices and ancillary assets outside its skill directory. Scripts keep their
executable flags but are never executed by preparation. Discovery targets are
recorded for the later launcher, not installed symlinks. Native/MCP settings and
resource measurement bytes are pinned opaque inputs; this component does not
validate their native semantics, credential entitlement or measurement quality.
Production inputs must receive the existing protected review/security/owner
gates before use; an artifact digest is not evidence of that approval.

The resource fragment contains the explicit CPUQuota, MemoryMax, TasksMax,
KillMode and Delegate settings, without an ExecStart or activation section.
CPU quota is relative to one CPU; TasksMax counts tasks, including threads. Target
acceptance must inspect effective limits and descendant cgroup membership, not
assume rendered settings were enforced. [Upstream systemd resource controls](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.resource-control.xml).
Fixture numbers are invented test inputs, not recommended PC limits or target
measurements. The final bundle always reports prepared, ready false, admitted
false and target_verified false. Inspection reconstructs it from exact pinned
inputs and rejects altered content, executable flags, extra files, future schemas
or readiness claims. The complete package has the existing artifact byte/file
bounds; required assets are not dropped to make it fit.

Replay of the same specification/inputs returns the same verified artifact.
Crashes before first publication leave no complete new candidate; crashes after publication
leave a sealed candidate with no launch or admission. Source artifacts and the
bundle must be captured together for recovery: reconstruction requires the exact
dependencies. Unknown schemas and incompatible policies remain intact for
reviewed migration. No live launch package has been imported or activated, so
rollback at this stage concerns repository preparation only.

## Verification and remaining gates

Offline tests use invented normalized runtime/kernel observations, with actual
SQLite, private files, lifetime locks and nine scratch-process deaths around
enrollment, probe, observation and desired-state commits. They cover wrong IDs,
worktrees/contracts/capabilities, stale revisions, revocation during observation,
late callbacks after pause, duplicate native mappings, restore and schema refusal.
No paid/native agent, live bot, credential, service or native daemon is a fixture.
Run `/usr/bin/python3 scripts/tests/run_isolated.py --suite all` for copied-source
tests under the OS sandbox; this is not distinct-UID/native integration proof.

The registry-only staged candidate passed 447 core checks and all four legacy suites.
The registry/planner account for 22 focused checks, including the nine process
deaths. The strict staged secret scan passed without repository allowlists.
These results validate the offline preparation, not the remaining native gates.

The launch-bundle preparation passes 20 focused checks, including two actual
scratch-process deaths before/after artifact publication. These use invented
instructions, permissions, skills and resource numbers, with real sealed files
and artifact verification. They do not exercise Git worktree creation, native
instruction loading, service activation, paid inference or WSL enforcement.
The combined clean staged candidate passes 467 core checks and all four legacy
suites; strict staged secret screening passes without repository allowlists.

Before PR 7 acceptance:

1. Wire real kernel-authenticated controller ingress and protected readers; prove
   WSL UID/cgroup/process and filesystem isolation, including detached children.
2. Pin and implement initialized native transports, exact-ID read/resume and
   independent lifecycle/control receipts for both providers. Verify actual app
   visibility and subscription topology without shared-home credential copying.
3. Add reviewed worktree/launch/instruction/skill manifests and resource profiles;
   apply the prepared bundles through authorized worktree creation/reuse, verify
   loaded instructions/skills and actual target limits, then demonstrate failed
   setup, unsupported controls and failed stop acknowledgment.
4. Normalize native temporary-capacity, quota/authentication and unknown outcomes
   from evidenced adapters, without error-prose guesses or multiplied retries.
5. Connect PR 8 ownership and PR 9 admission to every turn source, including goals
   and native-app activity, before enabling automated turns or delegates.
6. Prove company/project/topic attribution and current grants for design acceptance
   test 14; single-owner fixtures are not a completed multi-company boundary.
7. Join PR 6's producer/source checks and full-system recovery, then run a scoped
   builder fixture. Keep HamalBot wiring and the live native daemon unchanged.
