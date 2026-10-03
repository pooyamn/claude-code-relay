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
archive, but project extraction and operational checks are not complete. The separate
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
checkpoint capture. They are not a completed encrypted daily backup or a proven
native restore. No source data or generated archive has been deleted.

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
still require project and exact-session checks plus a final source delta.
Read-only Git probes on the PC resolved the captured relay, ai-hil and supervisor
worktree HEADs. The relay seed predates the new migration commits, so it must
receive the final source delta rather than being treated as an up-to-date checkout.

Matching native Linux Codex 0.160.0 and Claude 2.1.288 are installed in private
owner preparation directories and both version checks pass. The Codex package
matches the published release digest. Claude's manifest signature, pinned
Anthropic key fingerprint and binary checksum all pass. No session, login or
router transport has been started or changed. Background and manual Claude
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

ARM GCC 13.2.1, newlib, OpenOCD 0.12.0, CMake 3.28.3, Ninja 1.11.1,
GDB, Python venv and build dependencies are installed. Tool versions were read
as the ordinary Linux user. That user compiled and linked the fixture into an
ARM EABI ELF with exit 0; the linker support file is present. This is not an
actual project build, flashing or USB acceptance. A systemd binary-format trigger failed while
the WSL status path was read-only; the existing mount was left intact and this
compatibility issue remains to be reconciled before declaring runtime readiness.

MTProto is currently down. At 10:59 AM PDT, Defender quarantined the Windows
`mtg.exe` as `Trojan:Win32/Kepavll!rfn` with Severe severity, terminating both
proxy processes. The original download archive matches the official release's
SHA-256; that does not establish a false positive. WinSW 2.12.0 then failed to
report the child exits because its LocalService account could not open the
service-control manager, leaving both wrappers falsely marked Running. This
matches [the upstream restricted-user bug](https://github.com/winsw/winsw/issues/1136).
No executable was restored and no Defender exception was added. Security review
is pending; MTProto and its misleading service-health signal both require repair
before Mac-independent VPN acceptance can pass.

Khadang membership remains unchanged: Ai Dispatch member only; Oracova and Startup
Ideas inaccessible. The existing bot-add request is still pending. Target native
resume, topic cutover, physical bench transfer, independent recovery and Mac
retirement remain incomplete.

Detailed historical implementation evidence remains in
[deployment status](../pc-router/deployment-status.json) and the
[deferred roadmap](agentic-pc-20-pr-roadmap.md).
