"""Actual private capture death / independent writer probe, no live services."""
import os
from pathlib import Path
import sqlite3
import sys
from unittest import mock

from relay_core.system_snapshot import Component, SnapshotPolicy
from system_snapshot_fixtures import capture_fixture, fixture


def main():
    folder, action = Path(sys.argv[1]), sys.argv[2]
    if action == "writer_probe":
        blocked = 0
        for key in ("broker", "worker"):
            db = sqlite3.connect(str(folder / key / "state.sqlite"), timeout=0)
            try:
                db.execute("INSERT INTO state VALUES ('interfering-writer',?)", (b"must be blocked",))
                db.commit()
            except sqlite3.OperationalError as error:
                if "locked" in str(error):
                    blocked += 1
                else:
                    raise
            finally:
                db.close()
        return 42 if blocked == 2 else 1
    with mock.patch("relay_core.system_snapshot.protected_path", side_effect=lambda path, **_: Path(path)):
        components, policy = fixture(folder)
        def die(name):
            if name == action:
                os._exit(73)
        capture_fixture(components, policy, folder / "capture", checkpoint=die)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
