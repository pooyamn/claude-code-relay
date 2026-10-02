"""Synthetic task/wait facts; shared root/outbox files and process deaths are real."""
from native_session_fixtures import CONTROLLER
from relay_core.contracts import fingerprint
from relay_core.identity import Peer
from relay_core.task_diagnosis import DiagnosticAdmission, MaterialReceipt, TaskDiagnoses


def stalled_root(fixture):
    root = fixture.ledger.root("root-builder")
    if root.fields["usage"]["no_progress_handoffs"]:
        return
    for index in range(3):
        root = fixture.ledger.root(root.id)
        charged = fixture.ledger.charge(Peer(11, 101, 121), "delegate-" + str(index), "handoff", expected_revision=root.revision)
        fixture.ledger.assess_handoff(CONTROLLER, root.id, charged["receipt"]["scope"]["id"], "assessed-" + str(index),
                                     expected_revision=charged["record"].revision)


def diagnoses(fixture):
    def inspect(snapshot):
        # Invented stable blocker/wait facts, NOT observed operation provenance.
        return MaterialReceipt("synthetic-observation", fingerprint(snapshot), fingerprint({"synthetic_blocker": "unchanged"}),
                               fingerprint({"synthetic_wait": "none"}), "no_progress", True, False)
    return TaskDiagnoses(fixture.ledger, inspect_material=inspect)


def diagnostic_plan(guard, action):
    # Synthetic admission only; NOT real quota/activity/source enforcement.
    guard.admit_attempt = lambda record, attempt_id, plan: DiagnosticAdmission(plan["authorization_id"],
        fingerprint({"action": record.to_dict(), "attempt_id": attempt_id, "plan": plan}), fingerprint({"synthetic_admission": True}))
    return {"schema": "ccrelay.delivery_plan.v1", "intent_id": action.id, "intent_digest": action.fields["intent_digest"],
            "adapter_id": "synthetic-diagnostic-adapter", "authorization_id": "synthetic-admission",
            "target": {"session": "builder.task"}, "parameters": action.to_dict()["parameters"]}
