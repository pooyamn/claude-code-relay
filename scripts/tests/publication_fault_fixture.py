"""Actual scratch-only deaths across publication, non-idempotent effects and merge."""
import os
from pathlib import Path
import sys

from native_session_fixtures import CONTROLLER
from publication_fixtures import BASE, CTO, HEAD, execute, publication_fixture, publish, reviewed


if __name__ == "__main__":
    folder, point = Path(sys.argv[1]).resolve(), sys.argv[2]
    scratch = Path(os.environ.get("CCRELAY_TEST_SCRATCH", "/nonexistent")).resolve()
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or scratch not in folder.parents:
        raise SystemExit("isolated scratch required")
    with publication_fixture(folder) as s:
        s.ledger.checkpoint = lambda name: os._exit(73) if name == point else None
        if "publication_store" in point or "publication_branch" in point or point == "after_fake_branch_effect":
            publish(s)
            claim = s.engine.claim_publish(CONTROLLER, "pub-1", "branch", "attempt-pub-1-branch")
            evidence = s.provider.call(claim)
            if point == "after_fake_branch_effect":
                os._exit(73)
            s.ledger.reconcile(evidence)
        else:
            reviewed(s)
            s.engine.request_merge(CTO, "merge-1", "pub-1", head_sha=HEAD, base_sha=BASE)
            claim = s.engine.claim_merge(CONTROLLER, "merge-1", "merge-attempt-1")
            evidence = s.provider.call(claim)
            if point == "after_fake_merge_effect":
                os._exit(73)
            s.ledger.reconcile(evidence)
            s.state["result"] = "merged"
            s.engine.settle_merge(CONTROLLER, "merge-1")
    raise SystemExit("fault point not reached")
