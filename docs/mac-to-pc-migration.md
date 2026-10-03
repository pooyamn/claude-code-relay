# Mac to PC migration plan

Pouya's current priority is to move the existing working system to the PC,
keep the same Telegram topics, use Khadang instead of Hamal, and make the PC
the bench host. The new role and broker infrastructure is deferred. This plan
does not require completing the 20 PR roadmap before migration.

Pouya's revised continuity decision, 2026-10-03: keep Claude and Codex session
histories as checksum-verified backups. Start fresh PC sessions from project
handoff documents and preserved worktrees; restoring or resuming the Mac's
native session IDs is optional and must not delay cutover. Record the new PC
session IDs for subsequent operation and recovery. This is an explicit initial
migration choice, not permission to silently replace a failed PC session.

The Mac remains the rollback source until the PC passes the checks below.
Retiring its services is distinct from erasing a Mac or VM; no filesystem wipe
is authorized until the exact target is resolved and verified copies exist.

## Current inventory

The source OpenClaw configuration contains 14 bindings: eight topics in Ai
Dispatch, five in Oracova, and the standalone Startup Ideas group. Keep their
chat and topic IDs unchanged. The existing PC LG topic remains intact.

| Project | Chat | Topic |
| --- | --- | --- |
| startup-ideas | -5238984877 | Whole group |
| ai-hil | -1003550185469 | 1876 |
| supervisor-fw | -1003550185469 | 5786 |
| claude-code-relay | -1003550185469 | 816 |
| kicad-copilot-research | -1003550185469 | 6004 |
| hardware-lite | -1003550185469 | 6333 |
| qwen-lab | -1003550185469 | 10656 |
| mpu6000-i9 | -1003550185469 | 8653 |
| web | -1003550185469 | 8660 |
| marginal-requests (Marginal Requests) | -1004395661179 | 427 |
| augur-1 (Base board) | -1004395661179 | 18 |
| duts (DUT Board Design) | -1004395661179 | 53 |
| schematic-pipeline-lab (schematic pipeline speedup) | -1004395661179 | 2697 |
| mimic-fast-pcb (Mimic Fast PCB) | -1004395661179 | 3315 |

All five Oracova PCBA topics shown in Pouya's screenshot are required, including
inactive sessions. Each retains its own topic address, handoff, selected backend
and new PC session ID; preserving the General topic is not a replacement for
migrating these five sessions.

Selected tools and provider configuration must be read from source runtime
state, not inferred from the `claude-` agent names. Preserve both tools' histories
and known source session IDs as backup metadata. Missing old pins do not block
a fresh PC session with a checked handoff; record any inventory gaps rather than
guessing a transcript by modification time. Preserve the Qwen topic's actual
configuration rather than replacing its backend without a decision.

The source workspace is approximately 49 GB, with another 1.6 GB of OpenClaw
media, 2.3 GB of Codex sessions and 1.2 GB of Claude project history. The PC has
ample disk space. All source workspace files now have a checksum-verified PC
archive and an extracted workspace; project validation and operational checks
are not complete. The separate
physical bench MacBook is not the Mac VM holding the relay workspace. Its
selected operational projects, firmware, keys, captures and tool installations
now also have a protected, checksum-verified PC archive. That archive is not an
activated bench environment or a final checkpoint.

The protected Windows Khadang service currently routes one test forum and uses
Codex. A candidate now supports full chat/topic addresses, an explicit
whole-group route and distinct Windows Codex, Linux Codex and Claude paths
inside the same router; it is not yet deployed. A working native Linux transport for
Codex now passes isolated Windows-to-Linux native acceptance, including shared
events and actual tool identity. A standalone Claude client now also passes
authenticated native input and reply acceptance on the PC. Linux Codex's launch
path is now wired into the router candidate, but has not passed that version's
Windows/WSL acceptance or been deployed. A persistent shared daemon and live
routing for both tools are still required for the new PC sessions.
Claude's pinned streaming control interface now also connects and disconnects
authenticated native Remote Control on the PC through an explicit control
request. A phone-message round trip and live Telegram steering remain unverified.
Native remote connectivity alone does not supply those capabilities.
At 4:39 PM PDT on October 3, Khadang was a member of both Ai Dispatch and
Oracova PCBA. Startup Ideas remained inaccessible (Telegram HTTP 400). That
group still needs bot access; the other two groups do not need another invitation.
Membership does not establish a working topic route.

## Project handoffs

Prepare a handoff for every operational project, including unbound projects,
before its source writer is retired. Keep private project context in the
restricted migration copy, not a public repository. Each handoff records:

- The objective, current progress, important decisions and next concrete steps.
- The repository path, branch and commit, plus dirty and untracked work. The
  document references the preserved files; it does not replace them.
- Commands, test results, build artifacts and remaining failures, with evidence
  locations rather than unsupported claims that work is complete.
- Required tool/provider settings, instructions and skills, without secrets.
- Pending questions, approvals, running operations and external actions,
  separating confirmed results from unknown outcomes. Mark actions that must
  not be repeated and retain their ledger/receipt references. A prior approval
  is not new authority for a changed action or artifact.
- The history backup location and known source session ID for optional lookup.

Check the handoff against the final preserved worktree and action records after
quiescing the source writer. Verify that the fresh PC session loads it and can
continue the next step. Do not require the session to ingest all old transcripts
or reproduce the Mac session ID.

## Execution sequence

1. Preserve the source. Create a new restricted PC staging directory. Transfer
   separate archives over encrypted SSH and SFTP, retaining source paths, Git metadata,
   dirty and untracked files, symlinks, histories, configuration, skills,
   memories, media and action records. Record archive digests, source roots,
   capture times and failures. Initial copies are seeds while writers run,
   not consistent final backups. Do not overwrite existing PC projects or native
   logins, publish private data to Git, or copy live locks as valid ownership.
2. Establish working PC execution. Reuse the existing relay mechanisms, with
   only the portability and routing changes migration needs. Verify explicit
   fresh-session creation, handoff loading and interactive input for both Claude
   and Codex on the target, then persist their new native IDs. Preserve task
   context, unfinished work, tool configuration and permissions. A Windows or
   personal Linux runtime is acceptable if it delivers the same capabilities;
   secure multi-company role
   infrastructure remains a separate deferred project. Keep the protected
   Windows bot credential and deployment boundary intact.
3. Import bindings without creating topics. Address sessions by `(chat, topic)`,
   including an explicit whole-group route. Import selected backends and bind
   the verified new PC session IDs. Keep the existing LG binding and unrelated
   bot configuration. Hold uncertain incoming deliveries and external actions
   for reconciliation rather
   than replaying them to make migration appear complete.
