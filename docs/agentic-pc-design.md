# Agentic PC: design

Status: v5 (2026-10-01), after reviews by Claude Fable, Codex GPT-6-Astra and GPT-6.1-Sol (max effort). Owner: Pouya.
Target: Windows PC, WSL2 Ubuntu 24.04. Sessions run as user `pouya` (home `/Users/pouya`, so existing absolute paths keep working); the router runs as a separate user `relay`.

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

Threat model: one owner. The risks are mistakes and prompt injection (from web pages, documents, other sessions), not a hostile user on the machine. Protection is real where an action leaves the machine or touches `main`; inside the machine, sessions trust each other.

## 2. Model

- **Agent**: a role. Instructions, skills, role memory, the paths it owns.
- **Session**: one live conversation of an agent on one task, in Claude Code or Codex. Id `<agent>.<task>`. An agent can have several sessions.
- Sessions talk to sessions. One Telegram bot carries all traffic.
- Plain files are the source of truth. Built-in memory is off: Claude `autoMemoryEnabled: false`; Codex `memories` (already off; pin with `codex features disable memories`).

### Agents

v1: `ceo`, `cto`, `reviewer`. Then one at a time: `researcher`, `firmware`, `backend`, `frontend`, `pcb-schematic`, `pcb-routing`, `art-director`.

## 3. Memory

Every memory is a directory of small files, one fact per file, plus a generated index. Separate files mean concurrent sessions never overwrite each other; only the index is regenerated (by a script, under a lock).

| Layer | Location | Holds | Writes |
|---|---|---|---|
| Company | `~/agents/shared/COMPANY.md` | big picture, priorities, non-goals | `ceo` proposes, Pouya approves |
| Decisions | `~/agents/shared/decisions/` + index | one decision per file: date, reason, scope | `ceo`, `cto` |
| Agent | `~/agents/<agent>/memory/` + index | role knowledge across repos | sessions of that agent |
| Repo | `~/agents/shared/repos/<repo>/memory/` + index | project facts, each tagged with the commit it holds for | any session in the repo |
| Handoff | `~/agents/shared/repos/<repo>/now/<agent>.<task>.md` | where this session's work stands | that session only |

Rules
- Every fact file has frontmatter: `date`, `session`, and for repo facts `commit`. A repo fact from an unmerged branch is marked `unmerged` and is promoted only after its PR merges.
- Precedence when files disagree: decisions > company > repo > agent; newer beats older within a layer.
- Loading: company and the decisions index load in every session. Agent and repo indexes load at session start (instructed in AGENTS.md); individual fact files are read on demand.
- Handoffs are per session (`<agent>.<task>`), so two sessions of one agent never collide.
- Handoffs are written at checkpoints during normal work (every publish, every hand-back, every tool switch), not only at the end. Hooks cannot make a model write a handoff, so this is an instruction plus a check: the launcher warns when a handoff is older than the session's last commit.

## 4. Files

```
~/agents/shared/AGENTS.md          global rules
~/agents/shared/COMPANY.md
~/agents/shared/decisions/
~/agents/shared/skills/
~/agents/shared/sessions.json      registry (desired + observed state, ids)
~/agents/shared/repos/<repo>/memory/, now/
~/agents/<agent>/AGENTS.md         role, owned paths, boundaries
~/agents/<agent>/CLAUDE.md         "@AGENTS.md"
~/agents/<agent>/skills/           the agent's chosen skills (symlinks into shared/skills)
~/agents/<agent>/memory/
~/agents/<agent>/inbox/
~/repos/<repo>/                    main checkout (sessions never work in it)
~/worktrees/<repo>/<agent>.<task>/ one worktree per session, outside the main checkout
```

Worktrees live outside the main checkout so a session never picks up the main checkout's instruction files from a parent folder.

Global wiring
- `~/.claude/CLAUDE.md` imports shared AGENTS.md, COMPANY.md and the decisions index.
- `~/.codex/AGENTS.md` is a generated concatenation of the same, rebuilt on change.
- Claude `instructionFiles: "claude-md-and-agents-md"`.

## 5. Sessions

