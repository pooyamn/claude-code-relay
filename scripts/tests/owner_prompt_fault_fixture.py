"""Actual process death across synthetic prompt-send and owner-bind ledgers."""
import os
from pathlib import Path
import sys

from owner_prompt_fixtures import joined


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if not folder.resolve().is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("owner prompt crash fixture must stay in isolated scratch")
    def checkpoint(name):
        if name == boundary:
            os._exit(73)
    def after_bind():
        checkpoint("after_owner_bind_before_ack")
    with joined(folder, checkpoint=checkpoint, after_bind=after_bind) as (_, ledger, bridge, _, scheduler, now):
        ticket = bridge.enqueue("action-1")
        scheduler.verify()
        for _ in range(10):
            if ledger.status(ticket["id"])["state"] == "confirmed":
                break
            now[0] += 3000
            scheduler.step()
        bridge.bind("action-1")
    raise AssertionError("expected actual death at configured prompt boundary")


if __name__ == "__main__":
    main()
