"""Crash actual scratch processes; no host config, network or native runtime."""
import os
from pathlib import Path
import sys
from unittest import mock

from relay_core.identity import Denied
from relay_core.polling import CycleHealth, DurablePoller, PollerLock
from intake_fixtures import FakeGuard, FakeTelegram, message, open_ledger, process, response


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    scratch = Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()
    if not folder.resolve().is_relative_to(scratch):
        raise RuntimeError("fixture must stay inside isolated scratch")
    if boundary == "lock_probe":
        with mock.patch("relay_core.polling.protected_path", side_effect=lambda path, **_: Path(path)):
            try:
                with PollerLock(folder, bot_id=1002, owner_uid=os.geteuid(), observer=process):
                    sys.exit(0)
            except BlockingIOError:
                sys.exit(42)

    def checkpoint(name):
        if name == boundary:
            os._exit(73)

    ledger = open_ledger(folder / "ledger", checkpoint=checkpoint)
    with mock.patch("relay_core.intake.protected_path", side_effect=lambda path, **_: Path(path)):
        if boundary == "after_provider_ack":
            bot = FakeTelegram(folder / "provider.sqlite", checkpoint=checkpoint)
            health = CycleHealth(grace_seconds=10, startup_seconds=60, availability_seconds=30)
            poller = DurablePoller(bot, ledger, FakeGuard(), health, expected_username="SyntheticKhadang",
                                   long_poll_seconds=10, conflict_limit=3, network_timeout=20)
            poller.verify()
            poller.step()
            poller.step()
        else:
            ledger.capture(response(message()), 0)
            ledger.materialize()


if __name__ == "__main__":
    main()