4. Cut over one topic at a time. Checkpoint and quiesce that source writer,
   capture the final delta and checked handoff, validate the PC copy, then
   connect Khadang's new PC session to the same topic. Verify owner input,
   active-turn steering, tools, one rolling bubble, controls, attachments,
   app-origin updates where supported, and recovery of the new PC session after
   restart. Do not require recovery of its old Mac session. Disable Hamal routing
   for that topic only after Khadang receipts prove it works. Keep relay topic
   816 until last so the
   migration controller is not stranded. Do not restart the shared Mac native
   daemon or abandon an unfinished handoff.
5. Move the bench. Inventory and copy the physical bench projects, firmware,
   scripts, evidence and tool versions. Install and verify PC build, flash,
   debug, serial and USB control tools. The USB hub and boards are still on the
   MacBook; their cable must physically move to the PC. Validate each device
   and the canonical hub-port mapping, including per-port power control and
   dual-fed boards. If Windows cannot provide a required operation directly,
   use a compatible PC-hosted path; do not drop the capability.
6. Prove Mac-independent recovery. Verify access through the PC's tunnel/VPN
   without the current SSH jump through the bench Mac. Test service and session
   recovery after a controlled reboot, secure sign-in recovery, always-awake
   behavior, and TV-off/PC-online behavior. Preserve working VPN, subscription,
   MTProto and Cloudflare services. Maintain a recoverable off-machine copy and
   verify key/bootstrap recovery; a staging archive alone is not the approved
   daily disaster-recovery system.
7. Retire the Mac only after acceptance. Verify all bound and unbound operational
   projects, history backups, handoffs, topics, credentials and bench functions
   on the PC. Stop the obsolete Mac services and remove their credentials using
   recoverable
   operations where possible. Resolve the exact requested deletion target before
   erasing anything. Keep the verified archive independently of the source Mac.

## Completion evidence

These are required acceptance checks, not claims about the current deployment.

- All 14 existing bindings work through Khadang on the PC with the same IDs and
  intended tools; the LG topic also remains working.
- Repositories, local branches, dirty and untracked work, instructions, memory,
  media and native history backups are preserved and checked, including projects
  that were not bound to Telegram. Old native histories need not be restored
  into the active PC profiles or resumable to pass migration acceptance.
- Fresh Claude and Codex sessions load checked project handoffs and continue
  real unfinished work, with owner controls and a bounded rolling bubble. Their
  new IDs are recorded and their PC restart recovery is verified; uncertain
  actions are not repeated.
- The PC builds, flashes, debugs and controls the transferred bench hardware,
  including the required hub power operations.
- Remote access and reboot recovery work with the Mac absent. Off-machine
  recovery data and separately recoverable keys exist and are verified.
- The obsolete Mac deployment is retired, with any actual erasure explicitly
  resolved and authorized. Until then migration remains incomplete.

## Execution record

The record below retains earlier restore experiments and their limitations.
The revised fresh-session policy above supersedes old-session restoration gates;
those experiments are historical evidence, not additional cutover requirements.

2026-10-03: source binding inventory rechecked: 14 bindings. The design and roadmap
now explicitly defer new infrastructure in favor of this migration. The existing
PC LG deployment, source work, Hamal routing and Mac native sessions remain intact.

Initial archive copies on the PC have matching source and destination SHA-256
digests and administrator-owned, SYSTEM/Administrators-only permissions:

| Archive | Compressed size | Status |
| --- | --- | --- |
| Claude home and history | 602785851 bytes | Copied and checksum checked |
| Codex home and history | 3211655637 bytes | Copied and checksum checked |
| OpenClaw media | 1500246291 bytes | Copied, checksum checked and Linux reader accepted |
| OpenClaw state including agents, credentials and temporary work | 18622504681 bytes | Copied, checksum checked and archive reader accepted |
| Relay configuration | 658147 bytes | Copied and checksum checked |
| Owner Git, SSH, Claude and launch configuration | 40504 bytes | Copied and checksum checked |
| Remaining owner configuration and shell profiles | 14341221 bytes | Copied, checksum checked and Linux reader accepted |
| Full workspace including dirty and untracked work | 22649280767 bytes | Copied, checksum checked, Linux reader accepted and extracted |
| Fresh Codex SQLite snapshots | 168085642 bytes | Copied, checksum checked, Linux reader accepted and extracted |

The protected destination is
`C:\ProgramData\OracovaMigration\35d21d73d97ad5411f82033a86562528`.
Private local transfer receipts remain beside their generated archives. The
archives are initial seeds: source writers were not frozen, live socket objects
are not portable files, and database/worktree consistency still requires final
checkpoint capture. The archives alone are not a completed encrypted daily backup
or proof of native continuity; subsequent restore checks are recorded below.
No source data or generated archive has been deleted.

The small framed SSH transfer passed, but three bulk transfers stalled at 64 KiB
with blocked producers and receivers. Those exact owned receivers were stopped,
partial files retained, and the experimental helper retired. File-based SFTP is
the transport workaround; it does not claim to fix the underlying console-stream
failure. The accepted copy helper is `scripts/copy-pc-migration.rb`; its eight
argument-safety tests pass, including the physical bench source restrictions.
Windows tar rejected an entry in the media archive;
both the source reader and target GNU tar accepted the identical bytes. Future
POSIX archive verification uses the Linux reader instead of silently renaming
source files or dropping metadata to satisfy the Windows reader.

Ubuntu now has an ordinary `pou` user, UID 1000, with private home `/Users/pouya`.
Keeping the Unix source path is a compatibility measure for existing topic keys
and histories, not a company or role boundary. Native models have not been
launched there. The full Claude and Codex archives were extracted successfully
as UID 1000 into private preserved-state directories, separate from active
settings and logins. Workspace extraction also completed with exit 0 as that
same user, restoring `/Users/pouya/.openclaw/workspace`. These extracted seeds
still require project validation, a checked handoff and a final source delta.
Read-only Git probes on the PC resolved the captured relay, ai-hil and supervisor
worktree HEADs. The relay seed predates the new migration commits, so it must
receive the final source delta rather than being treated as an up-to-date checkout.

Matching native Linux Codex 0.160.0 and Claude 2.1.288 are installed in private
owner preparation directories and both version checks pass. The Codex package
matches the published release digest. Claude's manifest signature, pinned
Anthropic key fingerprint and binary checksum all pass. Preparation changed
neither logins nor router transport. Background and manual Claude
updates were disabled for the preparation invocation; permanent launch settings
still require inspection and merging. A real model must launch from the limited
interactive Windows owner token, not inherit the SSH administrator context.
The personal owner-registered WSL distro is not an accepted company boundary.

Ubuntu's original automatic-update configuration was still enabled and one
security-update job completed during preparation. It was not interrupted.
An additive root-owned policy file now sets all APT periodic-update switches to
0; both APT update timers are disabled and inactive. The original configuration
is preserved and manual updates remain available. This extends the owner's
existing no-auto-update preference to the PC's Linux environment, without
changing Defender or Windows update policy.

