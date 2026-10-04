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

Pouya's scope decision, October 3 at 11:19 PM PDT: exclude both the local Qwen
model server and Ai Dispatch's Qwen lab topic `10656` from the PC migration.
Do not bind that topic to Khadang or substitute Claude. Existing source files,
histories and backups are not authorized for deletion by this exclusion. This
supersedes the earlier requirement to migrate all fourteen original bindings:
thirteen are now required, with Qwen explicitly excluded.

The Mac remains the rollback source until the PC passes the checks below.
Retiring its services is distinct from erasing a Mac or VM; no filesystem wipe
is authorized until the exact target is resolved and verified copies exist.

## Current inventory

The original OpenClaw configuration contained 14 bindings: eight topics in Ai
Dispatch, five in Oracova, and the standalone Startup Ideas group. As of the
October4 readback, eleven included originals plus the existing PC LG topic
route to the PC (twelve total). Required routing migration progress is11/13;
Startup Ideas and KiCad remain pending. The three source bindings also include
Qwen, which is explicitly excluded. Keep the included chat and topic IDs
unchanged; the existing PC LG topic remains intact. Connected routing is not
the broader hardware, phone, source preservation or recovery acceptance.

| Project | Chat | Topic |
| --- | --- | --- |
| startup-ideas | -5238984877 | Whole group |
| ai-hil | -1003550185469 | 1876 |
| supervisor-fw | -1003550185469 | 5786 |
| claude-code-relay | -1003550185469 | 816 |
| kicad-copilot-research | -1003550185469 | 6004 |
| hardware-lite | -1003550185469 | 6333 |
| qwen-lab (excluded by owner; no PC route) | -1003550185469 | 10656 |
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
guessing a transcript by modification time. Qwen is excluded by the scope
decision above: do not migrate its provider or replace its backend with Claude.

The source workspace is approximately 49 GB, with another 1.6 GB of OpenClaw
media, 2.3 GB of Codex sessions and 1.2 GB of Claude project history. The PC has
ample disk space. All source workspace files now have a checksum-verified PC
archive and an extracted workspace; project validation and operational checks
are not complete. The separate
physical bench MacBook is not the Mac VM holding the relay workspace. Its
selected operational projects, firmware, keys, captures and tool installations
now also have a protected, checksum-verified PC archive. That archive is not an
activated bench environment or a final checkpoint.

The protected Windows Khadang service now routes the existing PC LG topic plus
Web, Base board, Marginal Requests, DUT, Schematic Pipeline, Mimic Fast PCB,
Hardware Lite, MPU6000-i9, ai-hil and Supervisor firmware
in their original forums. All five original Oracova PCBA topics are connected. The personal
router supports full chat/topic addresses, an explicit whole-group route and
distinct Windows Codex, Linux Codex and Claude paths. Linux Codex's exact
Windows-to-WSL launcher passed acceptance against the connected, separately
paired PC managed daemon and is now activated. Only Web has a genuine
owner-message round trip verified so far; the new PCBA routes have exact native
resume and confirmed connection notices. Linux Claude subscription login is
established; DUT and both lab topics have live native streams and Claude app
enrollment. Hardware Lite and MPU6000-i9 are also connected and enrolled.
The four newly migrated inactive topics passed actual handoff/tool-owner and exact-session
continuity checks, not yet genuine owner phone-message round trips.
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
   prepare Khadang's new PC session and the same-topic binding under a non-polling
   native/code/policy probe. Before activating that topic's PC input, disconnect
   Jamshid/Hamal for that address: remove its explicit binding, disable topic
   ingress so default routing cannot take over, stop its old live-update watcher
   and retire the source native-session pointer recoverably. Then activate
   Khadang and verify owner input and its same-topic reply. Pouya explicitly
   requires every Khadang-connected topic to disconnect from Jamshid; never
   leave both bots accepting project work. If activation fails, keep delivery
   held or restore the single old route only after the PC route is stopped;
   do not enable both as a recovery shortcut. Continue active-turn steering, tools,
   one rolling bubble, controls, attachments, app-origin updates where supported
   and new-session restart acceptance on the PC. Do not require recovery of
   its old Mac session. Keep relay topic
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

- All13 included existing bindings work through Khadang on the PC with the
  same IDs and intended tools; the LG topic also remains working. Qwen's
  explicitly excluded topic/server are not migrated or replaced, and their
  source files/history remain preserved rather than erased.
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

### Mac-style PC Codex daemon and exact Claude phone session

The working Mac VM uses Codex 0.160.0's managed daemon with Remote Control and
an owner-private Unix WebSocket. Its login/300-second launchd check starts only
a missing daemon. The former PC Windows setup instead has separate stdio
processes for Remote and Telegram; registering one does not share the other's
live conversations.

On October 3, the equivalent managed Unix daemon was installed in Ubuntu 24.04
on the PC. `Oracova-CodexWslRemote` runs as the exact Interactive/Limited Windows
owner, then Linux `pou` (UID 1000), at owner sign-in and with five-minute
supervision. The control directories/socket have owner-private permissions.
The observer verifies the kernel peer, generation, exact package inode and
reviewed binary hash before native initialization and read-only status/account
requests. It never resumes a conversation, sends a prompt or answers approvals.

Native bootstrap initially enables package auto-updates. The newly installed
daemon had no loaded conversations, so native `daemon update --from-cli --yes`
selected and pinned the identical reviewed 0.160.0 CLI package. The automatic
update marker is now absent; supervision uses `daemon start`, never bootstrap,
update or restart. This changed only the newly installed WSL daemon, not the
working Mac or existing Windows native processes. No inference was requested.

The WSL daemon is running but its native phone transport reports `errored`.
Both PC Windows and WSL profiles have the same OpenAI account fingerprint;
the working Mac VM has a different one. Account identity was compared without
exporting credential values. This explains why that PC account's host would
not appear in the other account, but **does not establish the cause of the WSL
connection error**. Pouya's account choice and a successful same-account phone
round trip remain pending. No credential transplantation or fresh login was
performed. WSL Telegram routing, boot/crash acceptance and original-topic
cutovers remain unverified; the existing LG binding and protected router code,
policy and credential are unchanged.

At Pouya's explicit request, native `remote-control pair --json` issued a
short-lived PC manual pairing code at `2026-10-04T01:09:31Z`, expiring at
`2026-10-04T01:19:34Z`. The one-shot operation ran as the ordinary interactive
owner against verified WSL daemon PID 1174; it did not restart the daemon,
change accounts or start inference. The protected, trigger-free task
`Oracova-CodexWslPair-CgBorX` is disabled after its confirmed receipt. Pairing
secrets remain in owner-private PC evidence and were not added to source.
The fresh read after code issuance still reports `errored`; issuing a code
does not establish mobile acceptance or a working phone connection. Phone-side
code entry and successful transport verification remain pending.

At `2026-10-04T01:19:09Z`, following Pouya's phone-side confirmation, native
`remoteControl/pairing/status` returned `claimed: true`. The same verified WSL
daemon's `remoteControl/client/list` contains one iOS phone, app 1.2026.267.
**Device pairing is verified; a working phone connection is not.** The daemon
still reports `errored`, and its actual WebSocket logs show HTTP 409 Conflict,
`Remote app server already online`. Earlier diagnostic output incorrectly
looked for a nonexistent `message` column; this version's logs store bodies in
`feedback_log_body`, and the diagnostic was corrected. Windows and WSL have
different installation fingerprints and remote environment IDs. WSL contains
only the one native Codex process; the conflicting cloud connection has not
been identified. Existing Mac, Windows Codex, Claude and Telegram sessions were
not stopped, re-paired or restarted. Code expiry after acceptance does not
undo the confirmed registered phone; do not issue another code as a connection
workaround.

At `2026-10-04T01:25:50Z`, the owner clarified that code entry produced no
error but added no PC. Root cause is now verified: the copied `state_5.sqlite`
contains the Mac's `remote_control_enrollments` row, including its server and
environment IDs. Those IDs match the WSL connection and issued pairing code;
fresh read-only RPC on the live Mac reports `connected` to that exact same
environment. The enrollment primary key is WebSocket URL, account ID and
app-server client name, **not installation ID**. The PC's different installation
ID therefore did not invalidate the migrated live-host registration. The code
paired the phone with the existing Mac identity, not a distinct PC.

Corrected acceptance: code claimed and phone registered against the copied
identity, **distinct PC enrollment and app visibility not verified**. Repair
must back up the PC database, clear only that copied enrollment locally, then
let the empty WSL daemon enroll its own host and issue a new native pairing
code. This requires stopping only the new WSL daemon while changing its cache,
not the live Mac, Windows remote hosts, Telegram router or any histories/auth.
At that observation no enrollment had been deleted; the owner was asked to
approve the targeted local cache removal.

After Pouya approved, the ordinary owner repair backed up the PC's database to
`/Users/pouya/.migration/codex-enrollment-repair-CgBorX/before.sqlite` (owner-only;
SHA-256 `d2309ab67750983bce88f1abb586a0cd5a6c3f2f8f7026e53a06dfdb322c2e86`).
Only the empty WSL daemon was stopped. Exactly one matching copied Mac enrollment
was removed locally; all other database data/schema, histories and logins were
verified unchanged. The source archive and live Mac enrollment were untouched.
Native startup regenerated the PC registration without revoking the Mac host.

At `2026-10-04T01:33:56Z`, the new WSL daemon PID 2141, generation 229385,
reports **connected**. Its environment fingerprint is
`411f13f2b5008f9b1d9be1f4a6900aa2e435f21bd7bb076c490b6cb57622cdfa`,
distinct from the still-connected Mac environment
`5424e0396b3c6136b14c48a326674545a1f796bae22b7f38750b4ba8a69417ba`.
The five-minute supervisor is running again; automatic updates remain disabled.
The protected one-shot repair task completed with result zero and is disabled,
not scheduled for replay. Existing Windows Codex, Claude and Khadang processes
and router code/configuration were not changed or restarted.

A fresh native pairing code was issued at `2026-10-04T01:33:28Z`, expiring at
`2026-10-04T01:43:31Z`, for this **distinct PC** registration. Its private value
was sent to the owner, not committed. The fresh native read at
`2026-10-04T01:35:21Z` reports connected, matching pairing/native environment,
`claimed: false`, and no registered clients. At `2026-10-04T01:38:03Z`, a fresh
native read reports **connected**, `claimed: true`, matching pairing/native PC
environment, and one registered iOS phone (app 1.2026.267). **Distinct PC host
enrollment and phone pairing are now verified.** Phone-side app visibility and
an actual conversation round trip still need confirmation. The earlier claimed
receipt belongs to the copied Mac identity, not this PC.

The fresh-host history restore now excludes `remote_control_enrollments` only
from the new copied database, after existing-destination and stopped-native
checks and before immutable history validation/native startup. It retains the
raw source snapshot, conversation rows and schema, checkpoints the standalone
copy and requires native reenrollment. This is a new-host migration rule, not
same-host disaster recovery. Five added fixtures cover preserved source/history,
WAL visibility, missing/empty enrollment tables and refused symlink redirects.

All 37 native-connector/observer/history fixtures pass in an OS sandbox without
network or owner credentials, including ten history-restore fixtures. Both
deployment scripts parse on Windows and eight exact
missing-socket classifier fixtures pass. Native absent-daemon `version` reports
errno 2 rather than JSON `stopped`; only that exact measured absence permits
startup. Other errors do not trigger a lifecycle retry.

Pouya explicitly requires the existing **PC - Native Claude** phone conversation
in Telegram, not a new conversation. Its existing Windows remote host and child
remain running. The inspected SDK 0.3.288 `/bridge` API registers a worker and
increments its epoch; a second worker attachment could supersede the working
one. It is not a non-owning Telegram client. No worker attach, replacement
conversation or inert Telegram topic was created. A non-owning client route to
the exact live `cse_*` conversation is still required.

### Actual router-to-managed-Codex launch acceptance

At `2026-10-04T01:53:10Z`, the current router candidate's real
`LinuxCodexChannel.ConnectVerified` passed on the PC. The fixed, protected
one-shot SYSTEM diagnostic used the existing launcher to create a **limited
Windows pou process in session 1**, then Linux UID 1000, and attached to the
existing daemon PID 2141 / generation 229385. It verified the exact native
package, Unix peer/socket alias, literal `ai-hil/web` workspace, authenticated
ChatGPT account and actual fixed native tool executor UID. The connector and
Windows launcher verified real denial of the protected Khadang credential.

