# PC WSL identity drill — 2026-10-03

Partial target evidence, not role/company cutover approval. Khadang, both native
remote processes, the seven VPN services and LG remained running. No model,
provider login, router credential, role account or persistent Linux service was
added. Original WSL configuration and Windows auto-login remain unchanged.

## Measured target

Host `DESKTOP-8SO9HDK`, WSL2 `Ubuntu-24.04`, kernel
`6.18.40.1-microsoft-standard-WSL2`, systemd `255.4-1ubuntu8.17`, bubblewrap
`0.9.0`. Unified cgroup v2 is mounted. `/etc/wsl.conf` enables systemd only:
default Windows interop and the `/mnt/c` drive mount are present. The system is
degraded because `systemd-binfmt.service` failed; restricted transient services
still ran. This bootstrap distribution is not the accepted worker host.

## Real Linux checks

47 focused regression tests passed through the existing enforced bubblewrap
runner as numeric UID 23100. Its OS probe verified a clean environment, denied
outside fixture reads/writes and excluded host networking. Sources came from
committed `de0ecbd` (`scripts` and `deploy/wsl` only), plus the existing untracked
`test_core_linux_wire.py` fixture, which was copied read-only, not edited or
included in this commit. The archive SHA-256 was
`8a25748717f16f7e9ba4b350f209784b0167c5606811131113567bc2afd638f2`;
that extra fixture's SHA-256 was
`2df9a2281e4e7ba466aa0deca0f564bb5b1a34f362f12fe43ca805864219bdef`.

The first run covered 44 tests; the final candidate added three fail-closed/
plan-only drill checks (47 total). Nine drill/runner checks also passed in the
Mac OS sandbox. The two-file candidate test archive SHA-256 was
`3cb6c5025067017ebe4ae494bfd09fdeb3f7e277548323155dab269ea12e8888`.
Final drill Python SHA-256 is
`e26acb922256754462feeebfb027558538339ec87ab14e79a90da43babb12d5d`;
shell launcher SHA-256 is
`a7da5e0e3202a4a2c46906030593939e03919eaf973c5d0d62ecb136371b81ef`.
The candidate tar preserved private source modes; non-root test entry initially
failed with Permission denied. Only these public copied fixture sources were
made root-owned/readable; no private state or production permission changed.

The 10 actual Linux wire tests cover pre-accept queued bytes, per-fragment
credentials, inherited/transferred connection impersonation, wrong broker UID,
missing credentials, transferred/truncated descriptors without leaks and frame
bounds. The original other 34 checks include synthetic policy/registry/proc observations
and the preparation planner. They do not turn mocked observations into live
launcher evidence. An initial root run correctly failed: the registry refuses
UID 0 as its protected owner. Running tests as a non-root fixture UID fixed the
test setup, not the production security check.

The new `deploy/wsl/run-identity-drill.sh --run` then passed 78 kernel assertions
in a disposable root-controlled systemd service. Real numeric builder 23100,
reviewer 23101 and CTO 23102 identities, each with private primary GID and only
supplementary GID 23200, could read/write their own synthetic home but could not:

- Read/write either other role's synthetic home or connect its private socket.
- Signal, ptrace or read process memory of either other role's fixture process.
- Write protected synthetic policy or cgroup migration files.
- Create user/mount namespaces, read the Windows drive or execute WSL `/init`.

Every role had all five capability sets empty and NoNewPrivileges enabled.
The fixture listener observed each real PID/UID/GID in both SO_PEERCRED and
SCM_CREDENTIALS. The successful unit was
`ccrelay-identity-proof-996e8ab9c00e.service` for the final candidate (80 ms
runtime, 2.9 MB memory peak; an earlier corrected fixture also passed all 78).
No synthetic UID process, runtime directory or transient unit remained after
the checks. Numeric fixtures did not create `/etc/passwd` entries.

The deterministic root fixture manager is not a worker template. It alone has
bounded setup/cleanup capabilities. systemd 255 dropped CAP_SETUID despite its
bounding ceiling during the seccomp/UID setup, so the fixture manager explicitly
retains ambient CAP_SETUID, then each child drops the entire bounding ceiling,
UID and remaining inheritable capabilities. This is the characterized fixture
launch mechanism, not a relaxation of worker permissions. The
[pinned systemd implementation](https://github.com/systemd/systemd/blob/v255/src/core/exec-invoke.c#L4484)
documents that drop. An earlier chmod-after-chown fixture failure was corrected
by ordering chmod first, rather than adding CAP_FOWNER. Failed fixtures exited
and their transient state was collected.

## Confirmed Windows-owner bypass

The one-shot `Oracova-WSL-OwnerBoundaryProbe-20261003` task used the exact owner
SID, Interactive/Limited and session 1. Its protected diagnostic verified the
process was **not** a Windows administrator, then ran only:

```text
wsl.exe --distribution Ubuntu-24.04 --user root --exec /usr/bin/id --user
```

It observed Linux UID 0, exit 0, at `2026-10-03T11:09:05.1792863Z`. No credential
was read. Thus distinct Linux UIDs alone do not protect this owner-registered
distro from a full-access Windows owner session. Protecting its VHD directory
from ordinary direct file reads did not prevent entry through WSL's launcher.
The owner-writable diagnostic JSON is evidence from this test, never a reusable
production authorization grant.

Before placing broker secrets or untrusted roles there, use a protected host
identity/topology that owner-account model processes cannot launch as root,
and test that denial from those real Windows tokens. Preserve owner management
and native phone access through explicit protected interfaces, not a shared
root-capable CLI or common writer socket. Disable role-host Windows interop,
Windows PATH insertion, fixed-drive automount **and** fstab mounting; deny manual
mount/namespace escalation and access to WSL init/interop endpoints. Automount
off alone does not prevent manual mounts.
[Microsoft WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config),
[Windows-side interop identity](https://learn.microsoft.com/en-us/windows/wsl/enterprise).

## Remaining acceptance

The drill shares one disposable cgroup across fixtures; it does not prove the
actual broker with separately launched role units, root-only registration,
process-generation/revocation recovery, or restrictions on every executable and
network path. Persistent provisioning, native subscription/login/app continuity,
company grants, publication, secure deployment and full-system restoration
remain separate gates. The new host-boundary risk is flagged for owner/Jev
review; Jev is not connected and has not cleared it. Nothing in these passing
tests authorizes live security-policy installation or cutover.
