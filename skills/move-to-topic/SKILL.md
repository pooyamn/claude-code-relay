---
name: move-to-topic
description: Move the current relay-bound Claude Code session into a NEW Telegram topic in the same group, keeping full context. Use when the user says "move this to a new topic", "let's continue this in a new topic", "split this off into its own topic", or similar. First suggest a few topic-name options for the user to pick, then create + bind the new topic.
---

# move-to-topic

When the user asks to move/continue the current session in a new topic, do this:

## 1. Suggest names, let the user pick
Look at the recent conversation and propose **3 concise topic-name options** (2–4 words each) that capture what this thread is about. Present them with the **AskUserQuestion** tool so they arrive as tappable Telegram buttons. Include a short "Other" is automatic — the user can type their own.

Do NOT pick a name yourself unless the user already gave one in their message.

## 2. Create + bind the new topic
Once the user picks (or gives) a name, run:

```bash
~/.claude/skills/move-to-topic/move-to-topic.sh "<chosen name>"
```

The script:
- resolves THIS session's folder + code and the group chat id automatically,
- creates the new topic (`message.action` / `topic-create`),
- binds it to the **same folder** — so it's the **same session** with full context (continues via `--continue`),
- posts a short "moved here" greeting into the new topic,
- defers a gateway restart (~12s) to activate the binding, so your confirmation lands first.

Relay the script's output to the user.

## Why this preserves context
A relay session is keyed by its **folder**, not its topic (`cr-<md5(folder)>`). Binding a new topic to the same folder routes the new topic to the exact same running session, so the entire conversation history is intact — nothing is copied or lost.

## Rules
- **Only inside a relay-bound session** ($TMUX + a `cr-<hash>` tmux session). If the script says it can't resolve the folder/target, tell the user this isn't a bound session; don't guess.
- The **old topic stays bound** as a harmless fallback; mention the user can `/unbind` it there if they want it gone.
- Activating a binding **restarts the gateway** (~12s, all sessions resume via `--continue`). That's expected; the tmux sessions themselves are not killed, only Telegram routing blips.
- On any error from the script, report it plainly; do not retry blindly (topic-create is not idempotent across fresh keys — a retry makes a duplicate topic).
