"""Actual isolated joined-driver death, with a non-idempotent fake provider."""
import os
from pathlib import Path
import sys

from controlled_resume_fixtures import controlled_fixture, run_resume


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    checkpoint = lambda name: os._exit(73) if name == point else None
    with controlled_fixture(folder, checkpoint=checkpoint) as fixture:
        run_resume(fixture)
    raise SystemExit("fault point not reached")
