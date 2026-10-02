"""Actual isolated scratch deaths at the joined estimate/model commit."""
import os
from pathlib import Path
import sys

from model_admission_fixtures import plan, scheduler
from native_session_fixtures import CONTROLLER
from quota_estimate_fixtures import estimates
from work_ownership_fixtures import NOW, work_fixture


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with work_fixture(folder) as f:
        f.clock[0] = NOW + 61000
        admission = scheduler(f)
        admission.initialize(CONTROLLER)
        estimates(admission, f).initialize(CONTROLLER)
        root = f.ledger.root("root-builder")
        f.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
        admission.observe_quota = lambda _: None
        action = f.ledger.load("estimated-turn")["record"]
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        admission.claim(CONTROLLER, action.id, "estimated-attempt", plan(f.ledger, action), expected_revision=0)
    raise SystemExit("fault point not reached")
