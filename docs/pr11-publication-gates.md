# PR 11 Publication gate preparation

The publication controller is prepared offline. It joins a frozen candidate,
authenticated reviewer and CTO decisions, current-target test evidence and
serialized merge attempts to the original task and action journal. Real GitHub,
protected checkpoint export, CI and safe installation of post-merge work remain pending;
PR 11 is not accepted. The broker's live `publish` operation remains disabled.

## Publication and role authority

`relay_core/publications.py` uses the existing protected work, root, admission and
outbox database, lifetime lock and FULL-sync transactions. Mandatory independent
readers verify checkpoints, authority, installation scope, remote state, tests,
queue rules and outcomes. Worker text, cwd and Git commit authors are not identity.
Policy is explicitly platform-owner-only; company grants remain unavailable until
the separate company boundary passes acceptance.

The publisher needs current writer custody and an exact native mapping. A stable
publication ID pins source, work, repository, commit and checkpoint. One active
publication per session and a retained counter allocate fresh
`pub/<session>/<number>` branches. Branch push and PR creation are separate intents;
the branch needs independent confirmation before PR dispatch. Storage performs no
remote action and starts no model turn. Terminal publications cannot reopen as
new work.

Only an authenticated different-provider reviewer can record a verdict for the
exact open head. The verdict produces a separate SHA-bound status intent; local
approval alone cannot authorize merge. Only an authenticated CTO can request a
merge, pinning head, base, PR number and review. Changed actors or commits cannot
retarget an existing request. No low-risk review exception is enabled by default.

## Repository scope and independent gates

Explicit policy pins repository ID and owner/name, App/installation IDs, base,
required checks, pending-request bound and test-evidence age. Base names currently
use the existing simple identifier contract, not arbitrary Git refs. Fixture
values are not runtime defaults.

Every action requires one repository and minimal step permissions: contents write
for branch/merge, pull requests write for PR creation and statuses write for
review, plus metadata read. The journal stores scope evidence, never a token or
private key. The future credentialed adapter must explicitly restrict repository
IDs and permissions when minting tokens; omissions inherit installation grants.
[GitHub installation token documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).

Merge requires independently passing, fresh tests for the exact head/base pair,
an isolated runner, current screening/owner authority, confirmed review status and
current reviewer/CTO bindings. Queue evidence must establish squash, no bypass,
an authorized-pair check and actual merge-group CI. Final validation rejects
target or authorization changes during the installation read. Model review is
never a substitute for build/test evidence.