Follow-up WSL entries returned `WSAETIMEDOUT`; the subsequent ordinary-user
inspection succeeded and confirmed the policy and timer state. No WSL restart
or extraction replay was performed. This transient entry failure still needs
characterization before declaring the host reliable for always-on sessions.

All six Codex SQLite databases now also have fresh backup-API snapshots, with
successful integrity checks and a verified protected PC archive. These preserve
committed WAL records rather than relying on the non-quiesced raw file copies.
Each database is consistent independently, not an atomic cross-database or
final per-topic cutover snapshot. The capture helper's tests cover a committed
live WAL record, a closed WAL database without companions, source data and
journal-mode preservation, private output permissions, and symlink rejection.
The Mac's read-only SQLite open failed for the inactive WAL case; the capture
connection uses `query_only` to permit normal journal initialization while
preventing SQL data writes. Only closed standalone backups use immutable reads.

At 12:03 PM PDT, a one-shot Interactive/Limited task under the exact Windows
owner SID and session 1 completed the preserved-history check as Linux UID 1000.
All 14 bound workspaces exist. All 15 captured pins (five Codex and ten Claude)
resolve to transcripts with matching session IDs, workspaces and message records;
the five Codex IDs also match the captured state database. All six closed
database snapshots match their capture digests and pass integrity checks. Eight
validator tests pass, including mismatched metadata, missing pins, truncated JSON
and symlink rejection. Conversation contents are not printed by the checker.

The initial limited-owner probes could not attach Ubuntu's disk:
`Wsl/Service/CreateInstance/MountDisk/HCS/E_ACCESSDENIED`. The distro directory
and VHD inherited administrator/SYSTEM-only permissions from its original
preparation. The personal migration distro now grants the exact Windows owner
Modify access under `C:\ProgramData\OracovaWSL\Ubuntu2404`; other protected
trees and existing grants remain unchanged. Original directory and disk ACLs
are saved in a protected rollback receipt. Normal-owner entry then succeeded.
The probe checks native exit status before attempting JSON parsing, retaining
private failure output rather than masking an entry error as malformed JSON.

Actual open/close probes, without reading credential bytes, were denied for
Khadang's protected token from Windows, Linux UID 1000 and Linux UID 0.
This is evidence for that Windows file boundary, not company isolation inside
the personal distro. Owner-writable diagnostic results are not authorization
grants. The successful task has no triggers and is terminal with exit 0;
failed attempts and their output remain available for diagnosis. No model,
native resume, action replay or routing change was started by these checks.

At 12:15 PM PDT, a second Interactive/Limited task in owner session 1 restored
the history folders at their original Unix paths as Linux UID 1000. It copied
all 149 Codex rollout files, all 744 files in Claude's project-history folder,
the Codex history/index files, and six working database clones from the closed
backup-API snapshots. The 901 regular files total 4,450,410,314 bytes. Source and
destination tree signatures match; directory modes and symlink targets are
included, and the preserved seeds remain untouched. Existing destinations and
partial copies are refused rather than overwritten or replayed. Settings,
credentials and hooks were not activated by this restore.

