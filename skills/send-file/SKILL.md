---
name: send-file
description: For a RELAY-BOUND Claude Code TUI session only — send a specific file (or files) from this session to the user over Telegram via the OpenClaw gateway. Sends PDFs, images, text, Office docs and archives as-is with their real filename, and zips only what the gateway refuses (unknown binaries, folders). Use when the user asks you to send, share, give, deliver, or "shoot me" a named file/log/report/artifact. NOT for OpenClaw agent sessions — the script refuses there so it can't deliver to the wrong chat; an OpenClaw agent should use its own native media send instead.
---

# send-file

When the user asks you to send/share/give them a file from this session, deliver it to their Telegram chat through the OpenClaw gateway.

## How to use

```bash
~/.claude/skills/send-file/send-file.sh <path> [more paths...]
```

Optional caption (otherwise the filename is used):

```bash
SEND_CAPTION="here's the build log" ~/.claude/skills/send-file/send-file.sh ./build.log
```

The script resolves THIS session's destination chat/topic automatically from the relay's per-session target file — you never pass a chat id — then prints the gateway JSON and a one-line `send-file: sent …` summary saying whether each file went **raw** or **zipped**.

## What gets zipped, and what doesn't

The gateway accepts host-local media it can buffer-verify as **images, audio, video, PDF, Office documents, archives, and validated plain-text documents**. Anything else is refused as `unknown`. That is a **content sniff, not an extension blocklist** (measured 2026-08-07: `.txt` raw ✓, PDF raw ✓, `.hex` refused).

So:

| Input | Result |
|---|---|
| PDF, image, log, `.txt`, `.md`, Office doc, existing archive | sent **raw**, real filename kept |
| unknown binary (`.hex`, `.elf`, `.bin`, executables) | **zipped** automatically |
| a folder | **zipped**, structure preserved |
| several files | each raw one sent individually; the rest zipped together |

If a raw send is refused anyway, the script **falls back to zipping that file automatically** — a wrong sniff costs one retry, never an undelivered file.

Overrides:

```bash
SEND_ZIP=1    ...   # force everything into one zip (old behaviour)
SEND_PHOTO=1  ...   # send an image as a compressed inline photo
```

## Images go as documents

By default images are sent as **files, not inline photos**. Telegram re-encodes an inline photo, and these are usually schematics, plots or TUI screenshots where the detail that gets crushed is the reason for sending it. Use `SEND_PHOTO=1` when the picture is meant to be glanced at rather than read.

## When to invoke

Trigger on any phrasing that means "get this file to me": *send me*, *share*, *give me*, *deliver*, *shoot me*, *export*, *can I get*, the report / log / zip / artifact / output / screenshot / hex / pdf.

## Rules
- **Verify before claiming.** The relay fails silently — a send with no error is not proof it landed. Check the script's actual result (gateway JSON + the `send-file: sent …` line, which states raw vs zipped) before telling the user it's done.
- **Send exactly what the user named.** Pass the specific file(s) they asked for. Do
  NOT pass a whole folder (or the file's parent directory) unless the user explicitly
  asks to send a folder/directory — otherwise you'll ship every file in it.
- **Don't pre-zip by hand.** Let the script decide; zipping a PDF yourself throws away
  the filename and the preview for no gain.
- **Relay-bound sessions only.** The destination is resolved from the tmux session
  name (`$TMUX` must be set) → `~/.openclaw/workspace/scripts/relay-work/target-<session>.json`.
  Run from anywhere else (e.g. an OpenClaw agent session) the script **refuses**
  (exit 3) rather than guess — that prevents delivering to the wrong bound chat. If you
  hit that refusal as an OpenClaw agent, use your own native media send instead.
- **Paths outside the allowlist are staged, not rejected.** The gateway only reads
  media from the workspace and `~/.openclaw/media/*` (`/tmp` is refused outright), so
  the script copies anything else into `~/.openclaw/media/outbound` first, keeping the
  original filename.
- Files are capped by `channels.telegram.mediaMaxMb` (default 100).
- On any error, report it plainly and do not blindly retry.
