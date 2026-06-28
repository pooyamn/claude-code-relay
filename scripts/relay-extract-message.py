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

import os

INBOUND_DIR = os.path.expanduser("~/.openclaw/media/inbound")


def _hsize(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{int(n)}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


def _link(name):
    """A compact on-disk pointer for an inbound file (already saved by OpenClaw),
    so Claude opens it on demand instead of having content/descriptions inlined."""
    p = os.path.join(INBOUND_DIR, os.path.basename(name))
    try:
        return f"\U0001F4CE {p} ({_hsize(os.path.getsize(p))})"
    except OSError:
        return f"\U0001F4CE {p}"


def rewrite_media(t):
    """Replace OpenClaw's bulky media payloads -- inlined document bodies and vision
    'Description:' blocks -- with a one-line link to the file saved under
    media/inbound. Keeps the prompt small (a 177KB hex no longer floods context)
    and hands Claude a path it can Read. No-op on plain text messages."""
    if "media://inbound/" not in t and "<file name=" not in t:
        return t
    t = re.sub(r'<file name="([^"]+)"[^>]*>.*?</file>',
               lambda m: _link(m.group(1)), t, flags=re.S)
    t = re.sub(r'\[media attached:\s*media://inbound/(\S+?)\s*\([^)]*\)\]',
               lambda m: _link(m.group(1)), t)
    # Drop the vision description block (link replaces it), the send-back
    # boilerplate, bare media markers, and the transient /tmp image path.
    t = re.sub(r'(?ms)^Description:[ \t]*\n.*?(?=\n*/tmp/openclaw/|\n*\[media attached|\Z)',
               '', t)
    t = re.sub(r'(?im)^To send an image back,.*$', '', t)
    t = re.sub(r'(?im)^\[Image\][ \t]*$', '', t)
    t = re.sub(r'(?im)^<media:(?:image|document)>[ \t]*$', '', t)
    t = re.sub(r'(?im)^/tmp/openclaw/\S+[ \t]*$', '', t)
    # Dedupe identical link lines: the [media attached:] header and the <file>
    # block resolve to the same saved file.
    seen, kept = set(), []
    for ln in t.split("\n"):
        if ln.startswith("\U0001F4CE"):
            if ln in seen:
                continue
            seen.add(ln)
        kept.append(ln)
    t = re.sub(r'\n{3,}', '\n\n', "\n".join(kept))
    return t.strip()


sys.stdout.write(rewrite_media(msg if msg else raw.strip()))