The pinned native Linux Codex 0.160.0 then read all five original pinned
conversations through its stdio app-server: relay, marginal-requests, web,
augur-1 and the older DUT Codex conversation. Their exact IDs, original
workspaces, full turns and message/tool item records were checked: 314 turns
and 19,660 items in total. All five remained `notLoaded`; loaded-thread lists
were empty before and after, and the owned reader process exited and was reaped.
Its clean environment contained no credentials, and its client permitted only
initialization and read RPCs. This uses the documented distinction between
[reading a stored thread and resuming it](https://learn.chatgpt.com/docs/app-server).
Thirteen preservation/restore tests pass. Windows and both Linux identities
again failed actual open/close checks on Khadang's protected token. The task
completed with exit 0; private results are retained under migration probe
`1885add62a8f45c7b8c25f781886d093` on the PC.

This proves Codex can read the restored full histories, not native continuation
or phone connectivity. DUT remains selected to Claude, not its older Codex pin.
Claude's subsequent context checks and login activation are recorded below;
unfinished-work continuation, source-final checkpoints and topic cutovers
remain pending.

At 12:32 PM PDT, native Claude 2.1.288 idle-resume checks had covered all ten
preserved pins. Nine passed: ai-hil, supervisor-fw, marginal-requests,
schematic-pipeline-lab, mpu6000-i9, web, augur-1, DUT and mimic-fast-pcb. Each
CLI loaded the exact stored conversation in its original workspace, reported
idle, answered a native context query with nonempty message context, and exited
with code 0. DUT reported 264,188 message-context tokens. Every preexisting
transcript byte remained intact; the sole accepted append was a strictly
validated `cost-state` record for that same session ID. Stored title events
are also scoped to the exact pin, without publishing their contents.

The relay's older Claude pin did not pass. Startup emitted a pending
`task_notification` before initialization completed, and the resulting transcript
append was not ordinary cost metadata. All 47,311,837 original bytes are intact;
the 3,755 appended bytes contain queue, user-notification, last-prompt and cost
records. The source seed remains unchanged. That attempt stopped and remains held
for background-task outcome reconciliation. The subsequent inspection reused
its retained failure and the two accepted checks after verifying their current
transcript digests; it did not reopen that held conversation. All ten owned
children are stopped. The overall task remains a failed acceptance gate, not an
all-green native restore. Private results are under migration probe
`b0e4553fac88b5773b54237296c683e3`, with the retained earlier evidence referenced
there. Its reviewed runtime candidate remains in the protected probe directory;
the source additionally guards retained evidence against foreign/duplicate
workspaces and changed pins.

These checks ran under Interactive/Limited Windows owner session 1 and Linux
UID 1000. The checker sent no user prompt. Tools, MCP servers and customizations were
disabled only for these diagnostic children, not removed from the migration
requirements. Their clean environments contained no credentials and explicitly
disabled [automatic interrupted-turn continuation](https://code.claude.com/docs/en/env-vars).
The background notification demonstrates why that option alone is not a complete
unfinished-work recovery protocol. At that checkpoint, Linux logins, actual
tool-enabled work, phone visibility and the Claude production transport had
not passed acceptance. Login activation is recorded below.
Seven focused regressions pass, alongside the thirteen history/restore tests.
Original preserved seeds and the source Mac sessions remain untouched.

At 12:45 PM PDT, the current PC Windows subscription caches were activated in
the ordinary Linux owner's native homes. The preserved Claude cache was expired;
it was not used in place of the current owner login. Codex's Windows account ID
matched the preserved source account. Linux Codex now selects ChatGPT auth,
and Claude selects `claude.ai` with matching Windows owner account metadata.
This uses Codex's documented
[file-cache transfer](https://learn.chatgpt.com/docs/auth) and Claude's documented
[Linux credential storage](https://code.claude.com/docs/en/authentication).
No API-key substitution was made and no tokens were printed or committed.

Native Codex account and quota RPCs succeeded with no loaded conversations.
Its effective configuration reports GPT-6 Astra, high reasoning,
`danger-full-access`, approvals `never`, reviewer `user`, file-based auth and
startup update checks disabled. Claude retains Opus `opus[1m]`, its source
hook/environment/model settings and 3,650-day retention, while applying the
owner's requested `bypassPermissions` and disabling automatic updates. The
existing Linux machine identity is preserved; only current owner account
metadata and the update preference were merged into its global JSON. Both
pinned CLI launchers are installed under the owner's `.local/bin`.

All five active Linux profile files are ordinary UID-1000 files with mode 0600.
The one-shot activation ran under the exact Interactive/Limited Windows owner
in session 1, then explicitly entered Linux as UID 1000. Windows login/settings
digests remained unchanged; its two native remote tasks and Khadang service
remain running. Windows, Linux `pou` and Linux root all failed actual open/close
checks on the protected Khadang token. The activation task is terminal with
exit 0. Private original inputs and receipts are retained under native profile
`9c45aa2aee1b2f6fe65295082856bc8f`, not in Git. Six focused merge/private-write
tests pass alongside the twenty history/context checks.

This activation sent no model prompt, did not resume any imported conversation
and changed no Telegram routing. In particular the held legacy relay Claude
conversation was not reopened with credentials. It does not yet establish
authenticated unfinished-work continuation, token-refresh/reboot recovery,
complete global instructions/skills/plugin/MCP migration, remote phone
visibility or the production Linux Claude/Codex transport.

By 12:51 PM PDT, both native Linux CLIs also completed authenticated model
calls in new private migration directories outside the bound workspaces.
Codex returned the requested constant, completed its turn, and reported no
tool operations. Claude likewise returned its requested constant using the
subscription login, with no tools enabled. Both ran from the limited
interactive Windows owner as Linux UID 1000, with session persistence disabled;
their owned processes exited and were reaped. Codex's current quota was checked
before inference against the owner's 10% reserve. No original session was resumed.

The first Claude check exited before inference: Windows PowerShell stripped
quotes from inline MCP JSON, which the CLI then interpreted as a nonexistent
file named `{mcpServers:{}}`. The corrected check generated JSON within Linux
and passed; the successful Codex call was not repeated. Both the failed attempt
and corrected evidence remain private on the PC. Model-call evidence is under
`native-inference-9cededc44b4983a3956722e7eccc2386` for Codex and
`native-inference-c84110028ef4dfe3daae5a527c79c4be` for Claude. This proves
working subscription inference, not unfinished-work recovery, phone continuity
or Telegram cutover.

At 12:54 PM PDT, the final check again ran under the limited interactive Windows
owner. Windows and both Linux identities were denied access to Khadang's token,
and no native Linux CLI remained running. Khadang and the Windows remote tasks
were still running. An administrator SSH context can open the Windows file even
when WSL selects Linux `pou`; Linux UID alone is not the boundary. Model launch
must retain the verified limited Windows parent. No credential bytes were read
by either open/close probe and no ACL was weakened.

Five bindings still need source-state reconciliation. Startup Ideas,
kicad-copilot-research and mimic-fast-pcb lack a selected backend marker;
hardware-lite and qwen-lab have a Claude marker but no exact session pin.
Mimic's existing Claude transcript is preserved, not silently selected. Qwen's
actual provider configuration must also be preserved and checked. These are
not missing-history permissions to invent replacement conversations. Native
pending-work recovery, authenticated continuation, final checkpoint capture and
topic cutover remain separate pending checks.

ARM GCC 13.2.1, newlib, OpenOCD 0.12.0, CMake 3.28.3, Ninja 1.11.1,
GDB, Python venv and build dependencies are installed. Tool versions were read
as the ordinary Linux user. That user compiled and linked the fixture into an
ARM EABI ELF with exit 0; the linker support file is present. This is not an
actual project build, flashing or USB acceptance. A systemd binary-format trigger failed while
the WSL status path was read-only; the existing mount was left intact and this
compatibility issue remains to be reconciled before declaring runtime readiness.

At 10:59 AM PDT, Defender quarantined the Windows
`mtg.exe` as `Trojan:Win32/Kepavll!rfn` with Severe severity, terminating both
proxy processes. The original download archive matches the official release's
SHA-256; that does not establish a false positive. WinSW 2.12.0 then failed to
report the child exits because its LocalService account could not open the
service-control manager, leaving both wrappers falsely marked Running. This
matches [the upstream restricted-user bug](https://github.com/winsw/winsw/issues/1136).
No executable was restored and no Defender exception was added. The original
detection remains unresolved; matching the download does not prove that sample
safe.

At 11:48 AM PDT, the two PC services were replaced with the MIT-licensed
[alexbers/mtprotoproxy](https://github.com/alexbers/mtprotoproxy), pinned to
`0614c35020943b2080c9bd27b5e6336270af389f`, using the existing signed Python
and checksum-verified PyCryptodome 3.23.0. The original FakeTLS secrets, domain,
links and listeners are unchanged: loopback TCP10990 behind the existing
TCP443/Cloudflare routes, and direct TCP8443. The flagged executable remains
absent. Defender is enabled and its scan/state checks found no detection against
the replacement at acceptance; this is not a formal security audit.

The native service host and both Python children run as LocalService, with
administrator-owned protected code/configuration and bounded private logs.
Only the two service paths, their bounded SCM recovery actions and the existing
TCP8443 firewall program filter changed. Child death now exits the host, allowing
Windows to observe failure without WinSW's privileged SCM query. An intentional
crash of the loopback proxy produced a non-Running service state and automatic
recovery under a new host PID; no manual restart was issued and the direct proxy
stayed running. Authenticated FakeTLS exchanges and Telegram `resPQ`/nonce
checks passed again after recovery on PC LAN ports 443 and 8443, both public-IP
ports from inside the LAN, and the public Cloudflare helper. Four local adapter
tests also pass. The legacy bench probe emits an undersized TLS ClientHello;
a current independent OpenSSL client passes without weakening server checks.

Protected rollback, installation, recovery and acceptance receipts are retained
in `C:\ProgramData\OracovaMTProto-2a2ae0dae7f749a2bcd664519271c88d`.
Public-IP checks from the LAN do not prove off-network reachability or router
forward ownership. External acceptance and Mac-independent recovery still need
to pass before retiring the Mac.

The 1:25 PM and 1:50 PM PDT rechecks passed authenticated FakeTLS and Telegram
`resPQ`/nonce verification on both LAN ports, both public-IP ports from the LAN, and the
public Cloudflare helper. Both replacement services remain Running/Auto as
LocalService, Defender realtime protection remains enabled, no replacement
detection was present, and the original flagged executable remains absent.

The 3:57 PM PDT read-only service check found both replacement services still
Running/Auto as LocalService, with Defender antivirus and realtime protection
enabled. This check read service/protection metadata; it did not repeat the
authenticated protocol checks or establish off-network reachability.

The 4:12 PM PDT membership recheck remains unchanged: Ai Dispatch member only;
Oracova and Startup Ideas inaccessible. The existing bot-add request is still
pending. Authenticated native continuation, topic cutover, physical bench
transfer, independent recovery and Mac retirement remain incomplete.

### Routing candidate for the original chats

The existing ledger already stores `(chat, topic)` bindings, but the live
in-memory router previously indexed sessions by topic alone and sent bubbles
to the primary forum. The candidate uses the complete address for input,
attachments, approvals, questions, menus and rolling bubble delivery. Explicit
additional chats still admit only Pouya; this does not grant employee access
or activate the deferred company infrastructure. In an ordinary group, topic
0 means no Telegram topic parameter. A missing topic in a forum remains its
General topic, 1.

Startup checks the complete registry and saved bubble destinations before
resuming any thread. Duplicate native thread IDs across addresses are rejected
instead of broadcasting their events ambiguously. Existing LG receipts remain
compatible; newly written receipts also retain their chat/topic destination.
Native resume excludes historical turns from the RPC response, not from the
agent's context, avoiding a hundreds-of-megabytes response on the bounded event
channel. The pinned native release already accepted that option in the prior
two-client diagnostic; migrated-session continuity is not established by the
routing fixtures alone.

The candidate builds without warnings and passes 521 local checks. New joined
tests route the same topic number in two forums and an ordinary group to three
distinct native IDs. They verify exact active-turn steering, per-chat edits of
identical message IDs, native-origin tool/input output, separate menus, denied
cross-chat approval/answer attempts and whole-registry rejection before resume.
These are deterministic fixtures, not live migrated-topic acceptance.

The Windows package is staged, not installed, in
`C:\ProgramData\OracovaRouterRouting-WWOQhn`. At 1:16 PM PDT, the separate
Windows routing harness passed all 33 checks with exit 0 against that exact DLL.
It ran under the non-elevated interactive Windows owner in session 1, after an
actual open/close denial against the protected bot credential. No credential
bytes were read. Candidate code is administrator-owned and read-only to that
owner; the accepted private result is under
`C:\Users\pou\.native-remote\router-routing-eu7EaP`. Its scheduled task is
terminal with result 0, no triggers and no restart policy. The live LG thread,
bubble, configuration and router process remain untouched.

The complete Windows suite also contains an existing administrator-owned
attachment-materialization fixture. An unprivileged attempt failed with
`The security identifier is not allowed to be the owner of this object`
in `Attachments.ProtectDirectory`, correctly enforcing the OS boundary. That
privileged fixture is preserved, not weakened or counted as passed: the complete
Windows suite and native attachment ACL probe must run after the exact-version
deployment decision. A standalone harness references the frozen DLL, so the
unprivileged routing checks can run without exposing the live bot secret to
unapproved administrator code.

Earlier diagnostic attempts and their output remain retained. Windows
PowerShell initially lost native stderr under `ErrorActionPreference=Stop`;
separate output capture then retained the privilege error. A later routing run
printed all 33 passing checks but its `Start-Process` wrapper lost the exit code.
The accepted runner instead owns the child process handle, records both streams
and exit status, and reaps the child. These fresh deterministic fixtures do not
resume or repeat any bound native task or external action.

The exact router DLL SHA-256 is
`26fa0d60980e3cc834178bfaf5719cafe9fdf9825a6ad677d3fcbfed06407959`.
The self-contained package SHA-256 is
`46cbee3a7e8565ade0ddc5caaede9c6b7d57f677166811c0f429185f263031fc`.
This is credential-bearing router code and changes routing authorization, so
activation needs Pouya's decision for this exact version and a matching native
OS-ACL deployment probe. No source binding, native model or Hamal wiring is
changed by staging it. Operational Linux Codex/Claude routing, per-topic
quiescing/final delta capture and bot membership checks remain prerequisites
for the original-topic cutovers.

### Shared Linux Codex transport acceptance

At 2:02 PM PDT, the Windows-to-WSL bridge passed native acceptance with task
result 0. Two clients used the frozen router DLL's existing `NativeRpc` code to
connect to one pinned Linux Codex 0.160.0 Unix WebSocket listener. Both observed
the same kernel peer PID and process generation. An inert diagnostic checkpoint
allowed the second client to resume that exact fresh thread without inference.
Paused goal updates, the dedicated `thread/goal/cleared` event and subsequent
goal reads all agreed across clients. No model turn or unknown diagnostic
operation was observed.

Execution used the exact Interactive/Limited Windows owner in session 1, then
explicit Linux UID 1000. Actual native `command/exec` returned UID 1000 and
could not open the protected bot credential; the probe never read credential
bytes. The native server used a fresh empty profile with no account. The Linux
server exited with code 0 and both Windows launchers were reaped. The live router remained
Running with unchanged configuration; no existing conversation, Telegram
binding, LG session or Hamal wiring was used or changed.

The bridge fixes two measured compatibility gaps. The pinned native server
publishes an owner symlink to a private short socket named by the requested
path's SHA-256. The adapter accepts only that exact mapping, checks the literal
socket and private directory, and rechecks kernel peer, executable inode/hash,
process generation and path identities. Arbitrary aliases, discovery and daemon
startup fallbacks remain rejected. Native notifications also carry `emittedAtMs`;
the bounded parser now preserves that integer metadata instead of rejecting the
whole notification. It is not treated as an acknowledgement or authority. Other
unexpected fields, duplicate keys, invalid numbers and overlarge frames still
fail closed. Earlier failures and their private diagnostics remain preserved;
no live action was replayed. The test's clear-event assertion was corrected
against the existing working relay implementation, not by increasing its timeout.

The self-contained Windows harness builds without warnings. All 62 focused
adapter, JSONL and Unix WebSocket regression tests pass in the verified OS
sandbox; this is not a full 983-test suite run. Diagnostic code is protected and
administrator-owned, read-only to the ordinary owner. Accepted receipts remain
under `C:\Users\pou\.native-remote\migration-linux-transport-1f92b34274a18d32365effd3ade5775f`.
The exact frozen router DLL remains unchanged.

This proves the transport and shared-event mechanism, not live app/Telegram
continuity. Persistent shared-daemon supervision, per-runtime routing, Claude
control, original-topic cutovers, final source checkpoints and recovery tests
remain pending. The interface is experimental according to
[official OpenAI documentation](https://learn.chatgpt.com/docs/app-server), so
the adapter stays version-pinned and must pass compatibility checks before an
upgrade. No deferred role or broker service was activated.

### Claude control interface compatibility

At 2:15 PM PDT, a fresh Windows-to-WSL diagnostic completed with task result 0
against pinned Claude Code 2.1.288. Both `--print` streaming JSON modes, with
and without `--remote-control`, accepted a single `initialize` control request,
reported an idle session, and exited with code 0 after input closed. Each used
a separate empty profile and fresh session ID. No credentials were copied, no
prompt or model turn was sent, and no original conversation was resumed.

The runner used the exact Interactive/Limited Windows owner in session 1 and
explicit Linux UID 1000. It verified the actual child's UID and executable inode
against the pinned binary hash. Both Windows and Linux open/close probes denied
the protected bot credential without reading its bytes. All diagnostic children
and the Windows launcher stopped. The accepted private receipt is under
`C:\Users\pou\.native-remote\migration-claude-transport-81dcd8100b7a6e8a2917b41cc7cf8bd6`.
Production routing, native remote tasks, the LG conversation and source bindings
were not changed. All nine focused regression tests pass in the verified OS
sandbox, including fresh-profile isolation, owner denial, failure retention and
child shutdown. This is not a full 992-test suite run.

This establishes parser and idle control compatibility only. Accepting the flag
does not establish that a remote connection was made or that the headless process
can synchronize phone messages. The [official CLI reference](https://code.claude.com/docs/en/cli-reference)
describes `--remote-control` as an interactive-session flag, while the
[Remote Control documentation](https://code.claude.com/docs/en/remote-control)
requires an eligible subscription login and a running local process. The later
authenticated check below establishes enrollment, not phone/Telegram message
continuity. Existing imported tasks must not serve as diagnostic fixtures. No
deferred role or broker service was activated.

At 2:27 PM PDT, a separate fresh streaming session successfully connected and
disconnected native Remote Control with task result 0. The owner login was
copied into an isolated private diagnostic profile without importing histories,
hooks, tools, MCP configuration or project instructions. Initialization reported
an idle session and Remote Control availability. The explicit `remote_control`
request returned a native bridge session ID and an HTTPS `claude.ai/code/` URL;
the subsequent disconnect was acknowledged. Raw responses and pairing details
remain private. No prompt was sent or existing conversation resumed.

The mechanism comes from the inspected, registry-integrity-verified
[`@anthropic-ai/claude-agent-sdk` 0.3.288 artifact](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.288.tgz): its `enableRemoteControl()`
method sends this control request, rather than relying on the interactive CLI
flag. That method is not declared on its public `Query` type, so this remains a
version-pinned integration that needs the same native compatibility check before
an upgrade. The SDK's user-message type also has `priority: "now"`; this is the
candidate mechanism for immediate steering, not yet an active-turn test result.
No SDK package or alternate CLI was installed on the PC for this inspection.

The accepted run used the Interactive/Limited Windows owner in session 1 and
actual Linux/native UID 1000. Both OS probes denied access to the protected bot
credential without reading bytes. The pinned native executable and ordinary
child identity were checked. Native exit was 0 and the Windows launcher stopped.
The terminal task has no triggers or restart policy; its private receipt is under
`C:\Users\pou\.native-remote\migration-claude-remote-c658e18cbaf04866622e3cc887c7453d`.
Its administrator-owned task and source code were sealed before launch. Windows
initially normalized the task descriptor and added a principal read ACE; the
documented [`TASK_DONT_ADD_PRINCIPAL_ACE` flag](https://learn.microsoft.com/en-us/windows/win32/taskschd/registeredtask-setsecuritydescriptor) produced an OS-verified protected
SYSTEM/Administrators-only descriptor. The task was never started while those
registration checks failed. The Windows API also normalized its principal name
to `pou`, which was resolved back to the exact owner SID before launch.

All 13 focused enrollment and compatibility tests pass in the verified OS
sandbox; this is not a full 996-test suite run. The live router stayed Running
with unchanged configuration and the original Windows native remote task stayed
Running. No binding, LG conversation or source writer changed. Phone/Telegram
round trips, immediate active-turn steering, controls, permissions/questions and
operational supervision remain required before original-topic cutovers.

### Claude native session client

At 2:52 PM PDT, the typed C# Claude client passed an authenticated PC check
against pinned Claude Code 2.1.288. A fresh, isolated conversation acknowledged
the exact submitted user UUID, emitted eight partial progress events, returned
the fixed diagnostic reply and reported idle after its result. The native process
exited with code 0, the Windows launcher stopped, and the one-shot task finished
with result 0. No operation remained uncertain. This used the ordinary Windows
owner in session 1 and actual Linux/native UID 1000; both OS probes denied the
protected bot credential without reading bytes.

The check used one inert subscription prompt with tools, hooks and MCP disabled.
It did not resume imported history, enroll Remote Control, poll Telegram or
change any live binding. Its private receipt is under
`C:\Users\pou\.native-remote\migration-claude-wire-f016dbb82c29396fcc0738180c05bd2a`.
The tested candidate DLL SHA-256 is
`2b7403e3a0ab0a3ac52c3c4ae201822ae1c4947788e735ab76fba217890d33d7`;
the sealed package SHA-256 is
`e1aef433d9aa233b6e3d175edd203644bc2a3c8571af353ced5395d59fc8308c`.
The previously frozen routing DLL and production configuration were not replaced.

`ClaudeNativeStream` preserves Claude's own control protocol rather than
emulating Codex requests or inventing turn IDs. Input uses native `priority:
"now"` and `--replay-user-messages`; its receipt establishes consumption, not
turn completion or active-turn steering. Native requests and explicit rejections
are journaled. A lost receipt stays uncertain, with no automatic resend or new
conversation fallback. An answer is bound to its native request ID, but a write
alone is not reported as permission acceptance. The controller still must
authenticate the human and bind approvals to the correct topic and task.

The pinned SDK also establishes two recovery details now covered by fixtures:
pending permission and user-dialog requests are siblings of the initialization
response payload, and `/clear` emits a distinct `conversation_reset` event.
The client restores pending questions, deduplicates live/replayed requests and
retains durable answer/cancellation records so an old request cannot revive an
answer. A reset invalidates the old session pin and its pending requests; the
controller must persist the new binding before further input. These are component
checks, not acceptance against a real unfinished project or human approval.

At the standalone-client milestone, all 563 PC-router self-checks and five diagnostic input-guard tests passed in the
verified OS sandbox with host credentials and network excluded. Both C# builds
have zero warnings and errors. The live router and original Claude remote task
remain running. Operational session launch/routing, active-turn steering,
questions/permissions, phone/Telegram round trips and original-topic cutovers
remain pending. No deferred role or broker service was activated.

### Mixed native topic routing candidate

The existing router now accepts explicit backend and runtime fields while
retaining the old five-field Windows Codex bindings. It selects each topic's
native transport and checks the entire registry before any resume. Windows and
Linux Codex events cannot enter each other's bubbles even if a payload names
the other thread. A missing adapter, foreign workspace, duplicate pin or
conflicting saved bubble stops startup rather than selecting another backend.
Linux path checks here are logical checks, not proof of filesystem ownership;
the operational launcher still must establish that boundary.

Claude has a separate path using its native message and control envelopes.
Owner messages carry human provenance and native `priority: now`; a replay
receipt proves consumption, not completed work or exact active-turn steering.
Only native idle finishes work. Pending questions survive initialization races,
and startup failure closes every acquired stream. App-origin inputs, assistant
text and tool names amend the same bounded bubble; thinking, subagent text and
raw tool arguments are not mirrored as progress.

Question answers are bound to the exact topic, session, active work and native
request. They preserve the original tool input and key answers by the full
question text, following the [Claude user-input contract](https://code.claude.com/docs/en/agent-sdk/user-input).
Cancelled or cross-topic nonces do not send a reply. Structured credential fields
and overlong requests cannot be published or approved from an incomplete
Telegram review; the owner can still deny the exact tool request. Unknown
dialogs are neither answered nor cancelled automatically. A native answer write
still remains uncertain because that protocol has no response acknowledgement;
real consumption/reconciliation evidence is required before further model input.

Claude model selection uses its initialization catalog, effort uses session-only
settings, and usage reads skip transcript scanning without blocking interrupt
or owner input. These acknowledgements are not independent model/settings
readbacks. The 10% owner reserve remains unenforced. Claude-only chats omit
Codex goals from the menu. Mixed chats use their supported command union because
[Telegram command scopes](https://core.telegram.org/bots/api#botcommandscope)
do not have a topic scope; `/help` and dispatch still use the exact topic.

All 609 PC-router checks and six diagnostic input-guard tests pass in the
verified OS sandbox, with host credentials and network excluded. Both C# builds
have zero warnings and errors. These are controller/component fixtures, not
Windows credential-boundary, phone or live-topic acceptance. The 3:19 PM PDT
read-only PC check found the original router and Claude remote task running
with the unchanged production configuration. No live binding, bot token,
protected release or Hamal wiring was changed.

Actual ordinary-owner launch acceptance, persistent Linux daemon supervision,
native answer-consumption reconciliation, exact reset rebinding, real
active-work/phone/Telegram and attachment-readability acceptance still need to
pass before original-topic cutover. `/clear` currently sends no reset; observed
native resets durably retain the new ID and hold old-pin input for explicit
reconciliation. This is pending implementation, not removal of reset support.
The Mac, physical bench transfer and independent disaster recovery remain in
scope; no new role or broker service was activated.

### Linux Codex router launch wiring

The router candidate now contains a Linux Codex connection path through the
existing Windows owner launcher and Unix WebSocket adapter. It launches only fixed `wsl.exe`
arguments for Ubuntu 24.04 user `pou` and isolated Python; it does not run a
shell, start a daemon, select a different socket or replay a failed connection.
The optional runtime policy pins the Windows launcher and all six connector
files in an administrator-owned package. Legacy Windows-only configuration
does not activate this path.

Before native initialization, the launch path checks the actual limited Windows
token and attempts to open the protected bot credential under that token. The
Linux connector checks literal workspace ownership, attempts the same credential
open, and verifies the existing daemon's kernel peer credentials, pinned executable
and process generation. Unexpected credential access closes the handle without
reading bytes and refuses launch. The controller brackets connection setup and
each frame with its Windows process observation; the connector continues checking
the Linux peer and workspace directories. These checks establish personal-owner
execution, not separate agent or company identities.

The native connection initializes once, reads the owner's ChatGPT account without
refreshing authentication, and executes only fixed `id -u` verification before
routing. Account metadata is not proof of successful inference. The service still
requires matching policy/code and Windows OS proof, and Linux bindings additionally
require that candidate's Linux launch/tool-owner proof before Telegram polling.
Native JSONL is bounded before RPC parsing; incomplete EOF frames, invalid Unicode,
duplicate readiness fields and changed process generations fail without fallback.

All 690 PC-router checks and 19 connector tests pass in the verified OS sandbox,
with host credentials and network excluded. The router and standalone Claude
probe both build with zero warnings and errors. These are component/controller
fixtures, not acceptance of the privileged Windows launcher. A read-only PC
check at 3:41 PM PDT found the original router and Claude remote task still
Running, with the production configuration unchanged.

Windows/WSL acceptance of this launcher, package deployment, persistent native
daemon supervision and native Claude launch acceptance remain pending. The prior isolated
shared-socket acceptance does not prove this new privileged launch path. No live
configuration, binding, token, protected release or Hamal routing was changed.

### Optional Claude source session resume connector

This connector implements the earlier original-session resume path. It is
optional under the revised migration policy. Explicit fresh-session creation
from a checked project handoff still needs wiring and target acceptance; the
following source-resume checks must not become gates for that new path.

The candidate now includes a Linux Claude stdio connector for the preserved
native profile, not the isolated diagnostic profile. Its launch arguments resume
only the supplied saved UUID, retain user/project/local settings and leave tools,
hooks, MCP configuration and model selection enabled. Explicit owner policy
selects full access; it is not inferred from a role name. The settings and stream
flags follow the [native CLI reference](https://code.claude.com/docs/en/cli-reference);
the special permission handler follows the
[SDK's stdio control routing](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py).
Actual custom-provider, Qwen and customization compatibility remain unverified.

Before any native launch, the connector requires an exact protected handoff
digest, the original transcript's size/hash, a quiesced source-writer declaration
and no unresolved external actions. The Windows parent must authenticate that
reviewed handoff and establish actual source quiescence; the JSON declaration
alone does not establish either. The known legacy Claude task remains held.
The connector verifies workspace ownership and actual credential open-denial,
then checks its owned native process's generation, executable, UID and inherited
lease descriptor. It never reads the protected bot credential, selects a fresh
conversation, reconnects or repeats uncertain input.

All 22 new Claude connector fixtures and 19 Codex connector fixtures pass in
the verified OS sandbox. These cover strict handoffs/framing, final output after
process exit, procfs exit races and cleanup without relaunch. The lock-contention
fixture uses an actual POSIX kernel lock on the Mac; it does not prove that the
pinned Linux Claude binary retains the descriptor or stops all detached tools.
The lease coordinates participating bridges, not arbitrary native CLI writers.

The Windows launch path and Claude topic factory are now implemented in the
router candidate. The optional runtime policy pins all seven Python files and
each handoff in an administrator-owned package. Every checkpoint binds the
exact chat, topic, workspace and native UUID; the whole selected registry is
validated before any native launch. The existing owner launcher supplies fixed
WSL arguments, verifies the actual limited console token and checks credential
open-denial before starting the connector. No new broker or role service is used.

The factory commits a handoff receipt before launch. A failed observation or
router restart cannot silently reuse that same checkpoint; a reviewed next
checkpoint or explicit protected-ledger reconciliation is required. This hold
does not complete automatic recovery: capturing subsequent PC checkpoints and
reconciling interrupted generations still need implementation and acceptance.
The channel checks exact bounded readiness and brackets native traffic with the
owned Windows process observation. An actual terminal process handle permits
draining only the original private output pipe, never another input or connection.

The generic router probe deliberately leaves Claude launch, tool-owner and
continuity acceptance unverified. It must not resume a production handoff merely
to test the launcher. Claude routing requires dedicated acceptance for the
matching policy/code before polling; the receipt-writing native probe is still
pending. Fixture results cannot supply those approvals or OS evidence.

All 778 PC-router checks pass in the verified OS sandbox. Both the router and
standalone Claude probe compile with zero warnings/errors. The fixtures cover
scope drift, owner/generation changes, terminal output, invalid UTF-8 and
handoff holds across an independently reopened SQLite connection. They do not
establish actual Windows/WSL or preserved-session acceptance. The 4:11 PM PDT
read-only PC check found the original router and Claude remote task Running,
with the production configuration unchanged.

Native descriptor/parent-death and tool-owner acceptance, source-writer fencing,
final checkpoints, PC restart recovery and live tool/phone round trips remain
pending. This is source wiring only; no PC native launch, production configuration,
topic binding or privileged deployment changed.

### Physical bench preservation and PC builds

At 1:28 PM PDT, the physical MacBook's operational archive completed with
source, SFTP and target reader exit 0. Its 38 explicitly selected members include
the bench repositories, signing and PKI material, original firmware backups,
capture records, compiler/tool installations, VPN and tunnel records, SSH
configuration and shell profiles. The 2,629,314,560-byte archive has matching
source and PC SHA-256
`48542d3b8f5ecbd74537ea3be82234667f1d6a42366473172ccab8398f44da2a`.
The destination is
`C:\ProgramData\OracovaMigration\38258191bb20aac6fae35f6f964cefd8`;
its archive and receipts are administrator-owned and accessible only to
SYSTEM/Administrators. No private key bytes were printed or published. The
source produced no warnings. GNU tar ignored two Apple backup/FileProvider
extended attributes while listing the archive successfully; the original
archive bytes and full reader warnings are retained privately.

The existing archive helper now accepts only the literal `bench` SSH source,
checks its ordinary `oracova` identity and owned canonical root, quotes every
remote argument, and rejects whole-home and parent-traversal selections. The
eight tests pass with 25 assertions. Source data travelled over SSH/SFTP into
private local and protected PC files. It is not encrypted at rest by this helper,
was not extracted or activated, and remains a seed while source writers run.
Darwin binaries are preserved evidence, not usable Linux replacements. Final
checkpoint capture and the encrypted off-machine daily recovery system remain
pending.

A compile-only check ran from the exact Interactive/Limited Windows owner in
session 1, then Linux UID 1000. Actual open/close probes denied access to both
the bot credential and protected bench archive tree. Four compile workers used
new private output directories, outside the preserved repositories; no model,
board connection, power change, firmware signing or flashing was performed.
Git state, the build inputs and the original pairing header remained unchanged.
The terminal one-shot task has no triggers or restart policy. Its private result
is retained under
`C:\Users\pou\.native-remote\migration-bench-38258191bb20aac6fae35f6f964cefd8`.

The real Nucleo trackpad firmware configured and built without warnings using
ARM GCC 13.2.1, CMake 3.28.3 and Ninja 1.11.1. Its 80,512-byte ARM executable has
SHA-256 `8fabc13cf4371711b845e53a7fcc10d147894eaa65d6666a0edbcd092be0d193`.
This proves that project's preserved sources and Linux toolchain can build on
the PC; it does not prove device operation or a Windows trackpad application.

The supervisor config-0 application configured successfully but failed to
compile. Its CMake target includes `platform/augur_pwm_stm32.c`, whose explicit
board guard reports:

```text
platform/augur_pwm_stm32.c:7:2: error: #error "PWM binding requires selected H5 config1 or H743 config2"
    7 | #error "PWM binding requires selected H5 config1 or H743 config2"
      |  ^~~~~
```

Both the CMake file and PWM source have identical hashes on the live Mac and
preserved PC seed. This is an existing source/board-selection conflict, not an
unproven Windows dependency or timeout explanation. The combined check therefore
retains result 1; the passing trackpad build does not turn it into an overall
pass. The guard, config-0 pinout and firmware source were not weakened or edited.
Supervisor build resolution, project/runtime validation and physical USB/flash/
debug/serial/hub-power acceptance remain pending. The hardware is still connected
to the MacBook.

### Active session checkpoint

Pouya confirmed Mac to PC migration on October 3. The three live Mac Claude
sessions, ai-hil, supervisor-fw and duts, saved task-specific handoffs and
reported idle. Native metadata showed the other three project Codex threads,
augur-1, web and marginal-requests, were not loaded and had no current goals.
These observations are not a source-input fence: Mac processes and routing
remain available until their PC replacements are verified.

The latest workspace delta completed successfully, transferring 18 new or
changed files without deletion and preserving replaced PC versions. The three
live-agent handoffs have matching source and destination SHA-256 values.
The PC supervisor worktree is at `816432b231da4f39ad636bd00b5bbea3c9aeee37`
and retains all 260 commits ahead of `origin/supervisor-fw-v3`. Those commits
were copied with Git metadata; no push of that branch was performed.

The first fresh PC DUT Claude startup failed before project work: native
Claude reported an expired OAuth session that could not refresh. The Windows
cache was current, while the earlier Linux cache copy was stale. An independent
Linux subscription login is awaiting Pouya's browser code; no API-key fallback
or old project action was replayed. The failed attempt and its new PC UUID are
retained for reconciliation, not silently replaced.

Native stderr also identified a separate launcher error: explicitly setting
`CLAUDE_CONFIG_DIR` looked for global JSON inside `.claude`, instead of the
migrated `HOME/.claude.json`. The candidate now uses native defaults with the
literal owner HOME; all 22 focused connector tests pass in an OS-verified
sandbox. This code change is not deployed to the protected router.

Original-topic cutovers remain **0 of 14**. The existing PC LG route, protected
bot credential, production configuration and shared Mac Codex daemon remain
unchanged. The three live handoffs are checkpoints, not evidence of completed
PC routing or Mac retirement.

Detailed historical implementation evidence remains in
[deployment status](../pc-router/deployment-status.json) and the
[deferred roadmap](agentic-pc-20-pr-roadmap.md).
