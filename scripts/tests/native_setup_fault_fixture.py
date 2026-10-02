"""Physical scratch setup-worker death; never a native session."""
import os
from pathlib import Path
import sys

from native_launch_fixtures import open_store
from native_workspace_fixtures import fixture_fields, open_workspace
from relay_core.native_launch import prepare
from relay_core.native_setup import WorktreeSetup


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    policy, spec, home, common, contract = fixture_fields(folder, initialize=False)
    store = open_store(folder / "inputs")
    with open_workspace(policy, home, contract) as workspace, WorktreeSetup(workspace, checkpoint=lambda name: os._exit(73) if name == point else None) as setup:
        setup.apply(store, prepare(store, policy, spec))
    raise SystemExit("fault point not reached")
