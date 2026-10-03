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

254 local and 257 actual Windows checks cover existing routing/goals/quota plus parser/path/stream
bounds, metadata spoofing, byte signatures, captions, denied senders, same-bubble
reporting, delayed staging/interrupt and stale-turn refusal. Windows adds actual
materialization/manifest/replay checks. Target native ACL evidence is recorded
in [`deployment-status.json`](../pc-router/deployment-status.json), separately
from provider download and real owner/image-model round trips.

`pc-router/MediaProbe` and `run-media-probe.ps1` provide an explicitly reviewed,
one-shot Khadang acceptance diagnostic, not an alternate live router. The
self-contained package must include the exact deployed router assembly. It uses
a separate protected ledger/claim, never opens the live database or polls updates,
and starts native inference only through the existing medium-owner launcher.
A generated randomized three-panel PNG contains no project data or truth metadata;
only its confirmed bot message can be removed. Upload/delete receipts, bytes,
truth and the native thread remain in protected diagnostic recovery state.
One structured-output turn has a 90-second response deadline; tools or ambiguous
effects stop it without retry. This exercises documented
[Telegram file uploads](https://core.telegram.org/bots/api#senddocument) and native
[`localImage`/`outputSchema`](https://learn.chatgpt.com/docs/app-server) inputs.
`--observe-only` diagnoses the native quota fields with no upload/thread/model.
The quota guard is a fresh coarse observation, not shared admission or reserve
enforcement. The first actual attempt stopped before upload/inference on the
characterized startup race documented in [PR 9](pr9-model-admission.md).

Actual generated-image acceptance passed at 12:28:44 UTC on 2026-10-03: Telegram
uploaded and downloaded identical PNG bytes (SHA256
`DACD38C74E37CCA9925D5B0F9C5B7B972E78DB7AF9F81254F2BBE7DF60412F11`),
and the native model returned the private randomized truth `red, blue, magenta`.
Exactly one turn completed, with no observed native tools or unknown operations.
The confirmed generated bot message was removed; its bytes and receipts remain.
The separate diagnostic worker exited, and the live LG thread/bubble, four
turn/start receipts, two sendMessage receipts and single topic stayed unchanged.
Managed account/permission readings matched before/after; rounded weekly usage
was 25% both times (not proof of zero cost or global reserve enforcement).
This proves the provider download/native image path, not authenticated owner
photo intake, in-flight media steering or phone/app continuity.

Remaining full-system gates: real owner photo intake and active media steering;
atomic albums (held, not partially sent); large files through an explicitly
reviewed local Bot API or equivalent transport; verified voice/video processing;
restricted-profile tool access, Claude, company/role grants, and unfinished
switch/clean-restore preservation of attachment bytes/paths. This is not PR 6 or
company acceptance. Register cache bytes and all manifests in the same daily
encrypted recovery cohort as the router ledger/native history; restoring a
staged file is not permission to resend an owner input. No cache pruning or
Hamal/Mac wiring change is performed here.
Include `state/diagnostics/media-*` ledgers/claims/truth/receipts in that cohort;
restoration never grants another diagnostic send or model turn.

## PC native-origin bubble and steering receipts (2026-10-03)

The PC handler previously ignored completed native `userMessage` items and
displayed only generic tool types. It now reflects bounded, literal native input
into the same topic bubble and names MCP/dynamic tools, with command completion
status/exit codes. Attachment URLs/paths, arbitrary MCP arguments/results and raw
reasoning are not mirrored. Known credential-shaped text uses the existing
literal/redaction helper; this is not a complete data-loss-prevention guarantee.
Slash text in this view never executes a bot command or authenticates a human.
Existing exact-thread/turn filters still reject stale or foreign events. A
bounded 2,048-item live display cache coalesces repeated completions; it is not
durable action-delivery authority. The rolling message remains bounded to 3,900
characters with its existing elapsed/goal footer.

The router also validates the returned `turnId` against `expectedTurnId` before
describing steering as accepted. A missing, malformed or different receipt
retains the original input and holds reconciliation, without a queued/fresh-turn
fallback or mutation replay. [Native steering and event contracts](https://learn.chatgpt.com/docs/app-server).

Joined fixtures cover a native-origin turn with **zero router model starts**,
native input/tool/output/final events editing an existing bubble, repeated
completion coalescing, stale/foreign exclusion and all three bad-receipt forms.
Formatter checks cover bounds, Unicode, malformed optional fields, redaction
and private attachment/tool metadata. The extended local suite passed 284 checks.
Fixtures do not establish that a phone client reaches this exact app-server.

`MediaProbe --steer` adds one finite actual-native acceptance test. It starts one
generated-image turn, then supplies a random value only through `turn/steer`.
Success requires an exact receipt, one `turn/started` event, correct private image
truth and that exact steering value in final structured output. Tools, an ended
turn, ambiguity or a deadline stop the diagnostic without starting a replacement
turn. `--observe-only` is mutually exclusive. It keeps the same protected claim,
ledger, quota guard and medium-owner launcher; no live router database or polling
is used. This is not authenticated Telegram-owner or phone round-trip acceptance.

Actual Windows release acceptance passed 287 checks before and after copying,
plus the diagnostic dependency run. The installed router DLL SHA-256 is
`A7F98406A09C52ADB92000BA5CAA0EFDD53E79735938A797B6713E796E1FE646`.
The fresh identity, credential/code denial, read-only attachment ACL, native
sandbox and goal-read proof passed at `2026-10-03T13:13:44.6488897Z` without a
model turn or polling. Activation resumed the exact LG thread/bubble 161 and
restored startup supervision. The previous release remains in
`release-8e082f06caf94458ac7f9cc937b8586b/previous-bin`.

The real steering diagnostic passed at `2026-10-03T13:16:49.731147Z`, run
`7804f93aac3e4ed4b3dc7ea12d6e209a`, native thread
`01a101e8-d5c0-7520-8e88-bfb33b3629cc`. One native turn accepted and consumed the
random steering value; the image answer matched private truth `blue, cyan,
green`. Telegram upload/download bytes matched SHA-256
`73145CE804E24D1F3C3B445502C39555016C6F611EA1BA138929A4DFD71094C9`.
No native tool or unknown operation was observed; the confirmed generated bot
message was removed, with its bytes/claims/receipts retained. The diagnostic task
finished with result 0, and its native PID 10112 was independently confirmed gone.
Included usage was allowed at rounded 29% before/after, not zero-cost or global
admission/reserve proof.

Fresh observation at `2026-10-03T13:18:41.4129076Z` confirms live native PID 13532,
idle/unheld bubble 161, zero unknown operations, unchanged main turn/start (4),
sendMessage (2) and created-topic (1) receipts. Native remote PIDs 5420/9188 and
all VPN/LG services remained running. Hamal and Mac wiring are unchanged. These
joined-fixture and isolated-native results do **not** prove real authenticated
owner steering through Telegram, phone-client attachment to the exact app-server,
employee/company isolation, goal-continuation admission or clean restore.

## Same-process phone transport diagnostics (2026-10-03)

The adapter now reads `remoteControl/status/read` from its own private native
app-server at startup and through owner-only `/remote`. The control amends the
existing bubble, remains outside the session dispatch lock, and never enables,
pairs, resumes, starts inference or changes a remote endpoint. It records the
native PID, observation time and hashed installation/environment identities;
host names, pairing tokens and unknown reply fields are not mirrored. Native
account updates invalidate the view; revision guards prevent delayed reads from
overwriting newer notifications. Read failures/cancellation do not turn a
diagnostic into an uncertain action or a replay. This is **diagnosis/visibility,
not a continuity fix**. A separate process's saved connected status is not
evidence that a phone reaches this router's active thread.

The deployment probe also reads exact stored thread metadata without resuming
it, then compares default source listing with explicit `appServer` listing.
Each listing uses `useStateDbOnly: true`, a 100-item page limit and at most two
pages; exhausted absence differs from a truncated search. It never changes the
thread's source to make it visible, mirrors history, or repairs metadata from
rollouts. Native source defaults and read-versus-resume semantics follow the
[official app-server contract](https://learn.chatgpt.com/docs/app-server).
Current [Remote setup guidance](https://learn.chatgpt.com/docs/remote-connections)
still requires the supported host/device/account pairing flow; an experimental
CLI/RPC connected observation alone does not prove that mobile setup is complete.

339 local and 342 actual Windows checks pass, including target candidate and
installed-binary validation. Added fixtures cover status typing, private metadata,
account/status races, failed/canceled reads without retry, wrong thread/workspace,
bounded pagination, default-versus-explicit source filters, foreign owner denial
and same-bubble command/menu integration. Real phone input/event continuity and
all-source admission remain acceptance gates. Existing native remotes must not
be restarted merely to make a diagnostic pass.

The actual PC probe at `2026-10-03T13:42:01.7168311Z` passed the existing native
identity, OS credential/code denial, offline sandbox, read-only attachment and
goal-read checks. Diagnostic native PID 14224 reported Remote Control **disabled**.
The exact LG thread's stored source is **`vscode`**, present in an exhausted
one-page default listing and absent from an exhausted explicit `appServer`
listing. This rules out the proposed default-source filter explanation for this
thread; no source/identity was changed to conceal the result. The transport gap
remains: the router's private app-server is not the separately running native
remote host. Enabling another endpoint, sharing history, or a connected status
alone would not establish one live owner/subscription, phone pairing or pre-turn
admission. The next continuity gate needs that real shared-host path and a
phone-to-existing-bubble test, not a filter workaround.

The candidate archive SHA-256 is
`E5AD5EBBE3D586FBEAD0550DD31F16CEB9B8ABD1B1F9DB7979D766182502ACF4`,
installed DLL
`AD0D4E1C3B0AAA267B1D31BF89A82B3008B9D54197911BD996E682B95E1F0E14`.
The protected policy is unchanged; rollback binaries remain in
`release-024efc8196454d4d84aed311b946a88a/previous-bin`. Neither the probe nor
visibility/status reads submitted a model turn, polled Telegram, enabled or
paired a remote endpoint, or resumed the diagnostic thread.

Fresh live status at `2026-10-03T13:44:57.5873586Z` identifies owner-session native
PID 4576 with the same LG binding, zero unknown operations and unchanged durable
model-start (4), sent-message (2), topic (1) and bubble 161 receipts. The current
remote view is **unavailable**, not a current disabled/connected assertion derived
from the earlier probe. `/remote` asks for a new same-process read. Startup
supervision was restored at `2026-10-03T13:45:34.8532400Z`; no extra endpoint,
pairing or inference was enabled. These distinctions deliberately prevent
historical/other-process status from being presented as live phone acceptance.

## Actual Windows shared-transport primitive (2026-10-03)

`pc-router/NativeSharingProbe` now verifies the missing multi-client local
transport against the pinned PC CLI, without changing production. The actual
0.160.0 `app-server --help` advertises capability-token authentication and
`--ws-token-sha256`; the [official transport contract](https://learn.chatgpt.com/docs/app-server)
specifies bearer authentication before JSON-RPC initialization. WebSocket
transport is **experimental and unsupported**, so this is a release-specific
adapter candidate, not a generally supported daemon or a production guarantee.

The one-shot task runs as the exact non-elevated `pou` in Session 1. It starts
only its own pinned native executable, with an empty child-only native home and
file-only credential storage; no production credentials/configuration/history
are copied. Inherited provider/token variables are removed. A random 256-bit
bearer stays in memory; only its SHA256 verifier reaches native argv. The
listener is explicitly loopback-only, with no firewall/public listener change.
Fixed read-only readiness polls do not retry initialization or native effects.

At `2026-10-03T14:06:02.3409292Z`, run
`d2284fb1efca48a3acf9ebabd12192ad` passed: missing and wrong bearer connections
were rejected with HTTP 401/403, two authenticated clients initialized against
one owned native process, and both returned the same hashed installation
identity. Both account reads returned null, Remote Control was disabled, and
loaded-thread lists were empty. There was no thread creation/resume, model turn,
tool command, enrollment, phone pairing or Telegram activity. Only the probe's
owned native PID 8384 was terminated after the test; its result/claim and native
home/private diagnostics remain under `.native-remote/sharing-probe-<run>` for
recovery. Nine method-whitelist guards pass locally and on Windows.

Independent readback at `2026-10-03T14:08:01.3136739Z` confirms PID 8384 is gone;
main native 4576 and existing remotes 5420/9188 retain their original creation
times. Khadang, all VPN services and LG remain running. Code/policy digests,
exact LG binding/bubble 161 and existing turn/start (4), sendMessage (2), topic
(1), resume and tool receipts remain unchanged; unknown is zero. The diagnostic
task is Interactive/Limited, Ready/result 0, with no restart policy or triggers.
The installer rejects a prior run before task/native effects; the actual check
at `2026-10-03T14:09:23.1391341Z` confirms an unchanged result digest, no triggers
or restart policy, and the diagnostic native PID still absent. Source and
runtime artifacts are sealed administrator-owned before
execution; this does not establish company-role isolation.

The live gap remains structural: both existing app-servers have private stdio,
and cannot acquire a shared local listener through a demonstrated live RPC.
Neither borrowing pipe handles nor tailing shared history is a continuity fix.
Next, implement a **reviewed** shared native owner connection and event
subscription while preserving the exact LG thread and existing remotes. Changes
to listener credentials/authentication, enrollment or deployment policy require
the protected owner/security review, not clearance inferred from this test.
Pairing secrets must never enter employee-accessible forum bubbles; use a
verified owner-private/native pairing surface. Phone input/output/tools/goals
in the existing bubble, ambiguous-effect recovery and all-source admission
remain unpassed gates. This test does not complete PR 6 or the full PC goal.

## Shared framing and native goal-event acceptance (2026-10-03)

`NativeRpc` now has a transport-independent framing boundary while preserving
its durable request receipts, explicit rejection handling and no-replay behavior.
The existing protected owner launcher still selects owned stdio; neither
`Program.cs` nor the live policy selects WebSocket. The candidate
`WebSocketNativeChannel` wraps an already-connected socket, bounds complete
UTF-8 text frames to 2,097,152 bytes, and translates transport failures into the
existing disconnected/unknown semantics. It never discovers, connects, enrolls,
reconnects or restarts a server. Closing a shared channel closes only that client
socket, not an external native process. A supplied PID is observation metadata,
not authentication or a role grant.

353 local and 356 actual Windows candidate router checks pass; fourteen new
checks cover fragmented Unicode, binary/invalid/oversized frames, close,
oversized outgoing refusal, notifications, confirmed/rejected/unknown effects
and denial of submission after disconnect. Twenty probe guards allow only the
fixed diagnostic methods and refuse turns, tools, login and remote enrollment.
These counts are **candidate** evidence; the installed live router stays at the
previous immutable release and its existing 342-check acceptance record.

The actual Windows `--events` test passed at
`2026-10-03T14:29:11.5212078Z`, run
`ac09f1fbb79b49738ae67e0c9a09db40`, using that candidate RPC/framing code.
It first repeated both explicit bearer denials and credential-free status
checks. Client A then created one diagnostic thread and an inert history
checkpoint in the empty child home; client B resumed the exact thread without
configuration overrides and subscribed to its events. A set a randomized goal
**paused**, then cleared it. B received both exact-thread native notifications
and verified both states by independent goal reads. No active goal, inference,
tool command, remote enrollment or Telegram action was submitted; zero turn
starts were observed during goal testing and both diagnostic ledgers have zero
unknown effects. The thread/checkpoint, ledgers/claims and native home remain
as recovery evidence; only the owned diagnostic process was terminated.
[Native goal and subscription contract](https://learn.chatgpt.com/docs/app-server).

Candidate archive SHA256:
`799CD6031482963861BDF168EC2809C6BE2F5091F81DD616881F09C66B22AAF9`;
candidate router DLL
`2B92C6703A1429C36581626677B61078C2FFE759CF5F923E83EC67E742C08F56`;
probe DLL
`2662976E8AB55C29558441FC2CBF73BF89CC3A9EB8BFCB30C46746461BCD672A`;
installer
`E4698399432AD6869C3B4DA99095373F4ACCFDF631872D77582972D0C03F4D05`.
The versioned installer preserves the previous test installer/artifacts.

Final cleanup retains the original disposal guarantee: even if a channel's
disposal fails, the reader is joined before resources are released. The final
source was rebuilt and passed all 353 local/356 Windows checks plus twenty
probe guards. Its cross-client goal-event test passed again at
`2026-10-03T14:41:03.812399Z`, run
`a096ac28cc4c46b9bdcbfb6487455bd3`, with both events/readbacks, paused-only goal,
zero model turns/unknown effects and its owned native process exited.
The earlier successful run/artifacts above are retained, not replayed.
Final archive SHA256
`308214C6EC508E8448D919511BAC906CF6FAFEA98A3DAA228D6330E455AB8180`;
candidate router DLL
`BDE16BE183B98D37F522F339FE792CA9318E3B735FF3C27D041E39BFB1CED0F0`;
probe DLL
`F5D9267841C911A4E7A76298037FD53A2EE733FCB2AA5E266A7A9FB5D0D42928`.
The same versioned installer above is used. This final candidate is not live.
Fresh readbacks at `2026-10-03T14:42:37.2305086Z` and
`2026-10-03T14:43:39.1612745Z` confirm matching final DLL digests, PID 17132
absent, unchanged live code/policy/PIDs/bubble/receipts, and all VPN/LG running.

Independent readback at `2026-10-03T14:31:29.5072234Z` confirms diagnostic PID
11740 is gone; the task is Ready/result 0, Interactive/Limited with no triggers
or restart policy. Main native 4576 and remotes 5420/9188 retain their original
creation times. All VPN/LG services are running; live code/policy digests,
LG binding, bubble 161, tool/resume/model/send/topic receipts and zero unknown
operations are unchanged. The candidate was not copied into the live service.

**Do not promote bearer acceptance into server authentication.** Client bearer
authentication and loopback placement do not establish a trusted upstream peer
under the prompt-injection threat model. The framing class deliberately cannot
authorize a native peer/role from a claimed PID or socket. A live shared adapter
still needs a protected, authenticated server/launcher lease and independent
daemon ownership so a router deployment does not terminate phone work. An
owned-stdio broker with a separately authenticated protected client endpoint is
a candidate way to preserve the existing native process boundary; it is not
implemented or approved here. Raw loopback sockets are not the company boundary.
Any listener/credential/deployment change requires protected exact-version
owner/security review. Existing remote processes must not be killed/restarted
for migration; supported private/native phone pairing and phone-to-bubble
tool/input/goal acceptance, recovery and all-source admission remain gates.
This is a working framing/event component, not the full continuity fix or PR 6
completion.

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
