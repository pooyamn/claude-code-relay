# Agentic PC: design

Status: v3, after an independent review (2026-10-01). Owner: Pouya.
Target: Windows PC, WSL2 Ubuntu 24.04, user `pouya` created with home `/Users/pouya` (`useradd -d`), so existing absolute paths keep working.

## 1. Goals and constraints

Goals
- Several agents on one PC, each with its own role, skills and memory.
- Each repo has its own instructions and project memory.
- Any session can switch between Claude Code and Codex without losing its working state.
- Sessions can message each other, and Pouya can see all of it.
- Everything works from a phone.

Constraints
- Claude and ChatGPT subscriptions only. No API keys.
- Agents are interactive sessions in tmux, not `claude -p` or one-shot runs.
- Phone access through the Telegram router (ccrelayd) and the Claude Code and Codex remote-control apps.
- Migrate gradually, one agent at a time.

## 2. Model

- **Agent**: a role. Instructions, skills, role memory, the files it owns.
- **Session**: one live conversation of an agent on one task, in Claude Code or Codex. Id `<agent>.<task>`, e.g. `pcb-routing.augur1`. An agent can have several.
- Sessions talk to sessions. One Telegram bot carries all traffic.
- Plain files are the source of truth; built-in memory is off in both tools (`autoMemoryEnabled: false`; Codex `memories` feature is already off, pin it with `codex features disable memories`).

### Agents

v1 starts with three: `ceo`, `cto`, `reviewer`. The rest are added one at a time.

| Agent | Owns |
|---|---|
| `ceo` | direction for Fidior and Oracova, outreach, docs, pricing, COMPANY.md |
| `cto` | architecture, task split, merges (via the router), bench/HIL |
| `reviewer` | pass/fail on other sessions' work with evidence; runs on the other tool |
| `researcher` | datasheets, parts, market, prior art; the search index |
| `firmware` | supervisor C, FPGA, bench firmware |
| `backend` | MCP/.NET, relay, APIs |
| `frontend` | oracova.com, hil-viewer, landing prototypes |
| `pcb-schematic` | `.kicad_sch`, BOM, part choice |
| `pcb-routing` | `.kicad_pcb`, fab outputs, ordering |
| `art-director` | brand, visuals, renders, design review |

## 3. Files

```
~/agents/shared/AGENTS.md          global rules
~/agents/shared/COMPANY.md         big picture (<= ~2000 words), always loaded
~/agents/shared/DECISIONS.md       dated one-line decisions with reasons, always loaded
~/agents/shared/skills/            shared skills
~/agents/shared/sessions.json      registry: id, agent, task, tool, cwd, tmux target,
                                   Claude session id / Codex thread id, topic, state
~/agents/shared/bus.jsonl          every inter-session message with its delivery result
~/agents/shared/repos/<repo>/MEMORY.md, NOW-<agent>.md    project memory, outside the repo tree
~/agents/<agent>/AGENTS.md         role, owned files, boundaries
~/agents/<agent>/CLAUDE.md         "@AGENTS.md"
~/agents/<agent>/.claude/skills/   symlinks to chosen skills
~/agents/<agent>/.agents/skills -> .claude/skills    (Codex reads .agents/skills)
~/agents/<agent>/memory/MEMORY.md  role knowledge
~/agents/<agent>/inbox/            long messages
~/repos/<repo>/AGENTS.md           repo instructions (Claude reads AGENTS.md natively since 2.1.277)
~/repos/<repo>/.worktrees/<agent>.<task>/   one worktree per session, branch <agent>/<task>
```

Project memory lives outside the repo so it does not diverge per branch or worktree.

Global wiring
- `~/.claude/CLAUDE.md` imports `~/agents/shared/AGENTS.md`, `COMPANY.md`, `DECISIONS.md` (user-scope imports load without a dialog).
- `~/.codex/AGENTS.md` is a generated concatenation of the same three, rebuilt on change.
- Claude setting `instructionFiles: "claude-md-and-agents-md"` so repo AGENTS.md and the agent's CLAUDE.md both load.
- Writes to `~/agents/shared/*.md` are blocked by hook for every agent except `ceo` and `cto`.

## 4. Sessions

- Start: `a <agent> <task> [claude|codex] [repo]`. The session starts **inside its own worktree** of that repo (or in `~/agents/<agent>` when there is no repo), because both tools load instructions only from the working directory and its parents.
  - Claude: `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1 claude --add-dir ~/agents/<agent>` so the role file loads next to the repo's.
  - Codex: `codex --remote unix://$HOME/.codex/app-server-control/app-server-control.sock -C <worktree>`, with the role delivered by a generated, gitignored per-worktree instruction file (exact Codex mechanism: open item).
- The launcher records the Claude session id or Codex thread id in `sessions.json`.
- Path ownership: each agent's AGENTS.md lists the paths it owns (e.g. `firmware/supervisor-c/**`, `web/**`). Agents read anything; changing another agent's paths goes through `agent-msg` to that agent or to `cto`. Unmergeable files (KiCad, binaries) rely on ownership alone: `pcb-schematic` owns `.kicad_sch`, `pcb-routing` owns `.kicad_pcb`.
- Switching tool: the session rewrites `NOW-<agent>.md`, then the other tool starts in the same worktree and reads it. Only the handoff file transfers, not the conversation.
- A `PreCompact` hook makes Claude rewrite `NOW-<agent>.md` before context compaction, so long-lived sessions do not lose their place.
- Reboot and crash: on start, the router reconciles `sessions.json` against tmux, sockets and daemon threads, marks missing sessions dead, alerts, and resumes them by id (`claude --resume`, `codex resume`). WSL, the Codex daemon and ccrelayd start at boot (Task Scheduler + systemd user units).

