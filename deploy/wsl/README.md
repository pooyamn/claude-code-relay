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
  the deployed artifact, policy, registry or launcher socket.
- `identities/session.service.in`: incomplete trusted-launcher template, not a
  runnable unit. PR 7 supplies the exact native command, measured resource
  profile and verified readiness. Each execution needs its own root-controlled
  non-delegated cgroup; namespaces/cgroup migration cannot be worker-controlled.

The legacy `systemd/` user units, `prod.json.example` and `keep-wsl-alive.ps1`
are historical references. Do not activate them or Windows tasks during this
preparation. No service/scheduler/configuration change is implied by a commit.

## Migration still to prove

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
