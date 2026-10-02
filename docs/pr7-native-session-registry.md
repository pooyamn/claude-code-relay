# PR 7 Native session registry preparation

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

## Verification and remaining gates

Offline tests use invented normalized runtime/kernel observations, with actual
SQLite, private files, lifetime locks and nine scratch-process deaths around
enrollment, probe, observation and desired-state commits. They cover wrong IDs,
worktrees/contracts/capabilities, stale revisions, revocation during observation,
late callbacks after pause, duplicate native mappings, restore and schema refusal.
No paid/native agent, live bot, credential, service or native daemon is a fixture.
Run `/usr/bin/python3 scripts/tests/run_isolated.py --suite all` for copied-source
tests under the OS sandbox; this is not distinct-UID/native integration proof.

The clean staged candidate passed 447 core checks and all four legacy suites.
The registry/planner account for 22 focused checks, including the nine process
deaths. The strict staged secret scan passed without repository allowlists.
These results validate the offline preparation, not the remaining native gates.

Before PR 7 acceptance:

1. Wire real kernel-authenticated controller ingress and protected readers; prove
   WSL UID/cgroup/process and filesystem isolation, including detached children.
2. Pin and implement initialized native transports, exact-ID read/resume and
   independent lifecycle/control receipts for both providers. Verify actual app
   visibility and subscription topology without shared-home credential copying.
3. Add reviewed worktree/launch/instruction/skill manifests and resource profiles;
   demonstrate failed setup, unsupported controls and failed stop acknowledgment.
4. Normalize native temporary-capacity, quota/authentication and unknown outcomes
   from evidenced adapters, without error-prose guesses or multiplied retries.
5. Connect PR 8 ownership and PR 9 admission to every turn source, including goals
   and native-app activity, before enabling automated turns or delegates.
6. Prove company/project/topic attribution and current grants for design acceptance
   test 14; single-owner fixtures are not a completed multi-company boundary.
7. Join PR 6's producer/source checks and full-system recovery, then run a scoped
   builder fixture. Keep HamalBot wiring and the live native daemon unchanged.
