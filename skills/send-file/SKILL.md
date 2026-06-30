---
name: send-file
description: Send a file, files, or a folder from this Claude Code session to the user over Telegram via the OpenClaw gateway. ALWAYS zips first because OpenClaw/Telegram block many file types (.hex, .exe, .sh, binaries). Use whenever the user asks you to send, share, give, deliver, or "shoot me" a file, log, report, artifact, build output, dataset, or any on-disk file from the session.
---

# send-file

When the user asks you to send/share/give them a file from this session, deliver it to their Telegram chat through the OpenClaw gateway. OpenClaw and Telegram silently block many raw extensions, so this skill **always zips first** — a `.zip` always gets through.

## How to use

Run the helper with one or more paths (files and/or a single folder):

```bash
~/.claude/skills/send-file/send-file.sh <path> [more paths...]
```

Optional caption (otherwise the zip name is used):

```bash
SEND_CAPTION="here's the build log" ~/.claude/skills/send-file/send-file.sh ./build.log
```

The script handles everything else:
- resolves THIS session's destination chat/topic automatically (from the relay's per-session target file — you never pass a chat id),
- zips the input(s) to a temp `.zip`,
- sends it as a document via `openclaw message send --media … --force-document`,
- prints the gateway's JSON result, then a one-line `send-file: sent …` summary.

## When to invoke

Trigger on any phrasing that means "get this file to me": *send me*, *share*, *give me*, *deliver*, *shoot me*, *export*, *can I get*, the report / log / zip / artifact / output / screenshot / hex / pdf.

## Rules
- **Always zip**, even a single already-compressed or plain file — that is the whole point (deliverability), and it is what the user asked for.
- Only works inside a **relay-bound** session; the target is resolved from `tmux` session name → `~/.openclaw/workspace/scripts/relay-work/target-<session>.json`. If the script reports "no relay target", tell the user this session isn't bound; do not guess a chat id.
- On any error (missing file, send failure), report it plainly and do not blindly retry.
- For multiple files it makes one combined zip; for a folder it preserves the folder structure.
