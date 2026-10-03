# Mac to PC migration plan

Pouya's current priority is to move the existing working system to the PC,
keep the same Telegram topics, use Khadang instead of Hamal, and make the PC
the bench host. The new role and broker infrastructure is deferred. This plan
does not require completing the 20 PR roadmap before migration.

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
| marginal-requests | -1004395661179 | 427 |
| augur-1 | -1004395661179 | 18 |
| duts | -1004395661179 | 53 |
| schematic-pipeline-lab | -1004395661179 | 2697 |
| mimic-fast-pcb | -1004395661179 | 3315 |

Selected backends and exact native session pins must be read from source runtime
state, not inferred from the `claude-` agent names. Preserve both tools' histories.
Missing pins require reconciliation, not choosing a transcript by modification
time or silently creating a replacement conversation. Preserve the Qwen topic's
actual configuration rather than replacing its backend without a decision.

The source workspace is approximately 49 GB, with another 1.6 GB of OpenClaw
media, 2.3 GB of Codex sessions and 1.2 GB of Claude project history. The PC has
ample disk space. All source workspace files now have a checksum-verified PC
archive and an extracted workspace; project validation and operational checks
are not complete. The separate
physical bench MacBook also holds bench projects and tools; it is not the Mac
VM holding the relay workspace.

The protected Windows Khadang service currently routes one test forum and uses
Codex. Multiple-chat routing and a working native interactive Claude transport
are required. Native remote connectivity alone does not supply that transport.
The last membership check found Khadang unable to access Oracova and Startup
Ideas, and only a member in Ai Dispatch. An owner request to add the bot is
pending. Recheck actual membership before routing changes.

## Execution sequence

1. Preserve the source. Create a new restricted PC staging directory. Transfer
   separate archives over encrypted SSH and SFTP, retaining source paths, Git metadata,
   dirty and untracked files, symlinks, histories, configuration, skills,
   memories, media and action records. Record archive digests, source roots,
   capture times and failures. Initial copies are seeds while writers run,
   not consistent final backups. Do not overwrite existing PC projects or native
   logins, publish private data to Git, or copy live locks as valid ownership.
2. Establish working PC execution. Reuse the existing relay mechanisms, with
   only the portability and routing changes migration needs. Verify exact-ID
   resume and interactive input for both Claude and Codex on the target before
   selecting their operational paths. Preserve task context, unfinished work,
   tool configuration and permissions. A Windows or personal Linux runtime is
   acceptable if it delivers the same capabilities; secure multi-company role
   infrastructure remains a separate deferred project. Keep the protected
   Windows bot credential and deployment boundary intact.
3. Import bindings without creating topics. Address sessions by `(chat, topic)`,
   including an explicit whole-group route. Import selected backends and verified
   pins. Keep the existing LG binding and unrelated bot configuration. Hold
   uncertain incoming deliveries and external actions for reconciliation rather
   than replaying them to make migration appear complete.
4. Cut over one topic at a time. Checkpoint and quiesce that source writer,
   capture the final delta, validate the PC copy, then connect Khadang to the
   same topic. Verify owner input, active-turn steering, tools, one rolling
   bubble, controls, attachments, app-origin updates where supported, and exact
   resume after restart. Disable Hamal routing for that topic only after
   Khadang receipts prove it works. Keep relay topic 816 until last so the
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
   projects, histories, topics, credentials and bench functions on the PC.
   Stop the obsolete Mac services and remove their credentials using recoverable
   operations where possible. Resolve the exact requested deletion target before
   erasing anything. Keep the verified archive independently of the source Mac.

## Completion evidence

These are required acceptance checks, not claims about the current deployment.

- All 14 existing bindings work through Khadang on the PC with the same IDs and
  intended tools; the LG topic also remains working.
- Repositories, local branches, dirty and untracked work, instructions, memory,
  media and exact native histories are preserved and checked, including projects
  that were not bound to Telegram.
- Claude and Codex continue real unfinished work, with owner controls and a
  bounded rolling bubble; uncertain actions are not repeated.
- The PC builds, flashes, debugs and controls the transferred bench hardware,
  including the required hub power operations.
- Remote access and reboot recovery work with the Mac absent. Off-machine
  recovery data and separately recoverable keys exist and are verified.
- The obsolete Mac deployment is retired, with any actual erasure explicitly
  resolved and authorized. Until then migration remains incomplete.

## Execution record

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
failure. The accepted copy helper is `scripts/copy-pc-migration.rb`; its six
argument-safety tests pass. Windows tar rejected an entry in the media archive;
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
still require project validation, native exact-ID resume and a final source delta.
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
Claude's subsequent context checks are recorded below; authenticated work,
settings/logins, source-final checkpoints and topic cutovers remain pending.

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
unfinished-work recovery protocol. Linux logins, actual tool-enabled work,
phone visibility and the Claude production transport still need acceptance.
Seven focused regressions pass, alongside the thirteen history/restore tests.
Original preserved seeds and the source Mac sessions remain untouched.

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

The 12:32 PM PDT membership recheck remains unchanged: Ai Dispatch member only;
Oracova and Startup Ideas inaccessible. The existing bot-add request is still
pending. Authenticated native continuation, topic cutover, physical bench
transfer, independent recovery and Mac retirement remain incomplete.

Detailed historical implementation evidence remains in
[deployment status](../pc-router/deployment-status.json) and the
[deferred roadmap](agentic-pc-20-pr-roadmap.md).
