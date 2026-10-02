"""Real scratch-process death around launch candidate publication, no native."""
import os
from pathlib import Path
import sys
from unittest import mock

from native_launch_fixtures import fixture, open_store
from relay_core.native_launch import prepare


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with mock.patch(
            "relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)):
        store = open_store(folder)
        policy, spec = fixture(store)
        prepare(store, policy, spec, checkpoint=lambda name: os._exit(73) if name == point else None)
    raise SystemExit("fault point not reached")
