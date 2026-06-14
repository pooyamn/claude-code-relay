#!/usr/bin/env python3
"""Extract ONLY the current user message from OpenClaw's composed agent prompt.

OpenClaw hands a cli backend a full agent prompt: untrusted metadata JSON
block(s), a "Conversation context (untrusted ...)" history block, then a
"Current message:" section with the latest turn. For a raw Claude-Code relay we
want just the user's actual text, since Claude Code keeps its own history.

Reads stdin, prints the stripped message to stdout. Falls back to the original
text untouched if the expected markers aren't found, so it can never blank a
legitimate message.
"""
import sys, re

raw = sys.stdin.read()
text = raw

# 1) Prefer everything after the LAST "Current message:" marker.
m = list(re.finditer(r'(?im)^[ \t]*Current message:[ \t]*$', text))
if m:
    text = text[m[-1].end():]
else:
    # No structured prompt — maybe just the simple inbound envelope. Strip it.
    text = re.sub(
        r'\A\[(?:Telegram|WhatsApp|Signal|Discord|Slack)[^\]]*\]\s*[^:(\n]*\([0-9]+\):\s*',
        '', text)

# 2) Drop a leading "[Replying to: \"...\"]" block (may span lines, ends with "]).
text = re.sub(r'\A\s*\[Replying to:.*?"\]\s*', '', text, flags=re.S)

# 3) Drop a leading "#1234 Sender Name (110123423): " conversation-line prefix.
text = re.sub(r'\A\s*#?\d*\s*[^:\n(]*\(\d+\):\s*', '', text)

# 4) Drop any leading metadata/json fences that slipped through.
text = re.sub(r'\A\s*```[a-zA-Z]*\s*', '', text)

out = text.strip()
# Safety: if stripping nuked everything, fall back to the raw input.
sys.stdout.write(out if out else raw.strip())
