"""Actual scratch process deaths; never a native/model/bot fixture."""
import os
from pathlib import Path
import sys

from native_session_fixtures import CONTROLLER
from tool_switch_fixtures import context, snapshot, switch_fixture


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with switch_fixture(folder) as s:
        s.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        s.engine.request(CONTROLLER, "switch-1", "work-1", "builder.other", expected_revision=s.ledger.work("work-1")["revision"])
        s.engine.attach(CONTROLLER, "switch-1", snapshot=snapshot(), context=context())
        s.engine.finish(CONTROLLER, "switch-1")
    raise SystemExit("fault point not reached")
