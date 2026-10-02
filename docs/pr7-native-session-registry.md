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

## Durable exact ID resume adapter

`native_resume.py` extends the existing protected delivery outbox rather than
creating a retry queue. A resume intent fixes the native mapping, root, binding,
enrollment digest, current registry revision and separately reviewed resume
settings digest. The required protected gate must
cover current source/context, reviewed runtime/setup, writer fencing and admission,
including possible native goal continuations. Unsupported or unadmitted requests
remain held without a native call. Controller identity must come from kernel
ingress, never a supplied role/UID header.

Before RPC, the attempt is committed and `prepare_resume()` invalidates cached
readiness and earlier probes while preserving the exact conversation/last turn.
Submission and fresh control checks precede one `thread/resume` call with the
recorded thread ID and worktree, without model/profile overrides or start/fork
fallback. A matching RPC ID/thread acknowledgment must also report sandbox and
approval settings matching that action's pin, then requires the registry's
independent fresh runtime/worktree/permission observation; owner pause, changed
revision or revoked binding cannot be replaced by that reply.

Errors, lost replies and interrupted commits retain the attempt as unknown, not
failed/retryable. A replacement action ID cannot bypass an unreconciled resume for
the same session in the authoritative outbox. Only trusted outcome reconciliation
can release that predecessor fence. Confirmation records observed resume, not
task completion or permission for another turn. Recovery requires both native
registry and outbox/evidence cohorts, plus the pinned runtime/workspace artifacts.

No initialized native transport, real observer/admission gate, Claude adapter or
live driver is enabled by this slice. The existing registry schema is unchanged;
control invalidation adds history events, not an automatic state migration. Native
app visibility, complete task/approval continuity and actual target behavior still
need their acceptance evidence.

## Prepared stdio RPC connection

`native_rpc.py` supplies the initialized callable used by the resume adapter on
explicit, exclusively owned nonblocking stream handles. It neither launches a
process nor discovers/connects to a socket. The protected launcher must verify
the actual role UID, runtime generation and pinned configuration/transport; the
required verification callback and descriptor checks are not independent proof
of those facts. Reviewed transport and initialization-result digests have no
default. The target CLI still exposes only its disabled read-only plan.

