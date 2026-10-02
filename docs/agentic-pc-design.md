# Agentic PC: design

Status: v6 (2026-10-01). Adds the `support` agent, issue intake, health checks, the ccrelay MCP server (built and tested), the Codex observer (built), and the session-history archive. Owner: Pouya.
Target: Windows PC, WSL2 Ubuntu 24.04. Sessions run as user `pouya` (home `/Users/pouya`, so existing absolute paths keep working); the router runs as a separate user `relay`.

## 1. Goals and constraints

Goals
- Several agents on one PC, each with its own role, skills and memory.
- Each repo has its own instructions and project memory.
- Any session can switch between Claude Code and Codex without losing its working state.
- Sessions can message each other, and Pouya can see all of it.
- The platform maintains itself: agents report problems, a support agent fixes them, the CTO proposes improvements.
- Every session's history is kept for future reference.
- Everything works from a phone.

Constraints
- Claude and ChatGPT subscriptions for all agent work. No paid API keys; free-tier keys are fine (held by `relay`, never in a session).
- Agents are interactive sessions in tmux, not `claude -p` or one-shot runs.
- Phone access through the Telegram router (ccrelayd) and the Claude Code and Codex remote-control apps.
- Migrate gradually, one agent at a time.

Threat model: one owner. The risks are mistakes and prompt injection (from web pages, documents, other sessions), not a hostile user on the machine. Protection is real where an action leaves the machine or touches `main`; inside the machine, sessions trust each other.

## 2. Model

- **Agent**: a role. Instructions, skills, role memory, the paths it owns.
- **Session**: one live conversation of an agent on one task, in Claude Code or Codex. Id `<agent>.<task>`. An agent can have several sessions.
- Sessions talk to sessions through ccrelay. One Telegram bot carries all traffic.
- Plain files are the source of truth. Built-in memory is off: Claude `autoMemoryEnabled: false`; Codex `memories` (already off; pin with `codex features disable memories`).

### Agents

v1: `ceo`, `cto`, `reviewer`, `support`. Then one at a time: `researcher`, `firmware`, `backend`, `frontend`, `pcb-schematic`, `pcb-routing`, `art-director`.

| Agent | Owns |
|---|---|
| `ceo` | direction for Fidior and Oracova, outreach, docs, pricing, COMPANY.md |
| `cto` | architecture, task split, merges, the improvement backlog and weekly streamlining proposals |
| `reviewer` | pass/fail on other sessions' work with evidence; runs on the other tool |
| `support` | the platform: ccrelay, watchers, Codex daemon, Telegram link, boot units, health checks, platform bugs |
| `researcher` | datasheets, parts, market, prior art; the search index |
| `firmware` | supervisor C, FPGA, bench firmware |
| `backend` | MCP/.NET services, APIs |
| `frontend` | oracova.com, hil-viewer, landing prototypes |
| `pcb-schematic` | `.kicad_sch`, BOM, part choice |
| `pcb-routing` | `.kicad_pcb`, fab outputs, ordering |
| `art-director` | brand, visuals, renders, design review |

## 3. Memory

Every memory is a directory of small files, one fact per file, plus a generated index. Separate files mean concurrent sessions never overwrite each other; only the index is regenerated (by a script, under a lock).

| Layer | Location | Holds | Writes |
|---|---|---|---|
| Company | `~/agents/shared/COMPANY.md` | big picture, priorities, non-goals | `ceo` proposes, Pouya approves |
| Decisions | `~/agents/shared/decisions/` + index | one decision per file: date, reason, scope | `ceo`, `cto` |
| Agent | `~/agents/<agent>/memory/` + index | role knowledge across repos | sessions of that agent |
| Repo | `~/agents/shared/repos/<repo>/memory/` + index | project facts, each tagged with the commit it holds for | any session in the repo |
| Handoff | `~/agents/shared/repos/<repo>/now/<agent>.<task>.md` | where this session's work stands | that session only |
| History | session-history archive (§10) | every transcript, verbatim | collector |

