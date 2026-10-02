"""One bounded diagnosis per material root state, with passive report intents.

No model, Telegram sender or automatic repair. Typed observations must come from
protected real task/wait/evidence readers; this module does not establish them.
The shared root/outbox transaction keeps diagnosis reservation and proposal atomic.
"""
from dataclasses import asdict, dataclass
from contextlib import nullcontext

from .contracts import canonical_bytes, create, fingerprint, intent_payload, transition
from .identity import Denied, identifier, integer, strict_json, validate_binding
from .work_ownership import WorkOwnership, _deadline, _digest


SCHEMA = "ccrelay.task_diagnosis.v1"


@dataclass(frozen=True)
class MaterialReceipt:
    observation_id: str
    scope_digest: str
    blocker_digest: str
    wait_digest: str
    trigger: str
    eligible: bool
    platform_bug: bool


@dataclass(frozen=True)
class DiagnosticAdmission:
    authorization_id: str
    scope_digest: str
    source_digest: str


class TaskDiagnoses:
    def __init__(self, ledger, *, inspect_material, admit_attempt=None):
        if type(ledger) is not WorkOwnership or not callable(inspect_material):
            raise Denied("protected work ledger and independent material/wait observer required")
        self.ledger, self.inspect_material = ledger, inspect_material
        self.admit_attempt = admit_attempt  # Absent scheduler means no executable attempt.

    def _reservations(self, root_id):
        return sum(self.ledger.load(intent_id)["record"].fields["action_kind"] == "diagnostic_turn" for (intent_id,) in
                   self.ledger.connection.execute("SELECT id FROM intents WHERE kind='external_action' AND root_id=? AND state='stored'", (root_id,)))

    def _snapshot(self, root_id):
        root = self.ledger.root(root_id)
        works = [self.ledger.work(work_id) for (work_id,) in self.ledger.connection.execute("SELECT id FROM work_items ORDER BY id")]
        return {"root": root.to_dict(), "work": [work for work in works if work["root_task_id"] == root_id],
                "owner_control": self.ledger.owner_control(root_id), "watchdog_handoffs": self.ledger.threshold(root_id)}

    def _material(self, snapshot):
        receipt = self.inspect_material(strict_json(canonical_bytes(snapshot)))
        if type(receipt) is not MaterialReceipt or receipt.scope_digest != fingerprint(snapshot) or \
                type(receipt.eligible) is not bool or type(receipt.platform_bug) is not bool or \
                receipt.trigger not in {"no_progress", "budget_exhausted", "deadline_exhausted", "verified_wait", "unverified"}:
            raise Denied("independently verified current material/wait scope required")
        identifier(receipt.observation_id)
        _digest(receipt.blocker_digest)
        _digest(receipt.wait_digest)
        root = snapshot["root"]
        # Source observation IDs, revisions, bookkeeping and diagnosis spending
        # are not new material. Recovery holds retain the same writer custody.
        works = [{key: value for key, value in work.items() if key != "revision"} for work in snapshot["work"]]
        for work in works:
            if work["state"] in {"owned", "held"}:
                work["state"] = "custody_held"
        material = {"root_id": root["id"], "owner_role_id": root["owner_role_id"], "criteria": root["acceptance_criteria"],
                    "policy_digest": root["policy_digest"], "limits": root["limits"], "evidence": root["verified_evidence_ids"],
                    "owner_desired": snapshot["owner_control"]["desired_state"], "work": works,
                    "blocker_digest": receipt.blocker_digest, "wait_digest": receipt.wait_digest,
                    "trigger": receipt.trigger, "platform_bug": receipt.platform_bug}
        return receipt, fingerprint(material)

    def _target(self, peer, root, session_id, *, platform_bug):
        binding = validate_binding(self.ledger.authority.registry.session(identifier(session_id)))
        allowed = {root.fields["owner_role_id"]} | ({"support"} if platform_bug else set())
        self.ledger._controller(peer, binding["role_id"])
        leader = self.ledger.authority.observer(binding["leader_pid"])
        if binding["revoked"] or binding["role_id"] not in allowed or binding["root_task_id"] != root.id or \
                binding["policy_digest"] != self.ledger.policy_digest or \
                (leader.uid, leader.start_identity, leader.cgroup) != (binding["uid"], binding["leader_start"], binding["cgroup"]):
            raise Denied("current accountable-owner or evidenced platform-support binding required")
        return binding

    def _action(self, action_id, root, session_id, kind, parameters):
        fields = {"id": action_id, "root_task_id": root.id, "requested_by_session_id": session_id,
                  "action_kind": kind, "parameters": parameters}
        return create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                      attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)

    def _notice(self, root, binding, material_digest, phase, diagnosis_id=None):
        notice_id = "task-report-" + fingerprint({"root": root.id, "material": material_digest, "phase": phase})[7:]
        parameters = {"root_id": root.id, "material_digest": material_digest, "phase": phase, "diagnosis_id": diagnosis_id,
                      "verified_evidence_ids": list(root.fields["verified_evidence_ids"]), "spent": dict(root.fields["usage"]),
                      "deadline": root.fields["limits"]["checkpoint_deadline"], "destination": "protected_owner_issues"}
        prior = self.ledger.load(notice_id)
        if prior is not None:
            return notice_id  # Frozen original report; status churn does not resend it.
        action = self._action(notice_id, root, binding["session_id"], "passive_task_report", parameters)
        self.ledger._enroll(action, {"schema": SCHEMA, "policy_digest": self.ledger.policy_digest,
                                    "meaning": "pending_protected_owner_report_not_sent"})
        return notice_id

    def prepare(self, peer, root_id, target_session_id, *, expected_revision):
        snapshot = self._snapshot(root_id)
        root = self.ledger.root(root_id)
        self.ledger._controller(peer, root.fields["owner_role_id"])
        if root.revision != integer(expected_revision, 0) or root.fields["state"] in {"completed", "cancelled"} or \
                not snapshot["owner_control"]["known"] or snapshot["owner_control"]["desired_state"] != "running":
            raise Denied("current nonterminal root with known running owner intent required")
        receipt, material_digest = self._material(snapshot)
        expired = _deadline(root.fields["limits"]["checkpoint_deadline"]) <= integer(self.ledger.now_ms(), 0)
        if receipt.trigger == "verified_wait" and not expired:
            return {"state": "verified_wait", "prepared_now": False, "meaning": "no_model_wake_or_stall_report"}
        if (not receipt.eligible and receipt.trigger != "verified_wait") or receipt.trigger == "unverified":
            raise Denied("task diagnosis trigger remains unverified")
        target_current = True
        try:
            binding = self._target(peer, root, target_session_id, platform_bug=receipt.platform_bug)
        except Denied:
            # Report the missing/revoked target through the protected monitor;
            # the historical/logical session reference is NOT actor authority.
            binding, target_current = {"session_id": identifier(target_session_id)}, False
        diagnosis_id = "diagnosis-" + fingerprint({"root": root_id, "material": material_digest})[7:]
        with self.ledger._transaction():
            if self._snapshot(root_id) != snapshot or target_current and self._target(peer, root, target_session_id, platform_bug=receipt.platform_bug) != binding:
                raise Denied("root, ownership or control changed during material verification")
            self.ledger._controller(peer, root.fields["owner_role_id"])
            now = self.ledger._clock()
            usage, limits = dict(root.fields["usage"]), root.fields["limits"]
            budget_hit = usage["turns"] + limits["diagnoses"] - usage["diagnoses"] >= limits["turns"] or usage["delegations"] >= limits["delegations"]
            if receipt.trigger == "no_progress" and usage["no_progress_handoffs"] < snapshot["watchdog_handoffs"] or \
                    receipt.trigger == "budget_exhausted" and not budget_hit or \
                    receipt.trigger == "deadline_exhausted" and _deadline(limits["checkpoint_deadline"]) > now:
                raise Denied("observed diagnosis trigger differs from the root ledger")
            prior = self.ledger.load(diagnosis_id)
            if _deadline(limits["checkpoint_deadline"]) <= now:
                held = transition(root, "held", expected_revision=root.revision)
                if held != root:
                    self.ledger._save_root(held, "diagnostic_execution_unavailable", asdict(receipt))
                notice_id = self._notice(held, binding, material_digest, "deadline_exhausted", diagnosis_id if prior else None)
                return {"state": "deadline_exhausted", "prepared_now": False, "notice_id": notice_id}
            if not target_current:
                held = transition(root, "held", expected_revision=root.revision)
                if held != root:
                    self.ledger._save_root(held, "diagnostic_execution_unavailable", asdict(receipt))
                notice_id = self._notice(held, binding, material_digest, "target_unavailable")
                return {"state": "target_unavailable", "prepared_now": False, "notice_id": notice_id}
            if prior is not None:
                if prior["context"].get("binding") != binding:
                    raise Denied("same-material diagnosis cannot silently move to a new execution")
                return {"state": prior["record"].fields["state"], "prepared_now": False, "diagnosis_id": diagnosis_id}
            reservations = self._reservations(root_id)
            phase = "diagnostic_budget_exhausted" if usage["diagnoses"] >= limits["diagnoses"] or usage["turns"] >= limits["turns"] else \
                "diagnostic_capacity_reserved" if usage["diagnoses"] + reservations >= limits["diagnoses"] or usage["turns"] + reservations >= limits["turns"] else None
            if phase:
                held = transition(root, "held", expected_revision=root.revision)
                if held != root:
                    self.ledger._save_root(held, "diagnostic_execution_unavailable", asdict(receipt))
                notice_id = self._notice(held, binding, material_digest, phase)
                return {"state": phase, "prepared_now": False, "notice_id": notice_id}
            held = transition(root, "held", expected_revision=root.revision)
            parameters = {"diagnosis_id": diagnosis_id, "material_digest": material_digest, "binding_digest": fingerprint(binding),
                          "owner_control_epoch": snapshot["owner_control"]["epoch"], "deadline": limits["checkpoint_deadline"]}
            action = self._action(diagnosis_id, root, binding["session_id"], "diagnostic_turn", parameters)
            self.ledger._enroll(action, {"schema": SCHEMA, "policy_digest": self.ledger.policy_digest,
                                       "binding": binding, "material_observation": asdict(receipt), "budget_reservation": {"turns": 1, "diagnoses": 1}})
            if held != root:
                self.ledger._save_root(held, "diagnostic_capacity_reserved", {"diagnosis_id": diagnosis_id, "material_digest": material_digest})
            notice_id = self._notice(held, binding, material_digest, "diagnosis_requested", diagnosis_id)
            self.ledger.checkpoint("before_diagnostic_prepare_commit")
        self.ledger.checkpoint("after_diagnostic_prepare_commit")
        return {"state": "stored", "prepared_now": True, "diagnosis_id": diagnosis_id, "notice_id": notice_id,
                "meaning": "budget_reserved_not_model_admitted"}

    def claim_attempt(self, peer, diagnosis_id, attempt_id, plan, *, expected_revision):
        current = self.ledger.load(identifier(diagnosis_id))
        if current is not None and current["record"].fields["attempt_id"] is not None:
            return self.ledger.claim(diagnosis_id, attempt_id, plan, expected_revision=expected_revision)
        if not callable(self.admit_attempt):
            raise Denied("actual all-source activity/quota/pacing admission required; reservation is not execution")
        action = self.validate_action(peer, diagnosis_id)
        admission = self.admit_attempt(action, attempt_id, strict_json(canonical_bytes(plan)))
        scope = {"action": action.to_dict(), "attempt_id": identifier(attempt_id), "plan": plan}
        if type(admission) is not DiagnosticAdmission or admission.scope_digest != fingerprint(scope) or admission.authorization_id != plan["authorization_id"]:
            raise Denied("current exact diagnostic admission receipt required")
        identifier(admission.authorization_id)
        _digest(admission.source_digest)
        def charge(claimed, frozen_plan):
            self._validate(peer, diagnosis_id, "delivering")
            root = self.ledger.root(action.fields["root_task_id"])
            usage = dict(root.fields["usage"])
            for counter in ("turns", "diagnoses"):
                if usage[counter] >= root.fields["limits"][counter]:
                    raise Denied("diagnostic root execution budget exhausted")
                usage[counter] += 1
            updated = transition(root, "held", expected_revision=root.revision, usage=usage)
            self.ledger._save_root(updated, "diagnostic_attempt_charged", {"diagnosis_id": diagnosis_id, "attempt_id": attempt_id,
                                                                         "admission": asdict(admission)})
            self._notice(updated, current["context"]["binding"], action.fields["parameters"]["material_digest"], "diagnosis_attempted", diagnosis_id)
        return self.ledger.claim(diagnosis_id, attempt_id, plan, expected_revision=expected_revision, commit_hook=charge)

    def validate_action(self, peer, diagnosis_id):
        return self._validate(peer, diagnosis_id, "stored")

    def validate_result(self, peer, diagnosis_id):
        """Scope check before applying recommendations; not permission to repair."""
        return self._validate(peer, diagnosis_id, "confirmed")

    def _validate(self, peer, diagnosis_id, required_state):
        current = self.ledger.load(identifier(diagnosis_id))
        if current is None or current["record"].kind != "external_action" or current["record"].fields["action_kind"] != "diagnostic_turn":
            raise Denied("diagnostic intent not found")
        action = current["record"]
        if action.fields["state"] != required_state:
            raise Denied("attempted diagnosis requires reconciliation, never replay")
        root_id = action.fields["root_task_id"]
        snapshot = self._snapshot(root_id)
        root = self.ledger.root(root_id)
        self.ledger._controller(peer, root.fields["owner_role_id"])
        receipt, material_digest = self._material(snapshot)
        binding = self._target(peer, root, action.fields["requested_by_session_id"], platform_bug=receipt.platform_bug)
        with (nullcontext() if self.ledger.connection.in_transaction else self.ledger._transaction()):
            if self._snapshot(root_id) != snapshot or current != self.ledger.load(diagnosis_id) or not receipt.eligible or \
                    receipt.trigger in {"verified_wait", "unverified"} or root.fields["state"] != "held" or \
                    not snapshot["owner_control"]["known"] or snapshot["owner_control"]["desired_state"] != "running" or \
                    _deadline(action.fields["parameters"]["deadline"]) <= self.ledger._clock() or \
                    material_digest != action.fields["parameters"]["material_digest"] or binding != current["context"]["binding"] or \
                    snapshot["owner_control"]["epoch"] != action.fields["parameters"]["owner_control_epoch"]:
                raise Denied("diagnostic material, owner control, binding or deadline changed")
            self.ledger._controller(peer, root.fields["owner_role_id"])
            if self._target(peer, root, action.fields["requested_by_session_id"], platform_bug=receipt.platform_bug) != binding:
                raise Denied("diagnostic target changed during validation")
        return action  # Necessary check only; PR 9 admission/current runtime still required.
