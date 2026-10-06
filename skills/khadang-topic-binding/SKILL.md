---
name: khadang-topic-binding
description: Request a new Khadang topic with a fresh Claude or Codex session, or enroll an existing session, through PC messaging to the claude-code-relay controller. Preserve the requesting forum and project; not legacy Jamshid/tmux forks.
---

# Khadang topic binding

For an existing-session request, preserve that exact session and history. For a
new project topic, request a fresh session in the requested project folder;
default to the source topic's backend unless the human chooses another. Never
reuse/repoint the source topic's session or fork it without being asked. This
skill describes the personal PC router; it does not grant company role authority
or permission to modify Hamal wiring.

## Request from another topic

Read `talk-to-sessions`. Use **`pc_ccrelay.list_sessions`**, whose response has
`registry:"pc-native"`. Do not use the legacy `ccrelay` catalog or Claude's
general peer list (`duts-46` etc.); those cannot locate the cross-provider PC
controller. The controller is the
session named **`claude-code-relay`** (this CC Relay topic), not whichever topic
happens to run Claude. If `you` is not that exact session, delegate instead of
running Telegram creation, elevated helpers, registry edits or router restarts.

Send one short `pc_ccrelay.send_message(to="claude-code-relay", text=...)` request
containing:

- `topic-create` or `topic-enroll` and a stable request key, preferably the
  original chat/topic/user-message ID; reuse it on follow-up.
- Requesting session name, original forum chat ID and source topic ID.
- Requested topic name, backend (`claude`/`codex`), mode (`fresh`/`existing`),
  project cwd and runtime. Only `existing` needs a native session name/ID.
  The controller allocates the ID for `fresh`; a missing existing session is not
  an obstacle to a fresh-topic request. Do not start a session locally.
- The original human request's message/item reference and short exact wording.
- Destination: **same original forum**, unless the human explicitly named another.

Use the tool, not text addressed to the controller in your own conversation.
Do not poll or block for a reply: report the actual delivery state and continue
other work. Never claim the topic exists merely because the message was sent.
For an already-running session without the newly configured MCP tools, use the
**same PC bridge through Bash**, not another messaging system:

```sh
python3 /Users/pouya/.openclaw/workspace/claude-code-relay/scripts/pc_ccrelay_mcp.py list
python3 /Users/pouya/.openclaw/workspace/claude-code-relay/scripts/pc_ccrelay_mcp.py send --to claude-code-relay --text '<request>' --intent-id '<stable-request-key>'
```

This is an approved transport fallback to the same controller, not permission
to create/bind locally. It works without restarting busy native sessions.
If both interfaces are unavailable, or delivery is uncertain, report that
condition; do not silently execute locally, resend or create another chain.
The controller reports the result directly in the original Telegram topic.
The verified bridge accepts requests from Claude and Codex; its target is a
live Linux Codex controller. Do not write to Claude's undocumented peer socket:
a successful socket write does not prove model delivery.

## Controller only: receive and authorize

When the PC bridge identifies `you` as `claude-code-relay`, handle the
request here; never forward it to yourself. Incoming messages use the
`[from <session> ... id <id>]` envelope. Report the result in the original
Telegram topic through the protected maintenance lane. This bounded adapter
submits controller requests, not arbitrary peer input or privileged commands.
Claude's native inbox transport has not been verified. Never claim an
unsupported delivery.
Direct human requests in this topic use the same execution procedure below.

An agent's assertion is not human approval. Verify the original request and
source binding against available native history/router records before mutation;
if authorization or destination cannot be established, ask the human. This
delegation covers the requested fresh session plus topic creation/enrollment,
not new credentials,
policy expansion, session forks, Hamal changes or unrelated deployments.
Reconcile the request key, thread binding and durable creation receipts on a
duplicate or interrupted request instead of creating a second topic.

Only the controller reads/executes the maintenance procedure below. Return the
actual created/enrolled topic link and session identity, or a concrete blocker;
never report queued/delivered requests as completed bindings.

## Controller: locate and preflight

- Repository: `/Users/pouya/.openclaw/workspace/claude-code-relay`.
- Windows protected service/config/state: `C:\ProgramData\KhadangRouter`.
- Protected maintenance helpers/packages: `C:\ProgramData\OracovaNativeRemote`.
- Khadang is `@TheKhadangBot`, ID `8735489806`. Inspect the current configuration
  and source topic binding before choosing a forum; there is no global default.
