"""Actual scratch-process death; no live sender or bot is ever involved."""
import os
from pathlib import Path
import sys

from intake_fixtures import process
from relay_core.telegram_outbound import SendOwnership
from relay_core.telegram_scheduler import TelegramScheduler
from telegram_fixtures import FakeOutbound, asset_store, open_telegram, protected_fixture, reply


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if not folder.resolve().is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("fixture must stay within isolated scratch")
    def checkpoint(name):
        if name == boundary:
            os._exit(73)
    with protected_fixture():
        if boundary == "lock_probe":
            with SendOwnership(folder, bot_id=1002, owner_uid=os.geteuid(), observer=process):
                os._exit(1)
        ledger = open_telegram(folder / "ledger", checkpoint=checkpoint)
        if boundary in {"before_bundle_commit", "after_bundle_commit"}:
            ledger.enqueue(reply(cursor={"stream_id": "stream-1", "expected": 0, "new": 50}))
        else:
            bot = FakeOutbound(folder / "provider.sqlite", checkpoint=checkpoint)
            scheduler = TelegramScheduler(ledger, bot, asset_store(folder / "assets"), ownership_check=lambda: None)
            scheduler.verify()
            scheduler.step()
    raise AssertionError("expected configured process death")


if __name__ == "__main__":
    try:
        main()
    except BlockingIOError:
        raise SystemExit(42)
