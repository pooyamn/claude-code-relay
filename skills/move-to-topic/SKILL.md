---
name: move-to-topic
description: Fork the current relay-bound Claude Code session into a NEW Telegram topic backed by a git worktree, so the fork is an INDEPENDENT session that continues with full context while the current topic stays alive. Use when the user says "move this to a new topic", "fork this into a new topic", "split this off", or similar. First suggest a few topic-name options for the user to pick.
---

# move-to-topic (fork)

When the user asks to move/fork the current session into a new topic, do this:

## 1. Suggest names, let the user pick
Look at the recent conversation and propose **3 concise topic-name options** (2–4 words each). Present them with the **AskUserQuestion** tool so they arrive as tappable Telegram buttons. Don't pick a name yourself unless the user already gave one.

## 2. Run the fork
Once the user picks (or gave) a name:

```bash
~/.claude/skills/move-to-topic/move-to-topic.sh "<chosen name>"
```

Relay the script's output.

## What it does (Option-B worktree fork)
For a git repo currently on a **feature branch** (with or without WIP), it:
1. commits any WIP on the feature branch (a checkpoint commit),
2. switches the **current** folder to the base branch (`main`/`master`),
3. adds a nested worktree `.worktrees/<branch>` on the feature branch (gitignored),
4. copies the current Claude transcript into the worktree's project dir so the fork **`--continue`s with full context**,
5. creates the new topic and binds it to the **worktree** (a new independent `cr-<hash>` session),
6. defers a gateway restart (~12s) to activate, so your confirmation lands first.

Result: **new topic = the feature-branch work + this conversation, independent**; **current topic = the same folder, now on the base branch, still alive.**

## Rules
- **Relay-bound session only** ($TMUX + a `cr-<hash>` tmux session). If the script can't resolve the folder/target, tell the user it isn't a bound session; don't guess.
- **Git repo on a feature branch required.** The script refuses if the folder isn't a git repo, is detached, or is already on `main`/`master` (nothing to fork). Report that plainly.
- It **commits the user's WIP** and **switches the current folder to base** — that is intentional (Option B) and the user has opted into it by asking to fork. Don't second-guess it, but if the script errors mid-way, report exactly which step failed.
- Activating restarts the gateway (~12s; sessions resume via `--continue`, tmux sessions aren't killed).
- On any error, report it plainly; do not retry (topic-create is not idempotent — a retry makes a duplicate topic).
