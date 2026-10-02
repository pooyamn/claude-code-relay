"""Real work ledger/locks; kernel, evidence, clock and writer facts are synthetic."""
from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from native_session_fixtures import native_fixture
from relay_core.contracts import create, fingerprint
from relay_core.work_ownership import WorkOwnership, ProgressReceipt, QuiescenceReceipt, HandoffReceipt


NOW = 1790966400000


def root_record(policy_digest, *, root_id="root-builder", turns=5, delegations=7, diagnoses=2):
    # Explicit fixture numbers are NOT production defaults or owner choices.
    return create("root_task", id=root_id, owner_role_id="builder", acceptance_criteria=["Verified fixture result"],
                  policy_digest=policy_digest, state="open",
                  limits={"turns": turns, "delegations": delegations, "diagnoses": diagnoses, "checkpoint_deadline": "2026-10-04T00:00:00Z"},
                  usage={"turns": 0, "delegations": 0, "diagnoses": 0, "no_progress_handoffs": 0}, verified_evidence_ids=[])


@contextmanager
def work_fixture(folder, *, checkpoint=lambda _: None):
    folder = Path(folder)
    with native_fixture(folder) as (_, authority):
        state = folder / "ownership"
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        clock = [NOW]
        def progress(scope, evidence_id):
            return ProgressReceipt(evidence_id, fingerprint(scope), fingerprint({"synthetic_test_evidence": evidence_id}), True)
        def quiescence(scope):
            return QuiescenceReceipt("fixture-all-writers-stopped", fingerprint(scope), fingerprint({"synthetic_writer_fence": "NOT-KERNEL-PROOF"}))
        def handoff(scope, evidence_id):
            return HandoffReceipt(evidence_id, fingerprint(scope), fingerprint({"synthetic_completed_result": evidence_id}), True, None)
        with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
            ledger = WorkOwnership(state, owner_uid=os.geteuid(), authority=authority, now_ms=lambda: clock[0],
                                   verify_progress=progress, verify_quiescence=quiescence, verify_handoff=handoff, checkpoint=checkpoint)
        try:
            yield SimpleNamespace(ledger=ledger, authority=authority, clock=clock)
        finally:
            ledger.close()
