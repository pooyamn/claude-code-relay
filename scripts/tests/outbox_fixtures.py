"""Invented delivery fixtures. Fake provider is NOT native runtime evidence."""
import os
from pathlib import Path
import sqlite3
from unittest import mock

from contract_fixtures import DIGEST, example
from relay_core.contracts import canonical_bytes
from relay_core.identity import strict_json
from relay_core.outbox import DeliveryLedger


CONTEXT = {"schema": "fixture.protected_source.v1", "source": "invented-sandbox"}


def open_outbox(folder, *, checkpoint=lambda _: None, policy_digest=DIGEST):
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Scratch /tmp ancestors deliberately do not pass production protection.
    # Only that check is substituted; DB/fsync/flock/process deaths are real.
    with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
        return DeliveryLedger(folder, owner_uid=os.geteuid(), policy_digest=policy_digest, checkpoint=checkpoint)


def session():
    return example("session", id="session-2")


class FakeNative:
    """Every call has an effect, even duplicated IDs: tests must prevent replay."""
    def __init__(self, path):
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS effects (request_id TEXT, body BLOB, receipt BLOB)")

    def close(self):
        self.connection.close()

    def rpc(self, method, parameters, *, request_id):
        if method != "turn/steer":
            raise AssertionError("no start/queue/resume/thread creation fallback permitted")
        response = {"id": request_id, "result": {"turnId": parameters["expectedTurnId"]}}
        self.connection.execute("INSERT INTO effects VALUES (?,?,?)", (
            request_id, canonical_bytes({"method": method, "parameters": parameters}), canonical_bytes(response)))
        return response

    def count(self):
        return self.connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0]

    def receipt(self):
        return strict_json(self.connection.execute("SELECT receipt FROM effects ORDER BY rowid DESC LIMIT 1").fetchone()[0])
