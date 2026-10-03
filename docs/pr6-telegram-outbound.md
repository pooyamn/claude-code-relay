# PR 6 Telegram send scheduler and receipt preparation

The protected outbound foundation, bounded format/media repair and current
source-grant dispatch checks and Telegram-local recovery snapshots are prepared
and tested offline. They give Telegram sends one durable queue, keep every
required reply chunk, and advance watcher offsets only with a complete confirmed
receipt set. This preparation does not convert
the live Mac relay or establish target-PC acceptance. PR 6 remains in preparation
until trusted producer/repair wiring, real owner-prompt acceptance and the
integration gates below pass.
Khadang is the authorized test bot; HamalBot wiring remains unchanged.

## PC owner-only inbound attachments (2026-10-03)

The Windows migration adapter now implements direct-owner photo/file delivery,
separately from the protected company sender above. It selects the largest photo
variant while preserving the original update/variants, retains captions and
file names/MIME as untrusted metadata, and downloads referenced bytes through
the [documented Telegram getFile API](https://core.telegram.org/bots/api#getfile).
The hosted transport has a conservative 20,000,000-byte ceiling, bounded
streaming and two concurrent staging jobs. Credentials remain in the SYSTEM
router; fixed-origin/no-redirect downloads validate paths, unique IDs and sizes.
Neither credential-bearing URLs nor Telegram file IDs go to the native model.

The cache is `state/attachments` under the protected PC router. Generated paths
never use a supplied filename. Files are flushed, SHA256-hashed, and sealed with
SYSTEM/Admin ownership/control and exact-owner read permissions only; the
router state/credential/code ACLs are not broadened. Manifests retain the source
digest, exact topic/thread binding, selected references, sizes/digests and
preparing/staged/held phases. Partial multi-part staging is not native input;
restart or an old staging receipt cannot automatically replay it.

Recognized PNG/JPEG/GIF/WebP signatures become documented native
[`localImage` inputs](https://learn.chatgpt.com/docs/app-server); this identifies
a format, not proof that a decoder or model successfully interpreted it. Other
files remain read-only paths with their original metadata and caption. No
automatic attachment execution or paid transcription is added. Audio/video are
retained files, not a verified transcript or visual interpretation.

Downloads do not hold the session dispatch/control lock. Active media records
the arrival turn and rechecks it after staging; ending/changing that turn holds
the file instead of converting steering into a fresh turn. Caption slash text
is content, not a relay command. Pre-native download/metadata failures retain
the update and amend the same bubble without holding the owner session or
declaring an uncertain model action. Unknown native effects still use the
existing no-replay gate.

229 local and 232 actual Windows checks cover existing routing/goals/quota plus parser/path/stream
bounds, metadata spoofing, byte signatures, captions, denied senders, same-bubble
reporting, delayed staging/interrupt and stale-turn refusal. Windows adds actual
materialization/manifest/replay checks. Target native ACL evidence is recorded
in [`deployment-status.json`](../pc-router/deployment-status.json), separately
from provider download and real owner/image-model round trips.

Remaining full-system gates: real Telegram download/native image interpretation;
atomic albums (held, not partially sent); large files through an explicitly
reviewed local Bot API or equivalent transport; verified voice/video processing;
restricted-profile tool access, Claude, company/role grants, and unfinished
switch/clean-restore preservation of attachment bytes/paths. This is not PR 6 or
company acceptance. Register cache bytes and all manifests in the same daily
encrypted recovery cohort as the router ledger/native history; restoring a
staged file is not permission to resend an owner input. No cache pruning or
Hamal/Mac wiring change is performed here.

## Prepared mechanism

`relay_core/telegram_scheduler.py` extends the PR 5 outbox in a separate private
directory. Component tables initialize in the same transaction as the base
schema. Enrollment atomically retains the original source, its digest, ordered
operations, exact native session/turn/submission references and a registered
stream's queued offset. Repeating an identical bundle ID returns its actual
state; changing its content or attribution is denied.

The queue prioritizes approvals, alerts and callbacks, then replies, bus traffic
and disposable status. A committed claim reserves shared global/chat spacing
before the request. Verified flood rejection retains a per-operation cooldown;
a bounded replacement intent links its terminal failed predecessor and negative
evidence. Only methods explicitly characterized in protected compatibility policy
may retry. Restarts retain cooldowns and counts. The example permits no retries;
its timing and identity values are invented, not approved production settings.
Model-capacity retries remain a separate PR 9 admission responsibility.

Only an unattempted disposable status edit may coalesce. Required reply content
cannot. An unresolved older edit or deletion fences later edits/deletions of the
same message, without stopping unrelated work. Pending selection uses indexed
intent state rather than decoding every completed historical reply.

`telegram_outbound.py` provides one fixed-host request per call. It refuses
redirects, paid sends, unverified alternate delivery topology and media URLs or
host paths. Upload bytes are private, content-addressed and sealed; their original
filenames and MIME types remain in the manifest. Uploads have a total request
budget, and media groups retain each attachment reference and returned message
ID. Transport exceptions do not expose a token-bearing URL.

Original response bytes are atomically published and fsynced separately from a
sealed envelope binding HTTP status and capture time to the exact intent,
attempt and plan. A JSON object or a response body hash alone is not that binding.
Verified receipts check the bot, chat, requested topic, edit message and group
count. Receipt reconciliation, replacement enrollment/cooldown and final stream
offset advancement commit in one SQLite transaction. Generic outbox hooks are
protected implementation calls, not worker RPCs or authority from decoded JSON.

`telegram_producers.py` is the common protected enrollment gateway for replies,
mirrored app turns, approval prompts, alerts, callbacks, bus messages and status.
It requires a source/route authorization callback; caller-chosen source IDs do
not authenticate a session. Formatting reuses existing native tables and classic
code blocks without invoking their transports. It returns a bundle ticket, never
a formatting placeholder as a real message receipt. Full media captions become
ordered text chunks rather than being sliced; tail trimming is limited to
disposable status, whose original text is also retained.

## Prepared source permission checks

`telegram_authority.py` adds a private source-grant component. A protected
kernel-authenticated controller, not a worker or identity header, issues a grant
for an exact manifest after checking native/source and human/company/root/route
provenance. It binds the full source, native IDs, operations, alternatives,
destination and registered role/session/root/execution. The mandatory current
context callback must consult protected authoritative state; source IDs,
model prose, decoded JSON and an old cached permission cannot supply it.
The real callback and native-source bridge are still integration gates. The
broker registry read channel below is prepared separately; it is not native,
human/company/root permission. Do not solve access to the broker's private
registry by sharing a worker-readable database or credential home.

The grant database retains issuance, revocation and explicit renewal revisions.
Revocation persists across reopening/snapshot; ordinary issuance cannot extend
or un-revoke a grant. A controller may explicitly reauthorize the unchanged
manifest/binding after fresh context checks, preserving all old revisions.
Already attested output may outlive its producing process; a revoked or changed
execution binding still fences it. Writer handoff/recovery reattribution requires
the later verified registry/migration protocol, not editing an old grant.

The scheduler now requires a protected current authorizer and the pinned guarded
transport contract. It checks a typed exact-operation permit before claiming.
The transport checks again after multipart/upload assembly, immediately before
its sole request. Permission revision/expiry, source/route or bot-owner changes
deny the request. The plan records the actual grant/revision/expiry-bound permit,
not a static bundle hash. Flood replacements and recipe-bound child bundles
recheck their original manifest's current source permission.

A pre-claim denial retains the unattempted operation on a visible permission
hold. Confirmed siblings and the queued cursor remain intact; unrelated work
can proceed. A trusted driver must revalidate before explicitly releasing that
hold. A denial/death after claim remains conservatively unknown without replay:
there is no durable local proof certifying that the request was never submitted.
Renewal cannot reset that attempt. Actual captured receipts may still reconcile
an effect admitted before revocation; revocation cannot unsend content or erase
confirmed evidence. The final check is the admission boundary, not a distributed
transaction promising cancellation of an already admitted/in-flight request.

Grant storage is `source-grants.sqlite`, schema v1, in a separate private outbound
source directory. Queue/bundle/policy remain v2. The disabled outbound config is
now v2 and names that directory; older configs are rejected for reviewed migration.
The guarded plan uses adapter `telegram-outbound.v2`. Existing attempted records
remain inspectable/reconcilable, never converted into eligible fresh sends.
No legacy live sender, controller RPC, service or bot wiring was enabled.

## Prepared protected registry reads

`binding_reads.py` supplies `BindingReadClient.session` to the source checker
without opening the broker's private SQLite registry from the outbound UID.
The broker's optional `--binding-read-policy` flag adds only exact session reads
on the existing bounded Unix channel. Kernel peer and per-fragment credentials
identify the caller; the client pins the serving broker UID. Each fresh request
binds its nonce, session, component UID, installed broker/read policy digests and
returned binding. Reader role ceilings apply at both ends. A disconnected,
denied, stale or malformed response cannot fall back to a cached registration.

The separate root-owned read policy admits explicit non-worker component UIDs,
not role headers or working directories. The broker reloads that policy before
and after each registry observation, so a changed permission during a slow read
fails closed. The broker's main policy remains pinned at startup; changing it
still requires the reviewed migration/reload path. This channel cannot register,
revoke, list all bindings or authorize worker actions. Revoked rows remain
inspectable but cannot supply source permission.

The example policy is disabled and tied to the example broker policy digest.
The sysusers template proposes adding `relay` to the existing socket-access
group, without exposing the private broker home/database or launcher socket.
No group membership was applied. The inert broker service has not been changed
to enable the flag, and no runtime service or outbound controller was activated.
The read request/result/policy contracts are v1; existing registry, grant,
queue/bundle and outbound configuration schemas are unchanged by this addition.

A protected controller can compose `Authority(broker_policy,
BindingReadClient(socket_path, read_policy))` with `SourceGrants`, but must still
supply its protected current native/root/company/route checker. Registered
identity does not establish source provenance or task admission. Attested output
may outlive its producer; do not invent process-liveness permission. Actual WSL
UIDs, socket permissions, installed artifacts and native-context integration
remain acceptance gates, not properties proved by Mac fixtures.

## Prepared format/media repair

`telegram_repair.py` constructs an immutable alternative when the original bundle
is enrolled: HTML or rich text to complete plain Markdown, an HTML edit to one
plain-text edit, or an uncaptained photo upload to a document containing the same
sealed bytes. Plain text retains URLs and every source character, with UTF-16
chunk limits. Routes, reply controls and buttons stay bound to the original;
buttons appear only on the final replacement chunk. Full photo captions remain
separate ordered text operations. Required content is not tail-trimmed.

Only the protected driver may authorize a repair. It must identify a definite
format/media rejection using the pinned compatibility artifact and exact captured
attempt. A generic `400`, model prose or a valid-looking JSON authorization is
not that characterization. The example policy permits no repairs, and no live
authorizer is installed. Uncharacterized rejection remains failed with its
original source, assets and response retained. Telegram error details may change;
verify the adapter's supported behavior before enabling a method.
[Telegram response contract](https://core.telegram.org/bots/api#making-requests).

One repair transaction enrolls the alternative and its link to the original
failed operation, negative evidence, recipe, policy and authorization. Stable IDs
make identical enrollment idempotent; changed authorization is denied. The
original operation stays failed for inspection. Confirmed siblings never replay,
and the original stream cursor advances only when every original or replacement
slot is confirmed. A replacement cannot spawn another format repair. All of its
chunks share the original operation's remaining rate-retry budget across restarts.
Uncertain older edits fence later mutations; a late repair cannot overwrite a
newer edit or deletion already attempted or confirmed.

Queue, bundle and outbound-policy schemas are now v2. Old state is rejected and
preserved for an explicit reviewed migration, not upgraded or reset at startup.
This preparation changes repository artifacts only; no live ledger was migrated.

## Prepared owner prompts

`owner_prompts.py` prepares deterministic, complete approval text from the PR 3
gate's authenticated prompt view. It displays the action, root/requester, intent
digest, approval, owner, expiry and every exact parameter, including any candidate,
base, screening verdict and exception contained in those parameters. Plain-text
JSON visibly escapes controls and non-ASCII data without discarding it; parameter
strings cannot become HTML or break a Markdown fence. Long prompts use ordered
chunks, with opaque Approve/Deny buttons only on the final chunk. A general-topic
policy uses `null`, not topic ID `1`.

The new gate `read_prompt` operation is limited to the kernel-authenticated
protected ingress, just like receipt binding and callbacks. It returns the exact
action/approval/nonce and any existing receipt. The client verifies the configured
gate UID through the existing Unix channel and checks response/policy binding;
caller-supplied identity headers are not used. No worker read, action execution,
deployment or restart operation was added. Installed channel/policy, send-owner
isolation and actual WSL credentials still need acceptance; a decoded view alone
does not prove them. The fixtures substitute those observations explicitly.

The approval bridge derives one stable bundle from that view and pinned owner
route. Enrollment is only a ticket. Binding requires the identical retained
source, every prompt chunk confirmed, and each sealed response/body/attempt
matching its stored receipt evidence. The gate then binds the actual message ID
carrying the buttons. Partial or uncertain delivery, guessed receipts, changed
candidates, foreign views, lost ownership or expired pending approvals cannot
create that binding. Confirmed delivery itself never grants or consumes approval:
the owner must still make an authenticated exact-message decision.

The send ledger and gate commit separately. Repeating a completed bind, including
after the gate committed but its response was lost, reconciles the same receipt
without sending another prompt or deciding for the owner. If the gate already
binds a prompt but the send component/history is missing, recovery holds for
component reconciliation instead of creating a replacement. Preserve both sides
and their artifact/policy versions in a full-system snapshot. Owner ledger v1 is
unchanged; older gate code lacking `read_prompt` denies the new client, with no
unauthenticated fallback. No live ingress, sender or employee grant is enabled.

## Evidence and limits

Run the copied-source OS sandbox, not the legacy suites directly:

```sh
python3 scripts/tests/run_isolated.py
python3 scripts/ccrelay_outbound.py --plan
```

The preparation command only reads examples. It has no token, run, service-start
or credential-discovery interface and creates no runtime state. The WSL kit adds
inert private directory and policy examples, not a sender service.

The new tests cover partial chunks, stable IDs and attribution, ordered streams,
priority and spacing, persisted flood cooldowns, bounded evidence-linked retries,
uncharacterized rejection, uncertain sends, stale edit fencing, forged receipt
payloads, tampered assets/responses, policy/schema drift, formatting, media groups,
voice, full captions and read-only preparation. Fourteen actual process-death
boundaries exercise bundle/claim/submit commits, the non-idempotent fake provider,
response publication and receipt/offset commits. Actual SQLite, fsync and flock
are used; only private-ancestor/kernel observations are substituted for scratch
storage. These checks do not prove distinct-UID WSL enforcement, real client
rendering, remote idempotency or live bot acceptance.

An additional fourteen actual process-death boundaries cover repair enrollment,
replacement claim/submit, remote acceptance, response publication and receipt/
cursor commits. The test verifies exactly one durable repair, retained original
negative evidence, no uncertain replacement replay and no premature cursor
advance. A complete protected response can reconcile the same attempt; a body
without its attempt envelope cannot. Multi-chunk repairs, shared retry exhaustion
across restarts, pinned method ceilings, changed source/control bindings and stale
edits also have deterministic tests. The compatibility authorizer and provider
are invented fixtures, not proof of a trusted live rejection classifier.

Owner-prompt tests join the actual scratch gate and outbound databases with
sealed captured responses. They cover complete and partial prompts, flood
replacement receipts, general topics, forged response/evidence with consistent
hashes, changed candidates/views, expiry, lost ownership, employee-versus-owner
callbacks, duplicate decisions and consumed-approval replay. Seven additional
actual process-death cases cover prompt enrollment, remote acceptance, response
publication and before/after binding, including commit before lost bind ACK.
Kernel/channel observations and the provider are synthetic; live UI and distinct
ingress/gate identities are not established by these tests.

The initial foundation passed all four legacy suites and 232 core tests on
2026-10-02, including 41 outbound tests. The repair preparation adds 18 focused
tests, including its fourteen-boundary process-death matrix. Later suite totals
also include independent capacity-retry and live-bubble regression coverage.
These are local conformance results, not approval to deploy.

Repair verification on 2026-10-02: all four legacy suites and 282 core tests
passed in the copied-source sandbox. The read-only preparation command passed
with sends, network and state changes disabled.

Owner-prompt verification on 2026-10-02: all four legacy suites and 297 core
tests passed in the copied-source sandbox, including 15 joined-prompt tests.
This did not poll or send through a live bot, run a model, enable a service or
change the user-owned Codex protocol edits.

Source-permission verification on 2026-10-02: the expanded working-tree run passed
all four legacy suites and 353 core tests, including 26 focused source/transport
checks. Four actual process deaths commit revocation around claim, final
validation, remote acceptance and complete response capture. Recovery preserves
the grant history, unknown attempts and original cursor; only sealed captured
receipts can reconcile an already accepted effect without another send. Current
registry/context revocation, expiry, changed manifests, typed-claim forgery,
worker/controller ceilings, partial replies, explicit renewal, multipart guards,
repair/flood inheritance and consistent grant snapshots also have coverage.
The clean staged-source run also passed all 353 core tests and four legacy suites,
excluding the user-owned protocol edits. Staged secret scanning and the read-only
preparation command passed; the latter remains disabled with no runtime I/O.
Kernel identities, context checks and provider are fixtures, not WSL/company or
live Khadang acceptance. No paid/model or live bot calls were made.

Protected-registry-read verification on 2026-10-02: the copied working-tree
sandbox passed all four legacy suites and 397 core tests, including 21 new
read-channel checks. Joined tests use actual registry/grant/queue transactions
and a non-idempotent fake provider. They cover fresh reads, role/UID ceilings,
forged or stale replies, outages, hot read-policy revocation, preserved holds and
post-claim uncertainty without replay. A separate scratch registry writer commits
revocation and exits abruptly; an existing client observes it without reopening
its grant ledger. This is actual SQLite/process-death evidence, not a Linux
daemon/IPC crash test. Socket/kernel/ancestor observations are substituted;
company/native provenance remains fixture-only. Both read-only planners report
the read policy disabled and perform no runtime changes or network calls.
The final clean staged-source run also passed all 397 core tests and four legacy
suites, excluding the user-owned protocol edits. The strict staged secret scan
passed. No paid/model calls, live bot traffic or runtime activation occurred.

Telegram documents global, group and chat flood limits and returns a wait in
`retry_after`. This supports persisted scheduling, not unrestricted paid
broadcasts or a universal exactly-once guarantee. [Telegram flood guidance](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)
and [response parameters](https://core.telegram.org/bots/api#responseparameters).
The API returns a sent Message or a media-group result; protected transport and
attempt binding still require compatibility validation.
[Rich messages](https://core.telegram.org/bots/api#sendrichmessage) and
[media groups](https://core.telegram.org/bots/api#sendmediagroup).

## Recovery and component backup

Recovery never resets an attempted intent to stored. A committed claim without
a reconciled outcome becomes unknown, even if death preceded the actual request.
Confirmed chunks stay confirmed. If both protected response files survived, the
trusted driver can validate and reconcile the same attempt without a network
send. A body without its envelope, an incomplete temporary, a timeout or a 5xx
does not authorize another send; preserve it for reconciliation. A stale backup
also cannot prove that an externally completed action did not happen.

PR 12 must capture a consistent outbound SQLite snapshot including streams,
bundles, original sources, repair recipes/links/authorizations, attempts, receipts,
cooldowns and shared retry counters; the sealed response bodies/envelopes;
immutable assets and their metadata; a consistent source-grant database snapshot
with its complete issuance/revocation/renewal history; pinned policy, including
the broker binding-read policy/client/server artifacts; adapter artifact and
trusted stream/registry evidence. Keep incomplete spool
files for inspection. The base outbox's database-only snapshot is not a complete
Telegram component backup. `telegram_snapshot.py` now prepares the local part
described below; the joined full-system archive remains PR 12 work.
Restore paused, revalidate identity/versions and
reconcile external evidence before permitting execution. Runtime lock metadata
is diagnostic data, not proof of restored ownership; reacquire the numeric-bot
lock and verify its live kernel process generation.

Quiesce dispatch when checkpointing the queue, grants, broker registry and native
source evidence together. A stale snapshot cannot prove current membership or
permission: restore paused and revalidate through current protected checks before
explicit release/reauthorization. Missing grant components, unsupported schemas,
old boot/execution mappings or unavailable current context must hold output, not
reconstruct permission from the bundle or an old boolean. Database-only source
snapshots do not establish full-system/clean-machine recovery. A backed-up
binding/read-policy tuple is not a fresh broker observation or current source
permission; restore paused and revalidate it through the protected channel.

### Prepared Telegram component snapshots

The protected driver calls `capture()` between requests, with upload and response
writers quiesced. It holds the queue's lifetime lock and freezes grant and queue
SQLite writers in a fixed order. Separate read connections use SQLite's backup
API to include committed WAL state without waiting on their own write
transactions. New destination databases select exclusive locking before backup
and leave WAL mode before sealing; no shared-memory or WAL sidecars are exported.
This uses SQLite's documented [exclusive WAL mode](https://www.sqlite.org/wal.html#use_of_wal_without_shared_memory).
It does not change the live databases' journal or locking modes.

The new private tree contains both databases, all sealed response bodies and
attempt envelopes, all immutable uploads, retained interrupted `.pending` files
and the exact outbound policy. Original names/MIME types, repair recipes and
links, stream identities/cursors, attempts, cooldowns and grant history remain
in their original databases. Missing referenced upload bytes, changing files,
unrecognized components, links or unsupported schemas refuse completion; the
source bytes and visibly incomplete destination are retained. A sealed manifest
is published last, with each file's length/hash and explicit forensic-only labels
for interrupted files. Existing destinations are never overwritten.

`inspect_snapshot()` performs read-only inventory, hash, policy and database
integrity/format checks. `restore_snapshot()` copies verified bytes into a new
private tree and publishes a final `restore.json` receipt; it never opens a native
runtime, sends a message, renews a grant, resets a cursor or starts a service.
The receipt's paused label is diagnostic, not an execution fence: the recovery
coordinator must keep services stopped and reacquire live ownership only after
review. Unsupported owner IDs/versions require reviewed migration, not a silent
permission rewrite.

The manifest identifies a recovery cohort and requires external broker registry,
native source registry, company/root context, adapter artifact and binding-read
policy digests. These are references only: their bytes, authenticity, coordinated
capture, current authorization and external outcomes still require separate
verification. This local snapshot is unencrypted and is not a full-machine
disaster-recovery archive. PR 12 must join it with the other components and
encryption; PR 13 must demonstrate complete clean-machine restoration.

Offline fixtures exercise joined recovery, preserved revocation/renewal history,
original uploads/response envelopes and authorized repair links, an independent
writer blocked during both database copies, and eight actual scratch-process
deaths around capture/restore publication. An uncertain accepted send remains
unknown after restore and is not resent; a sealed captured response can reconcile
its original attempt without network traffic. The clean combined commit candidate
passes 425 core tests and all four legacy suites; a strict staged secret scan
finds no leaks. No live component state, credentials, scheduler or service was
changed by this recovery preparation. These checks do not establish target WSL
durability, real identity isolation or full-system recovery.

Unknown schemas or policy changes require explicit reviewed migration. Do not
delete ledgers, clear offsets/cooldowns, replace uncertain intents or reclaim a
live owner's lock to make a startup pass. Prepared rollback concerns repository
artifacts only: no production state, services or bot configuration were migrated.
After activation, any rollback must preserve the compatible queue and reconcile
in-flight outcomes before choosing a send owner; replaying the old live direct
sender beside the new owner is not a rollback.

## Remaining acceptance gates

1. On target WSL, prove actual private ownership, distinct worker UIDs, sealed
   uploads/responses, process-generation checks, SQLite/filesystem durability and
   one host-wide send registry. The reused lifetime lock uses a separate send
   directory, never the intake poller directory. It does not fence another host.
2. Inspect Khadang's existing sender and poller before an authorized test. Pin
   bot identity and adapter behavior; characterize per-method rejection and rich
   table/code/media/client receipts. Do not run an unmanaged second sender or
   poller and do not change HamalBot configuration, token, bindings or services.
3. Wire kernel-authenticated producers, exact watcher stream registrations and
   guarded native observations, controller issuance and current source/context
   checks through real split-UID channels. Prove revocation/expiry and the final
   transport guard against real protected policy and company membership; the
   prepared checker interface and synthetic grants do not prove those bindings.
   The component-only broker read implementation is prepared, but real WSL
   socket/group/UID enforcement and protected source-controller integration
   remain unverified. Do not substitute it for native or company authority.
   Cut every send/edit/upload/bus/status/callback
   path over to the one owner together. The old scripts still use direct sends;
   this gateway does not itself establish their cutover or a phone-control loop.
4. Characterize exact format/media rejection under pinned compatibility and wire
   the protected runtime authorizer. The prepared recipe/repair transaction is
   not permission to treat every `400` as a format failure. Prove the real
   transport's negative evidence and recovery driver, including failed originals
   recovered from a spool. Unknown outcomes must not repair or replay. Keep the
   locally tested sibling/cursor/shared-budget invariants under real integration.
   Existing live formatter fallbacks have not been removed.
5. Integrate the prepared approval bridge with the real single send owner and
   trusted PR 3 ingress. Pin gate/client capabilities; verify complete displayed
   text, actual button-bearing receipts and raw callbacks through Khadang.
   Revalidate source/grants before execution, not just enrollment, and demonstrate
   the locally tested duplicate/candidate/crash/unknown invariants across real
   identities. Keep platform-owner approval separate from company employee work
   before enabling the v8 membership expansion. Tickets and prose cannot approve.
6. Join the prepared Telegram-local snapshots with the other protected components
   and verify paused full-system restore, later health/status reporting and
   owner-authorized canary/deployment. Only then evaluate live adoption. This
   foundation does not complete PR 6 or the full 20-step PC readiness goal.
