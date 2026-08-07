---
name: move-to-topic
description: Create a NEW Telegram topic bound to its own Claude Code session. Two modes - FORK the current session (worktree-backed, keeps full context) or bind a DIFFERENT folder (fresh session). Use when the user says "create a new topic", "make a topic for X", "move this to a new topic", "fork this into a new topic", "split this off", "give X its own topic", or similar.
---

# new-topic / move-to-topic

Two different jobs share this skill. Pick by what the user is asking for.

| Ask | Script | Result |
|---|---|---|
| "move/fork **this** into a new topic", "split this off" | `move-to-topic.sh` | New topic runs a **git worktree** of the current folder's feature branch, **resumed with this conversation's context**. Current topic stays alive on the base branch. |
| "create a topic for **X**", "give the website its own topic" | `bind-folder-to-topic.sh` | New topic runs a **new folder you choose**, **fresh session, no context carried**. Current topic and folder untouched. |

**Either way, the new topic gets its OWN new folder.** Never point a topic at a folder something else is already bound to — see pre-flight (c) for why that quietly breaks both topics. Which folder is **your** call, offered alongside the name in step 1; don't make the user specify it.

The only thing worth clarifying with the user is fork-vs-fresh when it's genuinely unclear ("create a new topic for designing the DUT board" — continue *this* conversation there, or start clean?). Default to **fresh** unless the new topic needs the history.

## 0. Pre-flight — MANDATORY, do this BEFORE creating anything

**Run this from a session bound to the group you want the topic IN.** Neither script takes a chat id: both read it from `relay-work/target-$KEY.json`, i.e. *the chat this session answers into*. Run it from the wrong session and the topic is created in the wrong group — silently, because every other check still passes. A plain terminal is not an option either: both scripts require `$TMUX` and a `cr-<hash>` session, so they die immediately outside one. Print the chat and confirm it is the intended group before going further.

Topic creation is **irreversible and can break the whole group**. Run these three checks first. If any fails, stop and report; do not work around it.

```bash
KEY="$(tmux display-message -p '#S')"
CHAT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["chat"])' \
   ~/.openclaw/workspace/scripts/relay-work/target-$KEY.json)"
echo "chat=$CHAT"
```

**(a) The chat MUST be a supergroup — `$CHAT` starts with `-100`.**

A **basic group** (id like `-5417839691`, no `-100` prefix) is not a forum. Calling `topic-create` on one makes Telegram **silently upgrade it to a supergroup, which CHANGES THE CHAT ID**. The gateway surfaces only the error text and drops Telegram's `migrate_to_chat_id`, so nothing self-heals: every `bindings` entry, `relay-work/target-*.json`, and `agents.list` workspace for the old id is orphaned and the group goes dead. This happened to Oracova PCBA on 2026-08-04 (`-5417839691` -> `-1004395661179`).

If it isn't `-100…`: **refuse**. Tell the user the group must be converted to a supergroup with Topics enabled first, and that doing so changes the chat id so every binding in that group has to be re-made. Their call, not yours.

**(b) The bot needs the Manage Topics admin right.** There is no read-only probe for this (no `getChat` in `TELEGRAM_MESSAGE_ACTION_MAP`). If `topic-create` returns `400: Bad Request: not enough rights to create a topic`, the bot is in the chat but lacks the right, or Topics is off for the group. Report it verbatim and point at *Group -> Edit -> Administrators -> [bot] -> Manage Topics* (and *Edit -> Topics*). **Do not retry** — `topic-create` is not idempotent and the idempotency cache replays failed results, so a retry needs a fresh key and risks a duplicate topic.

**(c) The new topic needs a NEW folder — never one that is already bound.**

A relay session is keyed by **folder only** (`cr-$(md5 folder | cut -c1-10)`), and so is its reply target (`relay-work/target-cr-<hash>.json`), while OpenClaw keys an agent by **peer**. Two peers bound to one folder therefore share **one Claude conversation and one reply target — last inbound wins**, so answers surface in whichever topic spoke most recently. This is invisible until someone notices a reply in the wrong topic (Oracova PCBA, 2026-08-04).

`bind-folder-to-topic.sh` now enforces this itself: it refuses a folder that has a live tmux session **or** that any binding already claims as its workspace, and creates the folder when it doesn't exist. You still pick a fresh folder in step 1 rather than leaning on the refusal.

To see the current state:

```bash
python3 ~/.openclaw/workspace/scripts/reap-dead-bindings.py   # dry-run; lists every bound folder + FOLDER_COLLISION
```