## 5. Messaging

One command for every session: `agent-msg <session|agent> "<text>" [--urgent]`.

| Target | Delivery |
|---|---|
| Claude Code | native cross-session inbox (per-session socket). Posting format from a script: open item; fallback is a bracketed paste into the tmux pane |
| Codex | `codex queue --thread <id> --message <text>`; `--urgent` steers the running turn |

- Headers are written only by `agent-msg`: `[from <session> · hop N · id <msg-id>]`. A body containing a header-shaped line is rejected. Text from Pouya arrives only through Telegram from his user id.
- A bare agent name goes to that agent's most recent live session. If none is live, the message is parked in `inbox/` and Pouya is alerted. Nothing auto-starts a session (usage budget).
- Delivery semantics: `bus.jsonl` records `delivered` or `failed` by actual result; failures retry with backoff; receivers drop duplicate msg-ids.
- Guards:
  - hop limit 3 per thread, enforced by `agent-msg` (Claude throttles loops natively; Codex does not);
  - `crossSessionInbound: "accept"` on agent sessions (they run with prompts skipped; without it, messages are held and dropped after 5 minutes).
- Review loop: see section 6a.

## 6. Enforcement (not prompts)

Sessions run with permission prompts skipped, so rules in markdown are advice only. What is actually enforced:
- **No credentials in sessions.** Worktrees push to a local bare mirror. Only the router holds GitHub, mail and payment credentials and performs those actions after Pouya taps Approve.
- **Deny hooks** (Claude `PreToolUse`, Codex hooks) on `git push` to remote origins, mail clients and known payment CLIs.
- **Branch protection** on `main` on GitHub.
- **Shared file protection**: hook-enforced write restriction on `~/agents/shared/*.md`.

## 6a. Branches and PRs

1. One branch per session, `<agent>/<task>`, in its own worktree.
2. The session commits and pushes to a local mirror; it holds no GitHub credentials.
3. The router pushes the branch to GitHub and opens the PR (no approval needed).
4. `reviewer`, on the other tool, reviews the diff and test output and posts pass/fail on the PR.
5. On pass, `cto` requests the merge and the router squash-merges. `cto`'s request is sufficient; no Pouya approval for merges. Branch protection on `main` allows only router merges.
6. Sessions rebase on `main` before review and before merge; a conflict goes back to the owner of the file.
7. The bus topic shows PR opened, review pass/fail, merged.

## 7. Knowledge

- Layer 1, always loaded: `COMPANY.md` and `DECISIONS.md`. `ceo` maintains COMPANY.md with Pouya's approval.
- Layer 2, on demand (deferred until there is material): local hybrid search (QMD or picoqmd, local models, MCP) over repo docs, handoffs, MEMORY/NOW files, datasheets, `bus.jsonl`. Results carry source and date and are wrapped as quoted data. No mail in v1. Never indexed: transcripts, keys, env files, dependency and build folders.

## 8. Visibility

| What | Where | Notifies |
|---|---|---|
| Inter-session messages, batched per thread: `A → B · hop · first line`, inbox files attached | Bus topic | no |
| A session's replies and incoming messages in context; no live progress bubble for agent-to-agent turns | Session topic | final reply only |
| Status board: per session state, task, queue, last activity, delivery failures, usage this window | Pinned message, edited on state change, at most every 30 s | no |
| Approvals with Approve / Deny (outside effects: email, payments, purchases, public posts; not merges) | Approvals topic | yes |
| Alerts: stuck, dead session, parked message, Codex lock conflict, failed delivery | Approvals topic | yes |

Telegram allows about 20 messages per minute per group, shared by all topics. If traffic grows, bus and status move to a second group.

Intervening: reply to a bus line to message its receiver as Pouya; `/pause`, `/resume`, `/stop all`; `agent-msg log <session>`. The remote-control apps show live sessions directly.

## 9. Router (ccrelayd)

Built: long-poll, topic → session routing, media, voice transcription, rich tables, progress bubble, Codex via daemon, `newcc`/`unbind`/`cancel`.
To add: inbound spool so a crash does not lose a message (today the offset advances before handling), session topics, bus topic, status board, approvals and the credentialed actions behind them, reconcile-on-start, `/pause` and `/stop all`.

## 10. Migration order

1. Shared folder, global wiring, enforcement hooks, COMPANY.md drafted and approved.
2. `ceo`, `cto`, `reviewer`.
3. `agent-msg`, bus topic, status board.
4. Remaining agents one at a time, with their worktrees.
5. Search index, digest, claims, once the basics are stable.

## 11. Open items

1. Message format for posting into a Claude session's inbox socket from a script.
2. How Codex should receive the per-agent role when started in a worktree (generated instruction file vs. config).
3. Build on the current Mac VM and migrate, or directly on the Windows PC.
