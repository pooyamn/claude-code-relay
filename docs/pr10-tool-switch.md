# PR 10 Tool switch preparation

The worktree checkpoint and durable switch controller are prepared offline.
The controller joins unfinished files and task context to the original work item,
native mappings and action history, then transfers writer custody only after
independent verification. Real native loading, protected writer fences and runtime
integration remain pending. No native session is launched, resumed or replaced,
and PR 10 is not accepted.

## Complete worktree checkpoints

`worktree_checkpoints.py` uses the existing worker-UID `WorkspacePreparation`
mapping, reviewed Git binary/version pins and mandatory writer guard. It requires
the exact already-prepared root, role, execution, workspace and contract; it never
creates or adopts another worktree. The real protected driver must enforce the
writer/descendant fence across both the worktree and shared Git metadata.

Capture preserves regular file bytes, directories, executable modes and symlink
targets throughout the worktree, including untracked and ignored output. It also
captures the linked worktree's Git metadata, including the raw staged/conflicted
index and in-progress merge/rebase records. HEAD, branch and status are recorded
alongside content hashes. Filename bytes are encoded without treating newlines or
non-UTF-8 names as separators. Symlinks are recorded without reading their targets.

File bytes are stored in ordered chunks, not squeezed into a JSON frame or a
deployment-artifact file limit. Entry and total-byte bounds require explicit
policy; test values are not runtime defaults. An exceeded bound or unsupported
special/hardlinked entry leaves the request unsealed and preserves the source.
No file is silently excluded to report a complete checkpoint. Special operation
state still needs the protected operation handoff; unsafe entries require a
verified alternative before cutover, not deletion to make capture pass.

Git's raw index distinguishes staged bytes from later unstaged edits. Captured
merge/rebase metadata preserves unfinished operations without running them.
Regular file reads reject link/type/inode changes, and capture compares the
entire tree again before sealing. A later untracked-content or mode change
invalidates freshness even when HEAD and Git status are unchanged. The original
sealed checkpoint remains available rather than being overwritten.

## Durable state and authority

The private worker-owned journal records a stable request before capture.
Entries, chunks and the sealed manifest commit together under SQLite FULL sync
and its lifetime lock. A pre-seal process death cannot select partial content;
post-seal replay returns the same historical checkpoint without another capture
grant. Changed specification, schema or policy is rejected for reviewed migration.
Manifest, entry, chunk and sequence checks detect missing or altered content and
unlisted chunks.

This journal is data, not authenticated authority. A worker can write its own
state. The protected switch controller must independently freeze the source,
verify/copy the bytes and bind them to current native and task evidence. A true
freshness result is not permission to launch a model, transfer custody, approve
publication or repeat an external action. No restore, checkout, reset, commit,
push or deletion of source files is performed by capture.

The read-only native planner reports both component schemas. Checkpoint capture,
policy configuration, switch activation and availability of protected switch
readers remain false. Runtime checkpoint/switch commands are unavailable.

## Switch controller and custody transfer

`tool_switches.py` uses the same protected SQLite component as work ownership,
root budgets, model admission and the action outbox. It requires the existing
native registry with the same authority and policy. A stable request pins the
source and destination sessions, native IDs, root, role, worktree, source claim,
writer token, owner-control epoch, decision and original deadline. Neither a
changed target nor a missing native mapping can become a fresh conversation.

The phases are `checkpoint_pending`, `checkpointed`, `completed` and `cancelled`.
Requesting a switch atomically holds the root and work item while retaining the
source binding. Normal release cannot open a custody gap during an active switch.
The attached capsule contains an exact worktree checkpoint reference, task
context, unfinished operations, publications, approval references, pending inputs
and a digest of every original action's intent, attempt, outcome and provenance.
References are not inherited authorization. Changed actions require a new verified
attachment, and uncertain external actions are never replayed by switching.

Transfer requires current independent human authority, complete checkpoint
verification, exact destination context and runtime/tool/permission fingerprints,
no active destination turn, and a held guard fencing old writers/descendants and
destination execution. Retained source or destination model/tool leases must be
released through the existing admission component's independent stop verifier.
Loading and checkpoint proofs are reread before commit, followed by current
authority, mapping, control and deadline checks. A test reproduced stale context
being accepted after the final checkpoint read; the final loading recheck closes
that race while both fences remain held.

