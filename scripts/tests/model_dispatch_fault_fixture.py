"""Actual scratch-only deaths around priority offers and model admission."""
import os
from pathlib import Path
import sys

from model_admission_fixtures import plan, scheduler
from native_session_fixtures import CONTROLLER
from work_ownership_fixtures import work_fixture
from relay_core.model_dispatch import DispatchPolicy, ModelDispatch


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with work_fixture(folder) as f:
        admission = scheduler(f)
        admission.initialize(CONTROLLER)
        dispatch = ModelDispatch(admission, DispatchPolicy(8))  # Fixture only.
        dispatch.initialize(CONTROLLER)
        action = f.ledger.load("turn-1")["record"]
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        if "offer" in point:
            dispatch.offer(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
        else:
            admission.claim(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
    raise SystemExit("fault point not reached")