The intended provider contract uses the asynchronous merge endpoint with an exact
head, explicit `merge_action: merge_queue` and `bypass_rules: false`. Its default
action can fall back to direct merge; a head-SHA guard does not atomically pin the
base. Enqueued means accepted into the queue, not merged.
[GitHub pull request API](https://docs.github.com/en/rest/pulls/pulls).

Consequently a protected required check must compare each actual merge group with
the authorized candidate/base, current root and approvals. This is a remaining
server-enforcement gate, not something local receipt types implement. CI must
handle `merge_group`, whose SHA differs from the PR head, and queue squash settings
must be verified on the server.
[GitHub merge queue documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue).

## Attempts and crash recovery

Each external step uses the original outbox. Its exact attempt and complete gate
witness commit together before any provider effect. Retained witnesses include
historical scope, checkpoint or remote observation, authority, installation,
tests and queue rules as applicable. Their digest binds them to the immutable
delivery plan. Missing or altered witnesses deny replay and initialization;
reading evidence never grants execution or refreshes authorization.

Bounded FIFO requests serialize each repository. Its slot commits with the merge
attempt and witness. Unknown acknowledgments and enqueued results retain the slot;
only independent exact merged/rejected evidence releases it. Only unattempted
CTO requests can be cancelled, preserving history. Replay after restart grants no
second execution. Root/writer recovery stays held without resetting budgets,
creating model leases or running a rebase.

The fake provider records another effect on every call. Recovery tests therefore
cannot conceal duplicate execution behind provider idempotency.

## Post merge replay candidates

`post_merge.py` prepares an actual local Git candidate without rewriting the
original worktree, branch or index. Its worker-owned journal is data, not authority.
A mandatory independent receipt binds a completed publication merge and current
permission to the exact root, source, published commit and merged commit. A writer
guard must cover both worktrees, shared Git metadata and surviving descendants.
No model, fetch, native continuation or installation is performed.

The original full checkpoint is sealed before the stable replay request. Source
and merged commits, and any dirty-work stash object, receive retained local refs.
A separately prepared worktree starts from the original baseline, fast-forwards
to the frozen source and rebases only commits after the published SHA onto the
merged SHA. Empty later commits are retained and merge topology is requested.
Git warns that manual merge resolutions may need reapplication, so promotion
still requires independent verification of later committed work rather than
accepting a successful rebase as semantic proof.
[Git rebase documentation](https://git-scm.com/docs/git-rebase).

Tracked staged and unstaged changes replay with `stash apply --index`, not ordinary
autostash. A real test found that `stash create` refreshes its input index even
though working files stay unchanged. Creation now uses a private copy of the
sealed raw index; exact source freshness remains enforced, not relaxed. The Git
runner accepts an alternate index only as a private, unlinked replay-index file
inside its worker journal.
[Git alternate index contract](https://git-scm.com/docs/git),
[Git stash documentation](https://git-scm.com/docs/git-stash).

The ordinary stash path also lost a real unstaged edit hidden by
`assume-unchanged`. The replay adapter now records every index entry's mode,
object ID, semantic flags and actual source presence in hashed rows. A small
manifest binds their count and ordered digest to the sealed raw index digest;
paths are not embedded in the bounded request. Inspection uses NUL-framed output
from the pinned Git binary and rejects changed debug framing, unknown extended
flags and unrepresented unresolved index state. Git's debug format is explicitly
unstable, so target compatibility checks remain mandatory.
[Git index inspection](https://git-scm.com/docs/git-ls-files).

Normalization clears hiding flags only in the private index copy. An absent
`skip-worktree` file remains index-only rather than becoming an unintended
deletion. Intent-to-add files come from the complete checkpoint and regain their
intent flag without staging their contents. A separate durable restoration phase
preserves combined flags and missing-file semantics. To restore an absent intent
entry, a reservation precedes a temporary empty candidate placeholder; exact
type, owner and content checks precede its removal. Sparse absence removes only
a generated candidate file whose mode and bytes match its current Git blob. It
never removes an original file or changed candidate work. Interrupted restoration
reconciles those known effects without repeating the earlier dirty apply.
[Git index flags](https://git-scm.com/docs/git-update-index),
[Git intent to add](https://git-scm.com/docs/git-add).

Restoration testing reproduced an `O_RDWR` permission failure when the overlay
revalidated a completed file after restoring its original read-only mode.
Completed files now use read-only handles and exact byte/identity checks;
only incomplete copies require write access. Unchanged complete files are not
rewritten or chmodded. Changed bytes, replaced paths and files that cannot be
opened safely retain the candidate as a conflict, without changing source
permissions or replaying dirty apply. The focused fault case also covers a
process death after flags are restored with read-only file/directory modes.

Untracked and ignored files, empty directories, modes and symlink targets are
copied from the checkpoint without following links. A path that upstream now
tracks produces a conflict, never an overwrite. File reservations precede copy;
an interrupted reserved write resumes only after its existing prefix matches
the original bytes. Candidate creation/source loading reconcile known Git state.
An unfinished rebase remains preserved; an ambiguous dirty apply is held and is
not applied a second time. Source changes invalidate the request, and a changed
sealed candidate cannot be selected as current. Neither candidate readiness nor
historical evidence grants installation or native execution.

Conflicts retain the original checkpoint/index/files, stash/commit refs and the
candidate's actual Git operation state. Exact same-path promotion with crash
reconciliation, independently verified conflict resolution, real protected
merge/fence readers and native context reattachment are still required. This
candidate step is not a replacement for that final workflow.

Promotion must independently verify the restored index flags, intent-to-add and
missing-file semantics against the complete original checkpoint. Full sparse
configuration, submodule state and manually resolved merge semantics also remain
gates; ordinary flag support is not proof of those workflows. Passing replay
tests is not permission to omit work that Git's default operations do not
represent. Such work stays preserved and requires a verified replay method
before installation.

## Recovery inventory and rollout

PRs 12–13 must include `ccrelay.publications.v1` in the consistent protected cohort:
policy metadata, publications and all revisions/counters, merge requests/slots,
results and publication grants. Include original action plans/outcomes, task,
work and model state, native registry, role bindings, protected decisions and
referenced Git objects/checkpoint bytes. A publication-only copy cannot recover
the system. Clean-machine restore starts held and reconciles external outcomes.

Include `ccrelay.post_merge.v2` policy/Git pins, requests and every revision, index
entry rows and manifests, file/placeholder reservations, source/result checkpoint
contents, retained refs and full object storage, staging worktree mappings and
complete unfinished candidate directories in that same recovery cohort. Index
rows include modes, object IDs, flags, actual presence and row digests; the
manifest includes count, ordered digest and original raw index digest. A path or
checkpoint header without its bytes/Git objects cannot recover later work. No
replay journal is live-enabled yet. Existing v1 journals are rejected and
preserved, not altered or silently recreated; any migration requires review.

Unknown schema/policy bytes are preserved for reviewed migration. This code is
not enabled in the live relay and creates no production state. Later rollback
must retain the compatible journal cohort, never delete attempts or slots to
make an old version start.

## Verification and remaining work

Twenty-seven publication cases cover role separation, exact commits/verdicts,
writer custody, owner pause/screening, repository scope, test freshness, target
races, queue enforcement, serialization, terminal outcomes and gate witnesses.
Twelve actual isolated process deaths span publication storage, branch dispatch,
merge requests/dispatch, lost acknowledgments after effects and settlement.
SQLite, deaths and non-idempotent fake effects are real. Kernel/native/GitHub,
checkpoint and CI observations are synthetic, not provider or PC acceptance.

All 23 real-Git replay checks passed in 23 serial sandbox children. These include
eight actual process deaths around request, worktree creation, source loading,
rebase, dirty apply, overlay and ready-state commits; preserved staged renames,
deletions and binary additions with later unstaged bytes; an ordinary later merge;
empty commits; tracked/untracked/ignored conflicts; symlink and mode preservation;
source/candidate drift; scope/authority denial and alternate-index confinement.
The source-index refresh reproduced by `stash create` is fixed by copying the
sealed index, not by weakening checkpoint freshness. Replay tests run singly
because a measured case takes about 25 seconds; coverage and the 60-second
sandbox-child ceiling are unchanged. Crash fixtures are prepared before spawning
the fault process, keeping its existing 20-second boundary allowance.

All 121 staged shared-workspace/checkpoint/switch/publication/launcher/setup and
batching regression checks passed in 31 serial sandbox batches, and the strict
staged secret scan passed. This is focused verification, not a new full-suite or
target-PC run. No live service, bot, credential, native session or user-owned
protocol edit was changed.

The special-index extension was checked with focused hidden-edit, combined-flag,
intent-to-add, missing-file, manifest-tamper and restoration-death cases during
development. On the final staged code, five real-Git replay cases passed,
including complete read-only revalidation, same-length candidate corruption,
death after restored index flags and after an overlay write, and ordinary dirty
replay. Sixteen parser, runner-selection and isolation checks plus all four
legacy suites passed on the preceding staged snapshot; those test/runner/parser
files are unchanged in the final snapshot. These results do not claim a new
full-core, native Windows or WSL acceptance run.

The isolated runner now accepts repeatable exact `--core-module` and
`--core-test` selectors. It validates the entire discovered core catalog before
selection, rejects invalid or duplicate selectors and labels focused runs as
partial coverage. No selectors still runs the full catalog. Discovery and
execution remain sandboxed, with a separate scratch directory per invocation,
serial children and the unchanged 60-second child ceiling.

The roadmap records staged regression results. Candidate execution uses copied
staged source in the OS sandbox without host home, credentials or network, with
serial batches and unchanged child timeouts. User-owned protocol edits are
excluded. The previous full-suite result remains PR 10 evidence, not a new full
run for this slice.

Focused checks now use the same copied-source OS sandbox directly, without an
ad-hoc unsandboxed runner:

```
/usr/bin/python3 scripts/tests/run_isolated.py --suite core \
  --core-module test_core_replay_index --core-module test_core_test_batches
```

Repeat `--core-module` for complete exact modules or `--core-test` for exact
discovered IDs. The complete catalog is still discovered and validated inside
the sandbox; unknown/duplicate selectors fail, selected tests are not imported
outside it, and the output explicitly identifies focused coverage. The default
continues to run the entire suite. Each child retains its existing time limit;
parallel invocations, if used, have separate scratch trees rather than a shared
build directory. A focused result must not be reported as full-system coverage.

Remaining work includes verified Git/checkpoint export, protected App and
human/security readers, the real provider adapter and outcome audit, enforced
merge-group authorization and independent CI, and verified same-path promotion
and conflict resolution of the prepared post-merge replay. Conflicts must preserve
all source and candidate work for resolution. Joined encrypted restore and distinct-UID
native PC acceptance remain required. No direct credentials or direct-merge
fallback are granted to workers.
