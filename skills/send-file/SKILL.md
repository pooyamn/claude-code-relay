---
name: send-file
description: For a RELAY-BOUND Claude Code TUI session only — send a specific file (or files) from this session to the user over Telegram via the OpenClaw gateway, always zipped (OpenClaw/Telegram block many types: .hex, .exe, .sh, binaries). Use when the user asks you to send, share, give, deliver, or "shoot me" a named file/log/report/artifact. NOT for OpenClaw agent sessions — the script refuses there so it can't deliver to the wrong chat; an OpenClaw agent should use its own native media send instead.
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
- **Send exactly what the user named.** Pass the specific file(s) they asked for. Do
  NOT pass a whole folder (or the file's parent directory) unless the user explicitly
  asks to send a folder/directory — otherwise you'll zip and ship every file in it.
- **Always zip**, even a single already-compressed or plain file — that is the whole
  point (deliverability), and it is what the user asked for.
- **Relay-bound sessions only.** The destination is resolved from the tmux session
  name (`$TMUX` must be set) → `~/.openclaw/workspace/scripts/relay-work/target-<session>.json`.
  Run from anywhere else (e.g. an OpenClaw agent session) the script **refuses**
  (exit 3) rather than guess — that prevents delivering to the wrong bound chat. If you
  hit that refusal as an OpenClaw agent, use your own native media send instead.
- On any error (missing file, send failure, refusal), report it plainly and do not
  blindly retry.
- For multiple files it makes one combined zip; for a folder it preserves structure.