This adapter implements JSONL stdio, not the existing Mac daemon's Unix
WebSocket transport. The upstream contract requires one `initialize` request,
its successful reply and then `initialized` before other requests. Supporting
stdio does not replace the required isolated native-app/daemon topology or prove
app visibility. The Unix adapter below is also disabled; target transport
acceptance remains a gate.
[Codex App Server](https://learn.chatgpt.com/docs/app-server).

RPC replies match both request ID value and type. Notifications and server
requests are captured with exact raw bytes and a connection generation before a
reply can be accepted. The protected capture bridge must durably record them and
demultiplex current authorized thread/root bindings; transport capture alone
does not authorize a foreign event. Caller-driven `poll()` continues receiving
tool and goal events while idle, without another background poller. Oversized,
malformed or ambiguous frames are refused, never truncated or silently dropped.
Native error details are returned without prose-based capacity classification.

Server replies require the exact pending typed ID, connection generation and a
separate current authorization. Concurrent/replayed replies cannot send twice;
JSON null results are supported. Approval is never automatic. A protected handler
can explicitly reply while an RPC awaits the server. Authorization/capture
callbacks receive detached copies, so mutating them cannot alter wire parameters
or manufacture an acknowledgment. Runtime pins are checked again after reply
authorization and before writing.

An outstanding RPC timeout, EOF or failed pin/capture closes the connection and
leaves outcomes for the existing outbox to reconcile. There is no reconnect,
RPC replay, start/fork fallback or inference from a successful write. Idle waits
retain partial frames without treating an absent event as a failed action.
Closing handles does not prove native/tool descendants stopped. Launcher,
independent observer, durable event/approval bridge, admission and joined restore
integration are still required; a restored controller must reconcile pending
actions before creating another connection.

All 37 focused sandbox checks pass: 23 new RPC checks, 12 resume checks and two
planner checks. Actual anonymous pipes exercise fragmentation, partial writes,
idle events, explicit replies, EOF and timeouts. A joined SQLite/outbox fixture
verifies exact resume over this connection and accepted resume with a lost reply
without replay. Provider behavior, runtime pins, event capture and admission
remain synthetic; no native process, login, bot or service was used as a fixture.
The full suite was not rerun for this slice. This is preparation, not PR 7
completion or target runtime activation.

## Prepared Unix WebSocket connection

`native_ws.py` adds WebSocket framing to the same RPC gates on an explicitly
supplied, already-connected Unix stream. It does not discover a home socket,
connect, start a daemon or fall back to stdio/TCP. The protected launcher must
still authenticate the actual peer UID/runtime generation and reviewed endpoint.
Descriptor checks and HTTP Upgrade are not role authentication. The read-only
target plan records this separate transport as inactive.

The upgrade checks HTTP status, Upgrade/Connection headers and the challenge
response before sending native initialization. Redirects, duplicate/malformed
headers and unrequested extensions/subprotocols are refused. Framed JSON is
strict UTF-8; client messages and control replies are masked. Fragmented messages
and partial headers/bodies survive idle waits, with aggregate byte/frame bounds.
Ping/pong is transport maintenance, not native approval. A partial control write
poisons the connection rather than becoming a harmless idle timeout. Close/EOF
leaves any pending native outcome unknown and cannot prove descendants stopped.

This is preparation for the upstream Unix WebSocket contract, which remains
experimental and unsupported for production workloads. Reviewed runtime/version
pins and compatibility acceptance are still required; offline framing does not
establish native-app access or a compliant role-isolated subscription topology.
[Codex App Server](https://learn.chatgpt.com/docs/app-server).

All 55 focused sandbox checks pass: the preceding 37 RPC/resume/planner checks
and 18 new WebSocket checks. Actual anonymous Unix socket pairs exercise the
upgrade, masked writes, fragmentation, idle events, control frames, protocol
rejection and explicit authorized replies. The same durable resume fixture now
runs over both transports, including accepted resume with a lost acknowledgment
and no replay. No real native daemon, socket path, login, model or bot was a
fixture. An initial oversized-header fixture attempted to keep writing after
the correct early cutoff; it now supplies exactly the header ceiling without
a delimiter and verifies refusal. The full suite was not rerun. Protected
launcher/observer/capture/admission wiring, Claude controls and target acceptance
remain pending; no live transport was activated.

## Prepared Linux native sender identity

`native_peer.py` supplies an optional `KernelUnixPeer` for the prepared Unix
transport. A protected launcher must select this credentialed path, not use the
plain framing fixture as an identity proof. The gate fixes the exact protected
binding and native process epoch, reuses the broker's `Authority` checks for role
UID, execution cgroup and surviving leader, and refuses policy/binding drift.
It borrows an explicit nonblocking descriptor without owning or discovering one.

Connection-time `SO_PEERCRED` alone is insufficient when a socket is forwarded.
The gate enables `SO_PASSCRED` and uses the broker's shared bounded `recvmsg`
helper to require exactly matching `SCM_CREDENTIALS` on every HTTP/WebSocket
chunk. Missing, duplicated, truncated, foreign or unexpected ancillary data is
refused. Incoming descriptors are closed, including when an earlier credential
entry is malformed. Current binding/process identity is checked again after the
read, so revocation cannot turn received bytes into evidence. A verifier bound
to this gate rejects an uncredentialed channel instead of falling back to reads
without sender evidence. Unsupported platforms have no UID fallback.
[Linux Unix socket credentials](https://man7.org/linux/man-pages/man7/unix.7.html).

Without the executable option below, the peer digest records sender identity
only. Neither mode proves effective native settings/context, provider entitlement,
admission or native-app visibility. The controller must use the production
kernel/proc observer and reviewed launch inputs, not a worker-supplied `Authority`
or normalized fixture.
Configuration observation, launcher/event integration and target
acceptance remain required. The read-only plan keeps this gate inactive; no
native process, daemon, bot or service was changed.

All 89 focused sandbox checks pass: 12 new peer checks, 22 existing identity/wire
checks and the preceding 55 transport/resume/planner checks. Actual anonymous
sockets and SQLite are used, but Linux credentials, options and proc observations
are explicitly substituted on this Mac. The initial fixture correctly failed
because its PID belonged to another builder execution; a child inside the intended
unit now represents the valid path, and the foreign execution remains a rejection
case. These tests validate integration and refusal, not real distinct-UID Linux
isolation. The full suite and native target acceptance were not run for this slice.

## Prepared native executable observation

`native_image.py` checks the actual file opened through Linux `/proc/PID/exe`
against an explicit reviewed binary under `/opt/ccrelay/native`. Both that file
and the installed path must have the same inode and metadata, root ownership,
non-writable protected ancestors, executable permission, no set-ID bits and a
bounded size. The initial read checks ELF magic and the complete SHA-256 byte
digest; a version string, argv or matching filename cannot replace that evidence.
Changed/deleted paths, interpreter wrappers, another inode with identical bytes
and unavailable proc access are refused. The observer follows only the fixed
kernel executable link; it does not discover sockets or run a program.
[Linux executable link semantics](https://man7.org/linux/man-pages/man5/proc_pid_exe.5.html).

The protected controller can provide `executable` and `executable_digest` together
to `KernelUnixPeer`. Its transport pin then includes the measured image pin.
Current checks reopen and compare the exact file metadata without hashing a
large binary for every frame. The existing process-generation/role/binding gate
brackets image observation; credentialed reads check again before returning
bytes. Replacement during a receive therefore cannot become a captured native
event, and a stale pin cannot authorize the next RPC. No image FD is retained.
Sender-only mode remains explicit preparation, not executable evidence; the
future protected launcher must require reviewed image inputs before readiness.

This is file observation, not continuous execution or memory attestation. Shared
libraries, executable mappings, injection/ptrace, same-PID exec changes between
observations, namespace isolation and native configuration/context require the
remaining protected launch and target acceptance gates. In particular, procfs's
executable link can be changed through a Linux process-control operation; the
target capability/isolation policy must prevent untrusted use of it.
[Executable link modification](https://man7.org/linux/man-pages/man2/PR_SET_MM_EXE_FILE.2const.html).
The existing launch/registry schemas and their expected runtime digests are not
silently redefined as a binary hash. The image pin is a separate transport input.
No native settings, admission, app visibility or Claude adapter is activated.

All 104 focused clean-staged copied-source sandbox checks pass: 12 image checks, three added
joined peer checks and the preceding 89 checks. Real files, byte hashing, atomic
replacement, sockets and SQLite are exercised; Linux proc routing, root metadata
and credentials are substituted on this Mac. Its scratch filesystem stripped
set-ID bits, so those negative cases explicitly supply Linux mode metadata rather
than weakening production checks. An earlier repeated-file fixture also correctly
failed to overwrite its own read-only file; the second candidate now uses fresh
scratch storage. These are fixture corrections, not native readiness evidence.
The full suite remains deferred to the next milestone.
The clean staged export excludes unrelated protocol edits; strict staged secret
screening passes without repository allowlists.

Recovery requires the reviewed installation path and bytes in the full-system
inventory, not just a version label. A replacement is a reviewed launch change;
the old connection cannot accept it as an automatic upgrade. After restart or
restore, construct a fresh image/peer pin and repeat observation before readiness.
Refusal closes the prepared client channel, not the native process or descendants,
and does not release uncertain actions for retry. No persistent component schema
was added. The read-only plan keeps executable checking inactive; no live daemon,
watcher, bot, installed native binary or service was changed.

### Loaded settings evidence remains pending

Official documentation describes `config/read` as layered configuration on disk,
not the effective permissions of a loaded thread. Disk contents cannot satisfy
the registry's independent native permission/context observation.
[App server configuration contract](https://learn.chatgpt.com/docs/app-server).

Read-only schema generation from the installed Codex 0.160.0 binary, with and
without `--experimental`, found no `thread/settings/get` or `thread/settings/read`.
`thread/read` reports current model/effort when loaded and persisted values
otherwise; its cwd and CLI version describe recorded thread state. Its schema
does not return loaded sandbox/approval settings. The generated
`thread/settings/updated` notification does include sandbox, approval, cwd and
model settings; only the experimental schema exposes `thread/settings/update`.
This is local compatibility evidence, not a live settings/control acceptance test.

The next observer integration must establish a fresh exact-thread settings
baseline and durable connection/control epochs before relying on notifications.
Neither requested resume overrides, a stale notification nor disk configuration
can stand in for that evidence. No settings mutation, live resume or inference
was performed during this inspection.

### Resume permission response verification

The generated Codex 0.160.0 `ThreadResumeResponse` reports `cwd`,
`approvalPolicy`, `approvalsReviewer` and the legacy `sandbox` policy. The
prepared `native_settings.py` adapter compares those returned native fields,
not request overrides or disk configuration, to an explicitly reviewed
`ccrelay.codex_resume_permissions.v1` contract. This provides a resume-response
baseline; it is not an independent post-resume observation or continuing
permission to run. The official resume API returns the same response shape as
thread creation. [Native resume contract](https://learn.chatgpt.com/docs/app-server).

`resume_action(..., settings_digest=...)` now requires that separate pin. It
changes the durable intent and delivery plan before any effect, without changing
the registry's broader permission/context digest. The native request still
contains only the exact thread ID and worktree. The current adapter is version 3:
missing pins are held before RPC, while mismatch, unsupported response shape or
failed verification after submission stays unknown without another resume.
Changing the action ID cannot bypass its unresolved predecessor. Successful
evidence references the sealed full response and retains canonical permissions alongside the
independent observation; an acknowledgment alone still cannot mark readiness.

Normalization follows the pinned schema's defaults and preserves network access,
writable roots, temporary-directory exclusions, approval-grant flags and reviewer
selection. Unknown fields, non-boolean flags, duplicate/unsafe roots and missing
required approval fields are refused. Named permission profiles and experimental
runtime workspace roots require complete effective-policy evidence; they are
held for that integration, never reduced to the legacy sandbox view. External
sandbox reporting does not prove actual OS enforcement.

Before activation, review the pin against the protected launch artifact and
current policy. An old unsubmitted intent without it needs explicit replacement;
do not rewrite an existing intent, discard unknown outcomes or reset counters.
Old confirmed receipts remain historical, not new settings evidence. Preserve
the existing outbox, native registry, full response/evidence and launch cohort
during recovery. The settings slice introduced no database migration; the capture
slice below adds immutable artifacts. Rollback to an older adapter is not
permission to execute current intents with weaker verification. The plan keeps
these checks inactive.

The preceding settings slice's clean staged sandbox run passed 167 focused settings, registry, resume,
outbox, identity and transport checks. Nine new settings checks and three added
resume checks cover mismatched permissions, exact intent pins, absent legacy
pins, preserved defaults and refusal rather than policy fallback. Nine actual
resume-driver deaths now include the boundary after settings verification;
accepted-write/lost-ACK recovery still does not repeat the non-idempotent fake
provider over pipes or WebSocket. Native settings, controller/admission and
Linux facts remain synthetic. This is not real provider/profile/WSL proof; the
full suite remains deferred to the next milestone. Strict staged secret
screening passes without repository allowlists.

Fresh settings/control epochs, complete loaded instructions/skills/MCP context,
native app visibility, subscription topology and actual isolation still require
the protected observer/launcher integration. No bound native session, daemon,
bot, service or model was used as a fixture or changed by this preparation.

### Durable native response capture

Native JSON is not the action ledger's financial JSON. The generated Codex
0.160.0 schema allows arbitrary JSON in MCP arguments, and resume can return a
large history. The [app-server contract](https://learn.chatgpt.com/docs/app-server)
documents these returned items. Two real-pipe synthetic-provider regressions
reproduced the previous failure: a finite floating-point argument or a 70 KB
history changed an accepted resume into `unknown`. The ledger forbids floats and
limits evidence to 64 KiB; neither restriction should be weakened for transcripts.

`native_capture.py` preserves the complete received JSON bytes in the protected
`ArtifactStore`, without redaction, rounding, truncation or execution. Non-executable
1 MiB chunks form a `native-payload` artifact. A separate `native-frame` artifact
contains `ccrelay.native_frame.v1` metadata: source and connection pins, unique
frame ID, kind, typed request ID, full-byte digest/size and payload reference.
Separating metadata preserves the existing store's full 8 MiB payload capacity
without increasing deployment limits. Original whitespace and numeric spelling
survive, not just the parsed representation. Repeated notifications have distinct
frame receipts even when their payload bytes are identical.

The protected launcher must attach capture before initialization and supply a
source digest derived from current kernel identity, binding, runtime and connection
context. A worker-supplied digest does not establish that provenance. Capture
checks this source before and after publication and invokes existing event/UI
listeners only after durable storage, with a detached parse. Foreign-thread
notifications are retained as connection evidence, not attributed to the bound
thread; existing exact-thread demultiplexing remains required. This is durable
individual-frame capture, not an ordered replay log or a fresh settings observer.

`CodexRPC.response_evidence` verifies the last matched response's exact method,
parameters, typed ID, return value, current transport and sealed bytes. An
in-memory capture cannot satisfy it. Adapter v3 requires that proof immediately
after resume, before independent observation can issue another RPC. The outbox
stores a compact `ccrelay.native_frame_receipt.v1` reference plus permissions and
fresh observation, not the full transcript. A missing, corrupt, mismatched or
revoked capture leaves an already-submitted action unknown, without another
resume, a new-ID bypass or inferred readiness.

Recovery must include both artifact components, their manifests/chunks, the
outbox and native registry, and the protected source/connection cohort. These raw
frames can contain private data and credentials: keep the store inaccessible to
workers and include it in encrypted recovery, not Telegram text or worker memory.
Preserve staging and orphan payloads for inspection; do not treat a payload
without its scoped frame artifact as a confirmed reply. A complete frame surviving
lost ledger acknowledgment is forensic evidence, not automatic reconciliation or
permission to resend. Historical reads verify stored bytes but do not grant
current execution authority. Rollback must preserve these artifacts and unknown
actions rather than discard them or route through an older adapter.

Protected source/producer wiring, persistent control epochs, ordered event recovery,
archive inventory integration and clean-target restore acceptance remain pending.
The plan reports capture inactive. No live native session, daemon, bot or model
was changed or used as a fixture.

The clean staged-source OS-sandbox run passed 203 focused capture, artifact,
resume, settings, registry, identity, outbox and transport checks in 51 serial
batches. Eight capture cases exercise exact-byte restoration, the full 8 MiB
payload, unique event receipts, typed IDs, tampering, source revocation and
post-durability listeners. Both regression histories and an observer issuing a
second RPC pass over real pipes and anonymous Unix WebSocket fixtures. Thirteen
actual synthetic resume-driver deaths include payload publication, scoped frame
publication and capture verification; recovery never repeats the provider effect.
Source/kernel/native settings and admission observations remain substituted,
not native Linux/WSL enforcement evidence. The full suite remains deferred to
the next milestone.

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

## Worker UID worktree preparation

`native_workspace.py` adds actual local Git worktree creation/reuse with a private
SQLite phase journal. It requires the effective non-root worker UID to match the
supplied broker role and checks private ownership, modes, links and metadata
pointers. The state is worker-owned, not a broker authorization record; neither
its phase nor its output can grant delivery, publication, approval or admission.
No live entry point, worker RPC, Git seed importer or native launcher was enabled.

The protected launcher must first validate the reviewed launch package, exact
specification/current execution and company/source grants, then dispatch under
the intended UID. Its mandatory `writer_guard` must independently quiesce/fence
old writers and all surviving native/tool/Git descendants across the workspace
and role-private Git metadata for the entire operation. A Python context manager,
expired lease or stopped parent is not that proof. The fixture guard is synthetic;
the real kernel/controller bridge remains unimplemented and required for use.

Creation journals the exact requested spec before touching a new branch. An
unexposed staging worktree is initialized without forced checkout, verified clean
at the exact baseline, and promoted using Git's worktree move. Each Git mutation
has an earlier committed phase. Existing target directories/branches are not
silently adopted by create. After an interrupted promotion, the target is verified
in place, preserving later dirty work rather than repeating initial checkout.
Empty unexposed staging can be initialized; partial/changed staging, branch-only
effects, collisions or missing recorded worktrees remain intact for evidenced
repair. No reset, clean, force or fresh-native-session fallback hides ambiguity.

Explicit reuse and prepared replay verify linked-worktree/common-directory
backlinks, requested branch and baseline ancestry and read NUL-delimited status.
They do not checkout or rewrite the index, tracked/untracked/ignored files or
unfinished-operation markers. Status hashes describe observations only; they are
not a snapshot of dirty contents or proof that a task is complete. The separate
setup helper below installs generated context without changing these Git rules.

The Git executable bytes/version are pinned; changing a recorded Git contract,
schema, policy or execution/specification requires reviewed migration/transfer.
The role-private bare seed must have bounded canonical local configuration.
Includes, configured filters/fsmonitor/remotes, external object alternates,
worktree configuration, legacy grafts and shallow/incomplete objects are refused without repair
or default-profile substitution. Seed import and supported repository extensions
still need target acceptance, not an assumption that every repo topology works.

Two actual Git regressions exposed why a commit-shaped name is insufficient.
Replacement refs materialized different files while HEAD retained the pinned SHA;
all helper Git calls now disable replacement objects. A worker-owned loose object
could also contain different bytes under its expected hash filename, passing the
existence check and reaching checkout. Full object integrity checking now runs
before journal registration or workspace writes, without lost-found output or
connectivity-only shortcuts. This is integrity validation, not source approval.
Historical-repository strict-mode checks are not imposed. The existing command
bound remains; large-repository performance/resource acceptance is a target gate.
[Git replacement objects](https://git-scm.com/docs/git-replace),
[Git object integrity](https://git-scm.com/docs/git-fsck).

Git children use explicit argv, private umask, no inherited home/credential/Git
configuration, disabled hooks and no network protocol/lazy fetching. A bounded
command timeout terminates its spawned process group and leaves effects for
fenced reconciliation; it does not establish absence of detached descendants.
Actual WSL resource limits and controller stop evidence remain required. Git's
documentation establishes hook disabling and global/system configuration
controls; our strict local-config allowlist is an additional preparation policy.
[Git configuration](https://git-scm.com/docs/git-config), [Git environment](https://git-scm.com/docs/git).

Recovery requires the journal, exact Git/policy/spec pins, role-private Git object
store/refs/worktree metadata and all worktree contents together. Database backup
alone is incomplete. PRs 12/13 must capture a quiescent consistent cohort and
restore initially unadmitted with fresh current-writer/native verification. No
real role workspace has been imported or prepared by this step. Rollback of the
repository artifact never authorizes removing a partial or dirty worktree.

## Worktree context installation

`native_setup.py` verifies the exact launch package against the prepared workspace,
copies its complete sealed tree into the worker's private `native-setup/artifacts`
store, and installs instruction/skill discovery links. License notices, assets
and executable flags survive; scripts are not executed. Native/MCP configuration
and resource fragments remain stored inputs, not activated settings or limits.
The worker journal records the pinned specification and bundle before effects.
Copy/link phases and atomic no-clobber symlink creation reconcile interrupted
installation without selecting a different bundle or resetting repository work.

Existing instruction/skill destinations, symlinked parents, changed links and
missing completed links are held for reviewed integration or evidenced repair;
the helper never overwrites project context. Replay verifies the copied artifact
and exact link targets. Unknown journal schemas remain intact. Recovery must
capture this journal and copied artifact tree alongside the existing workspace
cohort; relocating absolute discovery links requires explicit migration.

The same real worker UID and mandatory writer/descendant fence apply. A protected
launcher must still review/authorize and export inputs to the worker without
sharing protected homes. No such export/dispatch bridge, worker RPC or live entry
point is enabled. `files_installed` does not imply `native_loaded`, readiness or
admission; all three remain false. Codex documents repository skill discovery and
following symlinked skill folders. Instruction-link loading, complete effective
context, Claude discovery and target resource behavior still need pinned native
proof. [Codex skills](https://learn.chatgpt.com/docs/build-skills).

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
The registry/launch-bundle clean staged candidate passed 467 core checks and all four legacy
suites; strict staged secret screening passes without repository allowlists.

Workspace fixtures exercise real Git creation, promotion, branch/ref identity,
staged/unstaged/untracked/ignored bytes, merge markers, local SQLite, lifetime
locks and nine worker deaths at journal/Git boundaries, plus three deaths for
partial-staging/collision preservation. The actual fixture UID/file checks run;
target paths, ancestor observations and writer/descendant guards are substituted.
They do not prove distinct-UID WSL isolation, native startup, generated-file
loading, mid-command descendant death or protected dispatch.

The larger real-Git fixture set exceeded the old single-process 60-second harness
allowance; the final observed case passed alone in 2.85 seconds. The harness now
discovers cases inside the OS sandbox, validates the complete catalog and runs
every case exactly once in serial batches with the same per-child 60-second
ceiling. An eight-case batch grouped two heavy crash loops and exceeded that
allowance, so batches contain at most four cases. It neither imports candidate tests on the host nor parallelizes builds,
skips cases or relaxes the timeout. Batch coverage/schema checks are included.

The workspace candidate passed all 486 core checks in 122 serial batches and all
four legacy suites from a clean staged-source export. This includes 17 workspace
checks and two batching checks; both Git identity regressions were reproduced
before their fixes. Strict staged secret screening passed without repository
allowlists. These results still do not satisfy the native/WSL acceptance gates.

The context-installation slice passed 31 focused sandbox checks: nine new setup
checks, 20 launch-bundle checks and two planner checks. Six actual worker deaths
exercise committed registration, copy, link and completion boundaries. Tests use
real files, symlinks, Git and SQLite, but substitute target ancestors and writer
guards; they do not run either native agent. The full suite was not rerun for this
slice: 486 core checks and four legacy suites are the preceding milestone's
evidence, not a claim about this candidate.

The resume slice passed 65 focused sandbox checks across the adapter, registry,
planner and existing outbox, including 12 new resume checks and eight actual
process-death boundaries. The provider is deliberately non-idempotent; recovery
does not call it twice. Runtime/controller observations and admission are synthetic,
not real provider/UID/WSL proof. Strict staged secret screening passes without
repository allowlists. The full suite remains deferred to the next milestone.

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
