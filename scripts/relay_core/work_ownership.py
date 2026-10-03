"""Protected root budgets and durable work/resource custody, not turn admission.

No model, worker RPC, launch, kill, timer expiry or automatic lease stealing.
Mandatory protected evidence/quiescence verifiers must inspect actual artifacts
and all writers; typed claims alone do not establish their provenance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import sqlite3

from .contracts import canonical_bytes, create, decode, fingerprint, transition
from .identity import Denied, Peer, exact, identifier, integer, strict_json, validate_binding
from .outbox import DeliveryLedger


SCHEMA = "ccrelay.work_ownership.v1"
WATCHDOG_HANDOFFS = 3  # Pouya's approved no-progress watchdog, not a message hop count.


@dataclass(frozen=True)
class ProgressReceipt:
    evidence_id: str
    scope_digest: str
    result_digest: str
    acceptance_complete: bool


@dataclass(frozen=True)
class QuiescenceReceipt:
    proof_id: str
    scope_digest: str
    source_digest: str


@dataclass(frozen=True)
class HandoffReceipt:
    evidence_id: str
    scope_digest: str
    result_digest: str
    completed: bool
    progress_evidence_id: str | None


def _digest(value):
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:") or any(c not in "0123456789abcdef" for c in value[7:]):
        raise Denied("exact evidence digest required")
    return value


def _deadline(value):
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    delta = parsed - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


class WorkOwnership(DeliveryLedger):
    def __init__(self, directory, *, owner_uid, authority, now_ms, verify_progress, verify_quiescence, verify_handoff, checkpoint=lambda _: None):
        if not all(callable(value) for value in (now_ms, verify_progress, verify_quiescence, verify_handoff)):
            raise Denied("protected clock, evidence and all-writer quiescence verifiers required")
        self.authority, self.now_ms = authority, now_ms
        self.verify_progress, self.verify_quiescence = verify_progress, verify_quiescence
        self.verify_handoff = verify_handoff
        super().__init__(directory, owner_uid=owner_uid, policy_digest=authority.policy.digest, checkpoint=checkpoint)

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE work_metadata (schema TEXT NOT NULL,next_fence INTEGER NOT NULL,last_wall_ms INTEGER NOT NULL)")
        self.connection.execute("INSERT INTO work_metadata VALUES (?,1,0)", (SCHEMA,))
        self.connection.execute("CREATE TABLE roots (id TEXT PRIMARY KEY,watchdog_threshold INTEGER NOT NULL,body BLOB NOT NULL,digest TEXT NOT NULL)")
        self.connection.execute("""CREATE TABLE work_items (id TEXT PRIMARY KEY,resource TEXT NOT NULL,
            leased INTEGER NOT NULL,body BLOB NOT NULL,digest TEXT NOT NULL)""")
        self.connection.execute("CREATE UNIQUE INDEX exclusive_resource ON work_items(resource) WHERE leased=1")
        self.connection.execute("CREATE TABLE work_history (kind TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,body BLOB NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(kind,id,revision))")
        self.connection.execute("CREATE TABLE root_charges (id TEXT PRIMARY KEY,body BLOB NOT NULL,digest TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE handoff_assessments (charge_id TEXT PRIMARY KEY,body BLOB NOT NULL,digest TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE root_results (root_id TEXT NOT NULL,evidence_id TEXT NOT NULL,result_digest TEXT NOT NULL,PRIMARY KEY(root_id,evidence_id),UNIQUE(root_id,result_digest))")

    def _validate_component(self):
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_metadata'").fetchone():
            from .model_admission import SCHEMA as ADMISSION_SCHEMA
            admission = self.connection.execute("SELECT schema,policy_digest FROM model_metadata").fetchall()
            if len(admission) != 1 or admission[0][0] != ADMISSION_SCHEMA:
                raise Denied("unsupported joined admission schema; preserve database before root recovery")
            _digest(admission[0][1])
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capacity_metadata'").fetchone():
            from .capacity_journal import SCHEMA as CAPACITY_SCHEMA
            capacity = self.connection.execute("SELECT schema,policy_digest FROM capacity_metadata").fetchall()
            if len(capacity) != 1 or capacity[0][0] != CAPACITY_SCHEMA:
                raise Denied("unsupported joined capacity schema; preserve database before recovery")
            _digest(capacity[0][1])
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_dispatch_metadata'").fetchone():
            from .model_dispatch import metadata
            metadata(self)
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quota_estimate_metadata'").fetchone():
            from .quota_estimates import metadata
            metadata(self)
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_switch_metadata'").fetchone():
            from .tool_switches import metadata
            metadata(self)
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_metadata'").fetchone():
            from .publications import metadata
            metadata(self)
        metadata = self.connection.execute("SELECT schema,next_fence,last_wall_ms FROM work_metadata").fetchall()
        if len(metadata) != 1 or metadata[0][0] != SCHEMA:
            raise Denied("unsupported work ownership schema; preserve for migration")
        integer(metadata[0][1])
        integer(metadata[0][2], 0)
        self.connection.execute("SELECT id,body,digest FROM root_charges LIMIT 0")
        self.connection.execute("SELECT charge_id,body,digest FROM handoff_assessments LIMIT 0")
        self.connection.execute("SELECT root_id,evidence_id,result_digest FROM root_results LIMIT 0")
        for (root_id,) in self.connection.execute("SELECT id FROM roots").fetchall():
            self.root(root_id)
            self.threshold(root_id)
        for (work_id,) in self.connection.execute("SELECT id FROM work_items").fetchall():
            work = self.work(work_id)
            self.root(work["root_task_id"])
            if work["fencing_token"] is not None and work["fencing_token"] >= metadata[0][1]:
                raise Denied("resource fencing allocator regressed")
        results = {}
        for kind, record_id, revision, body, digest in self.connection.execute("SELECT kind,id,revision,body,digest FROM work_history"):
            event = strict_json(body)
            exact(event, {"schema", "record", "reason", "proof"})
            if kind not in {"root", "work"} or event["schema"] != "ccrelay.work_event.v1" or fingerprint(event) != digest or \
                    (event["record"]["id"], event["record"]["revision"]) != (record_id, revision):
                raise Denied("historical work/root evidence differs")
            proof = event["proof"] if event["reason"] == "verified_root_progress" else \
                event["proof"]["progress"] if event["reason"] == "completed_handoff_assessed" else None
            if proof:
                results[(record_id, proof["evidence_id"])] = proof["result_digest"]
        stored = {(root_id, evidence_id): digest for root_id, evidence_id, digest in self.connection.execute("SELECT root_id,evidence_id,result_digest FROM root_results")}
        if stored != results:
            raise Denied("accepted progress result index differs from immutable history")

    def _clock(self):
        value = integer(self.now_ms(), 0)
        prior = self.connection.execute("SELECT last_wall_ms FROM work_metadata").fetchone()[0]
        if value < prior:
            raise Denied("protected clock regressed; no deadline extension")
        self.connection.execute("UPDATE work_metadata SET last_wall_ms=?", (value,))
        return value

    def _controller(self, peer, role_id):
        role = self.authority.policy.roles.get(role_id)
        if type(peer) is not Peer or self.authority.policy.digest != self.policy_digest or role is None or \
                not role.fields["enabled"] or role_id not in self.authority.policy.controllers.get(peer.uid, frozenset()):
            raise Denied("current kernel-authenticated role controller required")

    def _actor(self, peer):
        actor = self.authority.actor(peer)
        if actor.policy_digest != self.policy_digest:
            raise Denied("work binding policy changed")
        return actor, validate_binding(self.authority.registry.session(actor.session_id))

    def _history(self, kind, value, reason, proof=None):
        event = {"schema": "ccrelay.work_event.v1", "record": value, "reason": reason, "proof": proof}
        self.connection.execute("INSERT INTO work_history VALUES (?,?,?,?,?)", (kind, value["id"], value["revision"], canonical_bytes(event), fingerprint(event)))
        self.checkpoint("before_work_state_commit")

    def _check_history(self, kind, value):
        revision = value["revision"]
        row = self.connection.execute("SELECT body,digest FROM work_history WHERE kind=? AND id=? AND revision=?", (kind, value["id"], revision)).fetchone()
        count, maximum = self.connection.execute("SELECT COUNT(*),MAX(revision) FROM work_history WHERE kind=? AND id=?", (kind, value["id"])).fetchone()
        if row is None or count != revision + 1 or maximum != revision:
            raise Denied("work/root history incomplete")
        event = strict_json(row[0])
        exact(event, {"schema", "record", "reason", "proof"})
        if event["schema"] != "ccrelay.work_event.v1" or event["record"] != value or fingerprint(event) != row[1]:
            raise Denied("work/root state and history disagree")

    def root(self, root_id):
        self._check_lock()
        row = self.connection.execute("SELECT body,digest FROM roots WHERE id=?", (identifier(root_id),)).fetchone()
        if row is None:
            raise Denied("root task not enrolled")
        record = decode(row[0])
        if record.kind != "root_task" or record.id != root_id or record.fields["policy_digest"] != self.policy_digest or fingerprint(record.to_dict()) != row[1]:
            raise Denied("root task state differs")
        self._check_history("root", record.to_dict())
        return record

    def threshold(self, root_id):
        self._check_lock()
        row = self.connection.execute("SELECT watchdog_threshold FROM roots WHERE id=?", (identifier(root_id),)).fetchone()
        if row is None:
            raise Denied("root watchdog policy not enrolled")
        threshold = integer(row[0])
        event = self.connection.execute("SELECT body,digest FROM work_history WHERE kind='root' AND id=? AND revision=0", (root_id,)).fetchone()
        original = strict_json(event[0])
        proof = original["proof"]
        if fingerprint(original) != event[1] or proof not in ({"watchdog_handoffs": threshold},
                {"watchdog_handoffs": threshold, "owner_desired_state": "running"}):
            raise Denied("root watchdog policy differs from enrollment")
        return threshold

    def owner_control(self, root_id):
        """Desired owner control, distinct from a watchdog/recovery hold.

