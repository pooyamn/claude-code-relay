"""Kill a scratch sender during authorized render repair; never touch a bot."""
import os
from pathlib import Path
import sys

from relay_core.telegram_scheduler import TelegramScheduler
from telegram_fixtures import FakeOutbound, asset_store, fixture_dispatch, open_telegram, protected_fixture
from test_core_telegram_repair import authorization


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if not folder.resolve().is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("repair fault fixture must stay in isolated scratch")
    def checkpoint(name):
        if name == boundary:
            os._exit(73)
    with protected_fixture():
        ledger = open_telegram(folder / "ledger", now=lambda: 1790913603000, checkpoint=checkpoint)
        bot = FakeOutbound(folder / "provider.sqlite", checkpoint=checkpoint)
        scheduler = TelegramScheduler(ledger, bot, asset_store(folder / "assets"),
                                      ownership_check=lambda: None, authorize_dispatch=fixture_dispatch, authorize_repair=authorization)
        scheduler.verify()
        parent = ledger.items("original")[0]["current"]["record"].id
        scheduler.repair_pending(parent)
        scheduler.step()
    raise AssertionError("expected actual process death at configured repair boundary")


if __name__ == "__main__":
    main()