Start: `a <agent> <task> [claude|codex] [repo]`. The launcher:
1. creates or reuses the worktree `~/worktrees/<repo>/<agent>.<task>` on branch `<agent>/<task>`;
2. links the agent's skills into the worktree (`.claude/skills` and `.agents/skills`), both excluded via the path from `git rev-parse --git-path info/exclude`, since a worktree's `.git` is a file;
3. for Codex, writes `AGENTS.override.md` = role + current repo AGENTS.md (tested: works through the daemon; `-c developer_instructions` does not);
4. starts the tool inside the worktree:
   - Claude: `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1 claude --add-dir ~/agents/<agent>`
   - Codex: `codex --remote unix://…/app-server-control.sock -C <worktree>`
5. records the Claude session id or Codex thread id in `sessions.json`.

Generated files (override, skill links) are regenerated after every merge into `main` and at every start.

Ownership
- Each agent's AGENTS.md lists the paths it owns. Changing another agent's paths goes through that agent or `cto`.
- Unmergeable artifacts (KiCad board, schematic, BOM of one hardware revision) are leased per session: `agent-msg lease <path> <minutes>`, checked by the router when the session publishes. Two sessions of the same agent cannot hold the same lease.

Switching tool: stop the current session (it writes its handoff), the router marks it `stopped`, then start the other tool on the same worktree. Never two live sessions on one worktree.

Recovery
- `sessions.json` keeps desired state (running, paused, stopped) separate from observed state. On boot or router restart, only sessions whose desired state is `running` are resumed, by exact id (`claude --resume <id>`, `codex resume <id>`). A failed resume alerts; it never silently starts a fresh thread.
- One Codex daemon. The router never deletes a thread lock held by a live process.
- Boot order: WSL (Task Scheduler) → systemd user units: Codex daemon, router, then session resume.

## 6. Messaging

`agent-msg <session> "<text>"` is the only sanctioned way to message another session. Claude's native `SendMessage` to other sessions is denied by permission rule for agent sessions (subagent messaging inside a session is unaffected), so nothing bypasses the router.

- `agent-msg` hands the message to the router over a local socket; the router assigns the id, the hop count and the header, stores it durably, then delivers.
- Delivery: Claude via its native inbox socket: connect to `/tmp/cc-socks/<pid>.sock` (path also in the session registry) and write one line `{"type":"user","message":{"role":"user","content":"<header + text>"}}`, then close. Codex via `codex queue --thread <id>`, or `turn/steer` on the daemon when sent with `--urgent`.
- States recorded per message: `stored`, `accepted` (target took it), `failed`. Retries only for `stored`/`failed`; the router drops duplicates it already delivered.
- Action requests need the exact session id, not a bare agent name. If the target is not running, the message is parked in its inbox and Pouya is alerted. Nothing auto-starts.
- Hop limit 3 per thread, counted by the router, not by the model.
- Agent sessions set `crossSessionInbound: "accept"`, because script-posted messages carry no permission class and would otherwise be held.

## 7. Enforcement

Real boundaries:
- **Separate OS user.** The router runs as `relay` and alone holds the Telegram token, GitHub credentials and any mail/payment credentials, in files `pouya` cannot read. Sessions ask the router for actions over a socket; the router authenticates the peer by uid and checks the action against policy.
- **No credentials in sessions.** Worktrees push only to a local mirror owned by `relay` (writable by group); publishing to GitHub is a router action.
- **GitHub branch protection** on `main`: required status `review` on the exact head SHA, branch must be up to date with `main`, only the router's token may merge.
- **Approvals** are single-use and bound to the exact action (recipient, amount, text hash). They cover email, payments, purchases, public posts. Merges follow `cto` policy, not Pouya's approval.

Guardrails, not boundaries: deny hooks on `git push` to other remotes, mail CLIs and curl to known APIs. They catch mistakes; they cannot stop a determined bypass.

Router authorisation fails closed: an empty allow list allows nobody.

## 8. Branches and PRs

Every published checkpoint goes to `main` after review.

1. The session commits a coherent checkpoint (builds, tests pass) and runs `agent-msg publish`.
2. The router pushes that exact commit to GitHub as `pub/<agent>.<task>/<n>` and opens a PR. Each publication is a fresh branch, so a squash merge never leaves a diverged branch behind.
3. `reviewer` (other tool) reviews that head SHA and reports pass/fail to the router, which sets the commit status `review` on that SHA. Any new commit or rebase invalidates it.
4. The router serialises merges per repository: rebase the publication onto current `main` if needed, re-run the review only if the rebase changed content, then squash-merge on `cto`'s request.
5. After the merge, the session updates its own worktree: `git fetch`, then `git rebase --autostash --onto origin/main <published-sha>`. Work done after the checkpoint, committed or not, is replayed on top; nothing is reset away.
6. On fail, the session fixes and publishes again (new publication branch, same thread on the bus).