Rules
- Every fact file has frontmatter: `date`, `session`, and for repo facts `commit`. A repo fact from an unmerged branch is marked `unmerged` and is promoted only after its PR merges.
- Precedence when files disagree: decisions > company > repo > agent; newer beats older within a layer.
- Loading: company and the decisions index load in every session. Agent and repo indexes load at session start (instructed in AGENTS.md); individual fact files are read on demand.
- Handoffs are per session and written at checkpoints (every publish, hand-back, tool switch). The launcher warns when a handoff is older than the session's last commit.

## 4. Files

```
~/agents/shared/AGENTS.md          global rules
~/agents/shared/COMPANY.md
~/agents/shared/decisions/
~/agents/shared/skills/            includes talk-to-sessions
~/agents/shared/issues/            one file per issue (§9)
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

Global wiring
- `~/.claude/CLAUDE.md` imports shared AGENTS.md, COMPANY.md and the decisions index.
- `~/.codex/AGENTS.md` is a generated concatenation of the same, rebuilt on change.
- Claude `instructionFiles: "claude-md-and-agents-md"`, `crossSessionInbound: "accept"`, `cleanupPeriodDays: 3650`.
- ccrelay MCP server registered for both tools (Claude user scope, Codex `codex mcp add`).

## 5. Sessions

Start: `a <agent> <task> [claude|codex] [repo]`. The launcher:
1. creates or reuses the worktree `~/worktrees/<repo>/<agent>.<task>` on branch `<agent>/<task>`;
2. links the agent's skills into the worktree (`.claude/skills` and `.agents/skills`), excluded via `git rev-parse --git-path info/exclude`;
3. for Codex, writes `AGENTS.override.md` = role + current repo AGENTS.md;
4. starts the tool inside the worktree:
   - Claude: `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1 claude --add-dir ~/agents/<agent>`
   - Codex: `codex --remote unix://…/app-server-control.sock -C <worktree>`
5. records the Claude session id or Codex thread id in `sessions.json`.

Generated files are regenerated after every merge into `main` and at every start.

Ownership
- Each agent's AGENTS.md lists the paths it owns. Changing another agent's paths goes through that agent or `cto`.
- Unmergeable artifacts (KiCad board, schematic, BOM of one revision) are leased per session (`ccrelay.lease`), checked when the session publishes.

Switching tool: stop the current session (it writes its handoff), mark it `stopped`, start the other tool on the same worktree. Never two live sessions on one worktree.

Recovery
- `sessions.json` keeps desired state (running, paused, stopped) separate from observed state. On boot or router restart, only sessions whose desired state is `running` are resumed, by exact id. A failed resume alerts; it never silently starts a fresh thread.
- One Codex daemon. Nothing ever deletes a thread lock held by a live process.
- Boot order: WSL (Task Scheduler) → systemd user units: Codex daemon, router, health checks, then session resume.

## 6. Messaging: the ccrelay MCP server

Sessions message each other only through the ccrelay MCP server (built and tested 2026-10-01: Claude → Codex → Claude round trip, three hops, all delivered and logged). The `talk-to-sessions` skill tells both tools how to use it.

| Tool | Does |
|---|---|
| `list_sessions()` | sessions you can message, their tool, reachable or not |
| `send_message(to, text, reply_to?)` | store, deliver, log; returns id and state |
| `message_log(limit?)` | recent inter-session messages |
| `publish()` | open the PR for the current checkpoint (§8) |
| `lease(path, minutes)`, `release(path)` | unmergeable-file leases |
| `request_action(kind, details)` | email, payment, post: becomes an Approve button |
| `report_issue(kind, title, details)`, `list_issues(status?)`, `comment_issue(id, text)` | platform issues (§9) |

