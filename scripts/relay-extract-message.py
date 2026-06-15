#!/usr/bin/env python3
"""Extract ONLY the current user message from OpenClaw's composed agent prompt.

OpenClaw's composed prompt comes in a few shapes; we handle them in priority
order:

  1. An explicit "Current message:" marker (most reliable) -> text after it,
     minus a leading "[Replying to: ...]" block and "#N Sender (id):" prefix.
  2. A "Conversation context (untrusted ...)" history block with no marker ->
     the trailing text after the last "#<n>" history line.
  3. Metadata blocks only (first message) -> strip the json-fenced
     "Conversation info"/"Sender" blocks, keep the rest.
  4. Legacy "[Telegram ...] Sender (id):" envelopes.

For a raw Claude-Code relay we want just the user's latest text, since Claude
Code keeps its own history. Falls back to the original input if nothing matches,
so it can never blank a legitimate message.
"""
import sys, re

raw = sys.stdin.read()
text = raw
msg = None


def strip_prefixes(t):
    """Strip a leading '[Replying to: "..."]' block, a '#N Sender (id):'
    conversation-line prefix, and a leading code fence from one message."""
    t = re.sub(r'\A\s*\[Replying to:.*?"\]\s*', "", t, flags=re.S)
    t = re.sub(r"\A\s*#?\d*\s*[^:\n(]*\(\d+\):\s*", "", t)
    t = re.sub(r"\A\s*```[a-zA-Z]*\s*", "", t)
    return t.strip()


# 1) Explicit "Current message:" marker (authoritative when present).
m = list(re.finditer(r"(?im)^[ \t]*Current message:[ \t]*$", text))
if m:
    msg = strip_prefixes(text[m[-1].end():])

# 2) "Conversation context (untrusted ...)" -> trailing message after last "#<n>".
if not msg:
    ctx = re.search(r"(?im)^Conversation context \(untrusted[^\n]*$", text)
    if ctx:
        lines = text[ctx.end():].split("\n")
        last = -1
        for i, line in enumerate(lines):
            if re.match(r"^\s*#\d+\b", line):
                last = i
        msg = "\n".join(lines[last + 1:]).strip()

# 3) Metadata blocks but no history (first message): strip them, keep the rest.
if not msg and re.search(r"(?im)^(?:Conversation info|Sender) \(untrusted", text):
    msg = re.sub(
        r"(?im)^(?:Conversation info|Sender) \(untrusted metadata\):\s*```[a-zA-Z]*\n.*?\n```\s*",
        "", text, flags=re.S).strip()

# 4) Legacy simple envelopes.
if not msg:
    t = re.sub(
        r"\A\[(?:Telegram|WhatsApp|Signal|Discord|Slack)[^\]]*\]\s*[^:(\n]*\([0-9]+\):\s*",
        "", text)
    msg = strip_prefixes(t)

sys.stdout.write(msg if msg else raw.strip())
