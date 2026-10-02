"""Actual scratch-only process death and competing SQLite writer, never live IO."""
import os
from pathlib import Path
import sqlite3
import sys
from unittest import mock

from relay_core.telegram_scheduler import TelegramScheduler
from relay_core.telegram_snapshot import DEPENDENCIES, capture, restore_snapshot
from source_grant_fixtures import CONTROLLER, sources
from telegram_fixtures import FakeOutbound, asset_store, open_telegram, protected_fixture, reply


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or not folder.resolve().is_relative_to(
            Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("fixture must stay in isolated scratch")
    if boundary == "writer_probe":
        for path in (folder / "ledger/outbox.sqlite", folder / "authority/grants/source-grants.sqlite"):
            with sqlite3.connect(path, timeout=0) as db:
                try:
                    db.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as error:
                    if "locked" not in str(error):
                        raise
                else:
                    raise AssertionError("snapshot did not fence both writers")
        raise SystemExit(42)
    def checkpoint(name):
        if name == boundary:
            os._exit(73)
    with protected_fixture(), mock.patch("relay_core.telegram_snapshot.protected_path", side_effect=lambda path, **_: Path(path)):
        ledger = open_telegram(folder / "ledger")
        ledger.register_stream("stream-1", session_id="builder.fixture", native_session_id="native-1",
                               initial_cursor=0, evidence_id="stream-evidence-1")
        store = asset_store(folder / "assets")
        store.stage(b"invented upload", filename="fixture.bin", mime_type="application/octet-stream")
        with sources(folder / "authority", ledger) as (grants, authority):
            body = reply(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
            grants.issue(CONTROLLER, body, expires_ms=ledger.now() + 86400000)
            ledger.enqueue(body)
            bot = FakeOutbound(folder / "provider.sqlite")
            bot.lost_ack = True
            scheduler = TelegramScheduler(ledger, bot, store, ownership_check=lambda: None, authorize_dispatch=grants.authorize)
            scheduler.verify()
            assert scheduler.step()["state"] == "unknown"
            capture(ledger, grants, store, folder / "snapshot", cohort_id="fixture-cohort",
                    external_digests={key: "sha256:" + "d" * 64 for key in DEPENDENCIES}, checkpoint=checkpoint)
            if "restore" in boundary:
                restore_snapshot(folder / "snapshot", folder / "restored", owner_uid=os.geteuid(), checkpoint=checkpoint)
    raise AssertionError("expected configured process death")


if __name__ == "__main__":
    main()
