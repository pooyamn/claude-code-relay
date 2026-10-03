# Preparing the role-isolated WSL2 relay

Design v7 requires separate local identities, not the old common `pouya` home.
The PC kit is preparation, not an approved installer or cutover. Existing Mac
sessions, subscriptions, Telegram polling and the remote-control daemon remain
untouched. The [20-PR roadmap](../../docs/agentic-pc-20-pr-roadmap.md) tracks the
remaining launch, authorization, backup/restore and target acceptance work.

Telegram integration tests use Khadang. HamalBot's existing configuration,
bindings, credentials, poller and services stay untouched until Pouya explicitly
authorizes a change. Verify the test bot's identity and existing poller ownership
before using it; testing is not permission for a production-bot cutover.

## Safe commands now

```sh
python3 deploy/wsl/identity-plan.py --dry-run
python3 scripts/ccrelay_intake.py --plan
python3 scripts/ccrelay_outbound.py --plan
bash deploy/wsl/setup-wsl.sh plan
bash deploy/wsl/pull-from-mac.sh --dry-run
python3 scripts/tests/run_isolated.py
```

The planner only reads example templates and existing account/group metadata.
It reports desired identities and rejects UID/name/home/group collisions; it
does not provision, install, enable, copy credentials, SSH or change config.
The old `root`, `user`, `enable` and bulk-copy/final-copy paths exit before any
operation. Their implementation remains below the guard as an audit reference,
not as instructions to bypass the new design. Consistent per-role migration is
still required; it is not replaced by a common-home copy.

## Prepared artifacts

- `identities/ccrelay.sysusers.conf`: example UID allocation for router, broker,
  publisher, backup, memory, deploy coordinator and five initial role identities.
  Account and supplementary-group state must be audited on the target before
  applying a reviewed artifact. No worker gets sudo, Docker or another role's
  private group.
- `identities/ccrelay.tmpfiles.conf`: private native homes, worktree/state roots
  and component directories; protected root-owned policy/code roots.
- `identities/broker-policy.json.example`: role/capability ceilings and explicit
  launcher grants. The all-zero per-role policy digests are example placeholders
  to replace with reviewed role-policy digests; the broker independently binds
  each registration to the canonical digest of the entire loaded policy.
- `systemd/ccrelay-broker.service`: inert protected broker service with no
  activation section. The policy must be root-owned, and workers cannot edit
  the deployed artifact, policy, registry or launcher socket. The prepared
  broker also owns the private durable message/action outbox. Its MCP client
  enrolls held messages and exposes participant-scoped status/log pages, not
  queued or delivered native input. [PR 5 evidence and recovery](../../docs/pr5-durable-delivery.md)
  lists the pending native transport, owner-ingress and admission gates.
- `identities/owner-policy.json.example` and `deployment-policy.json.example`:
  disabled exact-owner/channel and protected classification/bootstrap policies.
  Their owner/bot/chat/topic IDs are invented, not live configuration. Routine
  deployment cannot be enabled by this v1 policy.
- `systemd/ccrelay-owner-gate.service`: inert Linux credential-authenticated
  approval ingress, using a separate explicit socket group for only `relay`
  and the deploy coordinator. It neither polls Telegram nor starts/restarts
  candidate code. [PR 3 evidence and recovery](../../docs/pr3-owner-deployment.md)
  lists the remaining trusted Bot API, target-OS and screener gates.
- `identities/intake-policy.json.example`, `intake-config.json.example` and
  `systemd/ccrelay-intake.service`: disabled/inert Khadang-only durable intake
  preparation with pinned bot identity, private state and host-wide poller locks.
  The example username and IDs are placeholders. The entry point's `--plan`
  reads no credentials and calls no API. [PR 4 evidence and recovery](../../docs/pr4-durable-intake.md)
  distinguishes pending logical dispatches from native delivery and explains
  why a local lock cannot fence an unmanaged poller on another machine.
- `identities/session.service.in`: incomplete trusted-launcher template, not a
  runnable unit. PR 7 supplies the exact native command, measured resource
  profile and verified readiness. Each execution needs its own root-controlled
  non-delegated cgroup; namespaces/cgroup migration cannot be worker-controlled.
- `identities/outbound-policy.json.example` and `outbound-config.json.example`:
  disabled Khadang send preparation with invented bot/chat/timing values, no
  rate-limit retry grants and no live startup path. Private outbound, sealed
  asset and host-wide send-owner directories are inert tmpfiles templates.
  `ccrelay_outbound.py --plan` reads no keys and sends nothing.
  [PR 6 evidence and remaining gates](../../docs/pr6-telegram-outbound.md) covers
  receipt-bound offsets, safe format/media repair, trusted producer/owner UI
  wiring and real Khadang/WSL acceptance. All live direct senders stay unchanged.

The legacy `systemd/` user units, `prod.json.example` and `keep-wsl-alive.ps1`
are historical references. Do not activate them or Windows tasks during this
preparation. No service/scheduler/configuration change is implied by a commit.

## Migration still to prove

Actual PC evidence now includes 47 focused bubblewrap regressions and 78
credential-free cross-UID kernel assertions. It also exposes a host-side root
launch bypass from a non-elevated Windows owner process; this must be closed
before role/company activation. [Evidence and exact limitations](../../docs/pc-wsl-identity-evidence.md).
`sh deploy/wsl/run-identity-drill.sh` only prints a plan. `--run` is an explicit
trusted-root, reviewed-artifact disposable test on a credential-free target;
it starts one restricted transient system service, not an installer or model.
It refuses existing fixture state/provisioned role UIDs and uses only synthetic
homes, sockets and processes, removed with the transient RuntimeDirectory.
Do not run the root fixture manager as a worker or promote passing tests into
deployment authorization. Original interop/automount configuration is not
changed by the test.

1. Choose a disposable Linux/WSL environment and verify distinct-UID filesystem,
   process, socket, group, namespace and cgroup boundaries there. Unit mocks on
   the Mac do not prove this. See [PR 2 evidence and runbook](../../docs/pr2-identity-broker.md).
2. Prove per-role subscription login and native-app visibility with the exact
   provider sessions. Do not copy a shared credential home or expose a common
   writer/control socket to workers. Preserve phone/native apps and voice/media
   capabilities through the admitted adapters; unsupported topology is a gate,
   not permission to silently fall back or remove a capability.
3. Snapshot existing state consistently into private quarantine, inspect the
   manifest, and map each session/worktree to its role home deliberately. Dirty
   files, exact provider IDs, approvals and unknown actions must survive. Plain
   rsync of live SQLite/WAL files does not establish a consistent snapshot.
4. Restore paused, validate permissions/identity/runtime versions and reconcile
   external outcomes before admitting work. No SSH keys, provider logins or
   router/GitHub/R2 credentials are bulk-copied into worker homes.
5. Obtain owner authorization for the exact cutover artifacts and bot choice.
   Only one poller may own a token. Canary, then migrate one role at a time with
   recorded compatible rollback checkpoints. Never restart/kill the Mac Codex
   daemon or change the bench/VPN as part of this work.

Actual deployment commands, configuration merging and rollback drills belong
to the later protected deployment/restore/target-acceptance PRs. Target readiness
and approval of live cutover are separate decisions.