Old history without explicit intent is unknown, not permission for diagnosis.
"""
        self.root(root_id)
        control = {"known": False, "desired_state": "unknown", "epoch": 0}
        for revision, body, digest in self.connection.execute("SELECT revision,body,digest FROM work_history WHERE kind='root' AND id=? ORDER BY revision", (root_id,)):
            event = strict_json(body)
            if fingerprint(event) != digest:
                raise Denied("root owner-control history differs")
            proof = event["proof"]
            if revision == 0 and type(proof) is dict and proof.get("owner_desired_state") == "running":
                control = {"known": True, "desired_state": "running", "epoch": 0}
            elif event["reason"] == "root_control_requested":
                if type(proof) is dict and proof.get("schema") == "ccrelay.root_owner_control.v1" and proof.get("desired_state") in {"running", "paused", "stopped"}:
                    exact(proof, {"schema", "desired_state", "acceptance"})
                    control = {"known": True, "desired_state": proof["desired_state"], "epoch": revision}
                else:
                    control = {"known": False, "desired_state": "unknown", "epoch": revision}
        return control

    def _save_root(self, record, reason, proof=None, *, initial=False):
        value = record.to_dict()
        if initial:
            self.connection.execute("INSERT INTO roots VALUES (?,?,?,?)", (record.id, proof["watchdog_handoffs"], record.encode(), fingerprint(value)))
        else:
            self.connection.execute("UPDATE roots SET body=?,digest=? WHERE id=?", (record.encode(), fingerprint(value), record.id))
        self._history("root", value, reason, proof)

    def enroll_root(self, peer, record, *, watchdog_handoffs=WATCHDOG_HANDOFFS):
        if record.kind != "root_task" or record.revision != 0 or record.fields["state"] != "open" or \
                record.fields["policy_digest"] != self.policy_digest or any(record.fields["usage"].values()) or record.fields["verified_evidence_ids"]:
            raise Denied("new explicitly budgeted root required; no imported counters")
        self._controller(peer, record.fields["owner_role_id"])
        integer(watchdog_handoffs)
        with self._transaction():
            if self.connection.execute("SELECT 1 FROM roots WHERE id=?", (record.id,)).fetchone():
                current = self.root(record.id)
                original = strict_json(self.connection.execute("SELECT body FROM work_history WHERE kind='root' AND id=? AND revision=0", (record.id,)).fetchone()[0])["record"]
                if original != record.to_dict() or self.threshold(record.id) != watchdog_handoffs:
                    raise Denied("root ID cannot reset budgets or criteria")
                return current
            if _deadline(record.fields["limits"]["checkpoint_deadline"]) <= self._clock():
                raise Denied("new root deadline already expired")
            self._save_root(record, "root_enrolled", {"watchdog_handoffs": watchdog_handoffs, "owner_desired_state": "running"}, initial=True)
        self.checkpoint("after_root_enrollment_commit")
        return record

    def _runnable(self, root):
        if root.fields["state"] not in {"open", "active"} or _deadline(root.fields["limits"]["checkpoint_deadline"]) <= self._clock() or \
                root.fields["usage"]["no_progress_handoffs"] >= self.threshold(root.id):
            raise Denied("root held, terminal, expired or awaiting verified progress")

    def charge(self, peer, operation_id, kind, *, expected_revision):
        actor, binding = self._actor(peer)
        if kind not in {"turn", "diagnosis", "handoff"}:
            raise Denied("explicit root charge kind required")
        key = "charge-" + fingerprint({"root": actor.root_task_id, "session": actor.session_id, "operation": identifier(operation_id)})[7:]
        scope = {"id": key, "binding": binding, "kind": kind}
        with self._transaction():
            root = self.root(actor.root_task_id)
            prior = self.connection.execute("SELECT body,digest FROM root_charges WHERE id=?", (key,)).fetchone()
            if prior:
                receipt = strict_json(prior[0])
                if fingerprint(receipt) != prior[1] or receipt["scope"] != scope:
                    raise Denied("root charge ID reused with changed context")
                return {"record": root, "charged_now": False, "receipt": receipt}
            if root.revision != integer(expected_revision, 0):
                raise Denied("root charge revision changed")
            self._runnable(root)
            usage = dict(root.fields["usage"])
            # Preserve the preallocated diagnostic subset of the total budget.
            if kind == "turn" and usage["turns"] + root.fields["limits"]["diagnoses"] - usage["diagnoses"] >= root.fields["limits"]["turns"]:
                raise Denied("ordinary turn would consume the root diagnostic reserve")
            counters = ("turns", "diagnoses") if kind == "diagnosis" else ("turns",) if kind == "turn" else ("delegations",)
            for counter in counters:
                if usage[counter] >= root.fields["limits"][counter]:
                    raise Denied("root budget exhausted")
                usage[counter] += 1
            # Charging a delegation is not its completed/assessed result.
            updated = transition(root, "active", expected_revision=root.revision, usage=usage)
            if self._actor(peer)[1] != binding:
                raise Denied("root charge binding changed")
            receipt = {"schema": "ccrelay.root_charge.v1", "scope": scope, "root_revision": updated.revision, "usage": usage}
            self.connection.execute("INSERT INTO root_charges VALUES (?,?,?)", (key, canonical_bytes(receipt), fingerprint(receipt)))
            self._save_root(updated, "root_budget_charged", receipt)
        self.checkpoint("after_root_charge_commit")
        return {"record": updated, "charged_now": True, "receipt": receipt}

    def _progress(self, scope, evidence_id):
        receipt = self.verify_progress(strict_json(canonical_bytes(scope)), identifier(evidence_id))
        if type(receipt) is not ProgressReceipt or receipt.evidence_id != evidence_id or receipt.scope_digest != fingerprint(scope) or type(receipt.acceptance_complete) is not bool:
            raise Denied("independently verified evidence for this exact scope required")
        _digest(receipt.result_digest)
        return asdict(receipt)

    def _new_result(self, root_id, proof):
        if self.connection.execute("SELECT 1 FROM root_results WHERE root_id=? AND (evidence_id=? OR result_digest=?)",
                                   (root_id, proof["evidence_id"], proof["result_digest"])).fetchone():
            raise Denied("repeated result or renamed evidence is not new progress")
        self.connection.execute("INSERT INTO root_results VALUES (?,?,?)", (root_id, proof["evidence_id"], proof["result_digest"]))

    def progress(self, peer, root_id, evidence_id, *, expected_revision):
        root = self.root(root_id)
        self._controller(peer, root.fields["owner_role_id"])
        if root.revision != integer(expected_revision, 0) or root.fields["state"] in {"completed", "cancelled"} or evidence_id in root.fields["verified_evidence_ids"]:
            raise Denied("new evidence and current nonterminal root required")
        proof = self._progress(root.to_dict(), evidence_id)
        with self._transaction():
            if self.root(root_id) != root:
                raise Denied("root changed during evidence verification")
            self._controller(peer, root.fields["owner_role_id"])
            self._new_result(root_id, proof)
            usage = dict(root.fields["usage"], no_progress_handoffs=0)
            updated = transition(root, root.fields["state"], expected_revision=root.revision, usage=usage,
                                 verified_evidence_ids=list(root.fields["verified_evidence_ids"]) + [evidence_id])
            self._save_root(updated, "verified_root_progress", proof)
        self.checkpoint("after_root_progress_commit")
        return updated

    def assess_handoff(self, peer, root_id, charge_id, evidence_id, *, expected_revision):
        root = self.root(root_id)
        self._controller(peer, root.fields["owner_role_id"])
        prior = self.connection.execute("SELECT body,digest FROM handoff_assessments WHERE charge_id=?", (identifier(charge_id),)).fetchone()
        if prior:
            assessment = strict_json(prior[0])
            if fingerprint(assessment) != prior[1] or assessment["root_id"] != root_id or assessment["proof"]["evidence_id"] != evidence_id:
                raise Denied("assessed delegation cannot change identity")
            return {"record": root, "assessed_now": False}
        if root.revision != integer(expected_revision, 0) or root.fields["state"] not in {"open", "active", "held"}:
            raise Denied("current nonterminal root assessment required")
        row = self.connection.execute("SELECT body,digest FROM root_charges WHERE id=?", (charge_id,)).fetchone()
        if row is None:
            raise Denied("delegation budget charge not found")
        charge = strict_json(row[0])
        if fingerprint(charge) != row[1] or charge["scope"]["kind"] != "handoff" or charge["scope"]["binding"]["root_task_id"] != root_id:
            raise Denied("assessment differs from this root delegation")
        scope = {"root": root.to_dict(), "delegation": charge}
        receipt = self.verify_handoff(strict_json(canonical_bytes(scope)), identifier(evidence_id))
        if type(receipt) is not HandoffReceipt or receipt.evidence_id != evidence_id or receipt.scope_digest != fingerprint(scope) or receipt.completed is not True:
            raise Denied("completed assessed delegation required; waits/ACKs are not results")
        _digest(receipt.result_digest)
        progress = None
        if receipt.progress_evidence_id is not None:
            identifier(receipt.progress_evidence_id)
            if receipt.progress_evidence_id not in root.fields["verified_evidence_ids"]:
                progress = self._progress(root.to_dict(), receipt.progress_evidence_id)
        with self._transaction():
            if self.root(root_id) != root or self.connection.execute("SELECT 1 FROM handoff_assessments WHERE charge_id=?", (charge_id,)).fetchone():
                raise Denied("delegation/root changed during assessment")
            self._controller(peer, root.fields["owner_role_id"])
            usage = dict(root.fields["usage"])
            evidence = list(root.fields["verified_evidence_ids"])
            if progress and self.connection.execute("SELECT 1 FROM root_results WHERE root_id=? AND (evidence_id=? OR result_digest=?)",
                                                     (root_id, progress["evidence_id"], progress["result_digest"])).fetchone():
                progress = None  # Completed result counts, duplicated progress does not.
            if progress:
                self._new_result(root_id, progress)
                usage["no_progress_handoffs"] = 0
                evidence.append(progress["evidence_id"])
            else:
                usage["no_progress_handoffs"] += 1
            target = "held" if root.fields["state"] == "held" or usage["no_progress_handoffs"] >= self.threshold(root_id) else "active"
            updated = transition(root, target, expected_revision=root.revision, usage=usage, verified_evidence_ids=evidence)
            assessment = {"schema": "ccrelay.handoff_assessment.v1", "root_id": root_id, "charge_id": charge_id, "proof": asdict(receipt), "progress": progress}
            self.connection.execute("INSERT INTO handoff_assessments VALUES (?,?,?)", (charge_id, canonical_bytes(assessment), fingerprint(assessment)))
            self._save_root(updated, "completed_handoff_assessed", assessment)
        self.checkpoint("after_handoff_assessment_commit")
        return {"record": updated, "assessed_now": True}

    def control_root(self, peer, root_id, state, *, expected_revision, evidence_id=None):
        with self._transaction():
            root = self.root(root_id)
            self._controller(peer, root.fields["owner_role_id"])
            proof = None
            if state == "active":
                candidate = transition(root, state, expected_revision=expected_revision)
                self._runnable(candidate)
            if state == "completed":
                proof = self._progress(root.to_dict(), evidence_id)
                if not proof["acceptance_complete"]:
                    raise Denied("root acceptance criteria not established")
            updated = transition(root, state, expected_revision=expected_revision,
                                 **({"verified_evidence_ids": list(root.fields["verified_evidence_ids"]) + [evidence_id]} if proof and evidence_id not in root.fields["verified_evidence_ids"] else {}))
            self._controller(peer, root.fields["owner_role_id"])
            if self.root(root_id) != root:
                raise Denied("root control changed during verification")
            desired = "running" if state == "active" else "paused" if state == "held" else "stopped"
            control = self.owner_control(root_id)
            if updated == root and (not control["known"] or control["desired_state"] != desired):
                updated = decode(dict(root.to_dict(), revision=root.revision + 1))
            if updated != root:
                self._save_root(updated, "root_control_requested", {"schema": "ccrelay.root_owner_control.v1", "desired_state": desired, "acceptance": proof})
        return updated  # Neither terminal state nor owner pause releases writers.

    def set_owner_control(self, peer, root_id, desired_state, *, expected_revision):
        """Owner intent may resume bounded diagnosis without removing a task hold."""
        if desired_state not in {"running", "paused", "stopped"}:
            raise Denied("explicit root owner intent required")
        with self._transaction():
            root = self.root(root_id)
            self._controller(peer, root.fields["owner_role_id"])
            if root.revision != integer(expected_revision, 0) or root.fields["state"] in {"completed", "cancelled"}:
                raise Denied("current nonterminal root control required")
            control = self.owner_control(root_id)
            if control["known"] and control["desired_state"] == desired_state:
                return root
            target = root.fields["state"] if desired_state == "running" else "held" if desired_state == "paused" else "cancelled"
            updated = transition(root, target, expected_revision=root.revision)
            if updated == root:
                updated = decode(dict(root.to_dict(), revision=root.revision + 1))
            self._save_root(updated, "root_control_requested", {"schema": "ccrelay.root_owner_control.v1", "desired_state": desired_state, "acceptance": None})
        return updated

    def work(self, work_id):
        self._check_lock()
        row = self.connection.execute("SELECT resource,leased,body,digest FROM work_items WHERE id=?", (identifier(work_id),)).fetchone()
        if row is None:
            raise Denied("work item not enrolled")
        value = strict_json(row[2])
        exact(value, {"schema", "id", "root_task_id", "criteria", "dependencies", "assignee_role_id", "resource_id", "state", "revision", "binding", "claim_id", "fencing_token"})
        if value["schema"] != "ccrelay.work_item.v1" or value["id"] != work_id or fingerprint(value) != row[3] or \
                (value["resource_id"], int(value["binding"] is not None)) != row[:2] or value["state"] not in {"ready", "owned", "held", "completed", "cancelled"}:
            raise Denied("work item/index differs")
        for key in ("root_task_id", "assignee_role_id", "resource_id"):
            identifier(value[key])
        integer(value["revision"], 0)
        if type(value["criteria"]) is not list or not value["criteria"] or any(type(item) is not str or not item.strip() for item in value["criteria"]) or \
                len(value["criteria"]) != len(set(value["criteria"])) or type(value["dependencies"]) is not list:
            raise Denied("work criteria/dependencies differ")
        for dependency in value["dependencies"]:
            identifier(dependency)
        if len(value["dependencies"]) != len(set(value["dependencies"])):
            raise Denied("duplicate work dependencies")
        if value["claim_id"] is not None:
            identifier(value["claim_id"])
        if value["fencing_token"] is not None:
            integer(value["fencing_token"])
        if value["binding"] is not None:
            binding = validate_binding(value["binding"])
            if binding["root_task_id"] != value["root_task_id"] or binding["role_id"] != value["assignee_role_id"] or binding["policy_digest"] != self.policy_digest:
                raise Denied("work binding scope differs")
            identifier(value["claim_id"])
            integer(value["fencing_token"])
        elif value["state"] in {"owned", "held"}:
            raise Denied("owned work lost its writer custody")
        self._check_history("work", value)
        return value

    def _save_work(self, value, reason, proof=None, *, initial=False):
        values = (value["resource_id"], int(value["binding"] is not None), canonical_bytes(value), fingerprint(value))
        if initial:
            self.connection.execute("INSERT INTO work_items VALUES (?,?,?,?,?)", (value["id"], *values))
        else:
            self.connection.execute("UPDATE work_items SET resource=?,leased=?,body=?,digest=? WHERE id=?", (*values, value["id"]))
        self._history("work", value, reason, proof)

    def enroll_work(self, peer, *, work_id, root_id, criteria, dependencies, assignee_role_id, resource_id):
        root = self.root(root_id)
        self._controller(peer, root.fields["owner_role_id"])
        self._controller(peer, assignee_role_id)
        if type(criteria) is not list or not criteria or any(type(item) is not str or not item.strip() for item in criteria) or len(criteria) != len(set(criteria)) or \
                type(dependencies) is not list or len(dependencies) != len(set(dependencies)):
            raise Denied("explicit unique criteria/dependencies required")
        value = {"schema": "ccrelay.work_item.v1", "id": identifier(work_id), "root_task_id": identifier(root_id), "criteria": criteria,
                 "dependencies": dependencies, "assignee_role_id": identifier(assignee_role_id), "resource_id": identifier(resource_id),
                 "state": "ready", "revision": 0, "binding": None, "claim_id": None, "fencing_token": None}
        with self._transaction():
            if self.connection.execute("SELECT 1 FROM work_items WHERE id=?", (work_id,)).fetchone():
                old = self.work(work_id)
                if any(old[key] != value[key] for key in ("root_task_id", "criteria", "dependencies", "assignee_role_id", "resource_id")):
                    raise Denied("work specification cannot be rewritten")
                return old
            self._runnable(root)
            for dependency in dependencies:
                if dependency == work_id or self.work(identifier(dependency))["root_task_id"] != root_id:
                    raise Denied("dependency must be an earlier work item in this root")
            self._save_work(value, "work_enrolled", initial=True)
        return value

    def checkout(self, peer, work_id, claim_id, *, expected_revision):
        actor, binding = self._actor(peer)
        identifier(claim_id)
        try:
            with self._transaction():
                work = self.work(work_id)
                if work["root_task_id"] != actor.root_task_id or work["assignee_role_id"] != actor.role_id:
                    raise Denied("work is not assigned to this admitted root/role")
                if work["binding"] == binding and work["claim_id"] == claim_id:
                    return {"work": work, "claimed_now": False}  # No new execution permission.
                if work["state"] != "ready" or work["binding"] is not None or work["revision"] != integer(expected_revision, 0) or work["claim_id"] == claim_id:
                    raise Denied("work already owned, terminal or changed")
                self._runnable(self.root(actor.root_task_id))
                if any(self.work(dependency)["state"] != "completed" for dependency in work["dependencies"]):
                    raise Denied("work dependency not verified complete")
                token = self.connection.execute("SELECT next_fence FROM work_metadata").fetchone()[0]
                self.connection.execute("UPDATE work_metadata SET next_fence=?", (token + 1,))
                updated = {**work, "state": "owned", "revision": work["revision"] + 1, "binding": binding, "claim_id": claim_id, "fencing_token": token}
                if self._actor(peer)[1] != binding:
                    raise Denied("work claimant binding changed")
                self._save_work(updated, "work_claimed")
        except sqlite3.IntegrityError as error:
            raise Denied("resource remains exclusively owned by another work item") from error
        self.checkpoint("after_work_claim_commit")
        return {"work": updated, "claimed_now": True}  # Custody, NOT a model/tool activity slot.

    def validate_fence(self, peer, work_id, fencing_token):
        actor, binding = self._actor(peer)
        work = self.work(work_id)
        if work["binding"] != binding or work["root_task_id"] != actor.root_task_id or work["state"] != "owned" or work["fencing_token"] != integer(fencing_token):
            raise Denied("work/resource fencing token no longer current")
        return work

    def finish_work(self, peer, work_id, evidence_id, *, expected_revision):
        work = self.work(work_id)
        root = self.root(work["root_task_id"])
        self._controller(peer, root.fields["owner_role_id"])
        if work["state"] not in {"owned", "held"} or work["revision"] != integer(expected_revision, 0):
            raise Denied("current owned work required")
        proof = self._progress(work, evidence_id)
        if not proof["acceptance_complete"]:
            raise Denied("work acceptance criteria not established")
        with self._transaction():
            if self.work(work_id) != work:
                raise Denied("work changed during completion verification")
            self._controller(peer, root.fields["owner_role_id"])
            updated = {**work, "state": "completed", "revision": work["revision"] + 1}
            self._save_work(updated, "work_acceptance_verified", proof)
        return updated  # Writer/resource custody deliberately remains held.

    def release(self, peer, work_id, *, expected_revision):
        from .tool_switches import active_work_switch
        if active_work_switch(self, work_id):
            raise Denied("pending tool switch retains writer custody; cancel or complete its verified transfer first")
        work = self.work(work_id)
        root = self.root(work["root_task_id"])
        self._controller(peer, root.fields["owner_role_id"])
        if work["binding"] is None or work["revision"] != integer(expected_revision, 0):
            raise Denied("current writer custody required")
        receipt = self.verify_quiescence(strict_json(canonical_bytes(work)))
        if type(receipt) is not QuiescenceReceipt or receipt.scope_digest != fingerprint(work):
            raise Denied("independent all-writer/descendant quiescence proof required")
        identifier(receipt.proof_id)
        _digest(receipt.source_digest)
        with self._transaction():
            if self.work(work_id) != work:
                raise Denied("work changed during writer verification")
            self._controller(peer, root.fields["owner_role_id"])
            updated = {**work, "state": "ready" if work["state"] in {"owned", "held"} else work["state"],
                       "revision": work["revision"] + 1, "binding": None}
            self._save_work(updated, "writer_custody_released", asdict(receipt))
        self.checkpoint("after_work_release_commit")
        return updated

    def recover_inflight(self):
        super().recover_inflight()
        with self._transaction():
            for (root_id,) in self.connection.execute("SELECT id FROM roots").fetchall():
                root = self.root(root_id)
                has_writer = any(self.work(work_id)["root_task_id"] == root_id for (work_id,) in
                                 self.connection.execute("SELECT id FROM work_items WHERE leased=1").fetchall())
                if root.fields["state"] == "active" or root.fields["state"] == "open" and has_writer:
                    self._save_root(transition(root, "held", expected_revision=root.revision), "root_recovered_held")
            for (work_id,) in self.connection.execute("SELECT id FROM work_items").fetchall():
                work = self.work(work_id)
                if work["state"] == "owned":
                    self._save_work({**work, "state": "held", "revision": work["revision"] + 1}, "writer_custody_retained_on_recovery")
