# PR 2 protected identities and broker preparation

Local code/template preparation, 2026-10-01. Not deployed or target-WSL accepted.
The Mac legacy relay is unchanged; its directory-based caller is now explicitly
labeled routing rather than authentication. The new target stdio client is
`scripts/ccrelay_broker_mcp.py`, not a shared-state privileged MCP server.

## Implemented mechanism

The protected policy maps distinct worker UIDs to role capabilities, with
reviewer-only review, CTO-only merge requests, support-only deployment requests
and no worker owner approval. Empty role/controller allowlists, duplicate UIDs,
worker/broker/controller identity aliasing and unknown schemas fail closed.
The reviewed controller has explicit registration grants; a worker cannot
register itself or another session by changing directory or a request header.

The Linux broker authenticates the connecting process using `SO_PEERCRED` and
requires matching `SCM_CREDENTIALS` on every request fragment. This additionally
rejects writes from another process using an inherited/transferred connection;
received descriptors are closed and refused. Framing is bounded, duplicate JSON
keys are rejected, and fragments cannot reset the total read deadline. These
choices follow the documented [Unix credential semantics](https://man7.org/linux/man-pages/man7/unix.7.html),
but live Linux socket behavior is still an acceptance gate.

Registration derives UID, boot/start identity and cgroup from the kernel, not
caller arguments. It requires the exact `ccrelay-session-<execution>.service`
cgroup and root-controlled cgroup migration files, recording the registering
controller UID and policy digest. Every request rechecks peer credentials, the
unit, the leader's process generation and the active loaded policy. A protected
policy deployment must reload the broker; editing a file is not a hot update.
The [kernel cgroup
permission rules](https://docs.kernel.org/admin-guide/cgroup-v2.html#delegation-containment)
explain why root control and no worker delegation are necessary. Target tests
must demonstrate those conditions; a matching cgroup string alone is not proof.

`BindingRegistry` stores immutable canonical v1 bindings in private SQLite,
with full synchronous transactions, unique session/unit/execution indexes,
record/index agreement checks, durable revocation and consistent SQLite backup.
Identical registration replay is idempotent; changed intent, revoked replay,
incompatible schemas and uncertain writer transfer cannot reset identity.
Revocation fences requests but does not claim that a process or its descendants
stopped. Execution rotation/quiescence is added by PRs 7/8, not by clearing rows.

Only `whoami` and registered-peer introspection are enabled. Registration is
not runtime readiness. Even an authorized reviewer/CTO request cannot execute
publication, merge, deployment or external effects: later durable/admission,
approval and publication gates are mandatory. Existing messaging/issue/media
capabilities remain on the unchanged Mac path while those adapters are built.

## Provisioning and recovery

The [WSL kit](../deploy/wsl/README.md) supplies distinct identities, private
homes/component state, protected artifact/policy roots, an inert broker unit,
a worker template and a read-only collision/group audit planner. It applies
nothing. The old installer and credential-copy entry points are guarded before
their first operation; scoped consistent migration remains a later deliverable.
Only the trusted launcher may populate the target registry; cwd-derived legacy
mappings are not automatically promoted into authenticated identities.

Restore must include the root-owned policy, UID/home/group allocation and exact
artifact version plus the `ccrelay.binding_registry.v1` SQLite snapshot and its
`ccrelay.session_binding.v1` records. Copying only the database without a live WAL
is not the snapshot API. A `component_snapshot` must record the policy/artifact
digests, snapshot digest/size and schema; missing/unknown state is incomplete,
not an empty valid registry. Register this component with PR 12's full-system
package and PR 13's paused restore hooks before enabling it.

After restore, old boot/PID/unit observations cannot authenticate the new
machine; a reviewed launcher must reconcile exact sessions and writer status
before renewing bindings through the later transfer protocol. Back up the
incompatible original bytes before an explicit reviewed schema migration.
No v0/shared-state migration or automatic binding replacement is implemented.

Rollback of this unactivated preparation is code-artifact-only. After target
activation, stop admitted new work, preserve the database/policy/artifact
snapshot and use a schema-compatible reviewed artifact. A rollback may not
reactivate revoked bindings, restore stale external action intent as new, or
fall back to the shared-home legacy identity boundary. Owner cutover permission
is separate from repository publication.

## Evidence and pending acceptance

All four legacy suites and 64 core tests pass on the Mac; PR 2 adds 28 checks to
PR 1's 36. The planner and both entry points also work under isolated Python
(`-I`) in the copied-source sandbox. No provider or production socket is used.

Run `python3 scripts/tests/run_isolated.py`. Current checks use synthetic roles,
mocked Linux kernel metadata/ancillary messages and private SQLite fixtures
inside the existing Mac filesystem/network sandbox. For SQLite fixtures only,
the protected-ancestor check is mocked because the scratch ancestor is not a
production protected-state root; separate metadata tests exercise that check.
This proves conformance paths, not distinct-UID ACL or socket security on WSL.

Before trusting the target, a disposable Linux/WSL drill must demonstrate:

- Real builder/reviewer/CTO UIDs cannot read, write, signal, ptrace or attach to
  another role's home, native runtime or private socket, or alter policy/code,
  mappings, the launcher socket, cgroup membership or privileged service units.
- A real Unix connection gets the expected peer and per-fragment credentials;
  inherited/transferred sockets and `SCM_RIGHTS` cannot impersonate the sender.
  Multi-fragment and pre-accept buffered writes remain correctly authenticated.
- The reviewed launcher registers only its granted role with the exact live
  systemd cgroup and process generation. Cwd/header spoofing, dead/PID-reused
  leaders, changed policy, disabled/revoked records and incompatible DB schemas
  fail without erasing original state or starting a replacement session.
- Linux cgroup v2, namespace restrictions, actual systemd unit semantics and
  protected proc visibility work together, rather than relying on a sandbox
  directive that the installed runtime may not support or may ignore.
- Subscription/native-app continuity and readiness are independently proved by
  PR 7, and every later effectful handler repeats its applicable security,
  admission, publication and restore gates. Owner credential/key choices remain
  explicit; no live deployment is approved by this document.
