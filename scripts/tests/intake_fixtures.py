"""Synthetic Telegram provider/UID observations, never a real bot or home."""
import os
from pathlib import Path
import sqlite3
from unittest import mock

from relay_core.identity import Process
from relay_core.intake import IntakeLedger, IntakePolicy, provider_bytes, provider_json
from relay_core.owner_gate import OwnerPolicy
from owner_fixtures import broker_policy, owner_fields


def policy_fields():
    return {"schema": "ccrelay.intake_policy.v1", "bot_username": "SyntheticKhadang", "allow_users": [1001], "allow_chats": [],
            "bindings": [{"chat_id": -1003, "thread_id": 5, "role_id": "builder", "session_id": "builder.fixture"}]}


def policy(fields=None):
    broker = broker_policy()
    owner = OwnerPolicy({**owner_fields(), "gate_uid": 150, "ingress_uid": os.geteuid()}, broker)
    return IntakePolicy(policy_fields() if fields is None else fields, owner, broker)


def message(uid=1, text="Synthetic text", *, sender=1001, thread=5, **extra):
    return {"update_id": uid, "message": {"message_id": uid + 10, "date": 1790913600,
            "from": {"id": sender, "is_bot": False, "first_name": "Synthetic"},
            "chat": {"id": -1003, "is_forum": True, "type": "supergroup"}, "message_thread_id": thread,
            "text": text, **extra}}


def callback(uid=2, data="cc1:" + "n" * 32 + ":a", *, sender=1001):
    event = message(uid)["message"]
    event["from"] = {"id": 1002, "is_bot": True}
    return {"update_id": uid, "callback_query": {"id": "callback-" + str(uid), "data": data,
            "from": {"id": sender, "is_bot": False}, "message": event}}


def response(*updates):
    return provider_bytes({"ok": True, "result": list(updates)})


def open_ledger(folder, *, fields=None, checkpoint=lambda _: None, clock=lambda: 1790913600):
    with mock.patch("relay_core.intake.protected_path", side_effect=lambda path, **_: Path(path)):
        return IntakeLedger(folder, policy(fields), clock=clock, checkpoint=checkpoint)


def process(pid):
    return Process(pid, os.geteuid(), "fixture-boot:fixture-start", "/system.slice/ccrelay-intake.service")


class FakeGuard:
    def __init__(self):
        self.valid, self.checks = True, 0

    def check(self):
        self.checks += 1
        if not self.valid:
            from relay_core.identity import Denied
            raise Denied("synthetic lost owner lock")


class FakeTelegram:
    """Independent SQLite remote effects make ACK-before-death observable."""
    def __init__(self, path, *, checkpoint=lambda _: None):
        scratch = Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()
        if not Path(path).resolve().is_relative_to(scratch):
            raise RuntimeError("fake Telegram must stay inside isolated scratch")
        self.path, self.checkpoint = str(path), checkpoint
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY, body BLOB)")
            db.execute("CREATE TABLE IF NOT EXISTS calls (sequence INTEGER PRIMARY KEY, offset INTEGER)")
        self.errors, self.bot_id, self.username, self.webhook_url = [], 1002, "SyntheticKhadang", ""

    def add(self, event):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO pending VALUES (?,?)", (event["update_id"], provider_bytes(event)))

    def identity(self):
        return {"id": self.bot_id, "is_bot": True, "username": self.username}

    def webhook(self):
        return {"url": self.webhook_url}

    def updates(self, offset, timeout):
        if self.errors:
            raise self.errors.pop(0)
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO calls(offset) VALUES (?)", (offset,))
            db.execute("DELETE FROM pending WHERE id<?", (offset,))
            rows = db.execute("SELECT body FROM pending ORDER BY id LIMIT 100").fetchall()
        if offset > 0:
            self.checkpoint("after_provider_ack")
        return response(*(provider_json(row[0]) for row in rows))

    def offsets(self):
        with sqlite3.connect(self.path) as db:
            return [row[0] for row in db.execute("SELECT offset FROM calls ORDER BY sequence")]

    def pending_count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
