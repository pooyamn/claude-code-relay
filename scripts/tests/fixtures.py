"""Real-shape fixtures captured from OpenClaw's composed cli-backend prompt
(see relay-work/backend-debug.log). The composed prompt is:

  Conversation info (untrusted metadata):
  ```json { ... } ```

  Sender (untrusted metadata):
  ```json { ... } ```

  Conversation context (untrusted, chronological, selected for current message):
  #<n> <ts> <sender>: <history line>
  ... more #<n> lines ...

  <THE ACTUAL CURRENT MESSAGE — trailing text after the history>

The relay must reduce this to just the trailing current message.
"""

INFO = '''Conversation info (untrusted metadata):
```json
{
  "chat_id": "telegram:-1003550185469:topic:816",
  "message_id": "964",
  "sender_id": "110123423",
  "topic_id": "816"
}
```

Sender (untrusted metadata):
```json
{
  "label": "Pouya M (110123423)",
  "id": "110123423"
}
```

Conversation context (untrusted, chronological, selected for current message):
#947 Sun 2026-06-14 19:02:24 PDT ->#942 Pouya M: Did you pushed last changes v
#948 Sun 2026-06-14 19:03:25 PDT ->#816 Pouya M: Live update is not working
#963 Sun 2026-06-14 19:21:25 PDT ->#957 Pouya M: The updating has stopped
'''

# (composed prompt, expected extracted current message)
CASES = [
    # 1) multi-line current message after the context block
    (INFO + "\nStill not reliable , lets write some tests ,\nso you can see whats happening.",
     "Still not reliable , lets write some tests ,\nso you can see whats happening."),

    # 2) a /cc command as the current message (the forwarding bug)
    (INFO + "\n/cc model",
     "/cc model"),

    # 3) single-word current message
    (INFO + "\nstatus",
     "status"),

    # 4) first message, no Conversation context block (just metadata + message)
    ('''Conversation info (untrusted metadata):
```json
{ "chat_id": "telegram:-100:topic:5", "sender_id": "110123423" }
```

Sender (untrusted metadata):
```json
{ "id": "110123423" }
```

/newcc 461156''',
     "/newcc 461156"),

    # 5) plain message with no envelope at all -> returned unchanged
    ("just a normal message", "just a normal message"),

    # 6) legacy "[Telegram ...]" envelope with (id): prefix still strips
    ("[Telegram group id:-100 topic:5] Pouya M (110123423): hello there",
     "hello there"),

    # 7) "Current message:" + [Replying to:] + "#N Sender (id):" (reply format)
    ('''Conversation context (untrusted, chronological, selected for current message):
#964 Sun Pouya M: lets write some tests
#965 Sun [reply target] JamshidBot: Wrote test_extract.py

Current message:
[Replying to: "Wrote 34 lines to test_extract.py here is the content"]
#966 Pouya M (110123423): Update pauses after a while''',
     "Update pauses after a while"),

    # 8) "Current message:" with a bare message (no reply / no #N prefix)
    ("Conversation context (untrusted, ...):\n#1 a: hi\n\nCurrent message:\nwhat changed?",
     "what changed?"),
]
