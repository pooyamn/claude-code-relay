"""Actual process death within OS-isolated scratch, never a live adapter."""
import os
from pathlib import Path
import sys

from contract_fixtures import example
from outbox_fixtures import CONTEXT, FakeNative, open_outbox, session
from relay_core.runtime_delivery import CodexSteering


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if not folder.resolve().is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("fixture must stay within isolated scratch")
    def checkpoint(name):
        if name == boundary:
            os._exit(73)
    ledger = open_outbox(folder / "ledger", checkpoint=checkpoint)
    if boundary in {"before_store_commit", "after_store_commit"}:
        ledger.store(example("message"), CONTEXT)
    else:
        native = FakeNative(folder / "native.sqlite")
        adapter = CodexSteering(native.rpc, authorize=lambda *_: "fixture-gate-1", steer_supported=True)
        adapter.deliver(ledger, "message-1", "attempt-1", session())
    raise AssertionError("expected configured process death")


if __name__ == "__main__":
    main()
