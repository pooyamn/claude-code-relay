"""Actual scratch worker death at Git/journal boundaries, no native sessions."""
import os
from pathlib import Path
import sys

from native_workspace_fixtures import fixture_fields, open_workspace


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    policy, spec, home, common, contract = fixture_fields(folder, initialize=False)
    with open_workspace(policy, home, contract, checkpoint=lambda name: os._exit(73) if name == point else None) as journal:
        journal.prepare(spec)
    raise SystemExit("fault point not reached")
