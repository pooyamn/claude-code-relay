# PR 4 durable intake and poller preparation

Local preparation verified on 2026-10-02, not live deployment or target-WSL
acceptance. The new target intake persists original Telegram responses,
deduplicated updates, frozen routing decisions and logical dispatch records
before acknowledging them. It has no native/model execution or send path.
Khadang is the only prepared test-bot path; HamalBot wiring and Mac services
remain untouched.

## Intake mechanism and acknowledgment

The legacy `ccrelayd.py` advances its offset before handling and keeps jobs in
RAM. Its current Mac pipeline remains separate while the target adapters are
built. This PR adds `relay_core/intake.py`, `polling.py` and a thin
`ccrelay_intake.py` target entry point. Existing formatting, envelope, voice and
runtime capabilities remain in scope for the later adapters, not replaced by
a new model framework. The repository legacy authorization check now denies
an empty owner allowlist; no live copy was updated.

`IntakeLedger.capture` writes a bounded original response with a versioned
header and digest to private storage, flushes its file, publishes its spool
name and flushes the directory. It then commits unique update IDs, source
bytes/digests, routing/media references and the next acknowledgment offset in
one full-synchronous SQLite transaction. Only a successful commit lets the
poller issue that offset. A higher request cannot follow a disk, schema or
conflicting-replay failure.

