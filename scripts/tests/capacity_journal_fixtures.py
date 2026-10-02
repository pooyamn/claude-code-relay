"""Synthetic pinned failure classification; real root/outbox/capacity transactions."""
from dataclasses import replace

from model_admission_fixtures import plan, request, scheduler
from native_session_fixtures import CONTROLLER
from relay_core.capacity_journal import CapacityJournal, FailureReceipt
from relay_core.capacity_retry import RetryPolicy
from relay_core.contracts import fingerprint
from relay_core.runtime_delivery import evidence_for


def journal(f, admission, *, changes=None):
    def verify(scope):
        # Invented observations; NOT runtime/capture/account provenance.
        fields = dict(failure_id="failure-" + scope["source"]["id"], scope_digest=fingerprint(scope),
            source_digest=fingerprint({"synthetic_failure_not_runtime": True}),
            evidence_id=scope["source"]["outcome_evidence_id"] or "synthetic-unknown-observation",
            observed_ms=f.clock[0], classification="temporary_capacity", outcome="not_accepted",
            retry_after_ms=0, native_retry_pending=False, cooldown_pool="model")
        fields.update(changes or {})
        return FailureReceipt(**fields)
    # Invented finite fixture numbers, NOT approved production settings.
    return CapacityJournal(admission, RetryPolicy(1000, 4000, 250, 2, 20000), verify_failure=verify)


def rejected(f, admission, action, attempt_id, *, unknown=False):
    current = f.ledger.load(action.id)
    current_plan = current["plan"] or plan(f.ledger, action)
    if current["record"].fields["attempt_id"] is None:
        result = admission.claim(CONTROLLER, action.id, attempt_id, current_plan, expected_revision=0)
        if not result["may_execute"]:
            raise AssertionError("fixture attempt was not admitted: " + str(result))
    f.ledger.submitted(action.id, attempt_id)
    if unknown:
        f.ledger.unknown(action.id, attempt_id)
    else:
        f.ledger.reconcile(evidence_for(action, attempt_id, current_plan, outcome="rejected", provider_reference="synthetic-rejection",
            payload={"synthetic_negative_not_provider": True}))


def initial(f, *, unknown=False):
    admission = scheduler(f)
    source = admission.verify_source
    admission.verify_source = lambda scope: replace(source(scope), owner_requested=scope["action"]["id"] == "turn-1")
    admission.initialize(CONTROLLER)
    action = admission.enqueue(CONTROLLER, request(estimate=1))["record"]
    rejected(f, admission, action, "attempt-1", unknown=unknown)
    return admission, action
