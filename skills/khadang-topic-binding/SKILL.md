---
name: khadang-topic-binding
description: Create a Telegram forum topic and bind an existing native Codex session to the Windows PC Khadang router, preserving its exact session ID, project folder, and history. Use for owner-requested PC topic creation or enrollment, not legacy Jamshid/tmux forks.
---

# Khadang topic binding

Attach the requested existing session, not a new or forked conversation. This
skill describes the personal PC router; it does not grant company role authority
or permission to modify Hamal wiring.

## Locate and preflight

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

## Choose the forum

When a topic asks to create another topic, use **the same forum** unless the
owner explicitly names a different destination. Resolve its chat ID from the
authenticated requesting message's `chat.id`, or the requesting session's exact
live registry binding (`Chat`). Keep that chat ID for both creation and binding;
the new topic gets its own topic ID. Do not substitute Ai Dispatch, a topic ID,
or a forum inferred from a title, project folder or forwarded text.

For example, a request from DUT topic 53 stays in DUT's forum; a request from
Ai Dispatch stays in Ai Dispatch. If the source forum cannot be established and
no destination was explicitly requested, ask which forum before creation.
An explicitly requested destination still needs policy admission and bot rights.

## Create the topic once

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

## Enroll the existing session

Read [references/pc-enrollment.md](references/pc-enrollment.md) for the protected
registry enrollment and conditional code-deployment procedure. Preserve the
literal cwd; do not move the project merely to satisfy admission. An already
admitted workspace normally needs only enrollment, not a new router build.

## Verify and hand off

Require fresh live state with the exact chat/topic/thread/cwd/backend/runtime,
an unheld bubble, no uncertain initial sends or pending answers, preserved old
registry payloads, and unchanged shared Linux daemon. Restore the original
startup watchdog only after live verification. A confirmed bubble message ID
proves outbound delivery, not a human phone-to-model round trip.

Report the topic link (`https://t.me/c/<supergroup-number>/<topic-id>`), session
name, and actual verification limits. Do not ask the model to perform unrelated
work as a fixture or silently clear an existing recovery hold.
