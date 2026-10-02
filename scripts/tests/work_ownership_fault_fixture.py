"""Actual isolated work-owner death; no model, process launch or native writers."""
import os
from pathlib import Path
import sys
from unittest import mock

from work_ownership_fixtures import work_fixture
from test_core_identity import policy_fields
from relay_core.identity import Peer
from relay_core.identity import Policy
from relay_core.work_ownership import WorkOwnership
from types import SimpleNamespace


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    if point == "probe-lock":
        # No second binding/native registry. Measure the ownership lock itself.
        authority = SimpleNamespace(policy=Policy(policy_fields()))
        try:
            with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
                ledger = WorkOwnership(folder / "ownership", owner_uid=os.geteuid(), authority=authority, now_ms=lambda: 0,
                                       verify_progress=lambda *_: None, verify_quiescence=lambda *_: None, verify_handoff=lambda *_: None)
        except BlockingIOError:
            raise SystemExit(74)
        ledger.close()
        raise SystemExit("ownership lock unexpectedly admitted a second process")
    with work_fixture(folder) as f:
        f.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        if "charge" in point:
            f.ledger.charge(Peer(11, 101, 121), "turn-1", "turn", expected_revision=f.ledger.root("root-builder").revision)
        else:
            f.ledger.claim(Peer(11, 101, 121), "work-1", "claim-1", expected_revision=0)
    raise SystemExit("fault point not reached")
