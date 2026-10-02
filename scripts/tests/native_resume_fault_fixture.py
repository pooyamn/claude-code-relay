"""Physical isolated resume-driver death; fake non-idempotent provider only."""
import os
from pathlib import Path
import sys

from native_resume_fixtures import FakeResume
from native_session_fixtures import CONTROLLER, native_fixture
from outbox_fixtures import open_outbox
from relay_core.native_resume import CodexExactResume


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    checkpoint = lambda name: os._exit(73) if name == point else None
    with native_fixture(folder, checkpoint=checkpoint) as (registry, authority):
        ledger = open_outbox(folder / "ledger", policy_digest=authority.policy.digest, checkpoint=checkpoint)
        provider = FakeResume(folder / "provider.sqlite", checkpoint=checkpoint)
        CodexExactResume(provider.rpc, response_evidence=provider.response_evidence,
                         authorize=lambda *_: "fixture-admission", resume_supported=True).deliver(
            ledger, "resume-1", "resume-attempt", registry, CONTROLLER)
    raise SystemExit("fault point not reached")
