# Handoff: Claude Code → Codex, topic "CC Relay" (Ai Dispatch, topic 816)

Written 2026-10-01 by the Claude Code session in `/Users/pouya/.openclaw/workspace/claude-code-relay`. Read this first, then `docs/agentic-pc-design.md`.

## What this project is now

Two things in one repo:
1. **The live relay** that connects Telegram topics to per-folder Claude Code / Codex sessions (runs today through OpenClaw).
2. **The design and first parts of the "Agentic PC"**: several role agents (ceo, cto, reviewer, support, firmware, …) as interactive sessions, messaging each other, visible from the phone, moving to a Windows PC (WSL2) without OpenClaw. The design doc is the source of truth: `docs/agentic-pc-design.md` (v6+).

## Where things live (important)

- **Live scripts run from `/Users/pouya/.openclaw/workspace/scripts/`**, not from this repo. Edit there, test, then copy into `claude-code-relay/scripts/`. When copying `claude-relay-send.py`, replace the absolute `STATE_DIR = "/Users/pouya/.openclaw/workspace/scripts/relay-work"` with the portable `os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay-work")`. The repo's `relay-claude-settings.json` is a sanitized template; never overwrite it with the live one.
- Runtime state: `scripts/relay-work/` (pins, backends, bus.jsonl, msg-ops.log, issues/). Never commit it.
- **This repo is PUBLIC on GitHub.** 14 local commits are unpushed; push only when Pouya says so. Scan for secrets before any commit (`gitleaks`, plus grep for the test bot token prefix `8735489806`).

## Built and working

| Piece | Files | State |
|---|---|---|
| ccrelayd: Telegram router without OpenClaw | `scripts/ccrelayd.py`, `scripts/relay_tg.py` | running as tmux `ccrelayd-test` on test bot @TheKhadangBot, group "Pouya and Khadang" (-1004320138859): topic 2 = Claude test (`ccrelay-test/claude`), topic 5 = Codex test (`ccrelay-test/codex`), 59 = bus, 77 = issues |
| ccrelay MCP server | `scripts/ccrelay_mcp.py` | registered for Claude (user scope) and Codex; tools: list_sessions, send_message, message_log, report_issue, list_issues, comment_issue. Tested Claude→Codex→Claude, 3 hops |
| Codex observer | `scripts/relay-codex-proto.py`, `claude-relay-send.py` watcher | stays attached via the daemon; mirrors ChatGPT-app turns ("📱") and peer messages ("📨") into the topic. Verified with Pouya |
| Triage | `scripts/relay_triage.py` | rules work; Jev via Vercel AI Gateway free tier waits for the key; rules are a floor Jev can only raise |
| Health check | `scripts/health_check.py` | dry run works; not scheduled |
| History DB + search | `history/history.py` | SQLite FTS5 + sqlite-vec, secrets masked; run with `uv run --python 3.12 --with sqlite-vec --with fastembed` (system Python can't load extensions) |
| Backup packager | `history/backup.py` | builds encrypted 7z packages; R2 upload waits for the key |
| WSL migration kit | `deploy/wsl/` | written, not run |

Only the two test topics run the newest watcher code; live topics pick it up on their next watcher restart.

## Waiting on Pouya

1. R2 key (bucket `agent-history`) and Vercel AI Gateway key (free tier, buy no credits). Store in `~/.config/ccrelay/r2.env` and `vercel.env`.
2. Bench Mac: `/Volumes/DAPLINK` (DAPLink probe, hub index 2) wedges macOS's FSKit FAT driver; Finder and LaunchServices hang. Fix needs `LABEL=DAPLINK none msdos rw,noauto` in the bench's `/etc/fstab` (sudo, Pouya).
3. Windows PC: SSH key `~/.ssh/wsl_pc_key` was generated; Pouya must enable OpenSSH on the PC and send username + IP. Then run `deploy/wsl/`.
4. Which bot after migration (JamshidBot vs Khadang).

## Next steps (agreed)

1. Build a real tool-switch handoff into the relay: on `cc model <other>` ask the current session to write a handoff (this file is the manual version), then prefix the next message to the new tool with it. `cc model cx` today keeps no context across tools.
2. Optionally roll the new watcher code out to live topics one at a time, and investigate the OpenClaw gateway send timeouts on topic 18 that the health check found.
3. Draft `COMPANY.md` for the agents.
4. On the PC: work list in design §13 (router as separate `relay` user, durable inbound spool + outbox with delivery receipts, publication flow, registry, scheduler, collector/backup/health timers), then acceptance tests §13a.

## Standing rules from Pouya (do not break)

- **Never kill or restart the Codex remote-control daemon.** `scripts/codex-remote-ensure.sh` only starts it when it is down.
- **Never touch the bench VPN** (sing-box on the bench Mac).
- **Never offer a band-aid as the fix**; find the mechanism. Label workarounds as workarounds.
- **Never drop a capability** to make a problem go away.
- Free-tier API keys are allowed; no paid API keys. Keys live only with the router, never in a session.
- Do not touch the `pooyamn/oracova` repo (ai-hil); its backup goes to `pooyamn/oracova-backup`.
- Pouya reads on a phone: short replies, lead with the result.

## Verified facts worth knowing (details in the design appendix)

- Claude inbox socket: one line `{"type":"user","message":{"role":"user","content":"..."}}` on `/tmp/cc-socks/<pid>.sock`; held unless the target has `crossSessionInbound: "accept"` (agent-wire's `from-mode` wrapper does not change that on 2.1.287).
- Codex: `codex --remote unix://~/.codex/app-server-control/app-server-control.sock -C <dir>`; `-c developer_instructions` is ignored through the daemon; use a generated `AGENTS.override.md` (role + repo AGENTS.md).
- macOS `pgrep` hides the caller's own ancestors; use `ps -A -o pid=,ppid=`.
- Claude deletes transcripts after `cleanupPeriodDays` (now set to 3650).

## Backups done today

All workspace projects pushed to private GitHub repos (ai-hil to `oracova-backup` only), agent config to `pooyamn/agent-config`, personal files to `pooyamn/home-files`, encrypted transcripts to `pooyamn/session-transcripts` (password in `~/.config/backup/transcripts-7z.pass`). Survey of 15 similar projects: `docs/research/2026-10-01-prior-art.md`.
