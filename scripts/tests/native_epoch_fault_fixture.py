"""Actual isolated epoch-driver death; no native daemon/model or credentials."""
import os
from pathlib import Path
import sys
from unittest import mock

from native_epoch_fixtures import enroll_epochs, establish_baseline, open_epochs, settings_event
from native_resume_fixtures import FakeResume
from native_rpc_fixtures import RPCFixture


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)):
        ledger = open_epochs(folder / "epochs")
        wire = RPCFixture()
        enroll_epochs(ledger, wire, folder / "artifacts")
        wire.initialize()
        establish_baseline(ledger, wire, provider=lambda: FakeResume(folder / "provider.sqlite"))
        ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        wire.peer.write(settings_event())
        wire.rpc.poll(timeout_ms=100)
    raise SystemExit("fault point not reached")
