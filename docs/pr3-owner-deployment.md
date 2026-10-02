# PR 3 owner authorization and deployment preparation

Local preparation, not live deployment or target acceptance. The owner gate
persists exact-action decisions and single-use attempts. The bootstrap deployer
installs sealed content-addressed trees and changes a protected version pointer
without executing candidate code. Routine deployment is still disabled pending
independent publication/test gates. Mac sessions, bot wiring and services are
unchanged.

## Owner authentication boundary

`ccrelay_owner_gate.py` uses PR 2's Linux peer and per-fragment kernel credential
checks. Only the separate credentialed ingress UID may submit callbacks and
confirmed prompt receipts. Workers, the broker and launcher identities cannot
alias the ingress or gate. Root may enroll reviewed bootstrap intents, but an
enrollment is not an owner decision. No worker, cwd, request header or agent
message can grant an approval. The socket exposes no deployment, restart or
generic attempt handler.

The ingress is trusted to obtain raw updates directly from the Bot API and
verify its bot identity with `getMe`. A JSON object is not proof of Telegram
origin. This implementation authenticates that trusted ingress at the OS
boundary; actual durable intake and scheduler wiring belong to PRs 4–6. Until
that path and the target boundary pass their acceptance tests, do not enable
this gate or treat synthetic callbacks as authorization.

