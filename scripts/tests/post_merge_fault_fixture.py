"""Scratch-only actual process deaths around local Git replay effects."""
import os
from pathlib import Path
import sys

from post_merge_fixtures import loaded_fields, replay_fixture, request


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    data = loaded_fields(folder)
    with replay_fixture(data, checkpoint=lambda name: os._exit(73) if name == point else None) as replay:
        request(replay, data)
        replay.run("replay-1")
    raise SystemExit("fault point not reached")
