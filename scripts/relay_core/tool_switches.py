"""Joined durable tool-switch custody; no native launch, model or action replay.

Mandatory protected readers must verify actual checkpoint bytes/semantics,
all-writer fences, destination loading and human authority. Typed synthetic
receipts are conformance inputs, not authentication or target-PC enforcement.
"""
from dataclasses import asdict, dataclass
import hashlib

from .contracts import canonical_bytes, create, fingerprint, intent_payload, transition
from .identity import Denied, exact, identifier, integer, strict_json, validate_binding
from .model_admission import ModelAdmission
from .native_sessions import NativeSessionRegistry
from .work_ownership import _deadline, _digest


SCHEMA = "ccrelay.tool_switch.v1"
PHASES = {"checkpoint_pending", "checkpointed", "completed", "cancelled"}


@dataclass(frozen=True)
class SwitchAuthority:
    scope_digest: str
    source_digest: str
    decision_id: str


@dataclass(frozen=True)
class SwitchCheckpoint:
    scope_digest: str
    source_digest: str
    capsule_digest: str
    complete: bool


@dataclass(frozen=True)
class SwitchLoaded:
    scope_digest: str
    source_digest: str
    capsule_digest: str
    native_session_id: str
    active_turn_id: object
    read_only_fenced: bool
    runtime_digest: str
    tool_contract_digest: str
    permission_digest: str


@dataclass(frozen=True)
class SwitchFence:
    scope_digest: str
    source_digest: str
    all_old_writers_stopped: bool
    destination_read_only: bool


def metadata(ledger):
    if ledger.connection.execute("SELECT schema FROM tool_switch_metadata").fetchall() != [(SCHEMA,)]:
        raise Denied("unsupported tool-switch schema; preserve state for reviewed migration")


def active_work_switch(ledger, work_id):
    if not ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_switch_metadata'").fetchone():
        return False
    metadata(ledger)
    return bool(ledger.connection.execute("SELECT 1 FROM tool_switches WHERE work_id=? AND active=1", (work_id,)).fetchone())