Telegram confirms updates when `getUpdates` is called with an offset higher
than their IDs. IDs may restart randomly after a quiet week. The poller therefore
starts with offset zero to observe pending updates before using any saved high
value. After an empty response it also returns to observation; its cursor is
an acknowledgment for a freshly persisted batch, not a permanent numerical
high-water mark. Capture order has its own sequence, independent of those IDs.
These are our recovery rules derived from the [Telegram update and offset
contracts](https://core.telegram.org/bots/api#getupdates), not a remote
exactly-once guarantee.

The raw JSON layer preserves finite coordinates and other provider numbers,
rejecting duplicate keys, nonfinite values, invalid Unicode and excessive
nesting/size. It does not relax action contracts: monetary/action parameters
still cannot acquire authority through a provider float. Original wire bytes
remain in the spool; per-update semantic bytes/digests are stored in SQLite.
Event reads verify their bytes against the original batch, and dispatch reads
verify index/body/source agreement.

## Logical dispatch and owner controls

Root-owned policies explicitly allow the owner and permitted group usage, with
exact chat/topic to role/session mappings. Empty/invalid owner authorization
fails closed. A route is a delivery plan, not proof of a live session, task root,
turn identity or approval. PR 5 must independently resolve and guard those
identities; PR 7 supplies verified native readiness.

Materialization atomically creates one stable `tg-<bot>-<update>` dispatch and
moves its event from `stored` to `ready`. Competing materializers serialize
through SQLite. Replay retains the original route and cannot create another
logical dispatch. `ready` means pending downstream handling, not delivery or
completed model work. Held/unbound/unsupported and rejected events keep their
original content and reason without producing a model dispatch.

Priority lanes separate owner approval callbacks, direct owner stop/pause/
resume/interrupt controls, owner steering intents, and ordinary messages.
Group access does not grant owner control. Forwarded control claims and
commands addressed to a different bot cannot execute a control operation.
Explicit global/session control scope is accepted only in the pinned owner
control channel. Owner messages carry `prefer_steer`; they are not converted
into queued model follow-ups. Exact-turn steering, stop acknowledgments,
admission and unsupported/racing-turn behavior are still PR 5/7/9 work.

Callbacks beginning with the approval prefix go only toward the PR 3 owner
gate, never a worker. That gate still validates owner provenance, exact nonce,
prompt receipt, action, expiry and consumption. This PR does not grant approval
from a callback string, send an approval prompt or answer a callback.

Photos, voice, documents and other recognized media retain file IDs and
metadata; the original update also retains replies, captions and album
references. Filenames are metadata, never destination paths. Unsupported or
malformed media stays held with original bytes rather than disappearing.
Downloads/transcription belong in downstream admitted work and cannot block
the intake loop. A materialization batch verifies each source spool once,
rather than rereading a hundred-message response for every message.

## Poll ownership and health

Before polling, the transport verifies the configured numeric bot ID and
username with `getMe`, checks for an incompatible webhook, and reconciles
durable spool state. It never calls `deleteWebhook`, `setWebhook`, send methods
or download APIs. HTTP redirects are refused and token-bearing exception URLs
are not logged. The configuration defaults to disabled with invented IDs and
a placeholder Khadang username; its filename is not proof of bot identity.

A protected host-wide `/var/lib/ccrelay-pollers/<bot-id>.lock` uses a real
lifetime `flock`, not a PID-file assertion or state-directory-specific lock.
Each call rechecks the lock inode and process generation. Locks are never
unlinked on exit: replacing their inode could permit two owners. Workers
cannot edit the registry under the intended target UID policy. Mac tests use
synthetic UID/process observations with actual cross-process lock contention;
real Linux ownership is still a gate.

That lock fences cooperating local processes only. It cannot revoke a token
used by an unmanaged process or another machine. Inspect the existing Khadang
poller before any live test. Consecutive 409 conflicts persist across restart
and stop the target poller at the configured threshold; only a successful
durably captured poll clears the streak. `getMe`, a transient network error
or startup replay does not. Reconcile ownership through protected maintenance
before resuming a held poller; deleting the DB or repeatedly restarting it is
not recovery.

Known 429 cooldowns persist without repeated API calls. An independent thread
observes actual phase deadlines and time since durable poll completion. Timer
ticks and a busy network-error loop cannot fake durable progress; an explicit
provider cooldown extends its legitimate wait allowance. A stale cycle exits
only its own target process. The inert unit has `Restart=no`, no activation
section and no token in argv. It does not kill/restart any Mac daemon or start
another poller. Later support monitoring handles incidents without bypass sends.

## Recovery and migration

The tested process-death boundaries have distinct recovery behavior:

| Boundary | Retained state | Recovery |
| --- | --- | --- |
| Flushed temporary file before spool publication | Uncommitted staging bytes, no new cursor | Preserve staging; observe unacknowledged provider updates |
| Published spool before DB commit | Complete orphan response | Verify and import it before polling |
| DB commit before logical dispatch commit | Durable events and routing | Materialize once from stored records |
| Logical dispatch committed | Original pending dispatch | Retain its ID, do not create another |
| Remote acknowledgment before process death | Earlier acknowledged batch is already durable | Start by observing pending updates; retain prior dispatch |

Incomplete staging files are preserved but not interpreted as successful
responses. Corrupt batches, conflicting same-ID content, unknown schemas,
policy/bot drift or a legacy `offset` file stop without erasing original state.
Routing policy changes require explicit reviewed migration; replay does not
quietly reroute accepted work under a new policy.

PR 12 recovery must include a consistent `ccrelay.intake_ledger.v1` SQLite
snapshot, all referenced `ccrelay.intake_batch.v1` spool files, pending dispatches,
policies and component versions. Copying only an offset or live SQLite file is
insufficient. Snapshot the DB first, capture its referenced immutable batches,
and validate digests/permissions before declaring completeness. No spool pruning
is enabled; retention must respect backup and unfinished work.

Restore paused. Revalidate owner/bot/route identities, reconcile spool/dispatch
and unknown downstream effects, and prove the previous poller stopped before
claiming ownership. Reobserve remote pending updates before a higher offset.
Root schema/policy migrations preserve the original package; rolling back code
cannot clear deduplication, cooldown, conflict or external-action history.
Telegram retains unreceived updates for at most 24 hours, so a longer outage
cannot reconstruct never-captured messages from this ledger. The [retention
contract](https://core.telegram.org/bots/api#getting-updates) makes independent
freshness/liveness monitoring necessary; local persistence does not erase that
limit.

## Evidence and remaining acceptance

Run `python3 scripts/tests/run_isolated.py`. All four legacy suites and 142 core
tests pass; PR 4 adds 41 checks to the previous 101. Evidence includes actual
scratch-process deaths around disk/DB/dispatch/remote-ack boundaries, two
concurrent SQLite materializers, cross-process flock contention, malformed and
conflicting provider data, one-hundred-message source-verification behavior,
priority routing and deterministic liveness/cooldown checks. No actual Bot API,
subscription, native session or live credential was used. These are fake-provider
process tests, not power-loss or WSL permission proof.

`ccrelay_intake.py --plan` reads only example templates. It makes no network
call, reads no token and creates no state. The target `--run` path requires
explicit enabled root policies, the protected Linux ingress UID, pinned test
identity and host-wide ownership. Do not activate it from these examples.

Before trusted use, validate real WSL UID/group/proc/cgroup permissions, flock
semantics, systemd shutdown/deadline behavior and storage durability; prove
Khadang identity and exclusive ownership without altering HamalBot. Then join
this intake to PR 5's durable guarded runtime/action handling and PR 6's receipt
scheduler/approval UI. An intake-only canary is not a complete phone-control
cutover, and repository publication does not authorize one.