- Identity: the server takes the caller's identity from the folder it runs in; a session cannot choose its sender name.
- Header `[from <session> · hop N · id <id>]` is written by the server; the receiver answers with `reply_to`.
- Delivery: Claude via one JSON line on its inbox socket (`/tmp/cc-socks/<pid>.sock`); Codex via `codex queue --thread <id>`, or `turn/steer` for urgent.
- States per message: `stored`, `delivered`, `failed`; retries for failed; duplicates dropped by id.
- Hop limit 3, counted by the server. If the target is not running, the message is parked and Pouya is alerted. Nothing auto-starts.
- Claude's native `SendMessage` to other sessions is denied by permission rule, so nothing bypasses the log.

Codex observer (built 2026-10-01): the relay stays attached to every Codex thread through the daemon. Turns it did not start (the ChatGPT app, messages from other sessions) are mirrored into the session's topic, labelled "📱 From the ChatGPT app" or "📨 Message from <session>", followed by the reply; a turn that answered only through tools ends with "✓ Done".

## 7. Enforcement

Real boundaries:
- **Separate OS user.** The router runs as `relay` and alone holds the Telegram token, GitHub credentials and any mail/payment credentials, in files `pouya` cannot read. Sessions ask the router for actions over a socket; the router authenticates the peer by uid and checks the action against policy.
- **No credentials in sessions.** Worktrees push only to a local mirror owned by `relay`; publishing to GitHub is a router action.
- **GitHub branch protection** on `main`: required status `review` on the exact head SHA, up to date with `main`, only the router's token may merge.
- **Approvals** are single-use and bound to the exact action. They cover email, payments, purchases, public posts. Merges follow `cto` policy.

Guardrails, not boundaries: deny hooks on `git push` to other remotes, mail CLIs and curl to known APIs. Later, optionally, a Jev-backed pre-tool gate (allow / ask / deny per command, ~0.4 s). Its own published injection test let 10% of polite "the owner approved this" claims through, so it stays a guardrail; approvals remain in the router.

Router authorisation fails closed: an empty allow list allows nobody.

## 8. Branches and PRs

1. The session commits a coherent checkpoint (builds, tests pass) and calls `publish`.
2. The router pushes that exact commit as `pub/<agent>.<task>/<n>` and opens a PR. Each publication is a fresh branch.
3. `reviewer` (other tool) reviews that head SHA; the router sets the commit status `review` on that SHA. Any new commit or rebase invalidates it.
4. The router serialises merges per repository and squash-merges on `cto`'s request.
5. After the merge, the session runs `git fetch` and `git rebase --autostash --onto origin/main <published-sha>`; later work, committed or not, is replayed on top.
6. On fail, the session fixes and publishes again.

Rules: one open publication per session; routine low-risk changes may skip `reviewer` under a written `cto` policy.

## 9. Platform support

Intake
- Any agent reports through `report_issue(kind, title, details)` with kind `bug`, `improvement` or `feature`. Typical reports: a message not delivered, a Telegram topic not answering, a session that died, a missing tool.
- Each issue is one file in `~/agents/shared/issues/<id>.md` (status, reporter, session, timestamps), with the reporter's recent bus and log lines attached automatically. Local, not GitHub: the relay repo is public.
- Each new issue posts to the **issues** topic.

Triage
- A cheap classifier sorts each report and each health-check finding before any agent wakes: TypeSafe's Jev (a fast decision model) through Vercel AI Gateway's free tier (`typesafe-ai/jev`, $0.04/1M input tokens, covered by the monthly free credit; about $0.00002 per call). It returns kind, priority and the target agent. It only ever sees masked text. When it is rate-limited or down, plain rules decide instead.
- `bug` → `support`.
- `improvement`, `feature` → `cto`'s backlog.
- P1 (relay down, messages lost, a topic dead) → the alerts path; notifies Pouya.

Health checks
- A plain script runs every 15 minutes, no model: errors in `msg-ops.log` and the ccrelayd log, dead watchers, failed or held bus messages, Codex daemon status, stale handoffs, disk space, wedged USB mass-storage volumes on the bench (the DAPLink drive that hung Finder).
- It wakes the `support` session only when it finds something, with the findings attached. A quiet day costs nothing.