The same transaction advances the writer token, transfers the original work item
and completes the switch. It does not resume a native session, admit a model turn,
reset task limits/accounting or consume an approval. The root remains held for
explicit protected revalidation and ordinary admission. Cancellation retains
source custody and also grants no execution. A classified failure can store one
coalesced passive issue intent; actual issue delivery, owner notification and
admitted support repair are not connected yet.

The typed reader receipts in these tests are synthetic conformance inputs, not
native or kernel authentication. The real protected readers must inspect actual
source bytes and semantics, pending operations/publications/approvals, human
authority and loaded native state, with fences held throughout verification and
commit. The joined file test reads an actual checkpoint journal, but substitutes
UID/path protection and native loading. It is not a protected export or a live
Claude-to-Codex acceptance test.

## Recovery inventory

Register `ccrelay.worktree_checkpoint.v1` with the component recovery inventory.
Capture a consistent journal cohort containing metadata/policy, request/spec
rows, sealed manifests, ordered entries and every chunk. Preserve planned and
sealed history rather than promoting a partial request or resetting an existing
checkpoint ID. Verification after restart checks the sealed bytes; freshness
against the source requires a new writer fence.

The checkpoint references HEAD in the original retained repository; it does not
archive the shared Git object database, every ref or native transcripts. Full
repository and encrypted clean-machine recovery remain PRs 12–13 work. A tool
switch must keep that repository/worktree and independently join task context,
running operations, native IDs/contracts, pending messages/actions, publications,
approvals and outcome evidence. Copying this journal alone cannot recover the
working system or authorize replay.

Register `ccrelay.tool_switch.v1` in the same consistent recovery cohort as root,
work, model leases and action history. Include switch metadata, current rows,
every revision, capsule references and their complete checkpoint content, plus
the original native registry and binding/decision state. Unknown schemas and
incomplete history refuse authorization. A crash before transfer retains source
custody; after committed transfer it retains destination custody with no new
execution grant. Work recovery holds either writer, and replay of a completed
switch grants nothing. A component-only copy is not full-system recovery.

## Verification and remaining gates

Sixteen checkpoint cases exercise staged/unstaged/untracked/ignored bytes,
unfinished Git metadata, chunked binary files, safe symlink handling, empty files
and directories, changed content/modes, bounds, special/linked files, corruption,
immutable requests, writer-guard failure and recovery. Five actual isolated
process deaths straddle request, entry-capture and seal boundaries. Files, Git,
SQLite and process deaths are real; path/UID isolation and writer guards in these
Mac fixtures are synthetic, not native or distinct-UID PC acceptance.

The clean staged-source full run passed all 837 core checks in 210 serial sandbox
batches, the isolation probe and all four legacy suites. Candidate code ran only
inside the OS sandbox, without host home/credential/network access or increased
child timeouts. The strict staged secret scan passed. These results cover the
prepared checkpoint and controller code, not native or target-PC acceptance.

Twenty-seven controller cases cover original custody and task budgets, exact
request replay, incomplete handoffs, action changes/uncertain outcomes, retained
activity leases, stopped-writer requirements, revoked bindings, owner pause,
context/contract drift, deadline expiry, cancellation, passive issues and six
actual process deaths around request, checkpoint and transfer commits. A real
Git/checkpoint test rejects changed uncommitted bytes, reattaches a newly sealed
checkpoint and preserves both historical snapshots and staged/unstaged work.
The round trip checks Claude/Codex mappings and custody with synthetic native
loading; it does not claim actual native continuity.

Remaining work is protected checkpoint export; authoritative operation,
publication and approval snapshots; real all-source fences and loaded-context
readers; integration with current native resume and same-tool delta controls;
relay issue delivery and owner notifications; admitted support repair; and joined
encrypted restore. Destination setup must retain the original prepared worktree,
not create a separate path for its new session. Support repair must not acquire extra privilege, approval or
quota. Native Claude → Codex → Claude on the isolated target remains an acceptance
gate, not a result inferred from fixtures.
