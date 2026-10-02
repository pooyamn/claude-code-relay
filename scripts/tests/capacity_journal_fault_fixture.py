"""Actual isolated capacity-failure/proposal transaction deaths; no provider."""
import os
from pathlib import Path
import sys

from capacity_journal_fixtures import journal
from model_admission_fixtures import scheduler
from native_session_fixtures import CONTROLLER
from work_ownership_fixtures import work_fixture


if __name__ == "__main__":
    folder, point, job_id = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with work_fixture(folder) as f:
        admission = scheduler(f)
        admission.initialize(CONTROLLER)
        retry = journal(f, admission)
        retry.initialize(CONTROLLER)
        root = f.ledger.root("root-builder")
        f.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        if "proposal" in point:
            f.clock[0] += 1000
            retry.advance(CONTROLLER, job_id)
        else:
            retry.record_failure(CONTROLLER, job_id, "turn-1", jitter_ms=0)
    raise SystemExit("fault point not reached")
