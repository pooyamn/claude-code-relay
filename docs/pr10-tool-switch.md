# PR 10 Tool switch preparation

The worktree checkpoint foundation is prepared offline. It preserves actual
unfinished file and Git state, rather than treating an unchanged HEAD as a fresh
handoff. The durable switch controller, semantic/action handoff, destination
loading proof and writer transfer remain unimplemented. No native session is
launched, resumed or replaced, and PR 10 is not accepted.

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

The read-only native planner reports the checkpoint schema, while checkpoint
capture, policy configuration and tool-switch activation remain false. Runtime
checkpoint/switch commands are unavailable.

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

## Verification and remaining gates

Sixteen checkpoint cases exercise staged/unstaged/untracked/ignored bytes,
unfinished Git metadata, chunked binary files, safe symlink handling, empty files
and directories, changed content/modes, bounds, special/linked files, corruption,
immutable requests, writer-guard failure and recovery. Five actual isolated
process deaths straddle request, entry-capture and seal boundaries. Files, Git,
SQLite and process deaths are real; path/UID isolation and writer guards in these
Mac fixtures are synthetic, not native or distinct-UID PC acceptance.

The clean staged-source run passed 132 checkpoint/workspace/setup/launch/planner/
artifact/contract/identity/isolation checks in 33 serial sandbox batches. Candidate
code ran only inside the OS sandbox, without host home/credential/network access
or increased child timeouts. The strict staged secret scan passed. This is a
focused regression run; the preceding PR 9 full-suite milestone was 794 core
tests, not a new full-suite result for this checkpoint component.

Remaining work is the durable switch phase machine; actual source checkpointing
and protected export; operation/action/publication/approval snapshots; real
all-source quiescence and custody transfer; current destination loaded-context
proof; exact native session/turn validation for same-tool deltas; relay bug and
owner-notification integration; admitted repair/revalidation; and joined encrypted
restore. Support repair must not acquire extra privilege, approval or quota.
