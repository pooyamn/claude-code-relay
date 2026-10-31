# GT105 Windows CEC clock-gate policy

This policy gates only the IT5570 CEC engine's clock at EC XDATA `0x1E09`
bit 0. It leaves the GPIO mode and CEC pin multiplexer unchanged. Clearing
CECEN instead would select a PS/2 clock configured to hold the shared line
low on the tested machine, so this policy must not use that shortcut.

Validated machine: chip ID `0x5570`, revision `0x02`, BIOS `1.10`, firmware
date `2025-10-22` UTC. Changing BIOS, driver/library or protected policy
artifacts causes refusal, not a guessed write. The original gate bit is 0.

The independent 30-second test observed 145 stable samples and successful
SYSTEM rollback. This is not an end-to-end HDMI traffic or active-bus stress
test. An idle guard is required before applying the clock gate.

## Installation

Run `Install-CECPolicy.ps1` from elevated Windows PowerShell with an explicit
`SourceDirectory`. The installer expects the previously verified official
restricted PawnIO 2.2.0 installer and signed LpcIO module in this machine's
BIOS evidence folder; it never downloads or substitutes a driver.

It creates an admin/SYSTEM-only `C:\ProgramData\GT105CEC` directory and the
`GT105-CEC-ClockGate` task. Triggers are Windows startup and resume events
(Power-Troubleshooter 1, Kernel-Power 107/507). No login is required. The task
uses SYSTEM, single-instance execution, a bounded idle wait and at most two
one-minute retries. It does not continually write against the EC firmware.

The signed PawnIO provider remains installed because future startup/resume
runs need it. Windows security protections and firmware are not weakened.
The task uses only Windows-local files, not WSL or a remote Mac.

## Status and restore

From **Administrator PowerShell**, status is read-only:

```powershell
& ([scriptblock]::Create([IO.File]::ReadAllText('C:\ProgramData\GT105CEC\CEC-Policy.ps1'))) -Mode Status
```

Restore first disables the scheduled task, then restores the original gate
bit, preserving other current bits:

```powershell
& ([scriptblock]::Create([IO.File]::ReadAllText('C:\ProgramData\GT105CEC\CEC-Policy.ps1'))) -Mode Restore
```

`-Mode DryRun` checks eligibility without a target-register write. The latest
audit is `C:\ProgramData\GT105CEC\latest-run.json`; individual runs are in
the protected `runs` directory. Nonzero task exit means refusal/error, not
that CEC was disabled. Check `success`, `outcome` and before/after register
values rather than inferring success from task registration.

To uninstall, restore and verify first, then unregister only this task.
Remove the PawnIO provider only after confirming no other software uses it.

## Limits and verification

CEC is active during firmware/pre-Windows boot; this is not BIOS isolation.
Manual SYSTEM-task execution and exported trigger XML can verify deployment
without rebooting. They do not prove a real reboot/resume event has fired.
Coordinate a future restart/resume and TV behavior check with the owner.

Run portable checks with `python3 -m unittest discover -s pc-router/cec`.
The C# helper also has a hardware-free `SelfTest()` covering masked writes
and unsafe-state rejections. Deployment must additionally verify protected
artifact hashes, task principal/triggers, live gate state and idempotence.
