"""Actual scratch death with independently committed source revocation/effects."""
import os
from pathlib import Path
import sys

from relay_core.telegram_scheduler import TelegramScheduler
from source_grant_fixtures import CONTROLLER, sources
from telegram_fixtures import FakeOutbound, asset_store, open_telegram, protected_fixture


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if not folder.resolve().is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("source fault fixture must be isolated")
    with protected_fixture():
        ledger = open_telegram(folder / "send", now=lambda: 1790913600000)
        with sources(folder / "authority", ledger) as (grants, authority):
            def checkpoint(name):
                if name == boundary:
                    grants.revoke(CONTROLLER, "reply-1")
                    os._exit(74)
            ledger.checkpoint = checkpoint
            bot = FakeOutbound(folder / "provider.sqlite", checkpoint=checkpoint)
            scheduler = TelegramScheduler(ledger, bot, asset_store(folder / "assets"),
                                          ownership_check=lambda: None, authorize_dispatch=grants.authorize)
            scheduler.verify()
            scheduler.step()
    raise AssertionError("expected configured source process death")


if __name__ == "__main__":
    main()
