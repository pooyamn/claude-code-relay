"""Physical isolated death at the joined diagnosis/root/outbox transaction."""
import os
from pathlib import Path
import sys

from native_session_fixtures import CONTROLLER
from task_diagnosis_fixtures import diagnoses, diagnostic_plan
from work_ownership_fixtures import work_fixture


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with work_fixture(folder) as f:
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        guard = diagnoses(f)
        prepared = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
        if point in {"before_claim_commit", "after_claim_commit"}:
            action = f.ledger.load(prepared["diagnosis_id"])["record"]
            guard.claim_attempt(CONTROLLER, action.id, "diagnostic-attempt", diagnostic_plan(guard, action), expected_revision=0)
    raise SystemExit("fault point not reached")
