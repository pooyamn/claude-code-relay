# PR 12 Full-system backup preparation

The coordinated local capture foundation and an experimental streaming encrypted
package/verifier are implemented. They cover an explicit required component
cohort, not only conversations. This is **not yet an off-machine full-system
backup** and does not satisfy the approved 24-hour recovery target. No PC service,
scheduler, live credentials, storage account or bot is changed by this code.
PR 12 remains in preparation; the encryption format/key-custody choice is pending.

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
`restore_mode:paused`; those fields cannot be relabeled by the inspector. The
experimental outer encrypted package truthfully has `encrypted:true`; it does
not relabel the inner capture as complete-system coverage or authorize activation.

## Protected sources and coordinated capture

### Actual PC candidate inventory (2026-10-03)

`pc-router/inspect-backup-inventory.ps1` now discovers metadata on the actual
Windows host, without reading recovery-file contents, opening live SQLite
connections, starting models or changing source permissions/services. It records
literal UTF-16 names, sizes, attributes, ACLs, volume/file identities and link
counts. Final-entry handles request only `FILE_READ_ATTRIBUTES` and use
`FILE_FLAG_OPEN_REPARSE_POINT`; directory junctions are not traversed. This is a
**mutable-source diagnostic**, not a protected policy or coherent capture. Its
ancestor paths are not fenced, and 64-bit file indexes are not guaranteed unique
on ReFS. [Windows file metadata](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle),
[symbolic-link handle semantics](https://learn.microsoft.com/en-us/windows/win32/fileio/symbolic-link-effects-on-file-systems-functions).

The completed observation at `2026-10-03T12:59:04.6661113Z` contains 27 candidate
components, 6,059 entries and 5,506,010,424 logical bytes summed per pathname;
this is not deduplicated storage or a backup-size estimate. Ten SQLite candidates
include native goal, memory, queue, history and router state, with live WAL/SHM
sidecars. Required proposals include full workspaces and Git/dirty/ignored work,
both native runtimes and histories, router/media/action ledgers, LG/VPN state,
SSH host keys/configuration, GitHub login configuration, user/machine DPAPI and
credential stores, deployment artifacts, rollback copies and WSL state. These
are discovered candidates, not automatically authorized snapshot enrollment.

Two native-history reparse entries and one installed-runtime reparse entry remain
explicitly unresolved. Alternate streams, complete hardlink alias closure,
timestamps/SACLs, runtime/database-generation provenance and source consistency
are not established. Service definitions/credentials, task XML, firewall,
power/boot/driver/network state, VM/WSL registration and portable machine-bound
credential recovery still require protected API exporters or explicit owner
re-login/bootstrap paths. Copying DPAPI blobs is not proof of usable credentials
on a clean machine. Future company/role memories and registries must join the
same authoritative inventory after their host boundary is selected.

The detailed report is PC-local, administrator-owned, with only SYSTEM/admin
access inherited from its protected new directory:
`C:\ProgramData\KhadangRouter\state\recovery-inventory-da3483d6df3b452dbee63fc975b5ed0f\candidate-inventory.json`.
Its SHA-256 is
`5344FC6792DABB37E6D29D237E589D8E6E6F31A11214A11FD153FF6AC62F8AD7`.
Only sanitized counts/limitations are recorded here. This digest does not
authenticate a recovery catalog or certify source freshness. The report remains
`fullSystemBackup:false`, `encrypted:false`, `writersFrozen:false`, restore
paused; no daily job, encryption, off-machine upload or restore was performed.

Twenty-two actual Windows fixture checks cover a real NTFS junction/hardlink,
ACL metadata, empty directories, literal/surrogate names, entry bounds, absent
required sources, private no-overwrite output and truthful summary scope. The
first real discovery exposed PowerShell expression-list `+` precedence collapsing
dynamic folder tuples; named source fields fix the mechanism, and the regression
now tests actual dynamic-folder discovery and collector binding. Fixture success
and a published inventory are not PR 12 acceptance.

After this inventory, the router source was added at
`C:\Users\pou\workspaces\claude-code-relay`, branch
`codex/agentic-pc-preparation`, commit
`9ef8fad61643a2efe11dcde2537561ff79f12a5c`. A one-shot Interactive/Limited task
verified the exact ordinary owner, expected branch/commit and non-shallow history;
the task completed with result 0 at `2026-10-03T13:01:39.8796589Z`, and independent
ACL inspection confirms owner `pou` for the repository and `.git`. GitHub CLI's
existing login returned **HTTP 401: Requires authentication**, so this used a
**transport workaround**: an administrator-sealed, digest-pinned `git bundle
create --all` archive, then ordinary-owner Git clone and a repository-local
GitHub origin URL. [Git bundle semantics](https://git-scm.com/docs/git-bundle).
The retained bundle SHA-256 is
`54908CFD95BBDD192F1E5B2AA29E09C72CEB0708F62BFCD795773759C1325AC2`.
GitHub authentication remains unresolved; no credential was extracted or moved,
global config changed, model started or service restarted. Uncommitted/ignored
Mac work is not in this Git transfer and remains intact on the Mac. This source
copy and its one-shot evidence must join the next inventory/capture; the earlier
report is not retroactively current. Clone availability is not enforced
review/merge/deployment authority, publication acceptance or full-system recovery.

The same ordinary-owner source helper now supports a reviewed bundle update,
only from the expected commit/branch with no tracked, untracked or ignored work.
It verifies `FETCH_HEAD` before `merge --ff-only`, never forces checkout/reset or
changes global configuration. Existing run IDs cannot be replayed. Exact update
receipts remain in `.native-remote/source-clone-*/result.json`; a repository's
historical source observation is not self-authenticating proof of its latest
HEAD. This transfer mechanism still does not repair the rejected GitHub login.

The first update run stopped before creating its claim or changing HEAD: Windows
Git had marked `.git` Hidden, and `Get-Item -LiteralPath` without `-Force` reported
it missing despite the native directory existing. The guard now requests hidden
metadata with `-Force`, retaining the same reparse-point denial and unchanged
attributes/ACLs. `test-source-metadata.ps1` reproduces that actual hidden-directory
failure and checks the production guard against a real NTFS junction. Failed-run
evidence is retained; updates are not automatically replayed. All five actual
Windows metadata regression checks passed without touching a real repository.

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

## Experimental encrypted packaging and paused verification

`relay_core/encrypted_backup.py` uses a reviewed, digest-pinned, sealed `age`
executable to encrypt the capture to explicit native public recipients. The
producer requires no private recovery key. This is an **age format candidate**,
not the AES-256/7z format currently specified by design §10. It neither replaces
the existing transcript packager nor approves changing the production cipher,
key custody or storage. Owner format selection and deployment approval remain
required before live integration. [age CLI](https://github.com/FiloSottile/age),
[age format specification](https://age-encryption.org/v1).

The framed stream includes the protected policy, exact manifest-byte digest,
generated member names, bounded sizes/digests and payload bytes. It creates no
plaintext tar/zip archive and never interprets original source paths or symlink
targets as extraction instructions. Payloads stream in bounded chunks. An outer
record is published only after successful native encryption, final source
inspection and fsync; it retains the original capture timestamp and paused scope.

Verification requires ciphertext and policy digests from an independently trusted
catalog, not the archive's self-assertions. Public-key encryption authenticates
encrypted bytes, not the identity of whoever produced them. Independent catalog
authentication and freshness remain separate, unimplemented authority gates.
The private recovery identity reaches the native decryptor only through stdin;
home, credentials and plugin/updater settings are not inherited. Ciphertext is
passed through its verified no-follow descriptor, not reopened by an unchecked
path. Only newly created private destinations are permitted.

Generated-path validation, duplicate/member bounds, per-member digests, explicit
footer, final age authentication/EOF, successful native exit and full cohort
inventory verification all precede the recovered manifest and verification
record. The exact manifest bytes are preserved, including valid noncanonical
whitespace. Truncated ciphertext cannot publish a complete cohort even after
emitting plaintext. Unknown external-action state remains unknown and paused.
Actual process deaths before/after the package record, during decryption and
before/after the recovered manifest test those publication boundaries.

Each native crypto operation has an explicit bounded deadline and can stop only
its exact owned child. The macOS test sandbox now permits same-sandbox signals
and this process's descriptor reads; its probe proves own-child cleanup and
denial of even a signal-permission probe against the unsandboxed parent. No host
filesystem/network access is added. Crypto tests fail visibly without the
explicit reviewed runtime; there is no fake-crypto or silent-skip fallback.

## Verification and remaining work

Focused tests exercise real multiple WAL databases, independent writer processes,
large binary payloads, explicit credential exclusions, literal filenames,
read-only files/directories, missing or changed sources, failed lock acquisition,
database-path replacement, forged rehashed exclusions and payload tampering.
Five actual process deaths cover freeze, database copy, entry capture and the
before/after manifest boundary. Unknown external-action state is copied unchanged,
not reset to an executable action.

The encryption revision passed 67 clean-staged focused cases in 17 serial sandbox
children: 16 real-crypto, 22 system-capture, 16 Telegram snapshot, 6 isolation and
7 batching cases. All four legacy suites and the strict staged secret scan passed.
The complete 952-case catalog was discovered and validated, not fully executed.
The secret scan uses default rules without repository ignores/allow comments;
artifact hashes use the same explicit `sha256:` digest format as runtime contracts.
Neither these results nor the older full-core result establish Linux/WSL or
native-PC acceptance. User-owned protocol edits were excluded from staged tests
and remain unchanged.

macOS cannot create the invalid-UTF-8 filename fixture on this host filesystem.
Its lossless path encoding is checked here; the native filename capture assertion
is retained for Linux and has not passed target acceptance. Host ancestor
protection and the whole-cohort native writer guard are synthetic in these
conformance fixtures. Actual SQLite locks, files and process deaths are real.

Reproduce the focused checks with reviewed age/age-keygen binaries; the runner
copies only their pinned bytes into its private OS sandbox:

```sh
/usr/bin/python3 scripts/tests/run_isolated.py --suite all \
  --core-module test_core_encrypted_backup \
  --core-module test_core_system_snapshot \
  --core-module test_core_telegram_snapshot \
  --core-module test_core_isolation \
  --core-module test_core_test_batches \
  --age-runtime /absolute/path/to/reviewed-age-runtime
```

Still required before scheduling or declaring PR 12 accepted:

- Complete authoritative component inventory and protected schema/epoch readers,
  with coordinated cross-UID filesystem/native/ledger capture on WSL.
- Native filesystem recovery metadata and representations where needed, including
  group ownership, ACLs/xattrs, hardlink relationships and special-file state.
  Current file bytes/modes/link targets are not proof of those additional semantics.
- Owner-approved encryption format and separately held recovery key, authenticated
  package catalog, reviewed Linux runtime pins, and restricted credential recovery
  or explicit owner re-login. The experimental age packager does not settle those
  production choices. Never put a private decryption key in this package, public
  source or worker-readable memory.
- Verified off-machine upload, durable attempt/receipt/success state, interrupted
  upload reconciliation and capture-age alerts at 24 hours.
- Retention that preserves incremental dependencies, pinned sessions and unfinished
  recovery state; no pruning is implemented or authorized by local capture.
- Clean-machine extraction, UID/permission/version reconstruction, compatible
  component restore hooks and independent external-action reconciliation under
  PR 13, initially paused and without access to the source PC.

The existing transcript-only `history/backup.py` remains unchanged and must not
be described as satisfying those full-system requirements.