The protected policy pins one human owner ID, bot ID, chat ID and optional
topic. The ledger creates an opaque nonce before sending the prompt. A trusted
confirmed send receipt binds its exact message ID. A callback must match the
owner, bot, channel, message and nonce; inaccessible, forwarded, inline,
arbitrary-data and plain-prose claims fail. Telegram documents the callback's
sender and optional accessible message separately, and limits button data to
64 bytes. Our receipt and nonce checks are additional authorization rules, not
guarantees supplied by Telegram. See the [callback
contract](https://core.telegram.org/bots/api#callbackquery) and [button
contract](https://core.telegram.org/bots/api#inlinekeyboardbutton).

Show the exact action parameters, intent digest, screening state/exception and
expiry in the approval UI, not a model-generated substitute. Reviewer discussion
can inform that decision, but cannot authenticate it. A subsequent deny decision
on the original prompt revokes an unconsumed grant. A consumed action cannot be
revoked into an unattempted action. The final UI/scheduler is not implemented by
this preparation.

## Durable decisions and attempts

`OwnerLedger` uses private SQLite with full synchronous WAL transactions and
strict v1 records. Enrollment and prompt binding are immutable. Exact callback
replay preserves the current approval state; conflicting update/callback IDs
are refused. Owner expiry is checked against the protected clock at both grant
and consumption. A detected backwards clock holds authorization.

Consumption, the unique attempt record and the action's `delivering` state
commit together before an effect. An identical attempt replay returns
`may_execute=false`; it never supplies permission to execute again. Unknown
outcomes stay unknown until exact evidence confirms them. The hash-linked audit
records decisions, receipts and attempt changes without raw callback text or
secret-bearing payloads. It detects chain corruption but is not tamper-proof
against root or compromise of its own protected identity.

The local pointer crash tests establish these outcomes:

| Crash boundary | Recovered action | Permitted next step |
| --- | --- | --- |
| Before attempt claim | Stored, approval unconsumed | Original approved attempt may start |
| After claim, before pointer | Unknown, approval consumed | Inspect evidence; no blind reactivation |
| After pointer, before DB confirmation | Unknown then confirmed from exact pointer | Reconcile without another installation |
| After confirmation | Confirmed | Keep the original outcome |

These are local process-death tests, not power-loss or remote exactly-once
proof. Pointer writes flush the file and containing directory; a rename alone
would not establish directory durability. The [Linux fsync
documentation](https://man7.org/linux/man-pages/man2/fsync.2.html) explains that
distinction. Actual WSL storage/power-loss behavior remains to validate.

## Protected classification and artifact installation

`DeploymentPolicy` is loaded from protected root-owned input, never from a
candidate. Classification compares complete candidate/base trees, including
additions, deletions and executable modes. A bootstrap, a change outside the
explicit routine path allowlist, or any code in a credentialed component is
protected. Candidate files named like authorization/deployment policy do not
replace the installed policy.

Code running as `relay` can read its credentials regardless of the filename
edited. Calling a Python rendering patch harmless does not confine it. The
routine-update lane therefore belongs in a separate credentialless presentation
component with a fixed protected launcher and scoped inputs. That preserves
Pouya's choice not to review every relay change. The example policy describes
that lane; its identity/runtime isolation and independent review/tests must be
proved before PRs 11/15 enable it. V1 rejects attempts to enable routine
deployment now.

`ArtifactStore` accepts bounded byte trees, not arbitrary host paths or archive
extraction instructions. It rejects traversal, normalized dot segments,
duplicates, file/directory collisions, symlinks, hard links, extra entries and
changed bytes/modes. It flushes a sealed staging tree before publishing its
content-addressed name. Failed stages remain for inspection and are never
selected automatically. Files are immutable to ordinary workers, not to root
or a compromised deploy coordinator that owns the protected store.

`BootstrapDeployer` revalidates the entire artifact, current base, installed
policy, screening payload and explicit exception against the approved action.
Changing any of them invalidates authorization. A protected lifetime lock
serializes installation/activation. Activation changes only a version pointer:
no imports, subprocesses, credential copying, bot polling or service restart.
Runtime canaries, compatibility checks, service adoption and rollback are PR 15
work; the pointer's receipt is not evidence that a new router is running.

## Jev screening contract

`screening.py` is pure candidate masking and report validation, not a live Jev
client. It includes dependencies/configuration from the verified complete tree,
binds artifact and masked-payload digests, and distinguishes `clear`, `flagged`,
`unavailable`, `uncertain` and `incomplete`. Binary/uncovered or oversized input
cannot silently become complete clearance. Non-clear screening requires an
explicit exception in the exact action Pouya approves; triage's rules fallback
never supplies deployment clearance.

Masking takes explicit protected known values and common token/key patterns;
it does not discover homes, environment variables or live credential files.
Common literal/hex/URL/base64 forms of supplied values are covered. Arbitrary
secret encodings and unknown values are not guaranteed safe: source allowlists,
protected masking configuration and egress checks remain necessary before any
provider call. Reports in these tests are synthetic. A validated report object
is not evidence of an authenticated Jev response, and no live Jev/provider call
or paid fallback is enabled here. The later protected screener must establish
provenance and audit the exact submission before routine use.

## Preparation and recovery

The owner/deployment examples default to disabled and use invented owner/bot/
channel IDs. Never copy those IDs into an enabled policy. The inert service
template has no activation section, network access or token. The read-only
identity planner checks matching ingress/gate UIDs and explicit owner socket
group membership; workers receive no membership. Root installs a reviewed copy
of broker policy in the gate's protected policy directory so its service need
not read the broker's private directory. Policy changes require controlled
reload/migration, not candidate-controlled hot configuration.

Capture the following as required component state in PR 12:

- Owner policy, broker policy/version, UID/group allocation and reviewed gate
  and deployer artifacts.
- A consistent `ccrelay.owner_ledger.v1` snapshot from `OwnerLedger.snapshot`,
  including approvals, original intents, decisions, attempts and the audit head.
- Complete `ccrelay.artifact.v1` trees, active-pointer records, deployment policy
  and exact screening provenance/masking-policy versions. Masking secrets stay
  in restricted encrypted recovery or are supplied again by the owner.

No current state is auto-migrated. Unknown schema/policy or audit disagreement
preserves original bytes and stops. Restore the system paused, check policies,
permissions and expiry, and reconcile external outcomes before reuse. A stale
snapshot is not permission to repeat an action; PR 13 must reconcile later
external evidence. Rolling back code must retain consumed approvals and attempt
history and use a compatible reviewed schema. Do not clear a DB, reset an
unknown action, reactivate a revoked grant or select a stale pointer as an
unreviewed rollback.

## Evidence and remaining gates

Run `python3 scripts/tests/run_isolated.py`. All four legacy suites and 101 core
tests pass on the Mac; PR 3 adds 37 checks to the previous 64. The code executes
only in copied-source scratch with synthetic configuration and OS-enforced
host filesystem/network exclusions. Private ancestor observations are mocked
where Mac scratch differs from a protected Linux state root; actual file modes,
bytes, SQLite, locks, rename and process deaths are exercised. A path test
caught `PurePosixPath` normalization hiding `./`; validation now rejects dot
segments in the original text before normalization.

Before trusting this capability, demonstrate real distinct-UID Linux/WSL
permissions, per-fragment credentials, inherited/transferred socket rejection,
policy/store integrity, service group semantics and crash/durability behavior.
Then prove trusted Bot API intake, exact displayed prompts, confirmed receipts
and owner decisions through Khadang only, after verifying `getMe` and its
existing poller ownership. HamalBot credentials, bindings, polling, hooks and
services remain untouched. No live bot, publication, deployment or routine
automation is authorized by these tests or by pushing their code.