Rules: one open publication per session; the session keeps working meanwhile but does not publish again until it resolves. Routine low-risk changes (docs, formatting) may skip `reviewer` under a written `cto` policy; everything else is reviewed.

## 9. Knowledge

- Always loaded: COMPANY.md and the decisions index (one line per decision; full files on demand).
- On demand, deferred: local hybrid search (QMD or picoqmd, local models, MCP) over repo docs, memory, handoffs, datasheets and the bus. Results carry source and date and are quoted as data. Never indexed: transcripts, keys, env files, build output.

## 10. Visibility

One outbound scheduler in the router owns every Telegram send, with priorities: approvals and alerts first, final replies next, bus and status last. It tracks the group's ~20 messages/minute budget, coalesces, and honours `retry_after` durably.

| What | Where | Notifies |
|---|---|---|
| Inter-session messages, batched per thread, with delivery state | Bus topic | no |
| Session replies and incoming messages in context; no progress bubble for agent-to-agent turns | Session topic | final reply only |
| Status board: desired/observed state, task, open publication, queue, failures, usage this window | Pinned message, on change, at most every 30 s | no |
| Approvals (Approve / Deny) | Approvals topic | yes |
| Alerts: stuck, dead session, failed resume, parked message, delivery failure, stale handoff | Approvals topic | yes |

Intervene: reply to a bus line; `/pause`, `/resume`, `/stop all`. Telegram keeps inbound updates for 24 hours, so a longer router outage loses phone messages; a watchdog alerts Pouya's DM when the router is down.

## 11. Router (ccrelayd): work list

Built: long-poll, topic routing, media, voice, rich tables, progress bubble, Codex via daemon, bind/unbind/cancel.
Needed, in order:
1. Run as `relay`; fail-closed authorisation; action socket with uid check.
2. Durable inbound spool (persist before advancing the offset) and outbox.
3. Fix the Codex queue append/drain race (file lock); treat a send timeout as unknown, not started.
4. Message ids, states, router-owned hops; `agent-msg` client.
5. Publication flow, SHA-bound review status, per-repo merge serialisation.
6. Session registry with desired/observed state; resume by id; boot units.
7. Scheduler, bus, status board, approvals.

## 12. Migration order

1. `relay` user, router hardening (items 1–3), shared folders, COMPANY.md.
2. `ceo`, `cto`, `reviewer`.
3. Messaging and publication flow (items 4–5).
4. Remaining agents one at a time.
5. Search index once there is material.

## 13. Open items

1. Build on the Mac VM and migrate, or directly on the Windows PC.

## Appendix: verified facts (2026-10-01, Claude Code 2.1.287, Codex 0.159.3)

- Claude reads AGENTS.md natively (≥2.1.277); loads instructions from cwd and parents; `--add-dir` with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` loads that dir's CLAUDE.md; ignores `AGENTS.override.md`.
- Claude cross-session inbox; bypass-to-bypass delivers by default; script posts without a permission class are held unless `crossSessionInbound: "accept"`.
- `PreCompact` cannot run prompt or agent hooks.
- Posting into a Claude session from an unrelated process (tested 2026-10-01): one JSON line `{"type":"user","message":{"role":"user","content":"..."}}` on `/tmp/cc-socks/<pid>.sock`, no auth line needed on macOS/Linux. Claude delivers it as a message from another session, with its built-in rule that a peer message is never the user's approval. With prompts skipped and no `crossSessionInbound: "accept"`, it is held for a human (Deny / Deliver). Extra envelope fields (`from`, `from_mode`) are ignored: sender identity and permission mode cannot be asserted by a script, so the router's header carries the sender.
- Codex: `--remote unix://…` attaches the TUI to the daemon; `-C` needed; `-c developer_instructions` ignored through the daemon; `AGENTS.override.md` replaces AGENTS.md at its level; skills from `.agents/skills` and `.codex/skills` under the cwd tree and the user dir; `codex queue` exists without an urgent flag; `turn/steer` is the steer path; hooks on, memories off.
- A linked worktree's `.git` is a file.
- Telegram: ~20 messages/minute per group; updates kept 24 hours.

Reviews: `docs/reviews/2026-10-01-gpt-6-astra.md`, `docs/reviews/2026-10-01-gpt-6.1-sol.md`.