Fixing
- `support` works like every agent: its own worktree of the relay repo, PR, `reviewer`, `cto` merge.
- Rollout of platform changes: test group first; automatic check (one round trip in each test topic plus one `send_message`); then live topics; automatic rollback if health checks fail within 10 minutes.
- `support`'s AGENTS.md carries the standing rules: root cause before fix and a workaround labelled as one; never restart or kill the Codex remote-control daemon; never touch the bench VPN; never remove a capability to make a problem go away.

Streamlining
- Weekly, `cto` reviews the issue log, the bus (repeated hand-offs, stuck threads, long review loops), usage per agent and PR cycle times, and posts up to three concrete proposals with Approve buttons. Approved proposals become issues assigned to `support` or another agent.

## 10. Session history

Retention
- Claude's 30-day transcript deletion is off (`cleanupPeriodDays: 3650`), so nothing is lost before it is backed up.
- Local pruning only after the upload is verified by checksum, only for sessions idle 30+ days, never a session pinned by a relay topic or in the registry; every deletion logged to `relay-work/pruned.log`. A pruned session can no longer be resumed, and a pruned Codex thread disappears from the ChatGPT app.

Local database
- A collector follows Claude transcripts, Codex sessions and `bus.jsonl`, keeps a per-file read offset (so nothing is ingested twice and it catches up after downtime), and writes one SQLite file: FTS5 full-text search plus sqlite-vec vector search, no server.
- Tables: sessions (id, tool, agent, repo, title, start, end), messages (time, role, text, tool calls), with long tool outputs capped at 2 KB (the full output stays in the raw files) and secrets masked.
- Embeddings come from a small open model run locally (no API keys); on the Windows PC it uses the GPU if there is one. The same database serves the knowledge search layer (§11).

Daily backup to Cloudflare R2
- Contents, encrypted before upload (AES-256, password held by `relay`):
  - the day's new raw transcript lines per source (`raw/YYYY/MM/DD/<source>.7z`), secrets kept;
  - a consistent database snapshot (`VACUUM INTO`, `db/YYYY-MM-DD.7z`), secrets masked; the last 7 daily and the last 8 weekly snapshots are kept, older ones deleted.
- Every upload is verified (size and checksum of the stored object) before anything local is pruned.
- Restore: download the latest snapshot and the raw files since it, decrypt, replay the raw files into the database. If no snapshot survives, the database is rebuilt from the raw files alone (re-embedding takes hours of local compute, at no cost).
- Measured volume (2026-10-01): about 0.5 GB/month compressed raw and 0.4 GB/month searchable at today's pace; 2–3x with ten agents (estimate). R2 free tier: 10 GB-month, egress free; then $0.015/GB-month.

R2 setup (one time, by Pouya)
1. Cloudflare dashboard → R2 → Create bucket `agent-history` (location: Automatic).
2. R2 → Manage API tokens → Create API token: permission Object Read & Write, scoped to `agent-history` only.
3. Hand over the Account ID, Access Key ID and Secret Access Key. Preferably as a file on the machine rather than in chat, since chat text ends up in the archived transcripts.
4. The keys are stored in `~relay/.config/ccrelay/r2.env` (mode 600, owner `relay`); no session can read them. The key can touch only that bucket.

## 11. Knowledge

- Always loaded: COMPANY.md and the decisions index.
- On demand, deferred: local hybrid search (QMD or picoqmd, local models, MCP) over repo docs, memory, handoffs, datasheets, the bus and the searchable history. Results carry source and date and are quoted as data.

## 12. Visibility

One outbound scheduler in the router owns every Telegram send, with priorities: approvals and alerts first, final replies next, bus and status last. It tracks the group's ~20 messages/minute budget, coalesces, and honours `retry_after` durably.

| What | Where | Notifies |
|---|---|---|
| Inter-session messages with delivery state | Bus topic | no |
| Session replies, incoming messages and mirrored app turns | Session topic | final reply only |
| New issues and their status changes | Issues topic | P1 only |
| Status board | Pinned message, on change, at most every 30 s | no |
| Approvals (Approve / Deny), including `cto` proposals | Approvals topic | yes |
| Alerts | Approvals topic | yes |

