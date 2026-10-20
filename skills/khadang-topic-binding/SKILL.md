---
name: khadang-topic-binding
description: Create a Khadang topic with a fresh Claude or Codex session, or enroll an existing Codex session, using the PC controller's scripted workflow. Preserve the requesting forum; not legacy Jamshid/tmux forks.
---

# Khadang topics: script first

Normal requests use one invocation, not a hand-built sequence of native RPCs,
Telegram calls, SQL, restarts and proof checks. Preserve an explicitly requested
existing session/history; new projects get fresh sessions. Default to the
requesting forum and its backend. Without an explicit folder, a new project
uses /Users/pouya/.openclaw/workspace/<topic-slug>. Never fork/repoint the source.

## Direct Telegram Codex fast path

The owner can send `/topic Motorcontrol Plant --model sol6.1` in a bound forum
topic. The running bridge handles this directly: same forum, fresh Codex session,
explicit model, owner-side folder preparation, durable checkpoint, one Telegram
creation and hot binding. No agent planning turn, SSH, service restart, or
reconnection of other sessions is needed. The exact quoted English form
`Make a new topic “Motorcontrol Plant” Using codex , sol6.1 model` also matches.
Other wording/backends continue through the controller workflow below; do not
pretend that an agent message is the owner's `/topic` command.

Healthy-path target is about 10 seconds, not a guarantee during capacity,
transport or permission failures. Report actual elapsed time/phase receipts.
Registration may perform one short ready-and-wait Codex turn, without tools,
project work, a goal or delegation. A raw injected checkpoint alone is hidden
from Codex's native list (`has_user_event=0`); readiness requires the exact ID,
name and folder to appear in native `thread/list`, not just `thread/read`.
Lost registration/creation acknowledgments must not be retried automatically.

Native allocation must run under the existing ordinary-owner Windows/WSL lane.
Elevated SSH followed by `wsl.exe -u pou` is NOT equivalent: its DrvFS context
can still open protected credentials. Keep the actual credential-denial check;
do not disable it or alter ACLs to make allocation pass.

## Other topics: one routed request

Read talk-to-sessions. Use pc_ccrelay.list_sessions (registry:pc-native) to
identify yourself and controller claude-code-relay. Send one
pc_ccrelay.send_message there with topic-create/topic-enroll, stable request key,
original human wording/message reference, source thread/chat/topic, name,
backend, project folder, fresh/existing mode, and exact ID for existing mode.
Use the original forum unless the human explicitly chose another. Agent messages
are not human approval. No privileged local execution or legacy peer network.

Already-running sessions without MCP use this same PC bridge in one invocation:

```sh
python3 /Users/pouya/.openclaw/workspace/claude-code-relay/skills/khadang-topic-binding/scripts/request_topic.py --name headfix --intent-id '<original-message-key>' --source-update '<update-id>'
```

Report actual submitted/unknown state, not topic creation from an ACK. Do not
poll, resend uncertain effects or start a new chain. The controller reports the
actual result in the originating topic.

On native Windows, run the same helper through `wsl.exe -d Ubuntu-24.04 -u pou
--exec python3` and supply `--source-thread <actual-native-ID>`; do not interpret
the retained /Users/pouya paths as Windows paths. MCP is preferred when available.

## Controller: one scripted operation

The PC catalog must identify you as claude-code-relay. Direct owner and verified
delegated requests use the existing approved elevated PC maintenance connection:

```powershell
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\ProgramData\OracovaNativeRemote\topic-automation-20261013\run-topic-request.ps1 -Name headfix -SourceUpdate 759323025 -Backend codex -Workspace /Users/pouya/.openclaw/workspace/headfix
```

These values are examples, not defaults for future requests. Settings:

- -Name: exact requested title.
- -SourceThreadId: originating native UUID; defaults to this controller.
- -SourceUpdate: original owner Telegram update; omitted resolves a matching
  owner message in the exact source forum/topic.
- -Backend auto|codex|claude: auto preserves the source backend.
- -Workspace: literal admitted Linux folder; omitted uses a new topic folder.
- -Mode fresh|existing: existing supports Codex and requires -ThreadId.
- -PreflightOnly: check request/settings/rights without allocation or creation.

Do not add passwordless SSH, store credentials, install a privilege broker, or
execute an owner-writable PowerShell script elevated to reduce tool calls.

The script preflights source/owner/proof/pending-delivery/outbox bounds BEFORE
effects, allocates/checkpoints once, creates once, enrolls, runs conditional
Claude proof phases, verifies live state, and publishes the token-free catalog.
It preserves old bindings, holds, credentials and the shared Codex daemon.
Unrelated scoped output uncertainty stays held; native/unscoped uncertainty
blocks. No project work, goals or historical replay are test fixtures.

Return ready/ready-existing with actual link/native identity. Matching existing
topics are reused. A blocked or unknown result means stop and report its retained
receipt/blocker; never recreate, clear another topic's outbox, or claim service
Running proves delivery. Only actual human activity proves a phone round trip.

## Repair or installation only

Do not reread/rebuild/stage helpers for every normal request. The sealed package
contains pc-router/run-topic-request.ps1 and helper scripts with package.json
hashes. Read [references/pc-enrollment.md](references/pc-enrollment.md) only for
a missing package, interrupted receipts, unsupported existing-Claude enrollment,
or actual code/admission change. Reconcile confirmed creation results, never
automatically replay an ambiguous attempt.

Custom skill changes use shared-skills and renew both tools' Windows mirror.
This grants no company role authority or permission to change Hamal wiring.