Native status remained connected to the distinct PC environment, with one
registered phone and zero loaded threads. No project was resumed, no model was
started, no Telegram poller was created, and no live binding or production
router code/configuration changed. The diagnostic task
`Oracova-ManagedCodexProof-c2853fc76b074dfbbcdf638be6035c04` completed with result
zero and was disabled after receipt. Its protected evidence is
`C:\ProgramData\OracovaNativeRemote\codex-connector-c2853fc76b074dfbbcdf638be6035c04\proof\result.json`.
The tested candidate DLL SHA-256 is
`305c17b8ea11bdb296de2b1644b54b1e8cc77b592daa8dbf854f32d9e8478ae6`;
the diagnostic policy SHA-256 is
`a3e3f27a9710278087dc1e1bca57d6eb3de21883672f39ef1644c72ea90c4243`.
This proves the native connector, not acceptance of a future production policy
or a completed Telegram cutover.

The first diagnostic had already passed launch/account/tool identity but
explicitly rejected `remoteControl/client/list`: the probe omitted required
`environmentId`. The query was corrected using the working native pairing
observer's exact parameters, and a separate, fresh diagnostic run passed; the
failed receipt is retained and its task disabled. No uncertain operation or
original project was replayed. The installer also passed Windows parsing, its
fixed read-method guards passed on Windows, and all **787 PC-router fixtures**
passed in an OS sandbox excluding credentials and network. The next operational
step is checked fresh PC session creation from a source handoff, then the same
original topic binding. Original-topic cutovers remain **0 of 14**.

### First original topic live: Web, October 3 evening

Original-topic routing cutovers are now **1 of 14**. Web remains Ai Dispatch
chat `-1003550185469`, topic `8660`; no replacement Telegram topic was created.
Its fresh PC Codex thread is `01a104a6-9fce-74a3-bdb0-e6dc04237ce7`, model
`gpt-6-astra`, workspace `/Users/pouya/.openclaw/workspace/ai-hil/web`.
The existing Windows LG topic/session remains unchanged.

The full source and target Web directories match: **393 files, 522,066,731
bytes**, content/tree SHA-256
`f0770ffe769f5ede1619d2b64b603f5f9221e486f1097667627573c82b007a42`.
The final source read remained unchanged after the greeting exchange and
before retirement; its old native thread was no longer loaded. The private
`PC-MIGRATION-HANDOFF.md` also matches at both ends, SHA-256
`d6fe808e29a4ea5854eada96de66c7469ed8e5028c736304f7c03ebe51bda1dd`.
The last Fusion deliverable and landing-concept WIP notes are preserved. Fusion
automation on Windows is still unqualified, not replaced or discarded.

The one-shot session creation `cbd984bbed3d4784b7254840bc837208` confirmed
`thread/start`, `thread/inject_items` and `thread/name/set`. Its final assertion
failed because `thread/read` does not expose an injected raw-only Responses
item as a normal turn. An independent read of the exact native rollout found
the complete, exact user checkpoint, context SHA-256
`5db2b3691eb1bba7b4eecc7406152d58c20a8081c0703302404d30f06585b704`;
no creation or injection was repeated and no model turn was started by that
creation attempt. Failed evidence remains retained; the verification helper
now checks exact session identity and raw user checkpoint storage instead.

Protected deployment preimages are retained under
`C:\ProgramData\KhadangRouter\release-5270c60967fa4c8bb426a68279afb0be`.
The migration used a consistent SQLite snapshot and verified that all existing
LG binding and unrelated ledger data remained unchanged. Both pre-deployment
and installed Windows fixture runs passed **790 checks**. The exact new code
and policy passed a fresh production SYSTEM-to-limited-owner probe, including
UID 1000 execution against the still-running paired daemon PID 2141, generation
229385, and actual protected-credential denial. No generic probe inferred
Claude acceptance or generated a model prompt. Web-cutover release hashes:

- Router: `f61b190c8c4d212d982ce576e2223f35314fc18884e08d70558a7662f959a7a1`.
- Policy: `740cd20e8b688a7cc14f8faa574951f54f6c27c2d56df0b4f2d352a6f4a204e2`.
- Archive: `7fc51635af416e8f71f83565fe52be8d2e8ec7af0d4734fb421863d0dacaf203`.

Production activated at approximately `2026-10-04T02:13:43Z`; deterministic
owner-ready startup supervision is enabled again. Real Telegram owner updates
759322599/message 13599 and 759322600/message 13601 reached this exact PC
thread, with two confirmed native turns and same-topic replies. The first
reply confirms the handoff was loaded. Telegram response message IDs **13598
and 13602 are distinct**, with confirmed edits and terminal Done; no held,
unknown or pending response remained at the observed receipt. These are actual
owner messages, not a synthetic deployment canary. A read-only receipt helper
`pc-router/inspect-web-cutover.ps1` exposes only this route's acceptance metadata.

Pouya then explicitly required immediate disconnection from Jamshid for every
Khadang-connected topic. The controller removed only Web's Mac OpenClaw
binding, added `enabled:false` for that exact topic (preventing default-agent
fallback), stopped watcher `crw-c6111d2d6d`, and archived the old Mac native
pointer. Configuration validation passed, a structural comparison confirmed
all unrelated configuration was preserved, and the running gateway logged the
hot reload at `2026-10-03T19:17:12-07:00`. Its Telegram channel reloaded normally;
the shared Mac native daemon and other topic bindings were not restarted or
removed. Private preimages are in
`/Users/pouya/.openclaw/web-topic-cutover.7nQWLb`, with a protected PC archive.
That archive is 4,285 bytes, SHA-256
`1af94d158f90a86c430b8eb5b0b522a182e915de018724096a26ca6b4402b3f1`;
source producer, SFTP, target archive reader and content verification all passed.
The PC's ordinary-owner legacy session pointer now references the same new Web
thread; its prior value is retained as a private backup.

Remaining acceptance includes Web tool/steering/control/attachment and phone
UI/restart checks, the other thirteen original-topic cutovers, independent
Claude continuity, physical bench movement and Mac-independent recovery.
The Mac is not erased and full migration is not complete.

### Compact input formatting, October 3 evening

Plain Telegram text now reaches the native model unchanged: `Test`, not
`[Telegram owner 110123423; message 13604]\nTest`. Authenticated sender and
message IDs remain in the durable delivery ledger. Attachment trust warnings
and file metadata remain intact. This is the owner-only adapter; employee
identity or authorization has not been relaxed.

Telegram echoes use `↪ Test` instead of `↪ Native input: ...`. Restored current
bubbles and old native input events compact the legacy wrapper only for
display; native history and audit receipts are not rewritten. The same plain
input behavior is covered for Claude in fixtures, not claimed as live Claude
acceptance. Six added checks cover exact plain inputs, compact echoes, legacy
display, preserved footers and unchanged non-prefix text; the Mac suite passes
793 checks.

Deployed on the PC with **796 Windows checks** passing both before replacement
and against the installed bytes. Router SHA-256 is
`84ab5dea4b368980a0754fb64d23f2abbe0f63dcada6eafdb1f752e1a37e5690`;
policy and both topic/session bindings are unchanged. The matching two-runtime
credential/OS-boundary proof completed at `2026-10-04T02:32:51Z`. Live polling
and startup supervision are restored, and Linux daemon PID 2141 was not
restarted. Recovery binaries/probe/service configuration remain in
`C:\ProgramData\KhadangRouter\release-95d5215aa019402cb19dbe35e89aa111`.

A genuine owner update 759322603/message 13608 was accepted after activation.
Its confirmed native `turn/start` contains 14 characters without the delivery
header; sender/message provenance remains in the update ledger. The same Web
thread is actively working in new response 13609, with confirmed bounded edits
and no verbose prefix, unknown operations or pending responses. Exact `↪ Test`
formatting and legacy display compaction are fixture-verified; the latest live
tail is already long enough to roll the echoed input out of view.

### Base board and Marginal Requests routed, October 3 evening

Original-topic routing cutovers are now **3 of 14**. Khadang retains Oracova
PCBA chat `-1004395661179`, Base board topic **18** and Marginal Requests topic
**427**. No topic was created. Both retain their selected Codex model
`gpt-6-astra`; their replacement native IDs are
`01a104cc-9a63-7901-8897-abf8aff3dfb3` and
`01a104cc-d892-7c52-ba1e-e505edfb13d6`, respectively. The existing LG and Web
bindings remain unchanged.

Private project handoffs are saved in their workspaces and on the PC, with
exact persisted native checkpoint readback. The one-shot creation tasks
`9953fc55f092ce47256b668981d71d1d` and
`e389c66ee495b155dac0e992d44c2233` finished with result 0 and were disabled.
No model turn or Telegram polling was started by these creation tasks.
Base board's handoff SHA-256 is
`dde3218bb6bad93d10f1ee1c82e56230a6930eb0dc9cd6d4cee4249890ed2193`;
Marginal Requests' is
`95d990989cd907fb8c1a70354aa0634ad35b43229a7f4913a7d96604157efce7`.
The handoffs include current work rather than assuming an old conversation's
last commit is authoritative. In particular, the Base board PCB now includes
the later second-SDRAM-clock routing commit; its older "PCB untouched" status
is superseded.

Source/PC comparisons cover all **20,196 Base board entries** and **11,444
Marginal Requests entries**, including dirty and untracked render work.
Base board matches exactly. Marginal differs only in `.git/index` stat-cache
bytes; staged entries and flags independently match, and the original Mac index
is archived without overwriting the PC index. Logical stage and flag digests are
`fbf843de6066d916c8d1baa4eec20dc20c9471c624f70ce85b125878ce06d927` and
`9873bea34447523486ad7032b342347d5055908358ba210c6faa87e97e5077c2`.

The PC poller was stopped before the two Mac routes were retired. Jamshid's
explicit bindings were removed and ingress for exactly topics 18/427 disabled
to prevent default-agent fallback. Configuration validation and an exact
structural comparison passed; the gateway hot-reloaded at
`2026-10-03T19:55:20.152-07:00`. Old watchers `crw-9dab271b6c` and
`crw-1b1cf84102` were stopped and their source native pointers moved to a private
recovery directory. Eleven other original bindings and the shared Mac daemon
remain intact.

A late Base board source turn was explicitly **aborted**, not merely assumed
idle from a stale bubble. Its journal records `turn_aborted` at
`2026-10-04T02:53:34.724Z`, before any tool or assistant output; a final
comparison still matched the PC. Two owner inputs received before PCBA policy
admission remain recorded as denied updates 759322608/759322609. The latter
canceled the old turn. Neither input was replayed or counted as new PC-route
acceptance.

This was a **policy-only deployment**, not a new router architecture or binary
replacement. Policy SHA-256 is
`7e77aca790fc5786c9737c93e67855ee5967c7d36fe364d1f3a41f83c874364a`;
router SHA-256 remains
`84ab5dea4b368980a0754fb64d23f2abbe0f63dcada6eafdb1f752e1a37e5690`.
The matching production native/OS-boundary proof completed at
`2026-10-04T02:56:16.7849994Z`, covering all three Linux workspaces, UID 1000
execution, Windows native sandbox execution, and denied worker access to
protected router code and credentials. Paired Linux daemon PID 2141,
generation 229385, was not restarted. Recovery policy, consistent SQLite
snapshot, service and startup-task preimages remain in
`C:\ProgramData\KhadangRouter\release-0ca4ec73926349e6860824439a8f1a3a`.

Live exact-thread resume receipts and connection notices **4793** (Base board)
and **4794** (Marginal Requests) are confirmed in their original topics. The
02:58:52Z readback shows Running service, enabled startup supervision, four
bindings, zero uncertain operations and no held/pending responses. Both PC
legacy pointers now reference the same new native IDs, with old values retained.
Private Mac preimages and final Base board history were copied to the protected
PC archive `pcba-topic-cutover-20261003-sftp.tar.gz`: **30,395,746 bytes**,
SHA-256 `cd604c16966330f199fdb34ade587724fe0e9aae86cca42fb1374f0a13efbe3e`.
Capture, SFTP, digest/ACL verification and archive reading all passed.

