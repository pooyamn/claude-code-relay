# Relay session rules

You may be running inside a **relay-bound session**: a tmux session named `cr-<hash>`
whose output is scraped and forwarded to the user over Telegram. Two consequences.

## Sending files

The user cannot see your working directory. To actually deliver a file to them, run:

```bash
~/.claude/skills/send-file/send-file.sh <path> [more paths...]
```

Optional caption: `SEND_CAPTION="here's the log" ~/.claude/skills/send-file/send-file.sh ./build.log`

The script resolves this session's destination chat itself — never pass a chat id. It
sends PDFs, images, logs, Office docs and archives as-is with their real filename, and
zips only what the gateway refuses (unknown binaries, folders). Images go as documents
so Telegram does not re-encode them; `SEND_PHOTO=1` opts into an inline preview.

**Writing a file to disk is not delivering it.** Saying "saved to ./report.pdf" gives
the user nothing — they have no filesystem access. If you produced something for them,
run the script and report the result it prints.

If it refuses with "not inside a relay-bound Claude Code session", you are not in a
relay session; say so rather than retrying.

## Replies are scraped text

Your answer is read off the terminal and re-sent as a Telegram message. Markdown tables
are converted to native Telegram tables, so prefer a markdown table over ASCII/box
drawing when presenting tabular data.
