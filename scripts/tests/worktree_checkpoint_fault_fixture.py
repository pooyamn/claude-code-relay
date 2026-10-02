"""Real isolated snapshot deaths; no native session, model or real writer."""
import os
from pathlib import Path
import sys
from unittest import mock

from native_workspace_fixtures import fixture_fields, open_workspace
from relay_core.worktree_checkpoints import CheckpointPolicy, WorktreeCheckpoints


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    policy, spec, home, common, contract = fixture_fields(folder, initialize=False)
    with open_workspace(policy, home, contract) as workspace, \
            mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)), \
            WorktreeCheckpoints(workspace, CheckpointPolicy(128, 8 * 1024 * 1024),
                checkpoint=lambda name: os._exit(73) if name == point else None) as snapshots:
        snapshots.capture("checkpoint-1", spec)
    raise SystemExit("fault point not reached")