class ToolSwitches:
    def __init__(self, admission, registry, *, authorize, verify_checkpoint, verify_loaded, writer_guard):
        if type(admission) is not ModelAdmission or type(registry) is not NativeSessionRegistry or \
                registry.authority is not admission.ledger.authority or registry.policy_digest != admission.ledger.policy_digest or \
                not all(callable(value) for value in (authorize, verify_checkpoint, verify_loaded, writer_guard)):
            raise Denied("same-authority shared admission/native registry and independent switch readers required")
        self.admission, self.ledger, self.registry = admission, admission.ledger, registry
        self.authorize, self.verify_checkpoint, self.verify_loaded, self.writer_guard = authorize, verify_checkpoint, verify_loaded, writer_guard

    def initialize(self, peer):
        roles = self.ledger.authority.policy.controllers.get(peer.uid, frozenset())
        if not roles:
            raise Denied("protected switch controller required")
        self.ledger._controller(peer, sorted(roles)[0])
        self.admission._check()
        with self.ledger._transaction():
            if not self.ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_switch_metadata'").fetchone():
                self.ledger.connection.execute("CREATE TABLE tool_switch_metadata (schema TEXT)")
                self.ledger.connection.execute("INSERT INTO tool_switch_metadata VALUES (?)", (SCHEMA,))
                self.ledger.connection.execute("CREATE TABLE tool_switches (id TEXT PRIMARY KEY,work_id TEXT,active INTEGER,body BLOB,digest TEXT)")
                self.ledger.connection.execute("CREATE UNIQUE INDEX one_work_switch ON tool_switches(work_id) WHERE active=1")
                self.ledger.connection.execute("CREATE TABLE tool_switch_history (id TEXT,revision INTEGER,body BLOB,digest TEXT,PRIMARY KEY(id,revision))")
            metadata(self.ledger)
            for (key,) in self.ledger.connection.execute("SELECT id FROM tool_switches").fetchall():
                self.load(key)

    def load(self, key):
        self.ledger._check_lock()
        metadata(self.ledger)
        row = self.ledger.connection.execute("SELECT work_id,active,body,digest FROM tool_switches WHERE id=?", (identifier(key),)).fetchone()
        if row is None:
            return None
        body = strict_json(row[2])
        exact(body, {"schema", "id", "work_id", "root_id", "source_binding", "destination_binding", "source_native", "destination_native",
                     "source_claim_id", "source_fence", "owner_epoch", "deadline", "created_ms", "authority", "phase", "revision", "capsule", "last_failure"})
        if body["schema"] != SCHEMA or body["id"] != key or body["work_id"] != row[0] or body["phase"] not in PHASES or \
                row[1] != int(body["phase"] in {"checkpoint_pending", "checkpointed"}) or fingerprint(body) != row[3]:
            raise Denied("switch index/provenance changed")
        integer(body["revision"], 0)
        integer(body["source_fence"])
        integer(body["owner_epoch"], 0)
        integer(body["created_ms"], 0)
        _deadline(body["deadline"])
        for binding in (body["source_binding"], body["destination_binding"]):
            validate_binding(binding)
            if binding["root_task_id"] != body["root_id"]:
                raise Denied("switch binding cannot change root")
        count, maximum = self.ledger.connection.execute("SELECT COUNT(*),MAX(revision) FROM tool_switch_history WHERE id=?", (key,)).fetchone()
        latest = self.ledger.connection.execute("SELECT body,digest FROM tool_switch_history WHERE id=? AND revision=?", (key, body["revision"])).fetchone()
        if count != body["revision"] + 1 or maximum != body["revision"] or latest != (row[2], row[3]):
            raise Denied("switch history incomplete or changed")
        return body

    def _save(self, body):
        raw, digest = canonical_bytes(body), fingerprint(body)
        if len(raw) > 65536:
            raise Denied("switch capsule exceeds bound; use complete protected artifact references")
        self.ledger.connection.execute("INSERT OR REPLACE INTO tool_switches VALUES (?,?,?,?,?)", (body["id"], body["work_id"], int(body["phase"] in {"checkpoint_pending", "checkpointed"}), raw, digest))
        self.ledger.connection.execute("INSERT INTO tool_switch_history VALUES (?,?,?,?)", (body["id"], body["revision"], raw, digest))

    def _native(self, peer, session_id):
        binding = self.registry._controller(peer, identifier(session_id))
        row = self.registry._row(session_id)
        if row is None or row["binding"] != binding:
            raise Denied("exact retained native mapping required; no fresh conversation fallback")
        return binding, row["enrollment"]

    def _actions(self, root_id, switch_id):
        hasher = hashlib.sha256()
        for (key,) in self.ledger.connection.execute("SELECT id FROM intents WHERE root_id=? ORDER BY id", (root_id,)).fetchall():
            current = self.ledger.load(key)
            if current["context"].get("schema") == SCHEMA and current["context"].get("switch_id") == switch_id:
                continue  # Internal passive bug notices do not invalidate their own material.
            hasher.update(canonical_bytes({**current, "record": current["record"].to_dict()}) + b"\n")
        return "sha256:" + hasher.hexdigest()

    def _scope(self, peer, body):
        self.admission._check()
        work = self.ledger.work(body["work_id"])
        root = self.ledger.root(body["root_id"])
        self.ledger._controller(peer, root.fields["owner_role_id"])
        source, source_native = self._native(peer, body["source_binding"]["session_id"])
        destination, destination_native = self._native(peer, body["destination_binding"]["session_id"])
        if (source, destination, source_native, destination_native) != (body["source_binding"], body["destination_binding"], body["source_native"], body["destination_native"]) or \
                work["binding"] != source or work["state"] != "held" or (work["claim_id"], work["fencing_token"]) != (body["source_claim_id"], body["source_fence"]):
            raise Denied("original switch mappings/custody changed; no retarget or takeover")
        control = self.ledger.owner_control(root.id)
        if root.fields["state"] != "held" or not control["known"] or control["desired_state"] != "running" or control["epoch"] != body["owner_epoch"]:
            raise Denied("switch root/owner control is no longer current")
        target = self.registry._row(destination["session_id"])["record"].to_dict()
        return {"switch": body, "work": work, "root": root.to_dict(), "owner_control": control, "destination_observation": target,
                "actions_digest": self._actions(root.id, body["id"]), "model_leases": self.admission._attempts()}

    def _authority(self, scope, expected=None):
        proof = self.authorize(strict_json(canonical_bytes(scope)))
        if type(proof) is not SwitchAuthority or proof.scope_digest != fingerprint(scope):
            raise Denied("independent current switch authority required")
        _digest(proof.source_digest)
        identifier(proof.decision_id)
        if expected and (proof.source_digest, proof.decision_id) != (expected["source_digest"], expected["decision_id"]):
            raise Denied("original switch decision changed or was revoked")
        return asdict(proof)

    def request(self, peer, key, work_id, destination_session_id, *, expected_revision):
        key, work_id = identifier(key), identifier(work_id)
        work = self.ledger.work(work_id)
        root = self.ledger.root(work["root_task_id"])
        self.ledger._controller(peer, root.fields["owner_role_id"])
        prior = self.load(key)
        if prior:
            if (prior["work_id"], prior["destination_binding"]["session_id"]) != (work_id, destination_session_id):
                raise Denied("stable switch request cannot change its destination/work")
            return {"requested_now": False, "switch": prior}
        if work["state"] != "owned" or work["binding"] is None or work["revision"] != integer(expected_revision, 0) or active_work_switch(self.ledger, work_id):
            raise Denied("current owned work and no active switch required")
        self.ledger._runnable(root)
        source, source_native = self._native(peer, work["binding"]["session_id"])
        destination, destination_native = self._native(peer, destination_session_id)
        if source != work["binding"] or source["session_id"] == destination["session_id"] or \
                (source["role_id"], source["root_task_id"]) != (destination["role_id"], destination["root_task_id"]) or \
                source_native["worktree"] != destination_native["worktree"]:
            raise Denied("different exact sessions of the same root/role/worktree required")
        scope = {"id": key, "work": work, "root": root.to_dict(), "source_binding": source, "destination_binding": destination,
                 "source_native": source_native, "destination_native": destination_native, "owner_control": self.ledger.owner_control(root.id)}
        proof = self._authority(scope)
        with self.ledger._transaction():
            if self.ledger.work(work_id) != work or self.ledger.root(root.id) != root or self._native(peer, source["session_id"]) != (source, source_native) or \
                    self._native(peer, destination["session_id"]) != (destination, destination_native) or self.ledger.owner_control(root.id) != scope["owner_control"] or \
                    self._authority(scope) != proof:
                raise Denied("switch authority or material changed during request")
            now = self.ledger._clock()
            self.ledger._runnable(root)
            held = {**work, "state": "held", "revision": work["revision"] + 1}
            self.ledger._save_work(held, "switch_requested_writer_retained", {"switch_id": key})
            self.ledger._save_root(transition(root, "held", expected_revision=root.revision), "switch_requested_task_retained", {"switch_id": key})
            body = {"schema": SCHEMA, "id": key, "work_id": work_id, "root_id": root.id, "source_binding": source, "destination_binding": destination,
                    "source_native": source_native, "destination_native": destination_native, "source_claim_id": work["claim_id"], "source_fence": work["fencing_token"],
                    "owner_epoch": scope["owner_control"]["epoch"], "deadline": root.fields["limits"]["checkpoint_deadline"], "created_ms": now,
                    "authority": proof, "phase": "checkpoint_pending", "revision": 0, "capsule": None, "last_failure": None}
            self._save(body)
            self.ledger.checkpoint("before_switch_request_commit")
        self.ledger.checkpoint("after_switch_request_commit")
        return {"requested_now": True, "switch": body, "meaning": "custody_retained_not_native_stop"}

    def _checkpoint(self, scope, capsule):
        checked = {**scope, "proposed_capsule": capsule}
        proof = self.verify_checkpoint(strict_json(canonical_bytes(checked)))
        if type(proof) is not SwitchCheckpoint or proof.scope_digest != fingerprint(checked) or proof.capsule_digest != fingerprint(capsule) or proof.complete is not True:
            raise Denied("current complete protected file/semantic/action checkpoint required")
        _digest(proof.source_digest)
        return asdict(proof)

    def _loaded(self, scope, capsule):
        checked = {**scope, "capsule": capsule}
        proof = self.verify_loaded(strict_json(canonical_bytes(checked)))
        target = scope["switch"]["destination_native"]
        if type(proof) is not SwitchLoaded or proof.scope_digest != fingerprint(checked) or proof.capsule_digest != fingerprint(capsule) or \
                proof.native_session_id != target["provider_session_id"] or proof.active_turn_id is not None or proof.read_only_fenced is not True or \
                any(getattr(proof, key) != value for key, value in target["expected"].items()):
            raise Denied("independent exact destination context/contracts under a read-only fence required")
        _digest(proof.source_digest)
        return proof

    def attach(self, peer, key, *, snapshot, context):
        exact(snapshot, {"schema", "checkpoint_id", "checkpoint_digest", "spec_digest", "worktree"})
        if snapshot["schema"] != "ccrelay.worktree_checkpoint.v1":
            raise Denied("supported complete worktree checkpoint required")
        identifier(snapshot["checkpoint_id"])
        _digest(snapshot["checkpoint_digest"])
        _digest(snapshot["spec_digest"])
        exact(context, {"task_context", "operations", "publications", "approvals", "pending_inputs"})
        body = self.load(key)
        if body is None or body["phase"] not in {"checkpoint_pending", "checkpointed"} or snapshot["worktree"] != body["source_native"]["worktree"]:
            raise Denied("current pending switch on its original worktree required")
        scope = self._scope(peer, body)
        self._authority(scope, body["authority"])
        capsule = strict_json(canonical_bytes({"snapshot": snapshot, "context": context, "actions_digest": scope["actions_digest"]}))
        proof = self._checkpoint(scope, capsule)
        with self.ledger._transaction():
            if self.load(key) != body or self._scope(peer, body) != scope or self._authority(scope, body["authority"])["source_digest"] != body["authority"]["source_digest"]:
                raise Denied("switch source/control/actions changed during checkpoint verification")
            if _deadline(body["deadline"]) <= self.ledger._clock():
                raise Denied("switch deadline exhausted; original task retained")
            updated = {**body, "phase": "checkpointed", "revision": body["revision"] + 1, "capsule": {"data": capsule, "proof": proof}, "last_failure": None}
            self._save(updated)
            self.ledger.checkpoint("before_switch_checkpoint_commit")
        self.ledger.checkpoint("after_switch_checkpoint_commit")
        return {"state": "checkpointed", "meaning": "no_destination_execution_or_writer_transfer"}

    def finish(self, peer, key):
        body = self.load(key)
        if body is None:
            raise Denied("unknown switch")
        self.ledger._controller(peer, body["source_binding"]["role_id"])
        if body["phase"] == "completed":
            return {"transferred_now": False, "meaning": "no_execution_grant"}
        if body["phase"] != "checkpointed":
            raise Denied("complete verified checkpoint required")
        scope = self._scope(peer, body)
        authority = self._authority(scope, body["authority"])
        capsule = body["capsule"]["data"]
        if scope["actions_digest"] != capsule["actions_digest"]:
            raise Denied("pending actions/outcomes changed; checkpoint must be revalidated")
        proof = self._checkpoint(scope, capsule)
        if proof["source_digest"] != body["capsule"]["proof"]["source_digest"]:
            raise Denied("checkpoint bytes/semantics changed after attachment")
        with self.writer_guard(strict_json(canonical_bytes(scope))) as fence:
            if type(fence) is not SwitchFence or fence.scope_digest != fingerprint(scope) or fence.all_old_writers_stopped is not True or fence.destination_read_only is not True:
                raise Denied("held old-writer/descendant and destination launch fences required")
            _digest(fence.source_digest)
            loaded = self._loaded(scope, capsule)
            with self.ledger._transaction():
                if self.load(key) != body or self._scope(peer, body) != scope or self._authority(scope, body["authority"]) != authority:
                    raise Denied("switch authority, control, actions or leases changed during destination loading")
                final_proof = self._checkpoint(scope, capsule)
                # The checkpoint reader may take time or expose newer loading
                # evidence. Reread loading as well, while BOTH launch/writer
                # fences remain held; cached readiness is never this proof.
                final_loaded = self._loaded(scope, capsule)
                if final_proof != proof or final_loaded != loaded or self._authority(scope, body["authority"]) != authority or self._scope(peer, body) != scope:
                    raise Denied("checkpoint, loaded context or authority changed before writer transfer")
                if any(row["leased"] and row["session_id"] in {body["source_binding"]["session_id"], body["destination_binding"]["session_id"]} for row in self.admission._attempts()):
                    raise Denied("retained model/tool activity must have independent stop evidence before transfer")
                if _deadline(body["deadline"]) <= self.ledger._clock():
                    raise Denied("switch deadline exhausted before transfer")
                token = self.ledger.connection.execute("SELECT next_fence FROM work_metadata").fetchone()[0]
                self.ledger.connection.execute("UPDATE work_metadata SET next_fence=?", (token + 1,))
                work = {**scope["work"], "state": "owned", "revision": scope["work"]["revision"] + 1, "binding": body["destination_binding"],
                        "fencing_token": token, "claim_id": "switch-" + fingerprint({"switch_id": key})[7:]}
                self.ledger._save_work(work, "switch_writer_custody_transferred", {"switch_id": key, "checkpoint": final_proof, "loaded": asdict(loaded), "fence": asdict(fence)})
                self._save({**body, "phase": "completed", "revision": body["revision"] + 1})
                self.ledger.checkpoint("before_switch_transfer_commit")
            self.ledger.checkpoint("after_switch_transfer_commit")
        return {"transferred_now": True, "work": work, "meaning": "custody_only_root_held_no_model_or_external_action"}

    def cancel(self, peer, key):
        body = self.load(key)
        if body is None:
            raise Denied("unknown switch")
        self.ledger._controller(peer, body["source_binding"]["role_id"])
        if body["phase"] == "completed":
            raise Denied("completed custody cannot be undone by cancellation")
        if body["phase"] != "cancelled":
            with self.ledger._transaction():
                self._save({**body, "phase": "cancelled", "revision": body["revision"] + 1})
        return {"state": "cancelled", "meaning": "original_custody_retained_no_native_resume_or_root_reset"}

    def report_failure(self, peer, key, reason):
        if reason not in {"checkpoint_incomplete", "checkpoint_stale", "destination_unverified", "writer_fence_unavailable", "deadline_exhausted"}:
            raise Denied("masked supported switch failure reason required")
        body = self.load(key)
        if body is None:
            raise Denied("unknown switch")
        scope = self._scope(peer, body)
        material = {"switch_id": key, "reason": reason, "capsule": body["capsule"], "actions_digest": scope["actions_digest"], "owner_epoch": body["owner_epoch"]}
        action_id = "switch-bug-" + fingerprint(material)[7:]
        fields = {"id": action_id, "root_task_id": body["root_id"], "requested_by_session_id": body["source_binding"]["session_id"],
                  "action_kind": "report_issue", "parameters": {"switch_id": key, "reason": reason, "material_digest": fingerprint(material), "destination": "protected_owner_issues"}}
        action = create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                        attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
        with self.ledger._transaction():
            if self.load(key) != body or self._scope(peer, body) != scope:
                raise Denied("switch failure material changed")
            self.ledger._enroll(action, {"schema": SCHEMA, "switch_id": key, "binding": body["source_binding"], "meaning": "passive_bug_not_support_execution_or_approval"})
            if body["last_failure"] != action_id:
                self._save({**body, "revision": body["revision"] + 1, "last_failure": action_id})
        return {"intent_id": action_id, "meaning": "stored_not_delivered_no_repair_grant"}
