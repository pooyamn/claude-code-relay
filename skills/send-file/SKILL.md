---
name: send-file
description: Send project files over Telegram in relay sessions using explicit attachment markers, not a general file uploader.
---

Nothing to run. Write `📎 /absolute/path` on its own line in your final reply,
outside a code block, one line per existing file. Native Windows sessions use
`📎 C:\Users\pou\workspaces\project\file.zip` instead.

On PC Khadang, the file must be inside this topic's exact bound project folder,
not a credential directory or arbitrary home file. Linux symlinks/hardlinks and
Windows reparse paths are refused. The router reads as the ordinary owner,
with a 20 MiB per-file limit and 16 files per final.
PNG/JPEG files upload as inline photos; other formats upload as documents.
Zip folders first. Markdown file links alone do not request an upload.

The marker requests delivery; it is not proof of receipt. Do not claim Telegram
received a file without a confirmed upload receipt. The router reports known
failures; an ambiguous timeout is held rather than resent automatically.