That same script is the dead-binding sweep: it removes bindings whose workspace is gone, whose chat id was orphaned by a group->supergroup upgrade, and the agent/model/backend entries left behind. It runs automatically after every `newcc` bind and every 6h via `ai.openclaw.reap-bindings`, so you should rarely need `--apply` by hand.

## 1. Propose the name AND the folder together, let the user pick

**Every new topic gets its own new folder. No exceptions.** You choose it, the same way you choose the name — don't ask the user where the work should live, and don't reuse an existing folder because it looks related.

Propose **3 options** from the recent conversation via the **AskUserQuestion** tool (they arrive as tappable Telegram buttons). Each option is a **name + folder pair**, not a name alone:

```
"DUT Board Design"   -> ~/.openclaw/workspace/dut-board
"Fixture Design"     -> ~/.openclaw/workspace/hardware/fixture     (sub-project of hardware)
"DUT Bring-up"       -> ~/.openclaw/workspace/dut-bringup
```

Picking the folder:
- **Sibling** under `~/.openclaw/workspace/<slug>` when the work stands on its own.
- **Subfolder** of the parent work (`<parent>/<slug>`) when it is genuinely a sub-project of it — this is fine and does not collide, because the *path* is what keys the session.
- Slug = the topic name, lowercased and hyphenated. Keep them aligned so the folder is guessable from the topic.
- The folder does **not** need to exist. `bind-folder-to-topic.sh` creates it and runs `git init`, so it can later be forked with `move-to-topic.sh`.

Only skip the proposal if the user already gave both a name and a folder.

## 2. Run the script

```bash
~/.claude/skills/move-to-topic/move-to-topic.sh "<chosen name>"          # fork this session
~/.claude/skills/move-to-topic/bind-folder-to-topic.sh <folder> "<name>" # bind another folder
```

Relay the script's output. Both end with a **deferred gateway restart (~12s)** so your confirmation lands first.

**Never call `openclaw gateway call message.action … topic-create` by hand.** The scripts do the create, the code registration, the binding, the session launch, the watcher, and the restart as one unit. A hand-rolled create gives you an orphaned topic with nothing behind it — and skips every check above.

## What move-to-topic.sh does (Option-B worktree fork)

For a git repo on a **feature branch** (with or without WIP):
1. commits WIP on the feature branch (checkpoint commit),
2. switches the **current** folder to the base branch (`main`/`master`),
3. adds a nested worktree `.worktrees/<branch>` (gitignored),
4. copies the active Claude transcript into the worktree's project dir and rewrites its `cwd` rows, so the fork resumes with full context,
5. creates the topic, registers a relay code, binds it,
6. pre-launches the fork with `claude --resume <sid>` (`--continue` rejects a transplanted transcript), writes its reply target, starts its watcher,
7. defers the gateway restart.

## Rules

- **One folder per topic, always a new one.** The script refuses a folder that is already bound, but the rule is yours to follow, not the guard's to catch. If you find yourself wanting to reuse a folder "because it's the same project", make a subfolder instead.
- **Never test this on a live/bound folder.** A session is keyed by `cr-<md5(folder)>`, so a "throwaway" launched in a bound folder IS that session — this once destroyed a real 2,386-message context. Use a scratch dir nothing maps to.
- **Verify before claiming.** Don't report success until you've checked actual state (binding present, session ready, watcher up). The relay fails *silently*, so "no error" is not evidence it worked.
- **Relay-bound session only** (`$TMUX` + a `cr-<hash>` tmux session). If the script can't resolve the folder/target, say it isn't a bound session; don't guess.
- `move-to-topic.sh` needs a **git repo on a feature branch** — it refuses on a detached HEAD or on `main`/`master`. Report that plainly; `bind-folder-to-topic.sh` is the alternative when there's nothing to fork.
- `move-to-topic.sh` **commits the user's WIP** and **switches the current folder to base**. That is intentional (Option B) and implied by asking to fork. Don't second-guess it, but if the script errors mid-way, report exactly which step failed.
- **On any error, report it plainly and stop.** Do not retry, and do not fall back to raw RPC.

## If a chat id migrated anyway

Recover the new id from `~/.openclaw/logs/messages.jsonl` — it starts appearing at the upgrade minute. The `-100` + old-id trick does **not** reconstruct it. Then update `channels.telegram.groups`, every `bindings[].match.peer.id`, the `cliBackends[].args` peer, and `relay-work/target-*.json`, and restart the gateway.
