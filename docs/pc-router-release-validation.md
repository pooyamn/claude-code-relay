# PC router release validation

Every push (including tags), pull request, published release and manual workflow
run executes `.github/workflows/pc-router-release-validation.yml`. Both Windows
and Linux publish their own self-contained artifact using the pinned SDK, then
run `pc-router/validate-release.ps1` against that executable. A failed publish,
missing regression suite, failed check or changed assembly fails the job.

The upload-timeout integration regression drives the real router through:

1. Confirmed incoming input and native completion producing an outgoing ZIP.
2. A Telegram upload timeout after durable outgoing-file intent is persisted.
3. Continued input and steering in unaffected Codex and Claude topics, including
   a different topic in the same forum and the same topic number in another forum.
4. Retaining affected-topic input without native dispatch.
5. Reopening SQLite and restarting the observer: the original upload remains
   unknown, active unrelated work reattaches to the exact turn, and no upload or
   native input is replayed.

The named fast suite is `--self-test-input-isolation`; it is also mandatory
inside `--self-test`. Thus existing deployers that run the complete candidate
self-test before stopping production automatically include this regression.
The standard `pc-router/deploy.ps1` explicitly runs the shared release gate
before stopping the service and again on the installed artifact before startup.
Historical one-off deployers running only a focused suite are not reusable
release gates: run `validate-release.ps1` on the actual candidate before any
maintenance fence or service stop. Preserve the independent Claude host and
native agents during routine router deployment.

## Unlimited output and large-backlog recovery

`--self-test-output-recovery` restores/drains 300 saved answers in the same day,
ignores exhausted legacy daily-budget records, clears stale rate-limited flags,
and verifies restart/uncertain-send deduplication and known 429 recovery. The old
`--self-test-daily-output` CLI spelling remains an alias for maintenance tooling,
not a daily limit. The complete self-test runs these checks on every release.
The application daily cap was removed at the owner's request on October 18
Pacific; native work and output no longer wait until midnight. Telegram's own
retry_after limits still apply, and ambiguous sends are never retried.

There is no queue-length recovery cap. Individual saved records still undergo
validation, and genuinely uncertain sends remain non-replayable. The offline
`--validate-outbox` mode accepts a `{binding,bubble}` JSON envelope on stdin and
validates the complete saved outbox without opening production state or native
sessions.

Explicit owner-requested recovery may quarantine one exact uncertain Telegram
output using a protected, payload-hash-bound `owner-output-quarantine/` receipt.
The original operation remains unknown and is never resent or marked delivered.
The exact file delivery is retained in the protected recovery archive and removed
from the active outbox. This does not cover native-input uncertainty, authorize
replaying held input, or generalize to another forum, topic or workspace.

For Display's October 15 recovery, another historical ~20 MiB upload also timed
out. `recover-display-attachments.ps1` parked all 94 remaining historical unsent
attachment records in protected archive/meta, outside active automatic delivery.
Their source files remain untouched. The second uncertain receipt remains unknown
and separately quarantined; clean text continues under the daily budget. This
one-shot maintenance does not change attachment handling for new native answers.

For a Windows candidate in an isolated administrator test environment, without
production credentials (the full suite exercises real protected cache ACLs):

```powershell
dotnet publish pc-router/KhadangRouter/KhadangRouter.csproj -c Release -r win-x64 --self-contained true -o C:\Workspaces\router-candidate
./pc-router/validate-release.ps1 -CandidateDirectory C:\Workspaces\router-candidate
```

CI is validation, not deployment authority. It does not connect to production,
exercise a real Telegram round trip, run models, clear uncertain receipts or
restart services. Published-release validation reports failure; it does not
retroactively unpublish a release. Requiring the two status checks in GitHub
branch protection is a separate repository setting, not enabled by this file.

`--self-test-claude-questions` covers standalone notified question/approval text,
exact destinations, exhausted automatic quotas, stable restart nonces, confirmed
and ambiguous-send deduplication, 429 waits, cancellation, sensitive-request
redaction and removal of legacy prompts. This suite is also mandatory inside
`--self-test` on every push, PR and release; its fixtures cannot answer a real
native request or call Telegram.

## Native transport health and recovery

`--self-test-transport-health` is mandatory both as a named artifact gate and
inside the complete suite. Its inert fixtures cover a closed transport before
dispatch, disconnect after a write, open-but-unresponsive transport, restart
selection without replay, per-topic malformed-event isolation, and the actual
observer shutdown path. Run the watchdog's `-SelfTest` for its lifecycle guards.

Health is the authenticated transport's availability, not a cached PID or fresh
Telegram polling timestamp. Every five seconds the observer checks its required
Codex transports. After a minute without a successful RPC round trip it sends
only `thread/loaded/list`, a read-only probe with no model turn. A timed-out read
or closed connection requests supervised same-session reattachment. Critical
output/typing/health task failures also make the observer unhealthy rather than
leaving a service that polls indefinitely without delivering output.

The watchdog preserves its startup grace, two-observation check and maximum
three lifecycle attempts per ten minutes. It restarts the router only, never the
independent Claude host or Linux Codex daemon. Active or uncertain Windows
app-server work blocks that restart because this legacy worker is owned by the
router itself. Such a case remains visibly degraded for inspection; it is not
permission to kill native work or remove its hold.

Only a failure proven to precede both native mutation intent and transport write
is classified `retained-unsubmitted`. It cannot manufacture a permanent topic
hold or survive as a fake busy-without-turn reservation. The input remains
retained and is **not automatically replayed**. Any failure after a possible
write remains unknown/held. Malformed routed events fence their exact topic
without terminating the shared reader; diagnostics retain bounded error types
and scope, not raw model/tool content.

Deployment verification must check all bindings, same native daemon/host,
connection and background health, unchanged unknown operations, and unchanged
unrelated holds. A successful offline gate is not evidence of a phone round trip.

## Capacity refusals are not native failures

`--self-test-capacity` is required as a named artifact gate and inside the full
suite. Its 56 checks cover Claude and Codex admission, exact-topic notices,
confirmed notices, known rate refusals, uncertain notice delivery, status access
while full, restart without replay, and fresh input after capacity returns.

The configured maximum remains three active sessions. A full budget is detected
before any new native start or busy reservation and records `retained-capacity`,
not an attachment error or an uncertain native-input hold. A clean Telegram
notice explains that the input was not sent and needs to be resent when a slot
is free. It neither queues work nor automatically dispatches retained input.
Existing active work, approvals and genuinely uncertain sends remain protected.
If the notice itself has an uncertain send outcome, its original receipt remains
unknown and scoped to that topic; there is no automatic notice resend.