Intervene: reply to a bus line; `/pause`, `/resume`, `/stop all`. A watchdog alerts Pouya's DM when the router is down (Telegram keeps inbound updates only 24 hours).

## 13. Work list

Built and tested: Telegram long-poll and routing, media, voice, rich tables, progress bubble, Codex via daemon, bind/unbind/cancel; ccrelay MCP (`list_sessions`, `send_message`, `message_log`, `report_issue`, `list_issues`, `comment_issue`), bus log, bus and issues topics; Codex observer; `talk-to-sessions` skill.
Built here, not yet installed (2026-10-01; scheduling and live use wait for the PC): triage (`relay_triage.py`, rules tested, Jev path waiting for the key); health check (`health_check.py`, dry run found real problems: gateway send timeouts, the hung DAPLink drive); history collector and search (`history/history.py`: 126k messages from 226 sessions ingested in 26 s, secrets masked including known secret values, hybrid search verified); backup packager (`history/backup.py`: first full package 385 MB, encrypted and verified to decrypt; upload waits for the R2 key).

Needed, in order:
1. Router as `relay`; fail-closed authorisation; action socket with uid check.
2. Durable inbound spool and outbox; Codex queue race fix; send timeout treated as unknown.
3. `report_issue`, `list_issues`, `comment_issue`; issues topic; health-check script and timer; Jev triage with rule fallback.
4. Publication flow, SHA-bound review status, per-repo merge serialisation.
5. Session registry with desired/observed state; resume by id; boot units.
6. Scheduler, status board, approvals, `cto` weekly proposals.
7. History collector, local SQLite (FTS5 + sqlite-vec) with local embeddings, daily encrypted backup, pruning.

## 14. Migration order

1. `relay` user, router hardening (work items 1–3), shared folders, COMPANY.md.
2. `ceo`, `cto`, `reviewer`, `support`.
3. Publication flow and registry (items 4–5).
4. Remaining agents one at a time.
5. History archive and search index.

## 15. Open items

1. Build on the Mac VM and migrate, or directly on the Windows PC.

## Appendix: verified facts (2026-10-01, Claude Code 2.1.287, Codex 0.159.3)

- Claude reads AGENTS.md natively (≥2.1.277); loads instructions from cwd and parents; `--add-dir` with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` loads that dir's CLAUDE.md; ignores `AGENTS.override.md`.
- Claude cross-session inbox; bypass-to-bypass delivers by default; script posts without a permission class are held unless `crossSessionInbound: "accept"`.
- Posting into a Claude session from an unrelated process: one JSON line `{"type":"user","message":{"role":"user","content":"..."}}` on `/tmp/cc-socks/<pid>.sock`; extra envelope fields (`from`, `from_mode`) are ignored, so the sender is carried in the router's header.
- Claude deletes transcripts after `cleanupPeriodDays` (default 30).
- `PreCompact` cannot run prompt or agent hooks.
- Codex: `--remote unix://…` attaches the TUI to the daemon; `-C` needed; `-c developer_instructions` ignored through the daemon; `AGENTS.override.md` replaces AGENTS.md at its level; skills from `.agents/skills` and `.codex/skills`; `codex queue` exists without an urgent flag; `turn/steer` is the steer path; hooks on, memories off; new MCP servers are picked up by the running daemon.
- Through the daemon, a second client receives every turn on a thread it has resumed, including turns started by other clients.
- macOS `pgrep` omits the caller's own ancestors; use `ps -A -o pid=,ppid=` for process trees.
- A linked worktree's `.git` is a file.
- Telegram: ~20 messages/minute per group; updates kept 24 hours.
- Cloudflare (2026-10-01): R2 free 10 GB-month, egress free, then $0.015/GB-month; D1 free 5 GB total and 100k rows written/day, Workers Paid $5/month includes 5 GB then $0.75/GB-month.

Reviews: `docs/reviews/2026-10-01-gpt-6-astra.md`, `docs/reviews/2026-10-01-gpt-6.1-sol.md`.
