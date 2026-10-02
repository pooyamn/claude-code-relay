"""Real isolated death around one joined diagnosis/root/account/outbox commit."""
import os
from pathlib import Path
import sys

from model_admission_fixtures import plan, scheduler
from native_session_fixtures import CONTROLLER
from task_diagnosis_fixtures import diagnoses
from work_ownership_fixtures import work_fixture


if __name__ == "__main__":
    folder, point, diagnosis_id = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with work_fixture(folder) as f:
        admission = scheduler(f)
        admission.initialize(CONTROLLER)
        guard = diagnoses(f, model_admission=admission)
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        action = f.ledger.load(diagnosis_id)["record"]
        guard.claim_attempt(CONTROLLER, action.id, "diagnostic-attempt", plan(f.ledger, action), expected_revision=0)
    raise SystemExit("fault point not reached")
