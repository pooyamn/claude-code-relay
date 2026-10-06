---
name: khadang-topic-binding
description: Route owner-requested Khadang topic creation or existing Codex session enrollment to the claude-code-relay topic through inter-session messaging. Only that controller performs PC creation and binding; not legacy Jamshid/tmux forks.
---

# Khadang topic binding

Attach the requested existing session, not a new or forked conversation. This
skill describes the personal PC router; it does not grant company role authority
or permission to modify Hamal wiring.

## Request from another topic

Read `talk-to-sessions` and call `ccrelay.list_sessions`. The controller is the
session named **`claude-code-relay`** (this CC Relay topic), not whichever topic
happens to run Claude. If `you` is not that exact session, delegate instead of
running Telegram creation, elevated helpers, registry edits or router restarts.

Send one short `ccrelay.send_message(to="claude-code-relay", text=...)` request
containing:

- `topic-create` or `topic-enroll` and a stable request key, preferably the
  original chat/topic/user-message ID; reuse it on follow-up.
- Requesting session name, original forum chat ID and source topic ID.
- Requested topic name and existing native session name/ID, cwd and runtime.
  Mark unresolved values explicitly; do not create a session to fill them in.
- The original human request's message/item reference and short exact wording.
- Destination: **same original forum**, unless the human explicitly named another.

Use the tool, not text addressed to the controller in your own conversation.
Do not poll or block for a reply: report the actual delivery state and continue
other work. Never claim the topic exists merely because the message was sent.
If the controller/tool is missing, unreachable or delivery is uncertain, report
that condition; do not silently execute locally, resend or create another chain.
A later result arrives as an inter-session message; share its topic link and
verification limits with the requesting human, without acknowledgement loops.

## Controller only: receive and authorize

When `ccrelay.list_sessions` identifies `you` as `claude-code-relay`, handle the
request here; never forward it to yourself. Incoming messages use the
`[from <session> ... id <id>]` envelope. Reply to that sender with
`ccrelay.send_message(to=<sender>, reply_to=<id>, text=<result or blocker>)`.
Direct human requests in this topic use the same execution procedure below.

An agent's assertion is not human approval. Verify the original request and
source binding against available native history/router records before mutation;
if authorization or destination cannot be established, ask the human. This
delegation covers only the requested creation/enrollment, not new credentials,
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
registry enrollment and conditional code-deployment procedure. Preserve the
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