Routing and connection notices are **not owner input/reply acceptance**. Both
new PCBA routes still need genuine owner round trips, tools/steering/control/
attachment checks and phone UI/restart acceptance. Fusion files and the Mac
automation are preserved, but Windows Fusion import/save/render remains
unqualified and required. Eleven other original topics, physical bench movement
and Mac-independent recovery remain pending. Full migration is not complete;
the Mac has not been erased.

### DUT Claude cutover preparation, October 3 evening

Pouya explicitly requested that DUT retain Claude in its existing Oracova PCBA
chat `-1004395661179`, topic **53**. Its source session key is
`cr-87dfb2a5b8`, not the separate ai-hil session `cr-8551d639a0`. The source
Claude pane reports idle, no writers or uncertain external actions, and a
current uncommitted `PC-MIGRATION-HANDOFF.md`. No DUT work was started.

A full source/PC content comparison completed with **131,411 entries on each
side and zero differences**. The handoff also matches on both hosts:
`e639f198591c5326702d3bd9bd568397c6bce1eac86029ddbfb513e1563bdce7`.
This is copy acceptance, not an ingress fence or working Claude route.

The earlier failed PC creation record was located and retained: attempt
`cd6a8619ea17d909cf3af61c330a1a05`, native DUT UUID
`7dc840b0-402f-451e-bc79-dadfb706d363`. It reported UID 1000, native exit 1,
`ready: false`, and `nativeStopped: true`; no route was changed. Any continuation
must reconcile that exact attempt rather than silently create another UUID.

Linux Claude needs its own renewed subscription login. The valid Windows Claude
login is unchanged. A limited interactive owner task started one native Linux
login attempt `f737e0313ae24a55bc65ae692041e318` at
`2026-10-04T03:08:25.8637098Z`; the browser authorization link was sent privately
to Pouya. At `03:13Z` it was still running without a submitted code. The task's
nine-minute deadline applies to this attempt; an expired link must not be
reported as usable. Login URLs, authorization codes and tokens are not recorded
in this document.

Authentication is not the remaining route acceptance by itself: the protected
production policy has no DUT binding, and its generic probe deliberately does
not consume a real Claude checkpoint. Candidate-bound native launch,
tool-owner and continuity checks must pass before source ingress is retired
and the original topic is admitted on Khadang. DUT therefore remains on
Jamshid at that observation; original-topic cutovers were **3 of 14**, with existing PC
LG, Web, Base board and Marginal Requests unchanged.

### DUT connected to Khadang, October 3 at 8:59 PM PDT

The next Linux subscription login completed successfully at
`2026-10-04T03:19:47.0999143Z`, under the exact limited owner, using the same Max
account as the Windows login. The prior attempt expired without a submitted
code and was stopped/disabled. Windows authentication was not copied or changed;
no authorization codes, login URLs or tokens are recorded here.

Retained DUT native UUID `7dc840b0-402f-451e-bc79-dadfb706d363` passed two
separate actual native checks, not just fixtures. Run
`1340c3563eb7f0867d3799727670d29b` read the entire handoff and ran exactly
`id -u && sha256sum -- PC-MIGRATION-HANDOFF.md`: native tool UID 1000 and the
expected handoff hash matched. Run `f0584b2695ee26a7911032a40add5d6b` resumed
that same conversation and retrieved the earlier readiness marker without
being supplied its answer. Both ended idle, without uncertain effects or
project edits, and their one-shot tasks were disabled. Five Windows evidence
fixtures also passed before each native check; those are separate evidence.

The first launcher check failed before model input because the Windows owner
was signed into a disconnected RDP session while the physical console was
empty. `WindowsOwnerProcess` and startup supervision select only the active
physical console. After independently verifying the exact owner SID/session,
`tscon 1 /dest:console` transferred that existing session to the console.
This is explicitly a **temporary workaround**, not a headless-recovery fix.
Disconnected-owner token selection and startup remain outstanding.

A repeated complete content check again matched **131,411 entries, zero
differences**. Jamshid's exact DUT binding was removed, topic 53 explicitly
disabled against default fallback, and the actual gateway hot reload was
observed at `2026-10-04T03:57:14.195Z`. Its ten other bindings and all unrelated
configuration were preserved. Only `crw-87dfb2a5b8` and `cr-87dfb2a5b8` were
stopped; no shared native daemon was restarted. Source and PC legacy pointers
were respectively retired recoverably and updated to the retained PC UUID.

The PC staged only the DUT binding plus its exact protected Linux Claude
runtime. The four prior routes and all preexisting metadata, updates and
operations were preserved. Fresh native OS/credential/code checks passed at
`2026-10-04T03:57:37.7900477Z`; their matching proof was composed with the two
actual, pinned native acceptance reports. Production started at
`2026-10-04T03:58:46.2400038Z`. Same-topic connection message **4806** was
confirmed, and genuine owner update **759322620**, message **4807**, was
accepted into DUT. The service reported its exact Claude process connected,
with idle/unheld bubbles and zero unknown or pending effects. Startup
supervision was re-enabled. Original-topic routing is now **4 of 14**.

Deployment facts:

- Policy SHA-256: `0A697FF22F479A1125C0ADEF9DA699D197F57FF71B20DAA7D202A1BCCD70FEA7`.
- Router SHA-256: `84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690`.
- Rollback/preimage directory: `C:\ProgramData\KhadangRouter\release-39d50c0e1b8b48af8cfe546426dedb4b`.
- Preserved preexisting-ledger content digest: `8DD8260F41CABA9B9ABAA4C0C4719468D6866AAA28484A67A30AF876295BC913`.
- Private source preimage archive on PC: `dut-topic-cutover-20261003-sftp.tar.gz`,
  **22,218,438 bytes**, SHA-256
  `53f9024023db38f0b792dbaf1ac16f9d812135a3d6422586fd8a70372cb41620`.
  Independent PC hash, protected Administrator/System-only file ACL and actual
  Windows archive reader passed. This is a local recovery copy, not a completed
  encrypted off-machine disaster-recovery system.

Pouya then reported DUT missing from the Claude app and requested Mac-like
Remote Control behavior, **Claude only**. At that observation the streaming adapter
reports bridge state but does not enable Remote Control. The earlier native
`remote_control` control-request acceptance already established the applicable
version-pinned mechanism. Same-process app enrollment and phone/Telegram
continuity are the next change; Telegram routing success does not establish
those. Full migration, ten remaining original routes, bench relocation and
Mac-independent recovery remain incomplete. The Mac has not been erased.

### DUT same-session Claude Remote Control, October 3 at 9:27 PM PDT

DUT's existing native stream is now enrolled in Claude app Remote Control,
named **DUT Board Design - PC**. The native `remote_control` request returned
its cloud mapping and a validated first-party HTTPS app URL at
`2026-10-04T04:26:15.3061367Z`; its operation receipt is confirmed and the
protected `claude/remote/7dc840b0-402f-451e-bc79-dadfb706d363` state is `ready`.
The link was delivered privately and in the existing Telegram bubble. The
cloud mapping is not a replacement native UUID: native conversation
`7dc840b0-402f-451e-bc79-dadfb706d363`, PCBA topic **53**, workspace and native
subscription all remain the same. No second worker or model prompt was used
to enroll it.

The mechanism is explicit same-stream SDK control, not a second CLI or a
read-only bridge-status query. The measured SDK **0.3.288** contract on pinned
Claude **2.1.288** uses `enabled`, `name` and `keep_session_on_exit`. A confirmed
cloud mapping is retained and supplied as `reattach_session_id` on subsequent
initialization; a durable attempting/unknown enrollment is held for
reconciliation rather than repeated. Identity and URL validation reject
missing mappings, non-HTTPS/non-Claude hosts, userinfo, custom ports, empty
code paths and fragments. This is a **version-bound native adapter**, not a
claim that the private SDK contract survives upgrades without qualification.
An upgrade needs a compatible same-stream enable/reattach check.

Local credential/network/model-free checks passed **806**; actual Windows
checks passed **809** during staging, before replacement and against installed
bytes. They cover Claude-only enrollment, exact conversation ownership,
no Codex remote-control calls, confirmed-mapping reattachment, uncertain-effect
holds and URL validation. Those fixtures are separate from the actual live
native enrollment receipt and do not establish a phone connection.

Web had active work when deployment was first attempted. The preflight refused
before mutation; deployment proceeded only after all five routes were idle.
A fresh stopped-history checkpoint captured **249,409 bytes**, SHA-256
`f58f48f81295a9e4bd864c92c72e726020c187bf69629644fc4d74a883be0e9e`;
checkpoint SHA-256 is
`8ea204ce823c5d3229973c2e576134a6b3ee1739d9a8c0e9191c224140d5f385`.
Only the protected Claude package/checkpoint policy changed; its seven Python
files, bindings and native IDs did not. Existing code, policy, service/task
preimages and a consistent SQLite snapshot are retained.

Fresh installed-code owner/OS/credential/sandbox proof passed at
`2026-10-04T04:25:10.9520396Z`. The previous actual Claude handoff/tool-owner/
continuity reports were **explicitly reused**, not rerun or presented as new
model evidence: the pinned native executable, Python connector files, stream
parser, owner launcher, policy, ledger and program gates were independently
unchanged. That reuse is recorded separately in the protected production
proof; the new app hook additionally required fresh Windows fixtures and
actual live native enrollment.

Current policy SHA-256 is
`507DB6D32B51692EEB304C12566977E7A29EB6AC53ED0B2927546F472916C95D`;
router DLL SHA-256 is
`94111E96E68F5D935FAA3DF94085E81F06AC3867E28A75DF290A744048D55841`.
Policy/ledger/service recovery is in
`C:\ProgramData\KhadangRouter\release-d1f538b6fe9744739d9a2fc6a6a2efba`;
previous binaries are in
`C:\ProgramData\KhadangRouter\release-8784f5d8f3f345b0baab0ef722f4f5fb\previous-bin`.
At `2026-10-04T04:27:32.014519Z`, all five routes were healthy with zero unknown,
held or pending effects, DUT process **28446** connected, and the shared Linux
Codex daemon still **2141**. The idle shared-service restart recreated the
Windows native transport (**26764**); Codex behavior, daemon enrollment and
session IDs were unchanged. Startup supervision was restored at **04:27:47Z**.

`ready` means native cloud enrollment, **not** an observed phone connection.
Actual phone-to-DUT/Telegram continuity and native cloud reattachment across a
later restart remain to be accepted. Console-only owner selection and automatic
checkpoint refresh on recovery remain separate outstanding mechanisms.
Original-topic routing stays **4 of 14**; this app fix does not complete the
remaining migration or authorize erasing the Mac.

### Schematic Pipeline and Mimic Fast PCB connected October 3 at 10 17 PM PDT

All five original Oracova PCBA topics are now routed on PC. Schematic Pipeline
retains topic **2697**, with fresh native Claude conversation
`6159472a-7878-42e4-b497-ffbb64a7e2d6`; Mimic Fast PCB retains topic **3315**,
with `10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2`. Chat remains
`-1004395661179`. Their private project handoffs and original CAD/lab worktrees
are preserved. Recursive checksum comparisons found no differing project
content; Git indexes differed after status refresh and were not overwritten.
Dirty `tools/schcentre.py`, untracked schematic media and Mimic `.history/`
remain intact. The source schematic notes' `/tmp` experiment file is absent;
its committed findings are preserved, not falsely labeled a copied experiment.

Four actual native checks succeeded as the verified non-elevated Windows owner
and Linux UID 1000: each fresh conversation read its entire checked handoff,
ran the exact UID/checksum command, then a separate exact-ID resume recalled
the previous marker without being supplied its answer. Hooks and MCP were
disabled only for these bootstrap checks; production uses the unchanged
accepted native connector and ordinary project profile. All checks ended idle
and stopped, with no uncertain input or project writes. Nine focused synthetic
evidence/source-fencing tests passed; those are separate from the native checks
and do not represent a rerun of the earlier 809 router fixtures.

