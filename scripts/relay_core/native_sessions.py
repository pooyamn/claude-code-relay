"""Protected native-session mapping and fenced observation preparation.

No native launch/resume, model turn, worktree write, worker RPC or admission.
Peer must come from kernel-authenticated controller ingress. The mandatory
observer must independently inspect the pinned runtime/UID/execution and exact
conversation; a normalized object or cached record does not prove provenance.
Target transport, lifecycle, company/context and OS acceptance remain gates.
"""
from dataclasses import asdict, dataclass
import re
import sqlite3
import uuid

from .contracts import Record, canonical_bytes, create, decode, fingerprint, recovered
from .identity import Denied, Peer, exact, identifier, integer, strict_json, validate_binding
from .outbox import DeliveryLedger


SCHEMA = "ccrelay.native_session_registry.v1"
CAPABILITIES = {"read", "exact_resume", "steer", "interrupt", "pause", "goal", "app_visibility"}
DIGEST_FIELDS = {"runtime_digest", "tool_contract_digest", "permission_digest"}


def _digests(value):
    exact(value, DIGEST_FIELDS)
    if any(type(item) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", item) for item in value.values()):
        raise Denied("explicit pinned native contract digests required")
    return value


def _capabilities(value):
    if type(value) not in {list, tuple} or any(type(item) is not str or item not in CAPABILITIES for item in value) or \
            len(set(value)) != len(value) or "read" not in value:
        raise Denied("explicit unique native read/control capability contract required")
    return sorted(value)


def _enrollment(value):
    exact(value, {"session_id", "provider", "provider_session_id", "worktree", "desired_state", "expected", "capabilities"})
    identifier(value["session_id"])
    if type(value["provider"]) is not str or value["provider"] not in {"claude", "codex"} or \
            type(value["provider_session_id"]) is not str or not value["provider_session_id"]:
        raise Denied("exact existing native conversation ID and provider required")
    _digests(value["expected"])
    capabilities = _capabilities(value["capabilities"])
    if value["provider"] != "codex" and "goal" in capabilities:
        raise Denied("native goals are a Codex capability, not a generic control")
    return {**value, "capabilities": capabilities}


@dataclass(frozen=True)
class NativeObservation:
    """Trusted adapter output, never a decoded worker-provided authorization."""
    probe_id: str
    observation_id: str
    binding_digest: str
    provider: str
    provider_session_id: str
    worktree: str
    observed_state: str
    active_turn_id: object
    runtime_digest: str
    tool_contract_digest: str
    permission_digest: str
    capabilities: tuple


class NativeSessionRegistry(DeliveryLedger):
    """Reuse private SQLite/fsync/lifetime fencing, not an in-memory role map.

    Multiple local sessions may share a role, but a native conversation cannot
    silently belong to two mappings. Root/role/execution/native/worktree/expected
    contracts are immutable. PR 10 supplies reviewed transfer, not re-enrollment.
    cached() returns historical claims only; refresh() needs current controller
    binding and trusted observation. Neither return value is execution permission.
    """
    def __init__(self, directory, *, owner_uid, authority, observe_runtime, checkpoint=lambda _: None):
        if not callable(observe_runtime):
            raise Denied("independent protected native observer required")
        self.authority, self.observe_runtime = authority, observe_runtime
        super().__init__(directory, owner_uid=owner_uid, policy_digest=authority.policy.digest, checkpoint=checkpoint)

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE native_metadata (schema TEXT NOT NULL)")
        self.connection.execute("INSERT INTO native_metadata VALUES (?)", (SCHEMA,))
        self.connection.execute("""CREATE TABLE native_sessions (
            session_id TEXT PRIMARY KEY,provider TEXT NOT NULL,native_id TEXT NOT NULL,
            body BLOB NOT NULL,body_digest TEXT NOT NULL,enrollment BLOB NOT NULL,enrollment_digest TEXT NOT NULL,
            binding BLOB NOT NULL,binding_digest TEXT NOT NULL,probe_id TEXT UNIQUE,
            UNIQUE(provider,native_id))""")
        self.connection.execute("""CREATE TABLE native_history (
            session_id TEXT NOT NULL,revision INTEGER NOT NULL,body BLOB NOT NULL,digest TEXT NOT NULL,
            PRIMARY KEY(session_id,revision))""")

    def _validate_component(self):
        if self.connection.execute("SELECT schema FROM native_metadata").fetchall() != [(SCHEMA,)]:
            raise Denied("unknown native registry schema; preserve database for migration")
        self.connection.execute("SELECT session_id,revision,body,digest FROM native_history LIMIT 0")
        # Validate before WAL/recovery can rewrite incompatible records.
        for (session_id,) in self.connection.execute("SELECT session_id FROM native_sessions").fetchall():
            self._row(session_id)

    def _row(self, session_id):
        self._check_lock()
        row = self.connection.execute("SELECT * FROM native_sessions WHERE session_id=?", (identifier(session_id),)).fetchone()
        if row is None:
            return None
        record = decode(row[3])
        enrollment = _enrollment(strict_json(row[5]))
        binding = validate_binding(strict_json(row[7]))
        if record.kind != "session" or (record.id, record.fields["provider"], record.fields["provider_session_id"]) != row[:3] or \
                fingerprint(record.to_dict()) != row[4] or fingerprint(enrollment) != row[6] or fingerprint(binding) != row[8] or \
                binding["policy_digest"] != self.policy_digest or enrollment["session_id"] != record.id or \
                (record.fields["root_task_id"], record.fields["role_id"], record.fields["worktree"]) != \
                (binding["root_task_id"], binding["role_id"], enrollment["worktree"]) or binding["session_id"] != record.id or \
                (enrollment["provider"], enrollment["provider_session_id"]) != row[1:3]:
            raise Denied("native session index/contract/binding changed")
        if row[9] is not None:
            identifier(row[9])
            if record.fields["ready"] or record.fields["observed_state"] != "unknown":
                raise Denied("pending native observation cannot be ready")
        history = self.connection.execute("SELECT body,digest FROM native_history WHERE session_id=? AND revision=?",
                                          (record.id, record.revision)).fetchone()
        count, maximum = self.connection.execute("SELECT COUNT(*),MAX(revision) FROM native_history WHERE session_id=?", (record.id,)).fetchone()
        if history is None or count != record.revision + 1 or maximum != record.revision:
            raise Denied("native session revision history incomplete")
        event = strict_json(history[0])
        exact(event, {"schema", "record", "reason", "probe_id", "observation"})
        if event["schema"] != "ccrelay.native_session_event.v1" or fingerprint(event) != history[1] or \
                event["record"] != record.to_dict() or event["probe_id"] != row[9]:
            raise Denied("native session and latest history disagree")
        return {"record": record, "enrollment": enrollment, "binding": binding, "binding_digest": row[8], "probe_id": row[9]}

    def cached(self, session_id):
        """Historical status only. Never authorize delivery from this cache."""
        row = self._row(session_id)
        return None if row is None else row["record"]

    def _controller(self, peer, session_id):
        if self.authority.policy.digest != self.policy_digest:
            raise Denied("broker policy changed; preserve native registry for reviewed migration")
        binding = self.authority.registry.session(identifier(session_id))
        if type(peer) is not Peer or binding is None or binding["role_id"] not in self.authority.policy.controllers.get(peer.uid, frozenset()):
            raise Denied("kernel-authenticated controller for this role required")
        validate_binding(binding)
        role = self.authority.policy.roles.get(binding["role_id"])
        if binding["revoked"] or binding["policy_digest"] != self.policy_digest or role is None or \
                not role.fields["enabled"] or binding["uid"] != role.fields["uid"]:
            raise Denied("native session role/execution binding is no longer current")
        return binding

    def _event(self, record, reason, probe_id, observation=None):
        event = {"schema": "ccrelay.native_session_event.v1", "record": record.to_dict(), "reason": reason,
                 "probe_id": probe_id, "observation": observation}
        self.connection.execute("INSERT INTO native_history VALUES (?,?,?,?)", (
            record.id, record.revision, canonical_bytes(event), fingerprint(event)))

    def _save(self, record, reason, *, probe_id=None, observation=None):
        self.connection.execute("UPDATE native_sessions SET body=?,body_digest=?,probe_id=? WHERE session_id=?", (
            record.encode(), fingerprint(record.to_dict()), probe_id, record.id))
        self._event(record, reason, probe_id, observation)

    def enroll(self, peer, fields):
        enrollment = _enrollment(fields)
        binding = self._controller(peer, enrollment["session_id"])
        record = create("session", id=enrollment["session_id"], role_id=binding["role_id"], root_task_id=binding["root_task_id"],
                        provider=enrollment["provider"], provider_session_id=enrollment["provider_session_id"], worktree=enrollment["worktree"],
                        desired_state=enrollment["desired_state"], observed_state="unknown", observation_id=None, ready=False,
                        runtime_digest=None, tool_contract_digest=None, permission_digest=None, active_turn_id=None)
        with self._transaction():
            if self._controller(peer, record.id) != binding:
                raise Denied("native binding changed during enrollment")
            current = self._row(record.id)
            if current is not None:
                if current["enrollment"] != enrollment or current["binding"] != binding:
                    raise Denied("native rebind requires verified writer-transfer/migration")
                return current["record"]  # Lost enrollment ACK cannot reset later state.
            try:
                self.connection.execute("INSERT INTO native_sessions VALUES (?,?,?,?,?,?,?,?,?,NULL)", (
                    record.id, enrollment["provider"], enrollment["provider_session_id"], record.encode(), fingerprint(record.to_dict()),
                    canonical_bytes(enrollment), fingerprint(enrollment), canonical_bytes(binding), fingerprint(binding)))
            except sqlite3.IntegrityError as error:
                raise Denied("native conversation already belongs to another local mapping") from error
            self._event(record, "enrolled", None)
            self.checkpoint("before_native_enroll_commit")
        self.checkpoint("after_native_enroll_commit")
        return record

    def desired(self, peer, session_id, state, *, expected_revision):
        self._controller(peer, session_id)
        with self._transaction():
            row = self._row(session_id)
            if row is None or row["record"].revision != integer(expected_revision, 0) or self._controller(peer, session_id) != row["binding"]:
                raise Denied("native desired-state revision/binding changed")
            record = row["record"]
            if state == record.fields["desired_state"]:
                return record
            value = record.to_dict()
            value.update(desired_state=state, observed_state="unknown", observation_id=None, ready=False, revision=record.revision + 1)
            updated = decode(value)
            self._save(updated, "desired_state_requested")  # Request is NOT a native control receipt.
            self.checkpoint("before_native_desired_commit")
        self.checkpoint("after_native_desired_commit")
        return updated

    def prepare_resume(self, peer, session_id, *, expected_revision):
        """Persist control intent/invalidate probes; never perform a native call."""
        self._controller(peer, session_id)
        with self._transaction():
            row = self._row(session_id)
            if row is None or row["record"].revision != integer(expected_revision, 0) or \
                    self._controller(peer, session_id) != row["binding"] or \
                    row["record"].fields["desired_state"] != "running" or "exact_resume" not in row["enrollment"]["capabilities"]:
                raise Denied("resume revision/binding/desired state/capability changed")
            value = row["record"].to_dict()
            value.update(observed_state="unknown", observation_id=None, ready=False, revision=row["record"].revision + 1)
            pending = decode(value)
            self._save(pending, "resume_requested")
            self.checkpoint("before_native_resume_control_commit")
        self.checkpoint("after_native_resume_control_commit")
        return pending

    def refresh(self, peer, session_id, *, expected_revision):
        self._controller(peer, session_id)
        probe_id = "native-probe-" + uuid.uuid4().hex
        with self._transaction():
            row = self._row(session_id)
            if row is None or row["record"].revision != integer(expected_revision, 0) or self._controller(peer, session_id) != row["binding"]:
                raise Denied("native observation revision/binding changed")
            value = row["record"].to_dict()
            value.update(observed_state="unknown", observation_id=None, ready=False, revision=row["record"].revision + 1)
            pending = decode(value)
            self._save(pending, "observation_requested", probe_id=probe_id)
            self.checkpoint("before_native_probe_commit")
        self.checkpoint("after_native_probe_commit")
        # Never hold SQLite locks across a transport observation. A simultaneous
        # owner stop/pause, new probe or revocation must invalidate this result.
        try:
            observation = self.observe_runtime(row["binding"], pending, probe_id)
        except Exception:
            raise Denied("native observation unavailable; identity retained without readiness") from None
        self.checkpoint("after_native_observation")
        if type(observation) is not NativeObservation or type(observation.capabilities) is not tuple:
            raise Denied("decoded runtime claims cannot provide a native observation")
        identifier(observation.observation_id)
        if observation.probe_id != probe_id or observation.binding_digest != row["binding_digest"] or \
                (observation.provider, observation.provider_session_id, observation.worktree) != \
                (pending.fields["provider"], pending.fields["provider_session_id"], pending.fields["worktree"]) or \
                {key: getattr(observation, key) for key in DIGEST_FIELDS} != row["enrollment"]["expected"] or \
                not set(row["enrollment"]["capabilities"]) <= set(_capabilities(observation.capabilities)):
            raise Denied("native observation does not match exact identity/contract/capabilities")
        if observation.provider != "codex" and "goal" in observation.capabilities:
            raise Denied("native observation claims a control from another backend")
        value = pending.to_dict()
        value.update(observed_state=observation.observed_state, observation_id=observation.observation_id,
                     active_turn_id=pending.fields["active_turn_id"] if observation.observed_state == "unknown" else observation.active_turn_id,
                     **{key: getattr(observation, key) for key in DIGEST_FIELDS},
                     ready=pending.fields["desired_state"] == "running" and observation.observed_state == "running",
                     revision=pending.revision + 1)
        observed = decode(value)
        with self._transaction():
            current = self._row(session_id)
            if current is None or current["probe_id"] != probe_id or current["record"] != pending or \
                    self._controller(peer, session_id) != row["binding"]:
                raise Denied("native observation became stale during verification")
            data = asdict(observation)
            data["capabilities"] = list(observation.capabilities)
            self._save(observed, "runtime_observed", observation=data)
            self.checkpoint("before_native_observation_commit")
        self.checkpoint("after_native_observation_commit")
        return observed

    def recover_inflight(self):
        super().recover_inflight()
        with self._transaction():
            ids = self.connection.execute("SELECT session_id FROM native_sessions").fetchall()
            for (session_id,) in ids:
                row = self._row(session_id)
                updated = recovered(row["record"])
                if updated == row["record"] and row["probe_id"] is not None:
                    value = updated.to_dict()
                    value["revision"] += 1
                    updated = decode(value)
                if updated != row["record"]:
                    self._save(updated, "recovery_requires_fresh_observation")
