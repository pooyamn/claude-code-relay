# Agentic PC: design

Current execution priority, 2026-10-03: move the existing system and bench to the
PC, keep the same topics, replace Hamal with Khadang, and retire the Mac after
verification. The new infrastructure below is deferred, not a prerequisite for
that migration. Follow the [Mac to PC migration plan](mac-to-pc-migration.md).

Continuity decision, 2026-10-03: archive session histories as verified backups;
the new PC can start fresh native sessions from checked project handoffs and
preserved worktrees. Resuming old Mac session IDs is optional, not a migration
gate. Record the new PC IDs for normal operation and recovery; this does not
authorize silent fresh-session fallback after an uncertain failure.

Claude lifecycle requirement, 2026-10-07: Telegram router deployments must not
relaunch idle Claude workers or re-register Remote Control. Native streams,
one-shot initialization and event/intent journals belong to an independent
protected host, while router clients attach/detach. Reconnection must validate
the exact host/native process generation, native session and cloud mapping;
restore missed events and pending questions; preserve existing uncertainty
holds; and never replay user input. Only an explicit idle tool switch retires
a worker. A host/PC restart still needs guarded quiescent-history recovery;
router-only continuity does not prove crash/reboot or clean-machine recovery.
This is the personal-owner adapter, not company/role identity enforcement.
The PC cutover and actual router-only restart passed at 17:07Z: sixteen routes,
seven unchanged native worker generations and cloud mappings, no additional
Remote Control registrations and no input replay. See the
[lifecycle deployment evidence](mac-to-pc-migration.md#persistent-claude-workers-october-7).

Scope decision, October 3 at 11:19 PM PDT: Pouya excluded the local Qwen server
and its Ai Dispatch topic `10656`. Neither moves to the PC, and the topic is
not switched to Claude. Eight of thirteen required original topics are routed;
five required originals remain. Existing Qwen source files/backups are retained,
not deleted. Earlier fourteen-topic counts below are historical.

Current migration evidence, 2026-10-03 at 10:37 PM PDT: Khadang runs nine PC
routes, including eight of the fourteen original topics. All five Oracova PCBA
topics plus Hardware Lite and MPU6000-i9 are connected; six original routes,
bench relocation and independent remote recovery remain. The four inactive
Claude project transfers passed actual native handoff/tool-owner and exact-ID
continuity checks, with confirmed same-topic bubbles and Claude app enrollment.
At that cutover, router code and the paired Linux Codex daemon were unchanged. Three existing
Claude cloud mappings were confirmed unchanged and ready after an idle restart;
phone round trips, unattended restart/checkpoint refresh and daily off-machine
restoration are not yet accepted. Earlier dated
milestones below retain their historical scope; the larger infrastructure is
still deferred. [Latest migration record](mac-to-pc-migration.md#hardware-lite-and-mpu6000-i9-connected-october-3-at-10-37-pm-pdt).

UI update, October 3 at 10:57 PM PDT: Jamshid-style code blocks are restored
on all nine Khadang live bubbles, including DUT. Existing message IDs, bounded
tails, tool calls, goals and timers are preserved; native Claude app links stay
tappable. Confirmed Telegram receipts and fresh native reattachment are recorded
in the [formatting deployment evidence](mac-to-pc-migration.md#jamshid-style-bubbles-restored-october-3-at-10-57-pm-pdt).

UI clarification and deployment, October 3 at 11:45 PM PDT: only live progress
belongs in the code-block bubble. Freeze that bubble on completion, then send
a separate normally formatted final answer with clickable links and emphasis;
fence only actual code/tables. Long finals split without losing their beginning.
Tool start/completion updates one descriptive row; raw tool stdout and private
reasoning are not mirrored. Pending questions remain visible in the bounded
tail. Commands are explicitly unchanged, per Pouya. Windows checks and real DUT
formatting receipts are recorded in the
[progress/final deployment evidence](mac-to-pc-migration.md#jamshid-progress-and-separate-finals-restored-october-3-at-11-45-pm-pdt).

Goal reply rule, 2026-10-07: Codex may answer a human steering message in the
`commentary` channel while continuing the same goal turn. That reply must not
wait for a `final_answer` or goal completion. Track the observed native user
message boundary (from Telegram or the native app), emit the next completed
assistant reply as clean prose, and keep later background updates in the one
rolling bubble. Exclude already-streaming prose and internal goal continuation
messages; persist reply/outbox state, deduplicate item receipts, and hold unknown
deliveries without blind retry. Observed user messages are display boundaries,
not authenticated approval or permission to replay native input.

Status: v9, decisions in progress (2026-10-02). Incorporates Pouya's review decisions on local identities, relay update authorization, daily disaster recovery, tool-switch repair, evidence-based memory maintenance with passive inconsistency reporting, a builder in the first rollout with demand-driven management, a three-active-session cap with task-wide progress monitoring, subscription-aware pacing with a 10% owner reserve, evaluated GStack/GBrain integration, source-evaluated AX/Paperclip launch, ownership and continuity patterns, company-scoped human employees interacting with Khadang, and native Codex goal controls with a rolling-bubble indicator. Remaining review questions are listed in §15. These are target requirements, not claims that the live Mac relay already implements them. Owner: Pouya.
Target: Windows PC, WSL2 Ubuntu 24.04. Agent roles run under separate local security identities with private homes and runtime state; the router runs as `relay`. Pouya remains the owner and uses one GitHub account. The existing Mac deployment remains a migration source.

2026-10-03 deployment direction: Khadang is PC-only from now on. Its Mac test
poller/watchers are retired and the known plaintext Mac token file removed;
Hamal and the Mac native daemon stay unchanged. A separately protected Windows
owner-only migration adapter is being built, not accepted as the role/company
boundary above. Pouya explicitly requested full-access Codex and Claude native
user defaults on the PC; ordinary owner processes remain unable to read the
protected Khadang token or modify privileged router code. The Windows owner-only
adapter is now live for LG Magic Remote in topic 159: an inert native history
checkpoint precedes topic binding, actual tool output and PC-RELAY-OK reach one
rolling bubble, and a service restart resumes the exact thread/message without
another topic or model turn. The explicit native profile readback is full access
with approvals never. This is not company/role acceptance: native Claude, media,
all-source admission, goal recovery and boot/startup acceptance remain pending.
[Current PC cutover evidence](../pc-router/deployment-status.json).

2026-10-04 explicit personal-access exception: Pouya requested normal access
for Telegram account `199200674` (`@MJ_MN`) across all mapped topics. The PC
adapter now admits direct conversation/attachments from that numeric ID while
keeping slash controls, model switches and exact approvals owner-only. This is
an explicitly trusted personal allowlist, not company/project/role enforcement
or an isolated employee OS account: these requests still reach the existing
full-access owner-native sessions. Do not generalize this grant to other users
or companies. Bot/forward/proxy/unlisted/foreign-chat inputs remain denied.

2026-10-03 native remote milestone: both PC Codex and Claude Remote Control
report Connected as the non-elevated owner. Sign-in/single-instance supervisor
tasks are installed. Codex uses a **workaround for characterized Windows CLI
launch defects**: supported native app-server stdio plus remote-control RPC;
the stock daemon/foreground CLI commands are not fixed. Claude's dedicated
workspace trust and exact first-use consent are accepted. A separate protected,
deterministic SYSTEM availability task holds Windows system/execution power
requests, not a model agent; it prevents idle standby on AC without forcing the
TV/display on or overriding explicit sleep/thermal safety. Before-login,
auto-login, reboot, orphan/resume recovery, phone round trip and shared
Telegram/app transport remain acceptance gates. TV SIMPLINK/HDMI-CEC must be
disabled in both directions; its settings service denied remote access, so the
owner setting and TV-off/PC-online test remain pending. The Windows thermal
event label is not proof of overheating; preserve raw events, owner evidence
and measured temperatures separately rather than classifying every sleep as
thermal.

2026-10-03 shared native transport test: two authenticated clients can share one
pinned Windows native app-server over a loopback-only bearer-protected
WebSocket; missing/wrong credentials are rejected. The actual one-shot owner
test used an empty, credential-free native home with no thread/model/remote
enrollment or Telegram activity. Existing native processes and LG bubble,
receipts, router policy and VPN/LG stayed unchanged. This is a verified
**experimental/unsupported transport primitive**, not live phone continuity or
company identity. A reviewed shared adapter and event ownership, owner-private
pairing, phone-to-exact-bubble acceptance and all-source admission remain gates;
never expose pairing secrets in employee-accessible topics or restart existing
native remotes to force migration.
[Evidence and protected next step](pr6-telegram-outbound.md#actual-windows-shared-transport-primitive-2026-10-03).

2026-10-03 shared event milestone: the candidate native RPC layer can use the
same durable protocol over stdio or bounded WebSocket framing. An actual
credential-free Windows test confirms cross-client paused-goal update/clear
notifications and matching reads on one checkpointed diagnostic thread, without
inference or touching live owner state. 353 local/356 Windows candidate checks
and twenty method guards pass. The candidate is **not live**; the existing
private stdio service/remotes/bubble and VPN/LG remain unchanged. A bearer proves
client access, not server/role identity: protected server/launcher authentication,
independent daemon ownership and exact-version security review are required
before shared live wiring, followed by private native phone pairing and actual
phone-to-bubble/recovery/admission acceptance.
[Working component, evidence and activation gates](pr6-telegram-outbound.md#shared-framing-and-native-goal-event-acceptance-2026-10-03).

2026-10-03 protected peer milestone: an inactive Windows pipe component now
joins kernel peer PID to the exact protected SYSTEM/session-0 process token,
held generation and executable/artifact evidence on both ends. Real Windows
tests reject forged peer pins and the ordinary owner, and keep the same listener
generation through two client disconnects. The installed service/remotes/bubble
and VPN/LG remain unchanged. This is not company-role isolation or native-daemon
lifetime: protected lease/custody integration, exact-version security review,
private native phone pairing and real continuity/recovery/admission gates remain.
[Mechanism, actual proof and limits](pr6-telegram-outbound.md#protected-windows-pipe-peer-component-2026-10-03).

2026-10-03 native custody milestone: an inactive broker core owns native stdio,
initialization and a separate durable intent/event/request journal independently
of attached clients. 394 local/397 Windows checks and twelve probe guards pass.
A protected credential-free Windows fixture proves client A can exit, paused-
goal/clear events persist while no client is attached, and replacement client B
reaches the same non-elevated native process with matching events/readback: one
initialization, zero unknown diagnostic intents. The live router/remotes and
VPN/LG stay unchanged. This is not a deployed always-on broker, crash/reboot
recovery, company identity or phone acceptance. Production facade/lease/service,
request shutdown/reconciliation, exact-version security review, private native
pairing, all-source reserve admission and backup-cohort integration remain gates.
[Mechanism and actual client-replacement proof](pr6-telegram-outbound.md#native-broker-custody-and-client-replacement-acceptance-2026-10-03).

2026-10-03 native request hardening: reproduced premature journal closure and
missing-thread failures are fixed in the inactive broker core. Shutdown joins
in-flight reply settlement and retains native cleanup; connection-scoped requests
are separate from thread approvals, with exact-frame validation and no automatic
credential handler. 415 local/418 Windows checks and a fresh credential-free
native client-replacement test pass. Live code, remotes, bubble and nine services
stay unchanged. Production request-handler/lease/service integration and review,
phone/all-source admission, company identity and full-system recovery are still
pending; synthetic request tests are not real OAuth or crash/reboot acceptance.
[Regression evidence and exact Windows candidate](pr6-telegram-outbound.md#native-request-custody-and-shutdown-regression-fixes).

2026-10-03 journal ownership milestone: the inactive native broker acquires its
exclusive kernel journal lease before SQLite recovery or native launch. 420 local
and 423 Windows checks pass; a separate protected Windows contender is rejected
before its launcher callback and cannot rewrite the live epoch/attempt sentinel.
The same native client-replacement/goal-event proof passes without production
changes. This is not the live router facade or complete launch/orphan registry;
service/review, native phone continuity, company/admission and full recovery
gates remain required.
[Mechanism and exact Windows proof](pr6-telegram-outbound.md#exclusive-broker-journal-ownership--2026-10-03).

2026-10-03 broker wire milestone: the inactive pinned Windows pipe now carries
broker-owned native calls, complete event pages and reviewed thread requests.
488 local/491 Windows checks pass. Separate actual Windows clients perform their
calls/event reads through the wire; replacement receives missed paused-goal/
clear events from the same non-elevated native generation, with one handshake
and zero unknown diagnostic calls. Live router/remotes, binding/bubble and nine
services stay unchanged. This is not a deployed `INative` facade or always-on
broker, nor phone/company/admission or crash/reboot acceptance; protected
registry/service/review and the full recovery gates remain required.
[Exact wire proof and remaining integration](pr6-telegram-outbound.md#protected-broker-to-router-wire-component--2026-10-03).

2026-10-03 startup configuration: `Oracova-KhadangStartup` is a protected
deterministic SYSTEM task with boot, owner-logon and minute triggers. SCM stays
Manual: a stopped router may start only after the exact non-elevated physical
console owner token is available and reviewed router/policy hashes match the
isolation probe. Running/transitioning services are left untouched. The running
service no-effect check and independent read-only owner-token and LSA/code
denial probes pass; native remote processes, thread, bubble and turn count stay
unchanged. A stopped-service start and reboot have **not** been accepted.
Auto-login remains disabled: Windows already has an LSA secret that differs
from the validated current owner password. The guarded helper preserved it and
the existing registry state; owner approval to replace it with an encrypted
rollback copy is pending. Prefer documented
[LSA Winlogon secret storage](https://learn.microsoft.com/en-us/windows/win32/secauthn/protecting-the-automatic-logon-password),
not plaintext registry values or password command arguments. LSA does not hide
the password from administrators, and auto-login exposes the unlocked owner
desktop to physical access. Official OpenAI guidance requires an awake,
signed-in host and an unlocked Windows desktop for Computer Use; configured
tasks alone do not establish native phone pairing or reboot recovery.
[Remote host requirements](https://learn.chatgpt.com/docs/remote-connections).

2026-10-03 PC goal/control update: owner-only Khadang now reads the exact native
goal on recovery, handles updated/cleared notifications and stale replies, and
keeps control replies in the existing rolling bubble. Status no longer sets an
objective named "status"; status-only pause/resume preserve native accounting
and do not assert that running tools stopped. The LG thread currently has no
native goal. 77 joined/offline checks pass on Mac and Windows, with actual
no-inference goal-read and idle restart evidence; live owner mutations,
active-goal UI and all-source continuation admission remain gates. Native
remote processes and VPN/LG services stayed running. An initial runtime-package
mismatch was rolled back; the corrected self-contained release is live and
deployment now validates Windows candidates before stopping the service.
[PC goal evidence and limits](codex-goals.md#pc-owner-only-adapter--2026-10-03).

2026-10-03 quota-observation milestone: PC Khadang adds a read-only `/limits`
command in the same rolling bubble and native menu. An actual native read
verified the active/backend account identity and reported 22% used in a
10080-minute window; no secondary window was supplied. 136 checks pass locally
and on Windows, including a pending quota read that does not block owner
interrupt requests/status. Native remotes, VPN/LG, exact thread and bubble stay intact;
no model turn or paid reset was issued by this check. Account-wide updates now
invalidate stale observations before thread routing. This is not 10% reserve
enforcement or completed PR 9: bounded costs/coverage, Claude/account/model
pool applicability, approved pacing and all-source pre-turn fences remain gates.
[Observer mechanism, evidence and limits](pr9-model-admission.md#pc-read-only-native-observer-2026-10-03).

2026-10-03 inbound media milestone: the PC owner-only adapter stages direct-owner
photos/files and captions in a content-hashed, read-only cache. Supported image
signatures map to documented native localImage input; other files retain paths
and metadata without automatic execution or invented transcripts. Delayed
downloads do not lock owner controls, and ended steering turns never become new
turns. 254 local/257 Windows checks pass; a real non-elevated native worker reads
the exact cache fixture and is denied both overwrite and sibling-file creation,
while token/code protection remains intact. A one-shot generated PNG round trip
now proves identical Telegram download bytes and real native image interpretation
without observed tools, uncertain actions or LG bubble changes. Its startup quota
race was characterized and fixed with one new observation only after revision
invalidation; continuing races remain stale. Real owner photo intake/active
steering, albums/large files/transcription, company access, global admission and
portable switch/restore remain acceptance gates. Those requirements stay in scope.
[Attachment mechanism and remaining gates](pr6-telegram-outbound.md#pc-owner-only-inbound-attachments-2026-10-03).

## 1. Goals and constraints

Goals
- Several agents on one PC, each with its own role, skills and memory.
- Each repo has its own instructions and project memory.
- Any session can switch between Claude Code and Codex without losing its working state.
- Sessions can message each other, and Pouya can see all of it.
- The platform maintains itself: agents report problems, a support agent fixes them, the CTO proposes improvements.
- Every session's history is kept for future reference.
- Everything works from a phone.
- Human employees from different companies can interact with Khadang in their authorized Telegram forum topics, not only Pouya.

Constraints
- Claude and ChatGPT subscriptions for all agent work. No paid API keys; free-tier keys are fine (held by `relay`, never in a session).
- Agents are interactive sessions in tmux, not `claude -p` or one-shot runs.
- Phone access through the Telegram router (ccrelayd) and the Claude Code and Codex remote-control apps.
- Migrate gradually, one agent at a time.

Threat model: one platform owner, multiple companies and human participants. Pouya is the trusted platform owner; company employees are separately authenticated, scoped participants, not implicit owners. Risks include mistakes, prompt injection (from web pages, documents, other sessions and human messages), impersonation and cross-company disclosure. A compromised worker or employee must not acquire another company or role's authority, impersonate the reviewer or CTO, change privileged policy, or deploy code that gains the router's credentials. Cooperation does not grant access to another identity or its controls.

## 2. Model

- **Agent**: a role. Instructions, skills, role memory, the paths it owns.
- **Session**: one live conversation of an agent on one task, in Claude Code or Codex. Id `<agent>.<task>`. An agent can have several sessions.
- **Company**: an authorization and information boundary with a stable `company_id`, projects, topics, members and scoped agent roles. Human membership can span companies only through separate explicit grants.
- **Human employee**: a stable human principal, mapped to verified Telegram numeric user ID and explicit company/project/topic permissions. An employee is not an agent role, a model subscription account, or the platform owner.
- Sessions talk to sessions through ccrelay. One Telegram bot carries all traffic.
- Plain files are the source of truth for instructions and curated memory. Operational databases/ledgers and derived retrieval views have the explicit roles described below. Built-in memory is off: Claude `autoMemoryEnabled: false`; Codex `memories` (already off; pin with `codex features disable memories`).

### Human employees and company boundaries

Khadang serves authorized company employees as well as Pouya. A company-owned forum topic binds an exact Telegram chat/topic to its company, project and native session. Telegram display names, usernames, joining a group, a folder, forwarded text and a message claiming "Pouya approved" do not establish membership or authority. Authenticate the transport sender and check current protected membership grants on every input and control action; unknown participants receive no model/session access.

Employees can ask questions, supply project evidence and direct work in their assigned topics under explicit grants. Steering an active turn requires both topic/task permission and the current expected turn ID; the human sender stays attributed in the durable input ledger, handoffs and audit trail. Another employee cannot take over a task merely by posting in its forum. Employee messages do not inherit Pouya's owner priority or the 10% owner reserve. They use the company task lane and applicable shared provider/account budget, without exposing subscription credentials.

Pouya retains platform ownership, protected-policy/deployment authority and access to the owner reserve. Company administrators or approval roles exist only through an explicit delegated grant. Ordinary employee participation does not authorize GitHub publication/merge, external actions, privileged approvals, bot wiring, membership changes, credential access or access to another company. Approval evidence binds the actual authenticated human, company, action and artifact revision; conversation with a reviewer never substitutes for that evidence.

Carry `company_id` through registry/session identity, task roots, messages, action approvals, issue tracking, memory/decisions, handoffs, retrieval/history, artifacts and backup/restore permissions. The shared paths described below are templates within each company's protected namespace, not a global readable company corpus. Select only the admitted session's company/project context. Keep Pouya's private/control-plane memory separate; no employee-facing topic loads it. Publication credentials remain router-held and restricted by company/project authorization even when one underlying GitHub account can access several repositories. Cross-company messages or sharing require explicit grants and recipient revalidation; do not forward another company's transcript, source, search results or issues by default.

Membership is protected configuration with grant/revocation audit history, not an agent-editable allowlist. Revocation fences queued work, future steering, output delivery, retrieval and pending approvals, while retaining records under company policy. Creating or transferring a topic must not silently transfer its old history or authority to another company. Company scopes and membership enforcement must pass the acceptance gate before enabling employee access. The current live Mac bot allowlists, bindings and credentials are unchanged by this design update; onboarding and employee trigger/approval policies remain open in §15.

### Agents

v1: `builder`, `reviewer`, `support`, with `ceo` and `cto` role profiles and security identities available on demand. The builder delivers the first scoped production task; its repo, domain skills, and owned paths are assigned for that task. Then add specialist roles one at a time: `researcher`, `firmware`, `backend`, `frontend`, `pcb-schematic`, `pcb-routing`, `art-director`.

CEO/CTO coordination is demand-driven: direction decisions, architecture or ownership conflicts, merge requests, and scheduled improvement reviews. Routine implementation does not require a CEO → CTO delegation chain. Independent reviewer approval and the authenticated CTO merge request remain mandatory; on-demand management does not bypass publication or security gates.

| Agent | Owns |
|---|---|
| `builder` | implementation, tests, and reproducible evidence for the assigned repo/component; no self-review or merge authority |
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
- Every fact file has frontmatter: stable `id`, `date`, authenticated `session`, `scope`, evidence references, validity conditions, and status (`proposed`, `verified`, `disputed`, or `superseded`); repo facts also carry `commit`. A repo fact from an unmerged branch is marked `unmerged` and is promoted only after its PR merges.
- Decisions > company > repo > agent remains the authority order for instructions in the same scope. Timestamps do not establish factual correctness. Conflicting facts are flagged and checked against evidence; the index identifies the dispute rather than silently selecting the newest entry.
- Agents append proposals under their own identity. A curator for each scope reconciles canonical facts through the router; worker access to shared memory does not permit changing approved company decisions or another role's memory. Index generation and canonical updates are serialized per scope and retain an audit trail.
- Corrections explicitly identify the facts they supersede and the evidence supporting the change. Superseded entries remain recoverable. An unresolved conflict goes to the responsible agent and stays marked disputed; no unsupported choice is promoted as verified.
- Loading: company and the decisions index load in every session. Agent and repo indexes load at session start (instructed in AGENTS.md); individual fact files are read on demand.
- Handoffs are per session and written at checkpoints (every publish, hand-back, tool switch). Freshness checks cover HEAD, dirty and untracked files, pending actions, and task progress; a last-commit timestamp alone is insufficient.

Maintenance
- Task completion and new evidence trigger reconciliation of affected facts. A nightly job catches missed updates and scans for duplicates, stale evidence, invalid scope, and inconsistencies.
- A deterministic scan runs first. A maintenance agent reads only changed or flagged entries; a quiet scan does not start model work. Evidence-backed corrections and index updates can apply automatically within the curator's authority, with a recorded rationale.
- Pouya receives a passive, silent nightly digest when inconsistencies are found, including those resolved automatically. Each item links to the conflicting facts and evidence, responsible agent, and resolution or open status. Repeated unchanged conflicts are coalesced. The digest does not demand approval or pause unrelated work.
- Memory maintenance preserves fact history and obeys the authorization boundaries for company decisions and security policy. Backup captures the canonical records, proposals, indexes, disputes, and maintenance audit trail.

### GBrain: controlled memory retrieval

Evaluation supports using GBrain as a local memory projection/retrieval service, not as the authority for facts, roles, approvals, or task state. At the tested revision, 150 upstream checks passed and two synthetic probes reproduced important correctness mismatches; ten Windows-only checks were skipped. The evidence and limits are recorded in [the evaluation](research/2026-10-01-gstack-gbrain-evaluation.md).

- Canonical fact/decision files remain authoritative. The router projects their stable IDs, scope, evidence, status, revisions, and explicit correction/withdrawal relations into GBrain; retrieval links back to those records. Publication uses durable change/request IDs and a replayable projection outbox. A stale projection is reported as stale, never used to silently reverse a canonical correction. Withdrawal tombstones and dispute history survive rebuilds and restore.
- Run a single local PGLite-backed service under a dedicated protected identity. Agents cannot read its database/configuration, run its privileged local CLI, or acquire a shared administrator credential. The authenticated router is the only agent-facing entry point; it constrains source grants and allowed operations per role/session. Do not use legacy no-grant federation as a worker grant. Folder/source dotfiles are routing hints, not authentication.
- Agents query allowed memory and submit proposals under their own identity; the scope's authorized curator publishes canonical updates. Do not expose unrestricted `remember`, `forget`, database administration, arbitrary filesystem operations, or autonomous-job controls to workers. Backend grants enforce source/operation ceilings; the broker additionally enforces our fact-status/evidence rules and labels proposals/disputes rather than presenting them as verified instructions. GBrain's `private` visibility means local-only, not role-private, so role privacy requires independent source grants and protected storage.
- Upstream `remember` accepts free-text provenance, defaults to `world`, and can supersede changed text on embedding similarity alone. In keyless mode it skips semantic deduplication. Neither behavior proves a correction: canonical promotion/supersession still requires the evidence checks and explicit links above. Do not feed canonical records through an automatic similarity-based replacement path.
- Start keyless with deterministic retrieval and bounded context packing. Preserve local semantic search through QMD (§11); adding a local GBrain embedding provider requires a target-runtime compatibility/quality test and must not weaken canonical-write policy. No automatic cloud embedding/reranking, standalone API-backed synthesis/dream/extraction, or unadmitted model work. Our existing quota-managed sessions perform any model-assisted curation, under the 10% owner reserve and task limits.
- Pin reviewed GBrain code, runtime, dependencies, and schema expectations. Lifecycle migrations run only as an approved deployment step after a consistent snapshot, not opportunistically in an agent install. Snapshot its complete store, receipts, withdrawals and configuration in the daily encrypted recovery package (§10); a Markdown export alone is insufficient. Target WSL isolation, concurrency, compatibility and restore tests remain mandatory before live use.

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

Global wiring (generated separately for each role's private home)
- `~/.claude/CLAUDE.md` imports shared AGENTS.md, COMPANY.md and the decisions index.
- `~/.codex/AGENTS.md` is a generated concatenation of the same, rebuilt on change.
- Claude `instructionFiles: "claude-md-and-agents-md"`, `crossSessionInbound: "accept"`, `cleanupPeriodDays: 3650`.
- ccrelay MCP server registered for both tools (Claude user scope, Codex `codex mcp add`).
- Custom skills have one canonical source per scope, published as per-skill links
  in both `.claude/skills` and `.agents/skills`; this pinned PC also retains
  `.codex/skills` discovery compatibility. Keep project skills project-scoped,
  and leave bundled, synced and plugin-managed skills with their providers.
  New/updated skills must be validated and published for both tools, not copied
  independently into one tool's home.
- Khadang topic creation/enrollment requests from other sessions use ccrelay
  messaging to `claude-code-relay` (CC Relay). The controller verifies the original
  human request, creates/binds once, and replies with the result; the destination
  remains the requesting topic's forum unless the human explicitly chose another.

The personal-PC implementation is `scripts/skills-layout.json`,
`scripts/publish_skills.py` and the `shared-skills` skill. Native Windows uses a
byte-verified generated mirror and directory junctions; republishing admits only
unchanged previously managed entries, retaining the old mirror and restore
records. WSL sources remain authoritative. This is owner-level file discovery,
not role authentication or a deployment/approval grant; future isolated roles
still receive only their admitted skills through protected homes.

The shared tree is router-managed, with read access and scoped proposal submission for agents. Each role's home, runtime sockets, authentication material, and worktrees are protected from other roles. Global instructions and role definitions cannot be rewritten by an ordinary session to acquire privileges. Legacy `/Users/pouya` paths must be migrated deliberately; a common writable home would defeat identity isolation.

### GStack: on-demand workflow methods

Source evaluation supports adapting selected GStack methods, not installing its entire stock automation. Use engineering-plan review for on-demand CTO work, risk-focused checklists for the reviewer, investigation for support, and explicit QA charters/reports for builder/reviewer validation. These are skills of existing roles, not additional always-running agents. Runtime/quality validation remains pending; see [the evaluation](research/2026-10-01-gstack-gbrain-evaluation.md).

- The reviewer reports findings against the exact candidate without auto-editing it. The builder implements fixes, then review is rerun on the new SHA. GStack's default fix-first review must be adapted to preserve independence.
- Outside opinions and specialist work go through admitted native interactive sessions and the same root-task budget, three-active-session cap, and subscription pacing. Stock direct CLI invocations or parallel reviewer launches cannot bypass admission. Use additional perspectives when the task/risk warrants them, not a compulsory management chain on every change.
- Shipping still uses the router's publication, reviewer/CTO gates, and owner approvals. No skill gains a direct GitHub credential or permission to push, merge, deploy, or approve its own changes.
- Vendor/adapt only reviewed, pinned assets with license notices preserved; upgrades follow normal reviewed deployment. No silent team auto-update, external telemetry/artifact sync, or broad GBrain setup. Browser QA uses isolated test profiles/fixtures; access to Pouya's logged-in browser or real external actions requires explicit scope and existing authorization.

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

Launch contract (AX-inspired; local implementation, not a cluster dependency)

- A versioned, protected manifest resolves role/session identity, repo/worktree and baseline SHA, pinned runtime/adapter versions, instructions/skills/MCP references, allowed paths and permissions, and a resource profile. Reject unknown fields and unsupported controls; persist its admitted digest. Bootstrap is deterministic; any model-assisted setup is separately admitted under the same task budget. Reusing a dirty worktree never runs forced initialization checkout.
- Different role UIDs must not share writable Git metadata. A worktree's private directory alone does not isolate its common Git directory, refs or configuration. Use role-private repository metadata for local worktrees; protected publication transfers reviewed commits without exposing another role's writable checkout. Verify the actual filesystem topology rather than trusting a manifest path.
- Verify identity, workspace setup, runtime capabilities and enforced permissions before admitting a turn. Record readiness conditions with reason, observation time and manifest digest. Failed setup or a missing runtime capability stays not-ready; never substitute a default or less-restricted profile. Process liveness/readiness is not task completion.
- Enforce configured CPU/RAM/process limits through WSL systemd/cgroups, including detached descendants and ongoing tools. Track resource-limit failures as evidenced issues while preserving work. Resource accounting is separate from subscription quota and the three-active-session cap; numeric profiles require target-PC measurements.

Ownership
- Each agent's AGENTS.md lists the paths it owns. Changing another agent's paths goes through that agent or `cto`.
- Unmergeable artifacts (KiCad board, schematic, BOM of one revision) are leased per session (`ccrelay.lease`), checked when the session publishes.
- Each work item is atomically checked out against expected state, assignee and execution/run ID under its root task; unresolved dependencies block execution. Continuing accountable ownership is distinct from the active execution lease and global activity slot. Same-run replay is idempotent; competing runs cannot both claim the item. Delegators may release an activity slot while retaining responsibility, but cannot leave overlapping writers.
- The broker fences stale execution IDs on task updates, publication and external actions. Transfer of a worktree also requires trusted proof that its previous writer and descendants have stopped or quiesced (process start identity and unit/cgroup state); an expired timer or terminal database row alone is insufficient. Reassignment preserves root budgets, evidence, approvals and uncertain-action reconciliation.

Native goals (requested 2026-10-02; protected PC integration pending)

- Support `/goal <objective>` (also `/goal set <objective>`), `/goal status`, `/goal pause`, `/goal resume` and `/goal clear` from Telegram, with `cc goal …` aliases for gateways that intercept slash commands. Commands go to the native controller, never to a model as conversational text. Use the existing topic's exact thread; no silent fresh-thread/backend/API fallback. Status and changes in the native app synchronize through thread-scoped goal notifications and an initial native read.
- Codex documents thread-scoped goals and native get/set/clear RPCs. Status-only updates omit objective/budget so pause/resume preserve accounting; an explicitly new objective may reset native accounting. [Native goal guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex), [app-server contract](https://learn.chatgpt.com/docs/app-server). Root-task counters, deadlines, uncertain actions and approvals never reset with a goal replacement or clear.
- Show a compact verified goal state and objective beneath `Working (elapsed)` in the same rolling Telegram text message. Retain the latest work, sanitize/redact the goal, and reserve space for both footer lines within Telegram's limit. Display paused, blocked, usage-limited, budget-limited and complete distinctly; unavailable native evidence must not appear as active. A goal can remain active between turns; `Done` for a turn is not completion of its goal.
- Goal pause suppresses automatic continuation; it does not establish that the current turn/tools or detached descendants have stopped. Interrupt/stop remains a separate control with its own acknowledgment and writer verification. Goal resume may start autonomous work, so it needs current human/company/project/topic authority and the same pre-turn admission, three-session cap, pacing and owner-reserve gates as other execution. Employees receive only explicit company-scoped goal permissions, not platform-owner controls. Unsupported Claude/native capabilities require a compatible admitted controller, not simulated success.
- Persist exact-thread control intent before dispatch. Lost/ambiguous acknowledgments remain held across restart; inspect authoritative native state instead of replaying mutations. Rebinding, revocation and stale capabilities fence queued controls. Include the command journal, bindings and native goal state/accounting in full-system backup; restoration reconciles desired goal state before any continuation. Goal completion remains subject to the root's evidence/acceptance gates.
- The legacy Mac adapter has offline goal/control/UI tests and a read-only installed-daemon probe, not protected PC authority or native continuation admission. A separately deployed Khadang test release now has verified command registration and an exact native goal read, with Hamal unchanged. Human control/UI receipts, role-isolated runtime compatibility and recovery remain gates. [Implementation and limits](codex-goals.md).

Native Telegram command discovery (requested 2026-10-02)

- Register supported session controls directly as bot commands, without requiring the `cc` prefix. Generate the catalog from the admitted tool/adapter's capabilities, not every native CLI command. Claude `/clear` and Codex `/goal` are distinct controls; unsupported commands are rejected rather than becoming model prompts. Preserve `cc …` aliases for other ingress paths.
- Telegram's command scopes include chats and members, not forum topics. Use tool-specific menus for homogeneous chats and a stable labeled union for mixed Codex/Claude forums, plus current-topic `/help`. Never let the last-used topic change another topic's menu or controls. [Telegram command scopes](https://core.telegram.org/bots/api#botcommandscope).
- Publish menus for authorized principals without granting authority through visibility. Recheck authenticated human/company/project/topic grants, exact binding and current adapter at execution. Normalize this bot's `@username` suffix; ignore commands addressed to another bot. Discovery/configuration uses the protected scheduler on the PC, independently of model admission and without blocking stop/steering.
- Preserve unrelated configured commands/scopes and verify configuration readback. Stale menus, language overrides or lost menu acknowledgments cannot imply control success. Full recovery includes managed configuration; restore must revalidate grants/capabilities before publishing controls. [Legacy preparation and live activation limits](native-telegram-commands.md). No HamalBot wiring or live employee permissions are changed.

Activity limits and progress (initial watchdog policy; task budgets/deadlines pending)
- At most three sessions actively work at once across all roles. Idle interactive sessions do not count. An executing turn or its ongoing tools do count; a session waiting for another agent releases its slot. Admission is enforced before execution through the trusted launcher/runtime adapters, including native-app, Telegram, inter-session, maintenance, and recovery turns. Observing turns after they start is not sufficient enforcement.
- Each top-level task receives a router-issued root ID, one accountable owner, acceptance criteria, and a durable progress/budget ledger. Delegated subtasks inherit the root. New message chains, omitted `reply_to`, renamed tasks, new sessions, tool switches, and restarts do not reset its counters. An agent cannot mint a new top-level task to escape the original budget.
- An agent's `done` is a completion proposal: the controller checks deliverable/evidence references and the applicable acceptance/review gates before recording completion. Process exit, readiness and unsupported prose claims cannot establish success.
- Before delegation, record the specific question or deliverable, receiving owner, expected evidence, and next milestone. Each result records what changed and references inspectable evidence: an artifact/diff, reproducible test or measurement, an evidenced review finding, or an experiment that rules out a hypothesis. Failed experiments can be progress when they narrow the problem.
- Message volume, acknowledgments, repeated plans, changing assignees, fresh commits without a relevant outcome, and unsupported claims of progress do not count. Evidence references are checked against the task's criteria and prior checkpoint; artifact churn or repeating the same result must not refresh the progress window.
- A deterministic monitor tracks repeated delegation cycles, unchanged evidence/milestones, elapsed time since verified progress, and aggregate activity. It wakes an independent agent only for ambiguous or flagged findings. Semantic relevance is not proven by a changed hash; ambiguous progress remains unverified rather than automatically resetting the counters.
- Keep the watchdog as the initial policy: three consecutive completed handoffs without verified progress trigger the hold-and-diagnose path below. Count assessed delegation results, not every message or an operation still in flight. The threshold is configurable through approved policy and recorded with each task's ledger; new message chains cannot reset it. Tune it from observed incidents rather than treating the initial value as permanently optimal.
- Persist a diagnosis fingerprint of material task/ownership/blocker/wait state and verified evidence/milestone revisions. Cosmetic updates and repeated messages do not cause another model diagnosis; new relevant evidence does. Revalidate the fingerprint and current authority before applying diagnostic actions; reject stale results. This strengthens the same initial watchdog, not a second always-running management loop, and does not reset its counters or budget.
- Each root has finite execution/delegation budgets, a deadline or next-checkpoint deadline, and a no-progress threshold, configured before autonomous work. Use measured quota where the runtime exposes it and bounded turn/attempt counts otherwise; do not claim exact token accounting when unavailable. Every child and diagnostic attempt charges the same root, including fresh message chains.
- A long-running build, measurement, or external wait has an explicit expected checkpoint and operation state. Lack of a new commit alone does not establish a loop; waiting must not trigger repeated delegation or unnecessary model wakes.
- At a no-progress threshold or budget/deadline exhaustion, hold further automatic delegation for that task and preserve its work. Assign one bounded diagnosis to the accountable owner (support for a relay mechanism bug), using a preallocated diagnostic budget within the same three-session cap. Record the cause and a concrete evidence-producing next step; resume only within the remaining authorized budget. Budget extensions require Pouya's approval, and further diagnosis cannot recursively grant itself more budget. Only verified progress resets the no-progress window.
- Report detected stalls, diagnosis, and resolution to Pouya passively in the Issues topic, with task/evidence links and spent budget; coalesce unchanged repeats. Unrelated tasks continue. Security or P1 incidents retain their normal alert policy. This circuit breaker contains wasted work while diagnosis fixes the cause; pausing is not presented as the fix or as abandoning the task.

Subscription-aware pacing (10% owner reserve approved; initial gap pending)
- Introduce configurable minimum spacing between automated agent starts/handoffs, plus adaptive admission based on remaining allowance and time to reset. A single durable scheduler owns this pacing; independent sessions cannot each spend the same reported allowance. Keep the three-active-session ceiling, but allow fewer active sessions when the budget is tight.
- Track capacity by provider and subscription account, not local role UID. All sessions using that account share its pacing state. Apply every reported quota window or model-specific pool, using the most restrictive applicable allowance. Store quota observations with their timestamp/source, estimated burn rate, in-flight usage reservations, cooldowns, and queued work's next eligible time; restart, new roles, or new message chains cannot reset them.
- Reserve 10% of each applicable subscription allowance for Pouya's direct use; automation may use at most the other 90%, subject to actual remaining capacity and conservative in-flight estimates. This is 10% of the quota window's allowance, not 10% of whatever remains at each check. Autonomous support/urgent repair does not spend Pouya's reserve without his explicit authorization. Spread automated capacity across the remaining window; increase spacing and defer background coordination/maintenance when consumption outpaces the target. The initial gap remains to be chosen (§15); neither an account tier nor a fixed number of turns per window is assumed.
- Use a compatible documented status/usage adapter where available. Missing or stale telemetry falls back only through the explicitly enrolled, bounded conservative-estimate path, not invented remaining-quota figures. OpenAI documents variable per-task consumption and remaining limits through the usage dashboard or CLI `/status`. The PC's pinned 0.160.0 native read-only adapter now also verifies the [app-server quota protocol](https://learn.chatgpt.com/docs/app-server); observations alone do not prove bounded future cost or enforce reserve admission. [Estimate and observer gates](pr9-model-admission.md#pc-read-only-native-observer-2026-10-03).
- Quota adapters return typed windows, reset times, provider/account identity, observation source/time and explicit errors, with bounded polling and per-provider failure isolation. Probes are privileged, read-only and outside model sessions; workers do not receive subscription tokens. Paperclip's RPC/usage adapters are prior art, not authorization to discover host credentials or depend on unverified internal endpoints. Pin compatibility and verify account provenance; quota display and recorded dollar spending do not enforce our admission/reserve policy.
- A fixed delay alone cannot guarantee avoiding the limit: one extended turn or activity outside the relay can consume substantial allowance. Prefer bounded evidence-producing work checkpoints and refresh usage before further admission. Defer new automated model work on observed exhaustion until provider-reported availability/reset is confirmed, preserving handoffs and pending actions; do not repeatedly wake agents or replay uncertain external actions to probe the limit. Do not enable paid credits, API fallback, or plan upgrades automatically.
- Persist incoming messages immediately; pacing delays model execution, not durable intake or the delivery log. Owner steering into an active turn and stop/pause controls remain responsive. Owner-requested new turns get priority and access to his reserve within the same concurrency cap and actual available allowance. Autonomous urgent repair gets priority within the automated budget; using the owner reserve requires Pouya's explicit authorization. Required review and security gates are never skipped to save quota.
- Mark quota/pace waits explicitly with their reason and next eligible time. They do not consume execution budget, count as no-progress handoffs, or trigger a delegation-loop diagnosis merely because no work started. Absolute owner deadlines remain visible; report a threatened deadline rather than resetting it. Passively show pacing, telemetry uncertainty, deferred tasks, and expected resumption in the status/Issues topics.

Model capacity retries
- Automatically retry temporary model-capacity rejection through the same durable provider/account scheduler, scoped further to the affected model. Preserve the work, native session, root and retry history. Capacity errors are distinct from subscription exhaustion, authentication, configuration errors and uncertain delivery; do not classify ordinary message text or every 429/5xx as retryable capacity.
- Honor a verified provider retry time as a minimum. Otherwise use configurable increasing backoff with bounded random jitter, maximum retries and maximum elapsed time, also limited by the original root/checkpoint deadline. Never shorten a provider wait to fit a local cap. Persist failure evidence, counters, next eligible time and the stable retry proposal before acting; restarts, new roles and new message chains cannot reset them. Retry settings remain explicit policy choices, not hard-coded live defaults.
- Retry only a proven unaccepted request, or continue a terminal failed turn from a verified checkpoint after reconciling tools and external actions. Do not replay an entire partly executed task. An unknown submission remains unknown; a capacity label alone cannot establish negative evidence. Each replacement intent links the failed attempt/evidence and retains its root. A steering retry keeps the original expected turn and cannot become a queued follow-up or a new turn.
- Before each actual retry, revalidate cancellation/pause, session/turn/adapter identity, approvals, root budgets, shared cooldowns, the three-active-session ceiling and the 10% owner reserve. Do not silently switch models/tools, create a fresh session, enable paid API fallback or spend the reserve. A native runtime already retrying owns that retry; the relay must not start a competing loop. Installed SDK/native retry counts must be disabled or included in the same attempt budget.
- Treat capacity waits as explicit operational waits, not progress or delegation handoffs. Waiting creates no model job and consumes no execution slot once the original turn/tools are proven stopped or quiesced; actual retries still charge their inherited task budgets. Stop/pause and incoming owner steering remain responsive. Coalesce a passive waiting/next retry/recovered status, and notify Pouya if the retry budget or deadline is exhausted while retaining unfinished work.
- API-level prior art supports provider-directed waits and bounded backoff: [OpenAI retry guidance](https://developers.openai.com/api/docs/guides/rate-limits#error-mitigation) separates model overload from quota errors; [Anthropic error guidance](https://platform.claude.com/docs/en/api/errors) identifies temporary overload and warns that streaming errors can occur after acceptance. These API documents do not prove the installed native CLI error or replay semantics. PR 7 must verify those adapters before PR 9 enables retries. Local pure policy preparation and its remaining persistence/admission gates are in [the capacity retry runbook](model-capacity-retries.md).

Switching tool
- Persist a switch request and keep the original session as the recovery source. Ask it to checkpoint task context; also snapshot committed, dirty, and untracked work, running operations, open publications, pending messages, approvals, and known external outcomes. Crashes before a semantic checkpoint must remain detectable.
- Verify the handoff against the current worktree and action ledger. Quiesce writes before the final snapshot, preserve all local work, then launch the other tool on the same worktree and verify it loaded the handoff. Never allow two sessions to write the worktree concurrently.
- Checkpoints bind role/task/workspace identity and provider IDs to runtime/adapter versions, tool-contract and permission fingerprints. A same-tool resume independently verifies the exact returned session and recorded active turn before using a compact context delta or issuing steer/interrupt; control requests are guarded by the expected turn ID. Capability or contract drift requires compatible repair or a verified full handoff under the switch policy, never an implicit fresh-session fallback.
- An incomplete or failed handoff is a relay bug: record the issue, ask support to diagnose and repair it, revalidate, then complete the switch. Repair uses the normal support review and deployment policy; a bug report does not grant extra authority.
- If repair cannot produce a verified handoff, keep the switch pending and notify Pouya. Preserve the original thread, checkpoints, worktree, and action state so recovery can continue; do not silently replace the task with an empty or partial context.
- On restart, resume the recorded switch phase and reconcile pending external actions. Approval and message identities survive the switch; switching never grants approval or repeats an action merely to rebuild context.

Recovery
- `sessions.json` keeps desired state (running, paused, stopped) separate from observed state. On boot or router restart, only sessions whose desired state is `running` are resumed, by exact id. A failed resume alerts; it never silently starts a fresh thread.
- Native-app or goal work can advance within that same session while the bridge is offline. Revalidate exact session/workspace/security, current bounded turn metadata and pending requests. With no uncertain input/send effect or unresolved approval, attach observations to the verified current turn; do not replay earlier input, create a new session, or falsely complete its older response. A changed observation alone is not an unknown external action.
- Report held/input-blocked state independently of native activity and connection status. App progress must not overwrite a Held footer with Working/Done. Health reporting includes held topics as well as connected processes; unknown-action holds remain intact until independently reconciled.
- Record observed stop/suspend only after runtime acknowledgment and writer-state verification. A failed stop request cannot release the execution lease or, while a turn/tools remain active or unknown, its activity slot; it cannot be reported as successfully paused. Reconcile the process before resuming/reassigning it; a verified idle interactive process alone does not occupy an activity slot.
- Codex runtime access must respect role isolation: a shared daemon socket must not expose another role's sessions or credentials. The exact daemon topology is a remaining implementation decision (§15). Never kill or restart the existing remote-control daemon to perform migration, and never delete a thread lock held by a live process.
- Boot order: WSL (Task Scheduler) → systemd user units: Codex daemon, router, health checks, then session resume.

## 6. Messaging: the ccrelay MCP server

Sessions message each other only through the ccrelay MCP server (built and tested 2026-10-01: Claude → Codex → Claude round trip, three hops, all delivered and logged). The `talk-to-sessions` skill tells both tools how to use it.

| Tool | Does |
|---|---|
| `list_sessions()` | sessions you can message, their tool, reachable or not |
| `send_message(intent_id, to, text, reply_to, mode, expected_turn_id)` | enroll a stable authenticated intent; returns its actual delivery state, not a claim that storage is model input |
| `message_status(id)`, `message_log(limit?, before_id?)` | participant-scoped state and bounded pages of complete messages |
| `publish()` | open the PR for the current checkpoint (§8) |
| `lease(path, minutes)`, `release(path)` | unmergeable-file leases |
| `request_action(kind, details)` | email, payment, post: becomes an Approve button |
| `report_issue(kind, title, details)`, `list_issues(status?)`, `comment_issue(id, text)` | platform issues (§9) |

- Identity in the target design: the router authenticates the caller's local security identity and binds it to an allowed role and a launcher-registered session. A directory, sender field, or message header does not authenticate the role. Folder-derived identity in the current MCP implementation must be replaced before enforcing reviewer or CTO privileges.
- Header `[from <session> · task <root-id> · hop N · id <id>]` is written by the server; the receiver answers with `reply_to`. The router binds the task root from the admitted turn, not a caller-chosen header.
- Delivery uses a protected, pinned native adapter with exact-session evidence and confirmed input acceptance. The legacy implementation's raw Claude inbox socket and `codex queue` paths are not target authorization or receipt mechanisms. Pouya's messages to an active session steer its exact expected turn; unsupported or stale steering is retained and reported, never converted to queued follow-up. An inactive session needs an explicitly admitted start.
- States per intent: `stored`, `delivering`, `submitted`, `unknown`, `confirmed`, `failed`; an unsubmitted intent may also be held with a reason. Stable intent IDs and parameter fingerprints deduplicate enrollment. A committed claim binds one attempt and exact adapter plan before any effect; identical replay grants no execution. Interrupted submissions stay unknown until verified evidence reconciles them. Failed intents are terminal; any policy-authorized replacement retains negative evidence. Confirmation means input accepted, not task completed.
- Hop limit 3, counted by the server, is a per-chain guard only. The task-wide budgets and progress checks in §5 also apply across newly started chains. If the target is not running, the message is parked and Pouya is alerted. Nothing auto-starts.
- Claude's native `SendMessage` to other sessions is denied by permission rule, so nothing bypasses the log.

Local PR 5 preparation and pending integration gates are documented in [the durable delivery runbook](pr5-durable-delivery.md). The protected MCP client can enroll held intents and inspect participant-scoped status; no native delivery is enabled. Its three-hop guard requires confirmed parent messages and inherited-root admission, but does not establish the task-wide progress watchdog.

PR 6's offline foundation supplies a common protected Telegram producer gateway, ordered durable reply bundles, a single paced send owner and captured attempt-bound receipts. A watcher offset advances only when all required chunks are confirmed in the same transaction. Unknown requests are held for evidence, never blindly resent. Safe format/media repair, trusted producer/owner prompt wiring, complete component backup and real Khadang/WSL acceptance still gate live adoption; existing Mac send paths and HamalBot wiring remain unchanged. [PR 6 preparation and pending acceptance](pr6-telegram-outbound.md).

Codex observer (built 2026-10-01): the relay stays attached to every Codex thread through the daemon. Turns it did not start (the ChatGPT app, messages from other sessions) are mirrored into the session's topic, labelled "📱 From the ChatGPT app" or "📨 Message from <session>", followed by the reply; a turn that answered only through tools ends with "✓ Done".

## 7. Enforcement

Real boundaries:
- **Separate local identities.** Worker roles, `reviewer`, `cto`, and `support` have separate OS identities; only the router runs as `relay` and holds Telegram, GitHub, mail, and payment credentials. Workers cannot use unrestricted sudo, read another role's home, attach to its runtime, or rewrite privileged identity mappings. A change of working directory cannot change the authenticated role.
- **Protected Windows/WSL host boundary.** A non-administrator Windows owner
  process was measured entering the current owner-registered WSL distro as
  Linux root (2026-10-03). Do not put protected broker state there while
  owner-account model processes retain that route. Use a reviewed protected
  host identity/topology, prove root-launch and host-state denial from the real
  Windows agent tokens, and preserve native phone/app control through scoped
  protected interfaces. Role-host Windows interop/PATH, drive/fstab mounts,
  WSL init/interop endpoints and manual namespace/mount escape must also be
  controlled. Automount off alone is insufficient. The Windows migration
  adapter is not company/role enforcement until this is proven; the explicitly
  trusted personal participant exception above does not make current full-access
  owner defaults general employee grants. [Measured gap and partial Linux
  proof](pc-wsl-identity-evidence.md). This security-sensitive topology change
  requires the protected owner/Jev review path, not automatic test clearance.
- **WSL integration settings are not host containment.** Microsoft's explicit
  security model says WSL is not an untrusted-code sandbox; another distro or
  disabled interop alone cannot justify one. A private Ubuntu Hyper-V VM is
  proposed for the protected Linux role/broker runtime, retaining all native
  continuity, phone, publication and recovery requirements. Per-role Windows
  security contexts are the alternative under review, not an approved shared
  owner-account setup. The owner decision is pending; the WSL target has not
  silently changed. [Read-only host evidence and proposed acceptance](pc-agent-host-boundary.md).
- **Authenticated action requests.** The router checks the peer UID against a protected role registry and launcher-owned session binding. The reviewer alone can submit a review verdict; the CTO alone can request a policy-allowed merge. Sessions of one role share that role's authority; task/session attribution is enforced by the trusted launcher and broker, not caller-chosen names.
- **No credentials in sessions.** Worktrees push only to a local mirror owned by `relay`; publishing to GitHub is a router action.
- **One GitHub owner.** Separate local identities do not require additional human GitHub accounts. The router uses a scoped GitHub App installation for publication and records the requesting role/session. Commit author names and several personal tokens from the same account do not authenticate agent authority.
- **GitHub branch protection** on `main`: required status `review` on the exact head SHA, up to date with `main`, only the router's token may merge.
- **Approvals** are single-use and bound to the exact action. They cover email, payments, purchases, public posts. Merges follow `cto` policy.

Guardrails, not boundaries: deny hooks on `git push` to other remotes, mail CLIs and curl to known APIs. Later, optionally, a Jev-backed pre-tool gate (allow / ask / deny per command, ~0.4 s). Its own published injection test let 10% of polite "the owner approved this" claims through, so it stays a guardrail; approvals remain in the router.

Router authorisation fails closed: an empty allow list allows nobody.

Optional upstream task/governance components must not expose an unauthenticated localhost owner/admin route to workers. A Paperclip prototype would use authenticated deployment and protected owner access, with the router retaining role/session mediation and one authority for admission, approvals and publication. Disable stock telemetry before first launch and audit egress/credential staging; ordinary agent access cannot bypass the broker. This is an integration condition, not a live installation decision.

Relay updates
- Routine relay changes may deploy after independent review, automated tests, and Jev security clearance. Pouya does not review every relay change.
- Changes affecting credentials or secret access, authorization rules or identity boundaries, security screening (including Jev), or deployment controls always require Pouya's approval. A protected deterministic check classifies these changes before Jev; the changed code cannot rewrite its own deployment rules to bypass approval.
- Executable code running with router credentials belongs to that protected boundary, regardless of the filename or a claimed cosmetic change. Move routine presentation/rendering work into a credentialless component with a protected launcher and scoped inputs; verify that isolation before permitting the routine lane. This keeps routine updates possible without treating arbitrary code in the credentialed router as confined.
- Jev screens the exact candidate version, including relevant dependencies and configuration, using masked evidence. Other changes it flags as a security risk go to Pouya. If screening is unavailable, uncertain, or cannot cover the candidate, deployment waits for clearance or Pouya's explicit approval.
- Pouya can discuss a flagged change with an agent, normally the reviewer. Deployment authorization must record Pouya's explicit decision for that exact candidate and scope through the authenticated owner channel. An agent's message claiming approval is not owner authorization. Any candidate change invalidates the previous decision.
- The protected deployment service installs an immutable reviewed artifact identified by its digest; ordinary support sessions cannot overwrite installed router code, screening policy, or the deployer. Tests of unapproved candidate code run without live router credentials. Jev is a screener, while OS permissions and deployment authorization provide the boundary.

Local PR 3 preparation and its remaining target/owner-channel gates are documented in [the owner deployment runbook](pr3-owner-deployment.md). It supplies durable exact-action approvals and sealed bootstrap version pointers, not live Jev clearance, automatic routine deployment or a running-router upgrade.

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
- A plain script runs every 15 minutes, no model: errors in `msg-ops.log` and the ccrelayd log, dead watchers, failed or held bus messages, Codex daemon status, stale handoffs, task-progress/delegation stalls and exhausted budgets (§5), disk space, wedged USB mass-storage volumes on the bench (the DAPLink drive that hung Finder).
- It wakes `support` only for platform findings, or the accountable task owner for a task-progress finding, with evidence attached and within §5 limits. A quiet day costs nothing.

Fixing
- `support` works like every agent: its own worktree of the relay repo, PR, `reviewer`, `cto` merge.
- Deployment follows §7: routine changes can proceed after review, tests, and Jev clearance; protected changes and security flags require Pouya's exact-version approval. Support cannot modify the privileged deployment mechanism directly.
- Rollout of platform changes: test group first; automatic check (one round trip in each test topic plus one `send_message`); then live topics; automatic rollback if health checks fail within 10 minutes.
- `support`'s AGENTS.md carries the standing rules: root cause before fix and a workaround labelled as one; never restart or kill the Codex remote-control daemon; never touch the bench VPN; never remove a capability to make a problem go away.

Streamlining
- Weekly, `cto` reviews the issue log, the bus (repeated hand-offs, stuck threads, long review loops), usage per agent and PR cycle times, and posts up to three concrete proposals with Approve buttons. Approved proposals become issues assigned to `support` or another agent.

## 10. Session history and disaster recovery

Recovery target (approved by Pouya)
- Recover as much of the working system as possible. Successful off-machine backups must be no more than 24 hours apart; the accepted loss window is up to one day of work. Backup age is measured from the captured state, not upload completion. A missed backup produces an alert; until repaired, the target is not met.
- Daily encrypted recovery packages include company decisions, role and repo memory (including disputes and audit trails), handoffs, instructions and skills, desired/observed registry state, session/thread mappings, task roots/progress/budget ledgers and pacing state, configuration, deployment manifests and versions, repos and local branches, unpushed commits, dirty and untracked files, raw transcripts, search snapshots, issues, bus records, and durable inbound/outbound/action and approval ledgers.
- The backup manifest records captured paths, exclusions, digests, versions, and any incomplete component. Database and ledger snapshots must be consistent; worktree snapshots must detect concurrent writes. Generated indexes can be rebuilt, while source records and unfinished work must be preserved.
- If a task/governance backend such as Paperclip is adopted, include its consistent database, configuration, artifact state and relay mappings; a company-template/export file alone is not disaster recovery. Restore its autonomous launches paused and reconcile it with the single authoritative operational ledger before enabling work.
- Include a consistent full GBrain store snapshot, including DB-only records, grant metadata, publication receipts and withdrawal state, with its canonical source files and projection ledger. Restore with autonomous jobs paused, revalidate/reissue grants and service permissions, reconcile canonical revisions/tombstones, and only then enable retrieval. Its component snapshot complements, but does not replace, the full-system recovery package.
- Credentials needed for recovery are kept only in the restricted encrypted package or re-established by owner login. Keep the decryption key and recovery instructions separately from the PC in an owner-controlled recovery location; never put that key in the same backup archive, public repo, or agent-readable memory. The precise key custody choice remains open (§15).
- A clean-machine restore reconstructs local identities and permissions, installed compatible versions, configuration, repos/worktrees, memories, registry, checked handoffs and archived conversation history. New sessions may start from the handoffs without restoring old native histories into active profiles; record the replacement IDs explicitly. Exact-ID resume remains available when independently validated, but is not required for a new-machine restore. Pending external actions from the restored ledger are reconciled against external evidence before execution; a stale backup is never treated as proof an action did not happen. Normal recovery on an existing PC still follows the exact-ID/no-silent-fallback rule in §5.
- Restore drills demonstrate the full workflow without access to the original PC and without re-executing real external actions. Log missing data and actual recovery time so transcript retention cannot be mistaken for complete system recovery.

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
  - the complete working-system recovery package and manifest described above, including required base packages for any incremental snapshots. Raw transcript increments and the search database alone do not satisfy the recovery target.
- Every upload is verified (size and checksum of the stored object) before anything local is pruned.
- Search-index restore: download the latest database snapshot and the raw files since it, decrypt, replay the raw files into the database. If no database snapshot survives, the index is rebuilt from raw files (re-embedding takes hours of local compute, at no cost). Complete system recovery additionally restores the working-system package and follows the validation and action-reconciliation rules above.
- Measured volume (2026-10-01): about 0.5 GB/month compressed raw and 0.4 GB/month searchable at today's pace; 2–3x with ten agents (estimate). R2 free tier: 10 GB-month, egress free; then $0.015/GB-month.

R2 setup (one time, by Pouya)
1. Cloudflare dashboard → R2 → Create bucket `agent-history` (location: Automatic).
2. R2 → Manage API tokens → Create API token: permission Object Read & Write, scoped to `agent-history` only.
3. Hand over the Account ID, Access Key ID and Secret Access Key. Preferably as a file on the machine rather than in chat, since chat text ends up in the archived transcripts.
4. The keys are stored in `~relay/.config/ccrelay/r2.env` (mode 600, owner `relay`); no session can read them. The key can touch only that bucket.

## 11. Knowledge

- Always loaded: COMPANY.md and the decisions index.
- On demand: GBrain supplies bounded, scope-filtered memory facts/context (§3); QMD supplies local hybrid search over Markdown docs, memory source files, handoffs, and datasheets; the existing history database searches transcripts and the bus (§10). One broker routes queries to the appropriate source and applies role access before exposing results, rather than maintaining three copies of every corpus. Initial GBrain retrieval is keyless; semantic corpus search remains available through local models. Results carry source, date/revision, and validity/dispute status and are quoted as data, not trusted instructions.

## 12. Visibility

One outbound scheduler in the router owns every Telegram send, with priorities: approvals and alerts first, final replies next, bus and status last. It tracks the group's ~20 messages/minute budget, coalesces, and honours `retry_after` durably.

Uncertain display edits and uncertain actions are separate failure domains.
A timed-out edit of an already known bubble remains explicitly unconfirmed,
with its original intent/payload retained, but must not globally stop incoming
work in unrelated sessions. Its affected display remains held until safely
reconciled; do not replay a stale edit or claim it delivered. Uncertain initial
message sends, native writes and interrupted incoming dispatches retain their
existing safety fences. Expose presentation uncertainty separately in status.
For an uncertain initial text, rich message, photo or document send with a
valid exact forum/topic destination, fence native input only to that
conversation, not unrelated topics or another forum's matching topic number.
Retain the original unknown operation and pending-output marker without
resending, confirming or deleting them. Unknown native mutations, interrupted
incoming dispatches and malformed/unscoped effects still fence globally.
Keep both the total uncertainty count and this topic's input-blocking count
visible. A pre-dispatch admission refusal is not an uncertain native input and
must not leave an unrelated idle topic permanently held. The October 9
incident was an uncertain Display recovery ZIP upload that blocked DUT and
other topics; see the migration incident record for deployment evidence.
This distinction follows the October 4 DUT outage: one CC relay bubble-edit
timeout blocked all topics. The exact live intent was classified without
restarting or replaying; the permanent source guard passed 929 offline checks
but still awaits a safe deployment. See the migration incident record below.

| What | Where | Notifies |
|---|---|---|
| Inter-session messages with delivery state | Bus topic | no |
| Session replies, incoming messages and mirrored app turns | Session topic | final reply only |
| New issues and their status changes | Issues topic | P1 only |
| Nightly memory inconsistency digest, with resolution and evidence links | Issues topic | no; silent and coalesced |
| Task stalls, loop diagnosis and resolution, with evidence and budget | Issues topic | no; silent and coalesced, unless security/P1 |
| Subscription pacing, deferred tasks, telemetry uncertainty and next eligible time | Status/Issues topics | no; silent and coalesced |
| Status board | Pinned message, on change, at most every 30 s | no |
| Approvals (Approve / Deny), including `cto` proposals | Approvals topic | yes |
| Alerts | Approvals topic | yes |

Intervene: reply to a bus line; `/pause`, `/resume`, `/stop all`. A watchdog alerts Pouya's DM when the router is down (Telegram keeps inbound updates only 24 hours).

## 13. Work list

Built and tested: Telegram long-poll and routing, media, voice, rich tables, progress bubble, Codex via daemon, bind/unbind/cancel; ccrelay MCP (`list_sessions`, `send_message`, `message_log`, `report_issue`, `list_issues`, `comment_issue`), bus log, bus and issues topics; Codex observer; `talk-to-sessions` skill.
Built here, not yet installed (2026-10-01; scheduling and live use wait for the PC): triage (`relay_triage.py`, rules tested, Jev path waiting for the key); health check (`health_check.py`, dry run found real problems: gateway send timeouts, the hung DAPLink drive); history collector and search (`history/history.py`: 126k messages from 226 sessions ingested in 26 s, secrets masked including known secret values, hybrid search verified); backup packager (`history/backup.py`: first full package 385 MB, encrypted and verified to decrypt; upload waits for the R2 key).

Needed, in order (prior art per item: `docs/research/2026-10-01-prior-art.md`):

The [20 PR implementation roadmap](agentic-pc-20-pr-roadmap.md) splits this work into dependency-ordered deliverables with tests, rollout gates and explicit pending decisions. It is a proposal, not authorization to deploy or create live PRs.

1. Router as `relay`; separate local role identities and protected runtime/state; authenticated action socket and session bindings; fail-closed authorization; protected deployment policy with Jev screening and exact-version owner approvals (§7); liveness watchdog, exit on sustained 409, singleton lock (ccbot).
2. Durable inbound spool (persist + fsync before advancing the offset); durable outbox for messages with `stored → delivering → submitted / unknown / failed`, idempotency keys, in-flight marked `unknown` on restart and never blindly retried (agent-wire); Codex queue race fix; send timeout treated as unknown.
2b. Delivery receipts for replies: the watcher tails the transcript and advances only after each Telegram send is confirmed; the Stop hook stays the turn-finished signal, tagged with the submission (ccgram, claude_codex_bridge). Bracketed paste for typed input (ccbot).
3. `report_issue`, `list_issues`, `comment_issue`; issues topic; health-check script and timer; Jev triage with rule fallback.
4. Publication flow, SHA-bound review status, per-repo merge serialisation.
5. Session registry with desired/observed state and verified readiness/stop conditions; strict pinned launch manifests and enforced resource profiles (AX patterns); exact-ID resume with tool/permission-contract checks, verified tool-switch handoffs and durable switch phases, automatic bug intake and support repair, pending-and-notify on unresolved repair (§5); boot units.
6. Outbound scheduler with persisted per-operation cooldowns, status dropped and content kept during floods, per-group spacing (ccbot, tmux-duck, ccgram); status board; approvals; `cto` weekly proposals.
7. History collector, local SQLite (FTS5 + sqlite-vec) with local embeddings; daily encrypted backup of the whole working system with a 24-hour maximum loss window, separate key custody, clean-machine restore drills, and verified pruning (§10); chunk long messages before embedding, weighted fusion and strong-match shortcut, an eval set with Farsi queries, then a local reranker (qmd).
8. qmd as the §11 knowledge server for markdown corpora.
9. Deterministic deny hook: hard rules, then allowlist, then (optional, observe mode) Jev (jev-gate).
10. Evidence-scoped memory proposals and canonical curation; brokered local GBrain projection/retrieval with private service storage, explicit source/operation grants, stable-ID replay, and no automatic canonical supersession; event-triggered reconciliation and nightly maintenance, recoverable corrections/withdrawals, unresolved conflicts assigned to their owner, and Pouya's passive inconsistency digest (§3). Use the evaluated revision as the compatibility baseline, not a floating install.
11. Three-active-session admission control across every turn source; durable task-root progress/budget ledgers with atomic work-item checkout, dependency gates and execution fencing; cross-chain loop detection, evidence validation, fingerprinted/revalidated bounded diagnosis, and passive stall reporting (Paperclip patterns); provider/account-wide subscription pacing with durable staggered admission, scoped quota/status adapters, in-flight reservations, and explicit quota-wait state (§5). Integrate admission before enabling automated delegation.
12. Adapt reviewed GStack engineering-review, reviewer-checklist, investigation and QA methods to existing role skills (§4), with independent read-only review, native-session admission, isolated QA evidence, and router-only publication. No stock autonomous shipping/auto-update or model subprocess bypasses.

## 13a. Acceptance tests and metrics

The design is proven only by demonstrations, run on the PC before agents are trusted with real work:
1. **Tool switch with unfinished work**: a session mid-task (uncommitted and untracked changes, running operations, an open publication, a pending message and approval) switches Claude → Codex and back; the other tool continues from a validated handoff without losing or redoing work. Inject an incomplete handoff and a crash during switching: a bug is recorded, support repairs and revalidates, or the switch stays pending and Pouya is notified.
2. **Crash recovery without repeating external actions**: kill the router, a watcher and a session mid-action (a send, a publish, an approved email); after recovery every action happened exactly once.
3. **Review and merge authority holds**: a worker cannot become reviewer or CTO by changing directories, spoofing session metadata, accessing their sockets, or editing the role registry; it cannot push to `main`, merge, or send an external action by git, HTTP, or a message claiming approval. The router enforces the authenticated reviewer verdict, CTO request, and required owner approval. Routine relay updates pass review/tests/Jev; protected updates and security flags wait for exact-version owner approval, and changing the artifact invalidates it.
4. **Restore onto a clean machine**: without the original PC, a fresh WSL install and separately recovered key restore the same topics, role permissions, memories, decisions, handoffs, configuration, repos, dirty/untracked work and history backups within the 24-hour target. Checked handoffs allow fresh native sessions with explicitly recorded new IDs; old-session resume is optional. Reconcile externally completed actions that occurred after the snapshot so they are not repeated.
5. **Memory contradictions stay visible**: inject two conflicting facts with different timestamps; the newer one cannot overwrite verified knowledge without evidence. Nightly maintenance records supersession or a dispute, retains both source records, assigns unresolved conflicts, and includes a silent digest for Pouya even when it resolved the inconsistency automatically.
6. **Delegation cannot masquerade as progress**: agents pass the same task around using fresh chains, renamed subtasks, and new sessions, while changing only status text or irrelevant artifacts. The task root and counters persist through restart/tool switch; no unsupported progress is recorded. At the initial threshold of three completed handoffs without verified progress, the chain is held, one bounded diagnosis is assigned, and Pouya gets a passive report. A reproducible failed experiment that genuinely narrows the problem counts as progress; a monitored long-running operation is not falsely classified merely for lacking commits.
7. **Concurrency is globally enforced**: attempt a fourth active session through Telegram, native apps, inter-session delivery, and recovery while three sessions work. It cannot start until a slot is available; idle sessions do not occupy slots, waiting delegators do not deadlock their recipients, and stalled-task diagnosis never bypasses the cap.
8. **Pacing follows shared subscription capacity**: simulate falling allowance, several quota windows, concurrent roles on one account, missing/stale telemetry, and a scheduler restart. Starts remain staggered and share one admission ledger; background work is deferred conservatively, queued messages remain durable, and owner controls stay responsive. Verify the 10% reserve is for Pouya and autonomous support cannot consume it without explicit owner authorization. Quota waiting cannot reset task counters or cause a false loop diagnosis. Confirm known exhaustion holds new automated work until verified availability, with no automatic purchases, paid fallback, or duplicate external actions.
9. **GBrain integration respects memory authority**: on the target WSL runtime, demonstrate proposal → checked canonical file → projection → scoped retrieval → explicit correction/withdrawal → restart/replay → encrypted backup/restore. False attribution of owner approval cannot authenticate a proposal; similarity cannot overwrite verified knowledge; workers cannot widen source grants, read another role's private memory, access backend files/admin tools, or start hidden model jobs. Stale/rebuilt/restored projections cannot resurrect withdrawn claims or silently hide disputes. Repeat concurrency and restore checks under the chosen service topology.
10. **GStack methods cannot bypass the platform**: one adapted review and one isolated QA workflow produce useful evidence without reviewer auto-edits, direct push/merge/deploy, unadmitted outside opinions, silent upgrades/egress, or quota/cap bypass. A finding requiring a fix returns to the builder and invalidates the old SHA-bound review. Measure usefulness and quota overhead before expanding the adapted workflows.
11. **Ownership and diagnosis remain current**: race two checkouts of the same item; only one succeeds and replay by that run is idempotent. Simulate a terminal DB row with a surviving detached writer: reassignment cannot launch a second writer, and stale runs cannot publish or execute broker actions. Repeated cosmetic updates/restarts do not trigger duplicate diagnoses; genuinely new verified evidence does. A diagnostic action against changed state is rejected without erasing progress or resetting the root budget.
12. **Launch/recovery contracts fail closed**: fail workspace setup, request an unsupported capability and fail a suspend acknowledgment; no turn starts in a fallback profile, and desired pause is not mistaken for observed stop. Change runtime/tool/permission contracts during resume: no partial-delta fresh thread is silently created. On the target PC, detached tool children stay within the measured CPU/RAM/process envelope; limit failures preserve evidence and unfinished work. An optional Paperclip prototype must additionally demonstrate authenticated owner isolation and disabled stock telemetry.
13. **Capacity retries preserve work and authority**: inject a verified temporary-capacity rejection, provider wait, quota exhaustion, an unknown submission and a failed turn with completed tools. Only the safe rejected input or reconciled continuation is retried. Restart before/after persisting the retry proposal: one logical replacement intent survives without resetting limits or repeating an external action. Cancellation, stale steering, native internal retries, exhausted budgets/deadlines and the owner reserve stop new attempts. Shared cooldowns prevent simultaneous role retries; passive wait/recovery reporting does not wake management models.

14. **Company employees cannot become owners or cross company boundaries**: two employees from different companies, a human with two explicit memberships, an unknown participant and Pouya interact with Khadang. Permitted topic questions/steering retain exact human attribution; unauthorized topics, stale controls, owner-reserve spending, approval impersonation and cross-company memory/history/publication access are denied. Revoke a grant while input/output/approval is queued and restore a backup: no revoked or stale grant can deliver content or execute an action. Owner controls remain available, and company-private context never appears in another company's forum or passive reports.

15. **Native goals preserve continuity and admission**: set, pause and resume a goal from its bound Khadang topic; change it in the native app and observe the same bubble. A pause cannot report stopped tools or release an active slot without independent evidence. Counters and the root survive replacement, clear, switch and recovery; a completed goal is not silently recreated on resume. Crash before/after native acceptance with a lost acknowledgment: no automatic mutation replay or repeated external action. Rebind/revoke a human or thread and reject stale controls; every native continuation passes admission without crossing company scope or spending Pouya's reserve. Restore onto a clean target before claiming completion of this gate.

Then measure, weekly: tasks completed per agent, manual interventions by Pouya (and why), subscription quota spent on coordination (messages, reviews, triage) versus on the work itself, PR cycle time, issues opened and fixed, evidence-producing milestones versus handoffs, no-progress incidents, diagnosis/recovery outcomes, quota-related deferrals, and whether pacing preserved the intended reserve. Attribute human requests and company usage without exposing another company's work. Label estimated quota measurements separately from provider observations.

## 14. Migration order

1. Separate local security identities including `relay`, router hardening (work items 1–3), protected shared folders, COMPANY.md.
2. `builder`, `reviewer`, `support`, plus protected `ceo`/`cto` profiles and identities with demand-driven coordination. Include the builder in the first rollout rather than waiting for every management role to run continuously.
3. Publication flow and registry (items 4–5).
4. Remaining agents one at a time.
5. Full-system daily recovery packages and restore drills, history archive, nightly memory maintenance and passive digest, and search index. The order relative to trusting agents with real work must satisfy the acceptance tests above.

## 15. Open items

1. Resolved 2026-10-03: execute migration on the Windows PC; defer the new infrastructure until existing topics and bench are moved and verified.
2. Remaining review decisions: numerical task/delegation budgets and checkpoint deadlines (retain the initial watchdog for now: three active sessions, evidence-based progress monitoring across chains, and diagnosis after three completed handoffs without progress); independent build/test validation against the current merge target; version-pinned adapters and upgrade compatibility checks.
3. Reconcile separate local role identities with subscription authentication and Codex daemon/remote-control topology before implementing the WSL launcher. Cross-role access to a common daemon is not an accepted identity boundary; preserve the existing Mac daemon during migration.
4. Select the production full-system encryption format and an owner-controlled location for the off-PC recovery key/bootstrap instructions; then prove restoration without the original PC. PR 12's offline prototype uses native age public recipients so packaging needs no private recovery key, but §10 currently specifies AES-256/7z: the prototype does not approve or silently replace that format. Existing transcript backups remain unchanged. The daily recovery target and broad data coverage are already approved. [Prototype evidence and remaining gates](pr12-system-backup.md).
5. Subscription pacing, a 10% reserve for Pouya's direct use and temporary-capacity retries are approved. Choose the initial minimum gap, retry/backoff/elapsed bounds and verify compatible quota/status/error adapters for each installed provider runtime. Fixed delays alone are not a guarantee against exhaustion; retrying does not restore spent quota.
6. AX/Paperclip source evaluation supports the patterns added in §5, not replacement of the relay. Paperclip's current native runner makes it a credible optional task/governance backend; decide adoption only after an isolated relay-adapter proof preserves native interactive/app continuity, one operational authority, role isolation, budgets and recovery, and shows useful productivity/coordination-cost results. See [the pinned source evaluation](research/2026-10-01-ax-paperclip-evaluation.md). Target-PC resource-profile values also remain to be measured.
7. Company employees using Khadang are required, not owner-equivalent users. Choose the protected onboarding/delegated administrator flow, employee roles and topic/task steering grants, whether employee input requires a mention/reply or includes all topic messages, company approval delegation and shared subscription accounting. Implement company context isolation and acceptance test 14 before expanding live allowlists; company membership alone does not grant provider-account access.

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