The policy-only cutover preserved the five prior routes and unrelated ledger
content. It required an idle router, retained config/probe/task/database
preimages, and freshly captured all three stopped Claude histories. Exact
Windows owner/credential/code/sandbox and Linux native checks passed at
`2026-10-04T05:14:29.256403+00:00`. The probe service retained its running SCM
state after writing success; its actual process was inspected, then the
completed diagnostic was stopped normally, not relaunched after timeout.

Only the two source bindings were removed and their fallback ingress disabled;
source pointers were moved to recoverable private preimages. The Mac gateway's
hot reload was observed at `2026-10-04T05:16:30.308Z`. Eight source bindings
and unrelated configuration remain. No shared Mac or Linux Codex daemon was
restarted. Production launched at `2026-10-04T05:16:52.9198743Z`; the new
bubbles **4815** (Schematic) and **4814** (Mimic) have confirmed message IDs in
their original topics. All seven routes were unheld, idle and without unknown
or pending effects at `2026-10-04T05:17:00.478675Z`. Startup supervision was
restored Ready with its exact original quoted service path.

Both new native Claude streams enrolled in Remote Control, with confirmed
cloud mappings. DUT's existing mapping also reported ready after this idle
restart; exact same-cloud identity and phone interaction still need comparison,
so readiness alone is not declared full phone/recovery acceptance.

Current policy SHA-256 is
`FD0C4A5D7C44F9F7BC8FC542F083A533062C7153C9C9E043AC8021C1F7C4C76F`.
Router code remains
`94111E96E68F5D935FAA3DF94085E81F06AC3867E28A75DF290A744048D55841`.
Protected policy/database/probe preimages are in
`C:\ProgramData\KhadangRouter\release-fe1651ed3a1c4e9bbde0509dcf819a9b`;
the unchanged connector files and three new reviewed checkpoints are in
`C:\ProgramData\OracovaNativeRemote\claude-connector-fe1651ed3a1c4e9bbde0509dcf819a9b`.
Those checkpoints are consumed; another restart needs fresh reviewed captures.

The source preimage archive was independently checksum/read/ACL verified on PC:
`C:\ProgramData\OracovaMigration\fe1651ed3a1c4e9bbde0509dcf819a9b\lab-topic-cutover-20261003-sftp.tar.gz`,
**5,909 bytes**, SHA-256
`efc63f2a6026ae747f6e9c5f45f771e4baa4f8fdcad919795f9dced4d3859f16`.
The first copy failed before reservation because its protected run directory
was missing. The same retained archive was transferred after creating that
exact protected directory; no native/model action was repeated. This remains a
local migration recovery copy, not the daily off-machine disaster backup.

Original routing is **6 of 14**, with eight remaining. The Mac is not erased;
bench relocation, independent remote recovery and full-system restore remain.

### Hardware Lite and MPU6000 i9 connected October 3 at 10 37 PM PDT

Khadang now has nine PC routes, including **eight of fourteen original routes**.
Hardware Lite keeps Ai Dispatch topic **6333**, native Claude conversation
`5fc53034-e240-43b5-a2c4-75ee1947aefa`; MPU6000-i9 keeps topic **8653**,
conversation `a32bd2ef-172a-4a51-95ba-1b9bce4f44eb`. Both keep chat
`-1003550185469` and their selected Claude backend. No new topic was created.

Recursive source/PC checksums matched both complete projects apart from refreshed
Git indexes, which were not overwritten. MPU6000 is a separate nested repository;
its dirty RTL, generators, tests and golden data remain intact. Private handoffs
were created and read back. Four actual native checks verified full handoff reads,
Linux tool UID 1000, exact file hashes and separate exact-ID continuity as the
non-elevated Windows owner. Hooks/MCP were disabled only for bootstrap; production
uses the unchanged accepted connector. Thirteen focused synthetic evidence and
source-fencing tests passed; the previous 809 router fixtures were not rerun.

Hardware Lite's historical turn receipt names `9e452652-73b0-4a6e-a81a-47f7b02365e9`,
but no exact native source history or current pointer was found. This gap is
recorded, not replaced by a guessed transcript. MPU6000's old history is retained
in the private native seed: **570,956 bytes**, matching source and PC SHA-256
`2393e5488a3c3f775c2c9e144b72fbd2dfac753ac1a0cdffc4bfcb4e6b75fdc1`.
No old relay-repair or hardware action was replayed.

The cutover retained seven existing bindings and unrelated ledger content,
digest `DEA37AD4302FC514277C48D39BE7F04A16C294419A817B84CDECD817A6F93241`.
All five Claude histories were freshly captured after the idle service stopped.
New policy SHA-256 is
`B61DC1C276815DCF964094721337DAA794CC3C6FDA0E19C01A68E27AF2DBD663`;
router code remains `94111E96E68F5D935FAA3DF94085E81F06AC3867E28A75DF290A744048D55841`.
Fresh no-model, no-polling owner/credential/code/sandbox/Linux proof passed at
`2026-10-04T05:33:07.1097007Z`. The diagnostic intentionally stays Running after
success until stopped; it was stopped normally, not retried after an observation
timeout. The normal quoted SCM service path was restored.

Only source topics 6333 and 8653 were disabled and unbound, with recoverable
configuration/state preimages. Gateway hot reload was observed at
`2026-10-04T05:33:40.195Z`; six original bindings remain on Mac. Production
started at `2026-10-04T05:33:56.2166859Z`. Confirmed Telegram responses preserve
the original chat/topic addresses: messages **13627** and **13626** respectively
contain native Claude app links. MPU6000 later has rolling message **13628**;
this is not, by itself, proof of a genuine owner phone round trip.

All nine bindings were idle, unheld and without uncertain/pending effects at
`2026-10-04T05:37:56.9291576Z`; all five Claude streams were connected. Startup
supervision is Ready. The saved task XML omits the default Enabled setting;
Windows Task Scheduler's own parser confirmed it was enabled before restoring
that setting. The shared Linux Codex daemon stayed PID 2141, without re-pairing.
For DUT and both PCBA lab sessions, comparison with the retained pre-restart
database confirmed the same cloud mappings and fresh ready receipts after restart.
This proves those native mappings reattached, not phone UI, reboot or crash recovery.

Protected preimages are in
`C:\ProgramData\KhadangRouter\release-65fc17bfcb9d47a190ab128b096bba5d`;
the unchanged connector and five consumed checkpoints are in
`C:\ProgramData\OracovaNativeRemote\claude-connector-65fc17bfcb9d47a190ab128b096bba5d`.
Another restart still needs fresh reviewed checkpoints. Source recovery archive
`additional-topic-cutover-20261003-sftp.tar.gz` is retained in protected migration
run `65fc17bfcb9d47a190ab128b096bba5d`, **6,834 bytes**, SHA-256
`3a68d93668d8322a90258d4471bb5e104a396bce0a158fdd504e57893866c2cb`.
After a pre-reservation copy failure, the same archive was transferred without
recapturing or rerunning models. Windows reader, checksum and Admin/System-only
ACL checks passed at `2026-10-04T05:36:51.7084348Z`. This is not a daily off-machine backup.

Remaining originals: Startup Ideas, ai-hil, supervisor-fw, controller 816,
KiCad research and Qwen lab. KiCad retains OpenCode state but lacks a current
backend marker; Qwen has a retained `qwen` model override and custom provider
settings. Reconcile those settings rather than silently replacing their tools.
Bench relocation and independent remote/disaster recovery remain incomplete.

### Jamshid style bubbles restored October 3 at 10 57 PM PDT

