"""Actual isolated death before/after the joined model admission commit."""
import os
from pathlib import Path
import sys

from model_admission_fixtures import plan, scheduler
from native_session_fixtures import CONTROLLER
from work_ownership_fixtures import work_fixture


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with work_fixture(folder) as f:
        guard = scheduler(f)
        guard.initialize(CONTROLLER)
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        action = f.ledger.load("turn-1")["record"]
        guard.claim(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
    raise SystemExit("fault point not reached")
