# PR 11 Publication gate preparation

The publication controller is prepared offline. It joins a frozen candidate,
authenticated reviewer and CTO decisions, current-target test evidence and
serialized merge attempts to the original task and action journal. Real GitHub,
protected checkpoint export, CI and post-merge work preservation remain pending;
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

## Recovery inventory and rollout

PRs 12–13 must include `ccrelay.publications.v1` in the consistent protected cohort:
policy metadata, publications and all revisions/counters, merge requests/slots,
results and publication grants. Include original action plans/outcomes, task,
work and model state, native registry, role bindings, protected decisions and
referenced Git objects/checkpoint bytes. A publication-only copy cannot recover
the system. Clean-machine restore starts held and reconciles external outcomes.

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

The roadmap records staged regression results. Candidate execution uses copied
staged source in the OS sandbox without host home, credentials or network, with
serial batches and unchanged child timeouts. User-owned protocol edits are
excluded. The previous full-suite result remains PR 10 evidence, not a new full
run for this slice.

Remaining work includes verified Git/checkpoint export, protected App and
human/security readers, the real provider adapter and outcome audit, enforced
merge-group authorization and independent CI, and durable post-merge replay of
later committed, staged, unstaged, untracked and ignored work. Conflicts must
preserve the checkpoint for resolution. Joined encrypted restore and distinct-UID
native PC acceptance remain required. No direct credentials or direct-merge
fallback are granted to workers.
