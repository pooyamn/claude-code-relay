# Protected agent host — proposal, not installed

The measured Windows-owner WSL root bypass changes the next deployment action.
Registering another distro under the same account, using an elevated launcher,
or turning off interop is not a supported host-security boundary. Microsoft
recommends a separately managed VM to contain untrusted workloads; distinct
Windows security contexts are also required where host account separation is
intended. [Microsoft's WSL security model](https://github.com/microsoft/WSL/blob/master/doc/docs/technical-documentation/security.md).

Proposed target: one private Ubuntu Hyper-V VM for the protected Linux runtime,
retaining distinct worker/broker identities and the prepared Unix credential
protocols. Windows-native owner remotes, Khadang, VPN/Cloudflare/subscription
services, LG and development WSL stay in place during validation. This does not
prove that provider-native app/subscription continuity works from the guest.
That remains mandatory before migration, not a capability to remove.

The owner was asked to select this VM proposal or first review a separate
Windows account for every WSL role. No accepted-topology claim, feature
enablement, new account/distro/VM, virtual switch, scheduled task, credential
copy, existing service restart or reboot has been performed.

## Actual read-only preflight

`pc-router/inspect-agent-host.ps1` ran on the PC at
`2026-10-03T11:23:28.6796975Z`; `test-agent-host.ps1` passed eight focused
pure/readonly contracts on Windows. The inspector exposes no install/reboot
operation and never turns prerequisite observations into live-role acceptance.
Feature read denial remains Unknown, and absent typed hardware observations
fail instead of becoming false measurements.

- Windows 11 Pro, AMD Ryzen 7 8745HS, 8 cores / 16 logical processors.
- 12.80 GB usable memory, 6.19 GB then available; these are not a guest budget
  or a subscription-quota measurement.
- Firmware virtualization enabled; a hypervisor is already present.
- VirtualMachinePlatform Enabled, but Hyper-V hypervisor/services/management
  features Disabled, Hyper-V PowerShell module absent and `vmms` absent.
- No CBS or Windows Update pending-restart flag observed. That does not promise
  a future feature enable will need no restart.

The CPU's SLAT/VM-monitor properties reported false while the hypervisor was
already running. They are retained as raw observations, not used to label the
CPU unsupported. Microsoft documents that bare-hardware requirements are not
displayed with an existing hypervisor. Actual managed-VM boot/resource checks
remain necessary. [Hyper-V requirements](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/host-hardware-requirements).
Feature installation normally includes a restart; do not enable it until the
owner accepts the topology and remote recovery is ready.
[Official installation procedure](https://github.com/MicrosoftDocs/windowsserverdocs/blob/main/WindowsServerDocs/virtualization/hyper-v/get-started/Install-Hyper-V.md).

## Acceptance for either chosen topology

1. Owner/Jev review the exact protected architecture/artifacts. No live Jev
   clearance exists now. Keep owner-only Khadang; no employee/role cutover yet.
2. Prove denial from actual owner-account model tokens to privileged guest
   management, VHD/config/state, shared mounts and unscoped control endpoints.
   Agents receive no Hyper-V Administrators membership or guest root key.
3. Retain private Linux UIDs, root-controlled role cgroups, authenticated
   registration, private runtime sockets and independently enforced action
   policy. Test the actual broker/launcher, not only fixture directories.
4. Only explicit protected interfaces connect Windows and Linux: scoped inputs
   and action receipts, never a general privileged shell or common writer.
   Validate network/egress and VM startup without reconfiguring working VPN/LG
   services. Unknown actions remain held across a guest/host crash.
5. Measure resources with the three-active-agent cap, protect host remote
   availability, and separately enforce provider pacing and the 10% owner
   subscription reserve. Do not invent a guest memory profile from idle data.
6. Prove native session IDs, unfinished work, phone/app controls and tool-switch
   continuity; join the guest's complete state/config/dirty work to the daily
   encrypted package and clean-machine restore. After recovery approval, prove
   controlled reboot and before-login recovery with compatible rollback.

Current native PIDs 5420/9188 and Khadang/VPN/LG services were revalidated running
before this preflight. The original WSL distro was stopped; no new WSL instance
was started during the host inspection. Windows auto-login remains disabled
pending the separate saved-credential replacement approval.