Pouya explicitly approved restoring code-block formatting without dropping
tools, goals, the timer or the rolling size cap. Source commit `eaa39ce`
formats only bubble sends/edits with Telegram `pre` entities. Raw text remains
unchanged; native Claude app URL lines sit outside the code blocks and stay
tappable. Ordinary control/question messages remain plain. Entity positions use
the [Bot API's UTF-16 offsets](https://core.telegram.org/bots/api#messageentity).
Response-owned IDs and uncertain-delivery handling are unchanged.

821 Mac fixture checks and 824 actual Windows candidate checks passed without
credentials/network/models. Every one of the 187 installed artifact files
checksum-matched the tested self-contained candidate. Router DLL SHA-256:
`2A624143E1BFA56D40DC20287153197A9314B9E688C08580C0F39B75F6BF0747`.
Fresh installed OS/owner/credential proof passed at
`2026-10-04T05:55:30.3675633Z`; no model prompts were used for this deployment.
Earlier actual Claude tool-owner/continuity checks were explicitly reused for
unchanged native launch/control code, not represented as freshly rerun models.

All nine bindings remained byte-identical to the stopped database snapshot.
At `2026-10-04T05:56:40.8095638Z`, confirmed Telegram edit receipts showed
code-block entities, the existing message IDs, tappable app links and text
within 3,900 UTF-16 units for all nine bubbles. DUT message **4813** was edited
in place. Production resumed at `05:56:06.2686696Z`; five Claude streams connected
and all five prior native cloud mappings reattached unchanged with fresh ready
receipts. Startup supervision returned to Ready at `05:57:15.6504050Z`, with
zero unknown effects. Shared Linux Codex stayed PID 2141; Windows native
transport now reports PID 28048. Phone/reboot/crash/headless acceptance is separate.

Recovery preimages and the previous binary are in protected release
`C:\ProgramData\KhadangRouter\release-dd803e5f1b154406b816a0d72b444866`.
The five newly reviewed checkpoints in connector package
`claude-connector-dd803e5f1b154406b816a0d72b444866` are now consumed; another
restart still requires fresh reviewed histories. Their hashes are recorded
under `pc_service.jamshid_code_block_hotfix` in deployment status.

During staging, a stop request returned a failure although a fresh SCM read
confirmed the service had stopped. No forced termination was used. The registry
guard then caught four Unicode Name values decoded incorrectly as OEM437 in
the derived snapshot; the original was retained and only that snapshot repaired.
The database was untouched. Explicit UTF-8 fixed the helper; partial inert
checkpoints were compared with unchanged quiesced histories, not replaced or
replayed. Protected receipts retain this recovery evidence. Migration remains
8/14 originals, nine PC routes including LG; Mac retirement is not accepted.

### Jamshid progress and separate finals restored October 3 at 11 45 PM PDT

Pouya clarified that Jamshid's code block was only the live bubble: its final
answer was a separate normally formatted message. He explicitly deferred
command restoration. Source commit `e9427de` now implements that separation for
Claude and Codex, without changing command menus, aliases or control semantics.
Progress stays silent and bounded to 3,900 UTF-16 units, with descriptive tool
rows amended on completion, a readable timer/goal footer and pending questions
kept visible. Raw tool stdout and private reasoning are excluded. The final
preserves its full text, normal emphasis and links, and fences only actual code
or tables. Long answers split into parts; each part has a durable send intent
and confirmed message ID. Unknown delivery is held, not automatically resent.

The self-contained Windows candidate passed **845 checks** with no credentials,
network or models. All **187 installed files** matched that candidate. The Mac
full-suite rerun and duplicate probe packaging encountered disk exhaustion;
neither is reported as passing. Packaging completed on the PC without deleting
Mac files. Fresh installed owner/ACL/native Windows/Linux proof passed at
`2026-10-04T06:43:32.3242787Z`. Prior actual Claude launch/tool-owner/continuity
evidence was explicitly reused for unchanged native launch/control sources,
not presented as new inference. Five fresh quiesced history checkpoints were
captured for the idle restart.

At `2026-10-04T06:46:09.1727530Z`, the normal service was Running, the enabled
startup supervisor Ready, all nine bindings unchanged, all five Claude streams
connected, and unknown operations zero. Linux Codex remained PID **2141**;
Windows native transport was PID **25388**. Policy changed only the fresh
Claude package/checkpoints, not authorization, menus, credentials or routes.
Installed router DLL SHA-256 is
`E2356B7A0D2821B7588B2E2D5FF920D072C61E30AA856C6FAA14C8640C07767E`;
policy SHA-256 is
`390CEF2715C77E8C4CFE81D3A822F7FA3AF486C85EA73DA284A7EDC4F5CDF869`.

A deterministic two-message UI check in existing DUT topic **53**, without a
model task, returned confirmed Bot API receipts at `06:45:31.1588213Z`:
progress **4816** has a code-block entity and was edited to Done; separate final
**4817** has bold/link entities and no whole-answer code block. This is actual
Telegram formatting acceptance, not a phone screenshot or a new model round
trip. Existing historical bubbles do not retroactively create final messages.

Protected rollback/preimages and `ui-acceptance.json` are in release
`2594950b4dd146a4a6a0ddb25ba91784`. Its matching `claude-connector-` package's
five checkpoints are now consumed; another restart requires fresh reviewed
histories. A stop request initially reported failure, but fresh SCM inspection
confirmed normal shutdown, with no forced termination. The probe was stopped
normally and the exact normal service path restored. Previously prepared
migration helpers must be rebaselined to the current code/policy before use.
The larger migration remains paused: **8/13 required** originals are connected;
Qwen is excluded, and no remaining source topic/process was retired by this UI
change.

### CC relay attached to its existing PC controller October 4 at 12 15 AM PDT

Topic **816** in Ai Dispatch now routes through Khadang to the exact existing
PC Linux Codex conversation `01a0facd-1bc0-7d23-95d6-c32fde0c62db`, not a new
thread or topic. Native readback verified its current working turn and active
migration goal on ordinary UID 1000, shared daemon PID **2141**. The old Mac
copy was idle with a paused goal; only its exact OpenClaw binding and topic
fallback were fenced. Unrelated source configuration and the shared daemon
were preserved. Private config/pointer preimages were checksum-verified and
sealed on the PC; transcripts were not deleted.

Source `21c1ccf` fixes mid-turn attachment: subscribe before resume, adopt the
bounded latest in-progress turn, and ignore a stale snapshot after a newer
start/completion event. Existing holds, uncertain receipts and pending native
requests cannot be cleared by attachment. No new turn, model prompt, fork or
daemon restart is used. **861 actual Windows candidate checks** passed,
including attachment/completion-race fixtures. The candidate was built on the
PC with official, checksum-verified .NET SDK **8.0.425**; this build no longer
needs the Mac. Commands and the previously deployed Jamshid UI are unchanged.

Fresh installed OS/native/credential proof passed at
`2026-10-04T07:07:58.7819568Z`. Prior actual Claude launcher/tool/continuity
evidence was explicitly reused for unchanged native connector sources; five
fresh quiesced checkpoints were approved for this restart. Production started
at `07:13:55.7455995Z`; at `07:15:30.7079288Z`, all **ten** routes were live,
all five Claude streams connected, startup supervision Ready, and unknown
operations zero. Windows native PID was **21080**, Linux PID **2141** unchanged.
Installed DLL SHA-256:
`3FD09C88CA54F0716310C3649FBC7A48907362B0487AF80DE1E4599B3AE755C1`;
policy SHA-256:
`1204A440086705CC0B94988371CEBEFDAF392E18354A12C407458358B9E0D8DA`.

Real owner messages **13632** (`.`) and **13635** (`Hi`), updates **759322642**
and **759322643**, were accepted from this topic. Both have confirmed native
`turn/steer` receipts targeting the already-running turn
`01a105b1-77be-7881-85d0-6421d6ebde27`. Confirmed Telegram send/edit receipts
update the same rolling code-block message **13633**, with Working timer and
active goal; a sampled edit was 1,691 UTF-16 units. This proves genuine
Telegram-to-current-turn steering and outbound live updates, not just a saved
mapping. Earlier messages ignored before cutover were not automatically replayed.

Protected rollback, source backup and `controller-acceptance.json` are in
release `3fffc60319f748849fb3bf7da7d3b94d`; its matching Claude connector
package has five consumed checkpoints. Normal stop is required before replacing
the router. SCM paths must be changed/read back using `Invoke-CimMethod`:
PowerShell's `sc.exe` argument conversion had stripped embedded quotes.
A stale administrator SSH master stalled the first acceptance read; a fresh
pinned-host connection completed it without restarting the native daemon.

Migration is now **9/13 required originals** plus LG. Remaining required
originals are Startup Ideas, ai-hil 1876, supervisor-fw 5786 and KiCad 6004;
Qwen remains excluded. The current migration goal is active. Independent
remote/boot/disaster recovery, bench relocation and final source retirement
remain pending; this fix does not authorize erasing the Mac.

### Native model handoffs and clean goal replies October 4 at 1 AM PDT

Generation `0bc81f90bf4e4494a07d2d36b979271e` restores the requested `cc model`
syntax on paired Linux topics, with one retained native ID per provider, same
workspace, an actual destination handoff and atomic topic/receipt commit.
Unknown switches do not replay or create replacements. Claude model aliases
relaunch the exact saved ID with the requested model. Windows LG cross-tool
switches remain unsupported; no other legacy commands were restored.
Authoritative goal finals now use a durable separate normal-message outbox
while the single code-block live bubble continues. See the
[current command behavior](native-telegram-commands.md#current-pc-khadang-model-switching--2026-10-04).

924 PC Linux checks, 927 actual sealed Windows checks and 25 bridge tests passed.
A real, private candidate-bound Claude canary at `07:55:48.1231051Z` proved
native handoff delivery, tool UID 1000, idle completion and independent same-ID
resume/context continuity (`d7b87381-1e8b-499f-980a-2ae089692997`). Its isolated
journal did not change live bindings or fabricate Telegram owner updates.
The connector changed, so native continuity was tested again, not merely
carried forward from an older UI release.

Fresh installed no-model/no-polling OS proof completed at
`07:57:42.0933995Z`. Production restarted at `07:59:02.1388940Z`; fresh live
status at `08:01:19.0036219Z` confirmed all ten unchanged routes, five Claude
streams connected, zero holds/unknowns and the same Linux daemon PID 2141.
Windows native PID is 20320 and router PID 26248. Controller 816 remains on
the exact current native turn `01a105ca-712a-78a3-a009-9b5eb9090d75`, with active
goal and rolling bubble 13651 preserved. Startup supervision is restored Ready.
No goal, shared daemon, native task or Hamal wiring was reset.

Installed DLL SHA-256:
`C22B67C902C7303DFFFB28684CC5CD9183410065FEF909D4C965BE13C3DA31CF`;
policy SHA-256:
`E99D0BE6F9EDFA8B31D25AC2A672AA29BA3140CFAEF2D6A6B19C660D0FF2BA63`.
Protected preimages include the previous binary, policy, SQLite backup, five
quiesced native checkpoints, exact before/after active-turn observations,
fresh OS/native test reports and `live-acceptance.json`. The first status read
was older than startup and is explicitly retained as **not acceptance**;
only the post-start fresh observation is used above. Human model-switch/next
live goal-final receipts remain pending, not inferred from fixtures. Migration
is still 9/13; the main goal remains active with the owner's 5%-remaining pause
condition. This feature update does not complete or broaden retirement scope.

### ai-hil and supervisor firmware cutover October 4 at 1:27 AM PDT

Generation `e85f1d1280a04116b0988985527a6570` moves original Ai Dispatch
topics **1876** (ai-hil outreach) and **5786** (supervisor firmware review)
to prepared native Claude sessions `2c0bce31-f586-4d5e-9422-4be550763ed8`
and `dcf9169b-c044-4c39-9ba5-e27d2978722c`. Their actual handoff reads,
UID-1000 tool checks and independent same-ID context resumes had already
passed; the four retained results were reviewed, not rerun. No new model
prompts, replacement threads, binary update or project work were performed.

Actual source panes and completed native histories proved idle before fencing.
After ingress removal, graceful terminal shutdown changed one captured process
identity, so the helper refused further signals. Explicit reconciliation found
all four panes/watchers absent, no selected history or workspace producers,
and exactly unchanged user/assistant conversation rows; only shutdown metadata
was appended. Native pins were then retired recoverably. Final histories and
private config/UI preimages are retained on the PC in
`C:\ProgramData\OracovaMigration\e85f1d1280a04116b0988985527a6570\core-topics-final-sftp.tar.gz`
(16,962,982 bytes; SHA-256
`49546b5ebd8419f3f4f055ab417f67d8c79d186d354f1b42a23724f534d89b27`).
The digest, archive readability and administrator/SYSTEM-only access matched.
This scoped source fence is not a full-system consistent backup or restore test.

The scoped outreach files matched by checksum. Supervisor source and PC HEAD
both remain `816432b231da4f39ad636bd00b5bbea3c9aeee37`; the only worktree
content difference found was the existing PC portability change to
`firmware/supervisor-c/CMakeLists.txt`, which was preserved. No uncommitted
owner work was overwritten or pushed from that project.

A fresh no-model/no-polling installed OS/credential-denial proof finished at
`08:25:06.0694189Z`. Production started at `08:25:51.1482759Z`; fresh status
at `08:27:50.0147076Z` confirmed **12 routes, all seven Claude streams**, zero
held/unknown states and unchanged Linux daemon PID **2141**. Windows native
PID is **11252**. Exact controller turn `01a105f4-84f2-7551-9264-be181a4c82c3`,
active goal and rolling bubble **13659** survived. Startup supervision is Ready.
The first pre-start status read was rejected, not accepted as live evidence.
The service-stop error was reconciled through actual SCM Stopped state and
the same native turn; no force-kill or repeated native input was used.

Router DLL remains `C22B67C902C7303DFFFB28684CC5CD9183410065FEF909D4C965BE13C3DA31CF`;
current policy is `4DD5478914BB7B017D7E9AFF12BBCAEF486AF1DED9B2A13A588B2D0D02C1E923`.
Seven fresh quiesced checkpoints and all previous policy/database/probe/task
preimages are retained in the matching protected release/connector package.
The executed v2 helper hash is
`c76c03aa7df7f98adf1982e5f2d9e0f70e4a3af40c0a99ac1d09f8757a4cd5f2`;
the committed helper additionally waits for observed shutdown after an SCM
stop error. Twenty focused evidence/source-fence checks passed. The initial
mistyped observer hash failed before touching production; a regression now
checks the exact reviewed observer digest.

The previous genuine goal final was also confirmed in Telegram: message
**13658**, `08:07:55Z`, 329 UTF-16 units, no code-block entity and notifications
enabled. The continuing live goal bubble remained separate. Human-issued
cross-provider model-switch acceptance and new-topic owner input remain pending.

Migration is **11/13 required originals plus LG**. Fresh Startup Ideas access
still returns HTTP 400; KiCad retains OpenCode session
`ses_fda86bd86ffeX9tdQh70Q6uZoX` without a selected backend marker, so the owner
was asked which supported destination to use. Khadang still lacks Ai Dispatch
Manage Topics permission for the separate requested Oracova product topic.
Qwen remains excluded. Weekly quota is still 85% used / 15% remaining; the
5%-remaining pause condition has not fired. Remote/boot/disaster recovery,
bench restoration/relocation and final source retirement remain incomplete.

### Mac-independent Git and original bench identities October 4 at 1:48 AM PDT

Fresh ordinary-owner Windows `gh` 2.102.0 inspection found the existing
`pooyamn` GitHub login already valid, using the native **keyring**, with no
inline OAuth token in `hosts.yml`. No token was exported, copied, regenerated
or printed. The earlier HTTP-401 clone record is historical, not current auth
state. User Git configurations were absent in both Windows and WSL; native
`gh auth setup-git --hostname github.com` configured Windows Git, and WSL Git
now delegates to that same installed Windows CLI. The first WSL helper string
lost its path quotes in INI parsing; a private credential-fill check caught
the failure before acceptance, and the quoted value was corrected. See the
[GitHub CLI setup command](https://cli.github.com/manual/gh_auth_setup-git).

Both credential-fill checks now return `pooyamn` and a nonempty credential
without displaying the secret. Both Windows and WSL Git read private
`pooyamn/oracova` HEAD `c60533d220365424fff2a13ca1ca88d39cbc9c38` successfully.
Normal personal Git push authentication also succeeds without temporary
credential overrides, Mac SSH, helper delegation or a stored token file.
This is personal account access, not reviewer/CTO/company publication authority.
Current nonsecret user config hashes: WSL
`392f427dd9add385ea9f1a6d01a95b0067dc9fd3abfe70c702107c359c68eeea`;
Windows `df28c92fb34320ef6921c42ed978afdf6e9395384c90ea2342f16842093de882`.

Bench identity restore generation `722ba84a20f34aa3975d556a91d7ce94` completed
at `08:43:31Z`. The existing protected physical-bench archive again matched
SHA-256 `48542d3b8f5ecbd74537ea3be82234667f1d6a42366473172ccab8398f44da2a`
and 2,629,314,560 bytes. All **21 files / 12,899 bytes** under
`oracova-bench/keys` and `pki/nucleo1` matched a fresh physical-bench inventory,
including the original image/operator/policy keys, operator-key bundles,
device CA private key, device key and operator PEM/PKCS12 identity.
Only fixed individually hashed regular members were read; no arbitrary tar
paths, links, hooks or services were extracted/executed. Duplicate, wrong
content/size, missing and non-regular selected members are covered by four
passing fixture checks. The reviewed administrator-sealed restore script hash
is `569d926f53f6577639c3f8d31dc85490c1cd682536f13cf85008d8b27536311d`.

The active PC destination is **`/Users/pouya/oracova-bench`**, owned by ordinary
Linux UID1000. Directories are 0700, identity files 0600 and the preserved
`oimgkey.py` helper 0700. Existing destinations were not overwritten; private
key material was never displayed or committed. Eight private keys parse, six
certificate files parse, and the device issuer CA public key matches its
private key. The original `pouya.p12` does not accept an empty password; its
password is not recovered. The matching preserved operator PEM private key
is usable, but this is not a claim that the encrypted PKCS12 is unlocked.
No keys were generated, enrollment changed, signatures produced or hardware
commands executed. Private result:
`/Users/pouya/.migration/bench-identity-722ba84a20f34aa3975d556a91d7ce94/result.json`.

Legacy tools' `/tmp/oimgkeys` path now links to the private persistent key
directory. Root-owned `/etc/tmpfiles.d/oracova-bench-identity.conf` adds only
a non-replacing `L` rule; no existing configuration was overwritten and no
cleanup/replacement rule was added. The installed config matches
`69148fddc8c1fa3cae4a5d06672499da26a7d59fc7d31c8c3b80f6f33b85b42e`.
Creation passed on the live WSL installation and in an empty alternate-root
fixture; link-target hashes match the originals. Standard systemd tmpfiles
setup is already active/successful. This config is eligible for boot-time
recreation, but a real Windows/WSL reboot has **not** been performed or accepted.
The pinned [systemd 255 specification](https://github.com/systemd/systemd/blob/v255/man/tmpfiles.d.xml)
describes this non-replacing symlink behavior.

At `08:47:58.2243245Z`, the router still had twelve routes, seven connected
Claude streams, zero holds/unknowns, Linux PID2141 and Windows PID11252; no
router, daemon, subscription or VPN/LG service was restarted for this work.
The restore used the reviewed administrator bootstrap to read the protected
archive, then private ordinary-owner storage; it is not company-role isolation.
Full bench helpers/toolchains/network/hardware relocation, PKCS12 password
recovery, native headless/boot/remote acceptance and clean-machine disaster
restore remain required. Startup Ideas/KiCad/product-topic human choices and
access gaps also remain. This progress does not authorize erasing the Mac.

### Active bench payload and native startup checks October 4 at 2:19 AM PDT

The physical bench working payload is no longer archive-only. A fresh pinned
SSH inventory selected **1,451 regular files / 46,408,302 bytes / 74 directories**
under `/Users/oracova/oracova-bench`, excluding the Darwin-only
`xpack-openocd-0.12.0-7` installation retained in the protected original archive.
Non-regular selected members, unsafe paths and incomplete directory ancestry
are rejected. The inventory hash before and after transfer is identical:
`5ed4e3eca8e7d159b83623d5d2412106e4ee2de8e788b32db71d3758d4b529b0`.

An ordinary-owner, non-deleting `rsync --ignore-existing` copied **1,430 new
files / 46,395,403 bytes** into `/Users/pouya/oracova-bench`; existing keys/PKI
were excluded from copying. Every selected original file, including the 21
previously restored identities, then matched the fresh source hash and size.
Directories are 0700, imported files 0600; the existing key helper remains
0700. The copy did not replace existing PC files or execute imported code.
Generated inventories/receipts are private under
`/Users/pouya/.migration/bench-payload-KLsM5kkS`, not Git. The reusable checker
is `scripts/check_pc_bench_payload.py`, SHA
`465d0d903d9f02826333017f4e9f4499450ff45b56950e1072ec2697ba12abf0`.

Six narrowly scoped PC helper ports followed, with original matching versions
retained in the private `pre-port` directory:

- `daptls.py`, `tlsconsole.py`, `tlscmd.py`: Linux `/usr/bin/openssl`, with an
  explicit `BENCH_OPENSSL` override. TLS 1.3 and CA/error verification remain.
- `stamp.py`: the original local `~/oracova-bench/keys/dev.pem` identity, with
  optional `BENCH_KEYS_DIR`; no signing operation was run.
- `pl_lib.py`: native Linux hub-tool path/override and configurable board IP.
  On Linux, power actions refuse to run until both `BENCH_USB_HUB` and
  `BENCH_USB_PORTS` are explicitly supplied. Mac hub numbers are not reused.
- `bin/openocd`: quote the exact tool/override path; no silent substitution of
  generic distro OpenOCD for the required reviewed TCP-DAP build.

The reproducible `pc-router/bench-linux-paths.patch` matches SHA
`1a01fb3329c78a24914f445d71cef62deb7fc219cabbf7a6474b6f825ec93693`.
Its dry run succeeds against all six original preimages. After these deliberate
ports, 1,445 unchanged active files and all six retained original preimages
were reverified; the active six modified helpers are **not** claimed source-
identical. The original Darwin `dapbench` is also retained. Its original C
source builds with GCC13.3, `-O2 -Wall -Wextra -Werror`, into the new private
Linux ELF64 executable `bin/dapbench` (0700), SHA
`79248e4086fe90f4b1796be87a86b0be5bc768842466e37d3a4fdeec3914437d`.
The binary was not run: its default invocation contacts bench hardware.
Sixteen focused checks passed, including all top-level Python syntax, TLS path
declarations, preserved CA checks, mocked USB-power refusal/explicit mapping,
the quoted wrapper with harmless printf, and ELF/original-binary preservation.
No hardware, signing, enrollment, flashing or power operations were performed.

Fresh exact-peer native RPC reports PC Linux Codex PID2141 **connected**.
At `09:17:09Z`, the existing `Oracova-CodexWslRemote` supervisor again wrote
`managed-daemon-connected` for that PID; Windows host PID19992 is actually alive,
session1, non-elevated. Its installed runner matches source SHA
`61ec885dd8ff716efc715e8e5f4e6107d26813ad500a09a64fe999bf7342f3ed`.
The task is Interactive/Limited, enabled for owner sign-in and five-minute
checks. The installed Windows Codex/Claude supervisors and their native
processes also exist/alive, but their saved connection timestamps are not a new
phone round trip. Router startup and availability guards are installed; no
task, native daemon, live turn, pairing or service was restarted here. The
router's Linux Remote snapshot was never refreshed; its initial unavailable
value does not contradict the direct native connected observation. The
[official Codex lifecycle commands](https://learn.chatgpt.com/docs/developer-commands)
were checked before deciding not to create another managed daemon.

This is working-payload preservation and limited Linux portability, **not**
full bench acceptance. The TCP-DAP OpenOCD build, Linux hub tooling and actual
USB mapping/relocation, board network/TLS/serial/flash/debug checks, standalone
Claude phone/topic joining, real reboot and valid saved auto-login credential,
independent outside-LAN recovery and daily encrypted clean-machine restore
remain unverified. Original topic choices/access and final Mac writer/capture
closure remain required. Weekly quota is still 15% available; migration stays
active under the owner's 5%-remaining pause condition. The Mac is not erased.

### DUT global display hold cleared October 4 at 3 AM PDT

DUT's exact native session `7dc840b0-402f-451e-bc79-dadfb706d363`
was connected and had answered owner input 4820. Telegram confirmed its live
bubble 4821 and separate final 4822. However, a subsequent CC relay bubble
edit of message 13670 timed out. Its intent
`c52d56f5a9f247da87c3c2aaf9a1553b` entered the global unknown-effect fence,
blocking unrelated native admission, including DUT.

At `2026-10-04T10:00:58.9702471Z`, the administrator maintenance lane ran the
reviewed `pc-router/classify-display-timeout.ps1` helper, SHA
`de540eb6554fb9b8d635d8c3c78f3ea9ea51d5948398ca5c2207918d1ce88512`.
It pinned the installed policy/router, exact operation/payload digest and
uniquely confirmed original message. One SQLite transaction changed only that
operation's status to `unknown-presentation` and added a protected preimage
audit under `presentation-timeout/<intent>`. It did **not** confirm delivery,
retry Telegram/model input, change bindings/auth, or restart processes. No bot
credential was read. The ended Mac administrator SSH master was renewed using
the existing pinned PC host key; host verification was not bypassed.

Fresh router status at `10:01:33.8965733Z`: Running, global unknown 0, Windows
native PID11252 and shared Linux PID2141 unchanged; DUT PID79418 connected,
not held, not send-unknown, idle/Done. There is still one explicitly uncertain
presentation intent, and the existing CC relay process's display remains held.
A new genuine owner DUT round trip after this repair has not yet been observed.
Earlier messages 4818/4819 were independently rejected because their sender
was not the configured owner; employee authorization is not silently expanded.

Source now separates display uncertainty from admission holds and reports a
separate presentation count. All **929** PC Linux router checks passed,
including regression guards for unknown message sends, native input and
interrupted dispatches remaining fenced across restart. This source change is
**not yet installed**; a future deployment requires fresh exact checkpoints and
safe display reconciliation. The live intervention is the one-intent repair,
not a claimed permanent redeployment or final migration acceptance.

### Native CAD TCP bench tools and PC local maintenance October 4 at 3:21 AM PDT

The exact Linux OSS CAD Suite counterpart of the Mac's **20260621** release
is installed at `/Users/pouya/oss-cad-suite`. The official
`oss-cad-suite-linux-x64-20260621.tgz` archive has 717,428,552 bytes and SHA256
`2bc1823e76b4bcae8750c5063cde4a8ae0d9143bf255f5a1b956e372be60f732`.
The one-shot installer verifies that digest, bounds and validates all 29,836
members/contained links before extraction, and refuses an existing install.
No global PATH or shell configuration changed. Actual MPU6000 RTL simulation
passed all eight assertions, with both source inputs unchanged. Yosys,
nextpnr-ecp5 and ecppack version checks also succeeded; no FPGA was flashed.

The suite's bundled OpenOCD explicitly **rejects** TCP-DAP, despite matching
the Mac suite's build revision. That failure is retained, not called acceptance.
The bench now uses a separate ordinary-owner OpenOCD built from official source
commit `d3ebb8d2b9adbfd9a13072e8e446f424b5ff3c0e`, committed October 2.
The [official adapter documentation](https://openocd.org/doc/html/Debug-Adapter-Configuration.html)
describes the required CMSIS-DAP TCP backend. The source was unchanged through
the GCC13.3 warning-as-error build; no privileged OpenOCD process was started.
Build recipe, from that pinned checkout:

```sh
./bootstrap
./configure --prefix=/Users/pouya/.local/share/oracova-openocd-tcp-d3ebb8d2 \
  --enable-cmsis-dap-tcp --enable-cmsis-dap --enable-cmsis-dap-v2 \
  --enable-stlink --disable-doxygen-html --disable-doxygen-pdf
make -j2
make install
```

Native binary SHA256:
`cb908ffef98f3da2a064dfbcd76c6c4d353f39b8b277132a9114c65f0c822587`.
The bench wrapper and both probe gates now select this exact Linux build,
preserving explicit overrides and Darwin defaults. Actual config-only execution
accepts TCP host/port commands and reaches the success marker, **without `init`**
or any hardware connection. Ubuntu build prerequisites and zsh were installed
without upgrading or removing packages. Existing standard OpenOCD is retained.

Official **uhubctl v2.6.0**, commit
`352f5878e999c0a9d5a453b34110479b2056d7e7`, builds against native libusb and is
installed at `oracova-bench/bin/uhubctl`, SHA
`7b0eefa7c1a3c36ee5b80ef02ee49f2c57e20f475573c7b6ceb1d4268e0ea59e`.
Its version check exits before USB initialization. `pl_lib.py` uses that local
build; both Linux power helpers refuse action without explicit reviewed
`BENCH_USB_HUB`/`BENCH_USB_PORTS`. Mac hub numbers are not reused.

The physical Mac's `supervisor-tools` directory was separately copied:
**27 files / 150,004 bytes**, identical source hashes before/after. Its root
`dapbench` is now a GCC13.3 native ELF built from the unchanged original C,
SHA `79248e4086fe90f4b1796be87a86b0be5bc768842466e37d3a4fdeec3914437d`.
The original Mach-O is preserved privately; the benchmark was not executed.
The bench gate also selects its existing `bin/dapbench` Linux binary.
Linux USB reset resolves native libusb and requires an explicitly selected
`BENCH_USBRESET_SERIAL`, checking that serial before resetting; the original
90-second cooldown/four-per-hour cap remains. No USB device was reset.

Reproducible incremental patches are
`pc-router/bench-linux-local-uhubctl.patch`,
`pc-router/bench-linux-tcp-openocd.patch` and
`pc-router/supervisor-tools-linux.patch`; all source dry runs passed.
Twenty-six focused checks passed, including config-only TCP acceptance,
actual zsh parsing, native binaries, and real pre-hardware refusal of unmapped
recovery calls. All **1,444 unchanged bench files**, **23 unchanged supervisor
files**, and original preimages for every derived file were reverified.
Private receipts/preimages live in
`/Users/pouya/.migration/bench-tools-BSgEcASg`; final runtime receipt SHA
`f3beef381acc5b16b4305fd7bd37d2f81c2c363ff25b1bf476f80c10fc262415`.

PC-only maintenance now has an actual working path: native **Windows** SSH
client connects to Windows `127.0.0.1`, with `HostKeyAlias=10.0.0.35` and the
already pinned server fingerprint
`SHA256:YdnvvvajofzohZJOVGAezxXT7R6UbrRoWcL9Zf6lYCw`. A normal owner credential
authenticated the existing Windows administrator maintenance shell; protected
router hash/service readback succeeded at `10:12:04Z`. zsh installation and
fresh router inspection used this path without Mac SSH. No private key or
password file was copied/created, host checks bypassed or firewall broadened.
The pinned public-key file is `C:\Users\pou\pc-maintenance-known-hosts`.
OpenSSH is Running/Automatic. WSL-to-host TCP was refused by the existing
firewall rule, which still allows only the old Mac address; Windows-local SSH
is not outside-LAN recovery proof.

Fresh `10:21:30.7235132Z` service status: Running, 12 routes, seven Claude
connections, global unknown0, held0, shared Linux2141/Windows11252 unchanged.
The separate CC relay display hold/permanent guard deployment from the previous
incident remains pending. No daemon, pairing, model turn or service restarted.
Weekly usage is 14% remaining, above the owner's 5% pause threshold.
Actual USB/hardware relocation, board TLS/network/flash/debug acceptance,
legacy IOKit-only tools, original topic access/provider choices, full backup and
headless/reboot/outside-LAN recovery remain; the Mac is not ready to erase.

### Normal Telegram access and permanent display recovery, October 4 at 3:58 AM PDT

PC-only deployment `da599c5bc3014cda890d09e2c0abdf44` is live and verified.
The owner requested normal access for the account behind denied DUT messages
4818/4819, then clarified all topics and normal access. Actual numeric sender
`199200674` (`@MJ_MN`) now has conversation/attachment access across every mapped
topic; owner `110123423` alone retains slash/model/approval/goal controls.
No wildcard sender admission, new topic, role identity or company boundary was
introduced. Participant tasks still use the owner's existing native tool
permissions; this is a trusted personal allowance, not OS-level isolation.
No previously denied DUT input was replayed. A new human-account round trip has
not yet been observed.

995 Linux and 998 actual sealed Windows regressions passed. They cover direct
sender authentication across admitted topics, both Codex/Claude start/steer,
attachment admission, rejected controls, bots/forwards/proxy/unlisted users and
foreign chats. Actual fresh no-model Windows/WSL owner/credential/code proof
completed `10:50:51Z`. Native executables, launchers and connector sources are
unchanged; earlier Claude tool/continuity evidence was explicitly reused,
not described as a rerun. Seven histories were quiescent and hash-checked before
fresh checkpoints resumed their exact native IDs. All twelve bindings are
unchanged. Existing Linux Codex PID2141, exact current turn
`01a10676-f787-7fd0-89b9-aab30c4cfc40` and active migration goal survived;
the service-owned Windows native process is now PID19956. All seven Claude
streams connected, zero held/global-unknown sessions/effects, startup task
enabled/Ready. No Mac connection was used for deployment.

Permanent source guard `36dcce0` is now installed together with known-message
edit recovery. An uncertain edit of a retained confirmed Telegram message can
amend that same ID again; uncertain initial sends, final-answer sends and native
effects remain fenced. A new amendment of original progress message13670 is
confirmed. The original intent `c52d56f5a9f247da87c3c2aaf9a1553b` remains
`unknown-presentation` with its original audit/payload/result untouched—one
display-unknown operation is still correctly reported, not reclassified as
confirmed. The retained output backlog drained; current controller bubble13679
has zero pending response/final queues. Native work and old denied inputs were
not repeated.

Current DLL SHA256 `87e41db2c0f5b00c2f8f081ae9769f6fdc33ce1a05ffdafc498af49abfbb7db9`;
policy `a9bb49fec1aeac1e7da96fe2d494fe20f9adb50a8c4bc20d0ac86cb1703fb20f`.
Protected preimages, consistent SQLite snapshot, actual proofs, startup XML and
deployment receipts are under
`C:\ProgramData\KhadangRouter\release-da599c5bc3014cda890d09e2c0abdf44`.
Candidate archive SHA256
`3ddf45b2b7ddf3c29287ce3d640aa90b155c7e3ad2b16869c2da18391fba1ebc`.
Reviewed staging helper hash `78195e60...60303c`; final verifier hash
`c2866780...1724fc` fixes UTF-8 decoding of retained topic names. The initial
ANSI-name comparison failure was independently checked field by field: no
actual binding change occurred, and UTF-8 readback verified all twelve.
All seven new checkpoint digests are in deployment status; they are consumed,
so another manual restart still requires fresh quiescent evidence.

Bench/tool changes were committed and pushed as `4313273`. Full-source/archive
refresh, remaining topic choices/access, actual hardware/Fusion qualification,
off-machine disaster restore and headless/outside-LAN recovery remain open.
This is migration progress, not permission to erase the Mac or a completion claim.

### Full-source coverage audit and disk-free capture, October 4

The earlier seeds preserve **selected operational data**, not the entire Mac.
The physical machine has three local account IDs: Pouya501, postgres502 and
Oracova503. The Oracova SSH identity can enumerate its own home and selected
projects in Pouya's home, but cannot enumerate Pouya's Documents, Desktop,
Downloads, Library, Pictures, Music or Movies (`EACCES`). SSH as Pouya with the
existing migration key was rejected. An owner question requests authorized
access; no permissions, keys, passwords or TCC settings were changed.

The physical Pouya home reports about298GiB of accessible allocated data,
including about250GiB in `.lume`. Those figures omit inaccessible descendants.
The VM store has **not** been captured as a consistent powered-down VM image.
System/app folders, inaccessible personal data and the other account are not
certified by the existing operational archives. None may be inferred empty
from a failed directory enumeration.

The Mac VM reports only939MiB available on its data volume. New capture uses
`pc-router/capture-mac-stream.ps1`, not another source-local temporary archive.
The reviewed PC administrator launches the ordinary WSL owner's existing
pinned SSH connection; the remote ordinary Mac identity streams tar/gzip bytes
and a digest directly to new SYSTEM/Administrators-only PC storage. No new Mac
archive, source file deletion, credential transfer, extraction, model, native
restart, task replay, firewall or scheduler change is involved. Whole-home
selection is admitted only by the explicit Oracova-account profile; arbitrary
hosts, source roots, members and overwrite destinations are not accepted.

The receiver has explicit20GiB/15-minute bounds and preserves failed attempts.
It checks source producer status and diagnostics, matching streamed byte count
and SHA256, an independent PC file hash, ACLs and a WSL GNU tar reader. Later
helpers retain bounded source diagnostics only in protected private logs, never
the public result. A warning/producer failure is not relabeled as a full backup.
The source writers remain live: these are **recovery seeds**, not a coordinated
final snapshot, portable Keychain/login recovery, encryption-at-rest package,
daily off-machine backup or clean-machine restore acceptance.

Accepted new archives under `C:\ProgramData\OracovaMigration`:

| Profile | Run directory | Bytes |
| --- | --- | --- |
| VM Documents and Downloads | `7a7a38a27c024a21a9d360bd0f287657` | 1123348480 |
| Entire physical Oracova bench home, including Library | `831934f092504d6a91e5c3ae2dd988f3` | 2769418240 |
| VM code/src/test2/toolchains, media, applications, root working files and retained Trash | `f42ef1b7680f4a2bbfa58820fe51fcd1` | 2004654080 |

The respective SHA256 values are
`62ac5402bb061d81280e7c4d93b8c1b31f51a8836579ea2d9c736930d61a6e29`
and `f579571d709eb4a990e38d8e8c8906babeb8830af36dc486b2b7aaf8b3390a4a`.
The extra-work archive SHA256 is
`2823e651948a653b04bfeb2c9baee1a1594f5b12b537c3f4be6b11af57769f2c1`.
All three producer/transport/reader statuses are0; source/PC digests match, source
diagnostics are empty and target ACLs are protected. Actual ordinary Linux
UID1000 opens of all three archives were denied before reading any byte.
Final reviewed helper SHA256
`d546083c4c468df81d6b20a3c9bf26d7938993436a4183bd7834a919f2ed6290`,
sealed in `stream-helper-a83e69c68b3a4bcbbce4aa863038a5190` under the same
protected parent; all18 actual Windows fixtures passed. They include binary
bytes/hashing, byte bounds, overwrite refusal, explicit source selection, ACLs
and a real Windows-to-WSL literal-argument round trip, without any Mac/model
access in the fixture itself. Source archive acceptance is separate from tests.

Retained failures, not accepted backups:

- `d1d136cfb3bd4cda96baa1b2b7aabf18`: first VM attempt exited127 before any
  payload; quoted WSL option parsing was fixed and an actual Windows-to-WSL
  literal-argument fixture added. The old zero-byte run was not overwritten.
- `26e0e3edc680444f84695b80c6b4734b`: physical Pouya project subset,
  900075520bytes, digest
  `fd77168d7a2901177445e90c0297ecffb59741487450daa1be58c14de4a4125cf`.
  The transferred bytes match and the archive lists, but the source producer
  exited1. Keep it as partial recovery evidence; do not count these projects as
  fully backed up. This early helper retained a diagnostic digest, not its text.
- `156ddf55eefb4b14bc6a2ef3ae84499b`: VM Library,
  2748528640bytes, digest
  `3fd7c3f9a6aa8c4bd64810562ec750049eab27557557e9cf5354870de1e533f3`.
  Producer/transport exited1; a142-byte protected diagnostic identifies a
  permission-denied source, not a socket, changed file or missing-file warning.
  Streamed/independent PC digests, ACL and reader passed; retain the recoverable
  bytes without falsely certifying full Library/Keychain coverage. The full
  bounded diagnostic is retained privately; no source permission was changed.

Read-only router inspection at11:35:28Z remained Running with12 bindings,
all7 Claude streams connected, native PIDs2141/19956, held0, global unknown0
and retained presentation unknown1. Normal participant199200674 remains
enrolled; no runtime policy, topic wiring or native process changed during
these transfers. Latest measured weekly quota remains14% available, above the
owner's5% pause threshold; the goal stays active and incomplete.

Final source fences/current SQLite snapshots,
whole-source coverage, physical-account access and VM-image consistency,
off-machine encryption/key recovery/restore, outstanding routes, real hardware
and boot/outside-LAN acceptance remain required. The Mac is not ready to erase.

### Fresh disk-free SQLite recovery snapshots and exact Library gap, October 4

At12:01:57Z, all six current Mac Codex SQLite databases completed a fresh
backup-API capture. The new explicitly selected `vm-codex-sqlite` profile uses
the installed Mac Python3.14.7/SQLite3.53.4 to copy one database at a time into
memory, then serialize and stream a synthetic tar/gzip cohort into protected
PC storage. It never creates a source-side temporary database/archive, never
uses `immutable=1` on a live WAL source, and never installs old state over either
active profile. A read-only source connection prevents SQL data writes; SQLite
may initialize tiny WAL/SHM companions. Source writers remain live.

The accepted archive is
`C:\ProgramData\OracovaMigration\8aaf9a4e85aa4154aa199d0066743cf7\vm-codex-sqlite.tar.gz`:
174526546bytes, SHA256
`92c1bc8e8cadabd69a63a4733850af1d465e416b892c86917447d1295c6a7c930`.
Its six standalone snapshots total742313984bytes. Source producer, SSH/WSL
transport and GNU tar reader all exited0 with no producer warnings; source and
independent PC archive hashes match, and ACLs are SYSTEM/Administrators-only.
The ordinary Linux UID1000 could not open the archive and read zero bytes.
Measured source process peak RSS was2359148544bytes on the16GiB VM; data-volume
free space remained approximately941MiB after the capture. This is not a
new disk-based backup hidden under a different temporary path.

The PC independently parsed every synthetic member, matched every database's
digest/size against the manifest and ran SQLite integrity checks entirely in
memory. No generic archive extraction, active native database replacement,
source daemon restart, topic change, credentials login or model turn occurred.
SQLite cannot deserialize a WAL-header image directly: only the disposable
verification-memory copy has its two journal header flags normalized, following
the [SQLite deserialize documentation](https://sqlite.org/c3ref/deserialize.html).
The authoritative archived snapshot bytes and their digests remain unchanged.
The copy uses the [SQLite online backup API](https://sqlite.org/backup.html),
not an ordinary copy of live DB/WAL files.

Eight fixtures passed for committed WAL rows/source preservation, closed WAL
and nondefault page size, independent target integrity, byte bounds, source
symlink/hardlink refusal, unsafe archive members, and manifest digest mismatch.
All20 actual Windows stream/argument/ACL fixtures also passed. Production
acceptance is the six-database source/PC receipt above, not those fixtures alone.
The reviewed producer hash is
`8e9d1ad883e19ea8090d69f669652bf14548314ca3cd60e98123532d7e4e1afc`;
receiver hash `793c588b4cb4786712e188ff2dfbb76ab9927fea9bd3ae31cdf7eda6a2118272`,
sealed together in
`C:\ProgramData\OracovaMigration\stream-helper-8d952ede10ce454ebb304114dd64255f`.
Snapshot consistency is **per database**, not an atomic cross-database/project
or final writer-fenced checkpoint, and not daily encrypted off-machine restore.

A complete bounded read-only metadata walk of the VM Library at12:04:08Z
visited215233 entries:31131 directories,161236 regular files,22864 symlinks and
2 special entries, totaling22054921169 logical regular-file bytes. It did not
follow symlinks or read file contents, and did not hit its300000-entry bound.
Exactly one regular file was unreadable: a UID0/root-owned mode0600 file in
Group Containers. Its basename matches the failed tar diagnostic, resolving
the previously unexplained Library failure. The exact pathname/report remain
private, not in Git; public path hash is
`6cd71e0e7fac7f296cdc4dd602d6da8555a8633819d7bfce9a743b297ea5c9e5`.
The private report is under
`C:\ProgramData\OracovaMigration\6eda757be8cc41f1b62222533c4d6829`, SHA256
`255fb8211ff04009a001349674e0a9b1ec1d5b66d4ba6e6129baf41f3dacf8f31`.
The original readable Library data/failed archive are still retained. Mac
`sudo -n -l` denied noninteractive elevation; no password was guessed, permission
weakened or source data removed. Controlled source administrator access is
needed to preserve that file; broader physical-Pouya access is still pending.

### Additional VM home preservation, October 4

A fresh home-root metadata inventory found59 entries:37 hidden and22 visible.
Four new literal cohorts cover owner/tool configuration, package caches, editor
data and the original Darwin CAD installation. Caches are preserved, not assumed
disposable. These are separate bounded streams into SYSTEM/Administrator-only
PC storage; no source archive/temp file or active PC profile replacement occurs.
The reviewed receiver SHA256 is
`742b8ef5a8db689b1318702893584295d1556eca6cee7a0bbc6dbe7db655a772`, sealed in
`C:\ProgramData\OracovaMigration\stream-helper-17af1cf4f70d4c8fa6dc2c177d3394ea`.
All28 actual Windows argument/binary/bounds/profile/ACL fixtures passed.

Package-cache run`6aa41918b4704c4fbdc4e6368442ce3d` finished at12:43:19Z:
6822553600 compressed bytes, SHA256
`b8415b86fd67f98111611c8bca7079914ba0b3bd6d2d772e6c711388e8e785def`.
Source producer/transport/PC archive reader all exited0, with no source warnings;
source digest and independent PC file hash matched. Actual ordinary Linux
UID1000 archive open was denied before reading any bytes.

Editor run`8f7c64366204467dbe2de98c36c9e656` finished at12:47:33Z:
6675302400 bytes, SHA256
`ab42c26b99071dc1e8ee5a98ef961763706caa023d7d2c3265a601c2fd8ad904`.
Original Darwin CAD run`eb95e307685047a19209b5455535116d` finished at12:48:04Z:
571136000 bytes, SHA256
`c2991c213917fc0ec6c8eae0e7942589770989e63ba87774a3dfa0e2aa311ba3`.
Both passed the same0/0/0, no-warning, independent hash and protected ACL gates;
ordinary UID1000 open was independently denied without reading any bytes.
All three accepted archives total14068992000 compressed bytes. The Darwin
installation was not activated over the existing PC Linux CAD tools.

Owner/tool run`cbfcde4fe50745ecb84ac3630c7a5fab` is retained **unaccepted**:
2837524480 bytes, SHA256
`853be4b8916195f62b36b0af3669b4e5ad60d7718719ca5ea111bb0c715d21ba6`.
Producer/transport/reader exited0/1/0: tar itself completed but its152-byte
diagnostic references an unarchivable socket. The archive digest/readability/ACL
checks passed, but the no-warning gate correctly refused acceptance. No warning
was suppressed, old receipt reclassified or failed cohort retried.
A no-follow metadata walk of its19 directory roots visited156106 entries:
14153 directories,141322 regular files,629 symlinks and2 sockets. Regular files
total7954598285 logical bytes; none were unreadable. Its750000-entry bound was
not hit. Exact socket/diagnostic paths remain private. This metadata audit is
not a file-content manifest, socket reconciliation or a final writer fence.
The exact diagnostic is`pax format cannot archive sockets`. A bounded
current-source lstat of its normalized warning pathname ended with
`Errno::ENOENT`; the two sockets observed by the directory walk were not
assumed to be that same endpoint. No socket metadata acceptance or silent
regular-files-only recovery claim was fabricated.

The PC VPN, both MTProto services, both Cloudflare services, VPN state server,
SSH and Magic Remote services were observed Running/Auto without restarting
them. Router readback at12:27:59Z remained Running with12 routes, seven connected
Claude streams, native PIDs2141/19956, zero global unknowns and one retained
presentation unknown. Service state is not fresh outside-LAN protocol or
cold-boot acceptance. Physical-Pouya access, the root-owned Library file, final
source deltas, pending topics, hardware relocation and independently recoverable
off-machine backup remain required; the Mac is not ready to erase.
Post-transfer readback at12:49:49Z again confirmed all12 routes/seven Claude
streams and the same native PIDs/unknown counts. Participant199200674 remains
enrolled with owner110123423 unchanged. Cdrive free space was731657023488 bytes.
Final12:57:22Z readback retained the same state and independently confirmed the
Windows native PID alive. Administrator SSH was closed cleanly. Native weekly
quota remained13% available, above the owner's5% pause threshold; the migration
goal remains active and incomplete.

### Protected Windows recovery-settings export, October 4 at 6:37 AM PDT

`pc-router/export-pc-recovery-settings.ps1` now exports selected live Windows
settings without changing services, tasks, registry values, firewall, power,
login policy or native sessions. It reads service definitions/dependencies and
their registry configuration, scheduled-task XML, firewall/update policy,
non-password Winlogon values, owner WSL registration, power settings/capabilities,
network/adapter settings and Windows optional-feature state. These are read-only
API observations, not a full-machine or writer-fenced backup.
[Service properties](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-service),
[scheduled-task XML export](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/export-scheduledtask).

All12 selected sections were observed in new run
`d3c991de39074d399c7e959eaa7c5a15`, finished `2026-10-04T13:35:54.9390347Z`.
Private artifact:
`C:\ProgramData\OracovaMigration\d3c991de39074d399c7e959eaa7c5a15\settings.private.json`.
It contains2343247 UTF-8 bytes, SHA256
`00f9cdc8ed3820bc7c25331a7388a9fe82c903726b706b25b1755178069c7cd0`.
Independent saved-file hash, size, schema, section states and protected ACL
readback passed. Ten operational service definitions and86 selected task XML
documents were retained; all86 XML roots were independently parsed with DTDs
prohibited and external resolution disabled. The four required router/native
recovery tasks are present.81 tasks have no next-run timestamp; those absences
remain null, not invented dates or missing task exports.

Both the new directory and file are Administrator-owned, inheritance-protected,
with only SYSTEM/Administrators grants. Actual ordinary Linux UID1000 file open
was denied before reading any bytes. Service command lines, task actions,
network addresses and registry data remain private and must not be published.
Winlogon export is an explicit non-secret allowlist; `DefaultPassword` is
excluded. No LSA, DPAPI or Credential Manager API was invoked. Task/service
password portability is not established by this artifact.

The corrected exporter SHA256 is
`e170acabb3c29e3f3345849e119343a0ade6bcba79582893b95e640bb08290dd`;
fixture source SHA256 is
`795171228d9495e2295ece24893c5ab6e62ab4c03170257a47e25b38260c4a6a`.
The exact same bytes were sealed in
`C:\ProgramData\OracovaMigration\recovery-helper-41d27284915549a1968fdf269ff82885`.
All23 actual Windows fixtures passed, covering null/date/offset handling,
invalid timestamp rejection, private errors/data, password exclusion, real
read-only native commands, registry absence, binary values, ACLs, byte/hash
readback and no overwrite or false full-backup claim. Fixtures did not execute
production discovery or contact models/network.

The first run `5b4efafaee124d6db5d4249e1a767445` remains unchanged as an11/12
partial settings observation. Its task section was explicitly unavailable:
the initial exporter called `.ToString()` on absent next-run timestamps.
That was an exporter error, not a missing recovery task. After diagnosis and
regression tests, a distinct new run captured the corrected observations;
neither the partial artifact nor its old receipt was overwritten/reclassified.
The earlier sealed helper `recovery-helper-00411ef1ad74483ab1601983f78969a5`
and its19-fixture result are also retained.

Observed `AutoAdminLogon` remains0. The existing saved-credential mismatch and
owner's replacement choice remain unresolved; no credential or login policy
was changed. Router readback `13:38:05.5450775Z` remained Running,12 routes,
seven Claude streams, native PIDs2141/19956, global unknown0 and retained
presentation unknown1. Windows native19956 was independently alive; participant
199200674 remained enrolled for normal conversation/attachments, with owner
110123423 unchanged. Eight VPN/proxy/tunnel/state/SSH/LG services remained
Running/Auto. Cdrive free space was731640889344 bytes.

The artifact truthfully remains `fullSystemBackup:false`, `writersFrozen:false`,
`encrypted:false`, `restoreActivated:false`. Registry name/byte/link/ACL closure,
driver packages, BIOS/UEFI/BitLocker, Linux/WSL disk consistency, portable
credentials, final file/database/action-ledger capture, encrypted off-machine
custody and a clean-machine restore are not established. Protected Mac personal
data and final deltas still need source access. The Mac is not ready to erase.
Administrator maintenance SSH closed cleanly at13:41:09Z with exit0; no export
or test process remains pending. Native weekly quota is13% available, above the
owner's5% pause threshold. The migration goal remains active and incomplete.
