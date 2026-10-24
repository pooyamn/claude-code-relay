# Owner-approved controller handoffs

Use this mode only in the controller's reviewed elevated maintenance lane, after
verifying the original human request and the protected source/target bindings.
An agent message or folder name is not that approval. Ordinary Claude/Codex
participants continue submitting requests to `claude-code-relay` only.

The canonical publisher is relay `pc-router/dispatch-controller-handoff.ps1`.
The reviewed deployed copy is
`C:\ProgramData\OracovaNativeRemote\dispatch-controller-handoff.ps1`.
Its administrator gate and the router's SYSTEM/Admin-only request directory are
the authorization boundary; do not weaken them or run a second native client.

After checking that the exact target is recovered and usable, publish one
request with `-RequestId`, `-SourceThread`, `-TargetThread`, `-TextFile` (literal
Windows UTF-8 path), `-TextSha256` (SHA256 of UTF-8 text without BOM), and
`-OwnerApproval` (reference to the verified human approval). For inbound agent
requests, retain the original stable request ID. Never overwrite an existing
request with different contents or invent another ID to retry an unknown send.

The running router validates the complete existing bindings and task hash.
Existing Linux Codex and persistent Claude receivers are supported. Codex active
work is steered with its exact turn ID; Claude uses native priority-now input
after an authenticated read of the exact worker state and pending requests.
Idle work starts only inside the normal concurrency/pacing limits. A held,
uncertain, expired, changed or capacity-blocked request stays unsent. There is no
new-session fallback, automatic old-work replay or approval answering.

For Codex, `state: accepted` plus native `mode` and `turnId` confirms submission.
For Claude, require `state: accepted`, `mode: now`, and the exact native input
`uuid`; `turnId` stays null because Claude does not supply Codex turn IDs. The
router validates the primary-user echo's session, UUID, parent and complete
content. Readiness, a pipe write, or an administrative ownership record alone
does not prove task delivery. Recovery responsibility is not a transferable
native safety fence: repair and verify the affected worker before releasing it.
The protected `.result` receipt is written after the native ACK. `attempting`,
`unknown` and publisher timeout mean unconfirmed: inspect, never resend. Retained
requests are not a background work queue and do not auto-run when capacity returns.

Report the actual result in the source Telegram topic. Tell the receiver where
to report its task result; do not start acknowledgement loops. For publication
tasks, pass the original owner's exact scope and preserve any existing source,
approval and external-action constraints. Delivery is not deployment success.