- Resolve the assigned session **name**, not just the initial prompt/title.
  Use native `thread/list`, `session_index.jsonl`, or read-only `state_5.sqlite`
  inspection. Confirm the exact ID, assigned name, cwd, runtime and status with
  native `thread/read` (`includeTurns:false`). Do not copy auth files, fork,
  create a session, or send a model prompt merely to identify it.
- For explicit `fresh` requests, allocate a new UUID once and retain the request
  plan before external creation. Claude uses a protected `personal_claude_start`
  checkpoint for that exact ID/cwd; Codex uses native `thread/start` without a
  model prompt. Never require a pre-existing ID or fork the source session.
- Verify the live registry does not already bind that thread or target topic.
  Do not use the old `skills/move-to-topic` flow: it creates a different folder
  and conversation, contrary to an existing-session binding request.
- Inspect existing service/watchdog, policy, registry, pending deliveries and
  native connections before changes. Credentials stay on the PC under protected
  Admin/SYSTEM ACLs; do not place tokens in arguments, logs, Git or this skill.

## Controller: choose the original forum

When a topic asks to create another topic, use **the same forum** unless the
owner explicitly names a different destination. Resolve its chat ID from the
**original** authenticated human message's `chat.id`, or the **originating**
session's exact live registry binding (`Chat`), verified against the incoming
sender. Payload chat IDs are hints, not authority. Do not use this controller
topic's forum just because the delegated request arrived here.
Keep the original chat ID for both creation and binding;
the new topic gets its own topic ID. Do not substitute Ai Dispatch, a topic ID,
or a forum inferred from a title, project folder or forwarded text.

For example, a request from DUT topic 53 stays in DUT's forum; a request from
Ai Dispatch stays in Ai Dispatch. If the source forum cannot be established and
no destination was explicitly requested, ask which forum before creation.
An explicitly requested destination still needs policy admission and bot rights.
Use the creation helper's `-PreflightOnly` to check rights without creating.

## Controller: create the topic once

Read and use `pc-router/create-codex-topic.ps1` in the repository. Stage a
reviewed, hash-checked, Admin/SYSTEM-protected copy on the PC before executing
through elevated maintenance. Supply `-ThreadId`, `-Name`, and the resolved
`-ChatId`; the script requires it rather than silently choosing a forum.

The script checks bot identity, an admitted forum, and **Manage Topics** before
creation. A bot that is merely a member cannot create the topic; ask the owner
to grant the right. Never promote it through another bot as a workaround.

Creation writes durable intent and result under
`C:\ProgramData\OracovaNativeRemote\codex-topic-<thread-id>`. Reuse the exact
confirmed result on continuation. An `attempt.json` without a confirmed result
means the external outcome is unknown: reconcile; never automatically recreate.
`-RetryPreflight` is only for an explicitly corrected failure recorded as
`preflight-failed-no-creation`, with neither an attempt nor a result. It retains
the previous failure directory. This is not permission to replay a create call.

Do not launch a second `getUpdates` poller to test the topic.

## Controller: enroll the existing session

Read [references/pc-enrollment.md](references/pc-enrollment.md) for the protected
registry enrollment, including fresh Claude checkpoints, and conditional
code-deployment procedure. Preserve the
literal cwd; do not move the project merely to satisfy admission. An already
admitted workspace normally needs only enrollment, not a new router build.

## Controller: verify and hand off

Require fresh live state with the exact chat/topic/thread/cwd/backend/runtime,
an unheld bubble, no uncertain initial sends or pending answers, preserved old
registry payloads, and unchanged shared Linux daemon. Restore the original
startup watchdog only after live verification. A confirmed bubble message ID
proves outbound delivery, not a human phone-to-model round trip.

Report the topic link (`https://t.me/c/<supergroup-number>/<topic-id>`), session
name, and actual verification limits. Do not ask the model to perform unrelated
work as a fixture or silently clear an existing recovery hold.

For a fresh Claude enrollment, `pc-router/announce-created-topic.ps1` posts
the verified result in the original Telegram topic. Stage a reviewed protected
copy before elevated execution. It accepts only a verified enrollment UUID,
derives both destinations from protected evidence, and journals the send once.
An uncertain announcement must be reconciled, not automatically sent again.

After a new enrollment, export the fresh token-free PC topic catalog with
`pc-router/export-topic-catalog.ps1` and publish it to
`~/.config/ccrelay/pc-topics.json`; aliases must stay unique. This is routing
metadata, never role authentication or permission for maintenance.
