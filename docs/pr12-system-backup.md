# PR 12 Full-system backup preparation

The coordinated local capture foundation is implemented. It captures an explicit
required component cohort, not only conversations. It is **not yet an encrypted,
off-machine full-system backup** and does not satisfy the approved 24-hour recovery
target. No PC service, scheduler, live credentials, storage account or bot was
changed. PR 12 remains in preparation.

## Required coverage

The protected runtime inventory must cover company decisions; role/repository
memory and disputes; handoffs; instructions and skills; native registry and exact
thread mappings; root/work/progress/budget/admission/retry state; inbound,
outbound, action, approval, publication and switch histories; issues and bus
records; immutable deployment artifacts, versions and policy; repositories,
object stores, local branches and unfinished dirty/untracked/ignored work; raw
transcripts and the history database. Later memory/search/governance components
extend this same inventory rather than establishing a separate backup authority.

This foundation does not discover or certify that inventory. A small fixture
cohort cannot prove complete system coverage. Missing or incompatible required
components fail before a complete manifest is published. The capture scope is
always `configured-cohort`, `full_system_backup:false`, `encrypted:false` and
`restore_mode:paused`; those fields cannot be relabeled by the inspector.

## Protected sources and coordinated capture

`relay_core/system_snapshot.py` requires a protected `SnapshotPolicy`, explicit
component instances, a whole-cohort filesystem/native writer guard and a clock.
The policy pins each component's source root, original owner UID, deployed
version digest, exact SQLite paths and exclusions. Supplying a different root,
omitting a database or adding a convenient exclusion cannot shrink that policy.
Describing root-owned configuration does not grant another UID access to it.

The protected driver must independently establish current component/runtime
bindings and permissions, and hold all filesystem/native writers, including
detached descendants, throughout capture. A declared callback is not that proof.
The registered live SQLite connections must belong to those current components;
their path strings alone are not runtime or connection-generation provenance.
Cross-UID component export/freeze integration and target enforcement remain gates.

All registered SQLite write transactions are acquired in deterministic path
order before any database is copied. Caller-owned transactions are rejected
without rollback. Failure to acquire a later lock releases only capture-owned
transactions. Independent read connections use the backup API while those
writes remain frozen, avoiding backing up the connection holding its own write
transaction. Copies are integrity checked and converted to standalone DELETE
journal databases, retaining committed WAL state without requiring sidecars.
The shared `snapshot_io.py` helper also serves the existing Telegram component
snapshot. [SQLite backup API](https://www.sqlite.org/backup.html),
[SQLite transaction locking](https://www.sqlite.org/lang_transaction.html),
[standalone WAL recovery considerations](https://www.sqlite.org/wal.html).

A fault test reproduced a path replacement escaping the original SQLite fence:
the lock covered the old file, but the independent copy opened its replacement.
Database file identities are now pinned to that fence and rechecked after lock
acquisition, before and after component copies, during final validation and
before sealing. A changed database retains both original and partial export and
cannot publish a complete manifest. This does not replace the driver's separate
proof of the current runtime/connection binding.

## Bytes, metadata and publication

The scanner uses directory-relative, no-follow handles and verifies file/path
identities. Original bytes and permissions are not changed. It preserves regular
file contents and modes, empty directories and symlink targets without following
them. Literal paths are canonical base64 metadata; payload files have numbered
names, so newlines, tabs, leading dashes and pathspec-looking names are never
commands or extraction paths. Regular bytes stream in 64 KiB chunks. Entry and
total-byte bounds are explicit policy, not truncation or permission to omit work.
Inventory rows are bounded; metadata memory remains bounded by the configured
entry count, not constant memory.

Registered SQLite paths receive coherent database copies, not raw file copies.
Unregistered SQLite files, hardlinks or special files fail visibly instead of
being silently skipped. A future component-specific representation must preserve
those requirements; failure is not permission to remove the affected work.
SQLite WAL/SHM exclusions explicitly point to their standalone database copy.
Other exclusions must identify generated state or an owner re-login requirement,
with a reason bound to the protected policy. Process lock files must be explicitly
excluded as generated ownership, never restored as proof of a live process.

Every capture creates a new private destination, without source overlap or
overwrite. Payloads and inventories are sealed, hashed and checked for missing,
extra or changed bytes. A second source scan verifies the whole captured cohort.
Per-component inventories precede the final fsynced cohort manifest. Process
death before that manifest leaves a visibly incomplete private export; death
after it leaves verifiable capture bytes. Neither case advances an upload cursor,
activates a runtime, changes authorization or repeats an external action.

Capture age begins before acquiring the writer fence, not when upload eventually
finishes. Later freshness logic must retain this conservative timestamp and the
approved 24-hour bound. Reading a locally hashed package proves integrity against
its expected policy, not independent authenticity, current grants or off-machine
durability. The expected policy must itself be included in the encrypted recovery
package and separately authenticated before a clean-machine restore trusts it.

## Verification and remaining work

Focused tests exercise real multiple WAL databases, independent writer processes,
large binary payloads, explicit credential exclusions, literal filenames,
read-only files/directories, missing or changed sources, failed lock acquisition,
database-path replacement, forged rehashed exclusions and payload tampering.
Five actual process deaths cover freeze, database copy, entry capture and the
before/after manifest boundary. Unknown external-action state is copied unchanged,
not reset to an executable action.

All 49 final clean-staged focused cases passed in 13 serial sandbox children:
22 system-capture cases, 16 Telegram snapshot regressions and 11 isolation/runner
checks. All four legacy suites and the strict staged secret scan passed. The
complete 934-case catalog was discovered and validated, but not fully executed.
Neither these results nor the older full-core result establish Linux/WSL or
native-PC acceptance. User-owned protocol edits were excluded from staged tests
and remain unchanged.

macOS cannot create the invalid-UTF-8 filename fixture on this host filesystem.
Its lossless path encoding is checked here; the native filename capture assertion
is retained for Linux and has not passed target acceptance. Host ancestor
protection and the whole-cohort native writer guard are synthetic in these
conformance fixtures. Actual SQLite locks, files and process deaths are real.

Still required before scheduling or declaring PR 12 accepted:

- Complete authoritative component inventory and protected schema/epoch readers,
  with coordinated cross-UID filesystem/native/ledger capture on WSL.
- Native filesystem recovery metadata and representations where needed, including
  group ownership, ACLs/xattrs, hardlink relationships and special-file state.
  Current file bytes/modes/link targets are not proof of those additional semantics.
- Streaming encrypted packaging, separately held owner recovery key and restricted
  credential recovery or explicit owner re-login. Never put the private decryption
  key in this package, public source or worker-readable memory.
- Verified off-machine upload, durable attempt/receipt/success state, interrupted
  upload reconciliation and capture-age alerts at 24 hours.
- Retention that preserves incremental dependencies, pinned sessions and unfinished
  recovery state; no pruning is implemented or authorized by local capture.
- Clean-machine extraction, UID/permission/version reconstruction, compatible
  component restore hooks and independent external-action reconciliation under
  PR 13, initially paused and without access to the source PC.

The existing transcript-only `history/backup.py` remains unchanged and must not
be described as satisfying those full-system requirements.
