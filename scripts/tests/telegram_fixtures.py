"""Invented Telegram sends, independent SQLite effects, no keys/network/home."""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import sqlite3
from unittest import mock

from relay_core.contracts import canonical_bytes
from relay_core.intake import provider_json
from relay_core.telegram_outbound import AssetStore, OutboundPolicy, Response
from relay_core.telegram_producers import bundle
from relay_core.telegram_scheduler import TelegramLedger
from relay_core.telegram_authority import DispatchPermit


def fixture_dispatch(request):
    """Invented authority only; production requires protected current grants."""
    return DispatchPermit(request, "fixture-source-grant", 1, 9223372036854775807)


def policy_fields(**changes):
    # Invented timing/upload bounds, not production defaults or quota choices.
    return {"schema": "ccrelay.telegram_outbound_policy.v2", "bot_id": 1002, "bot_username": "SyntheticKhadang",
            "test_bot": "khadang", "allowed_chats": [-1003, -1004, 1005], "global_spacing_ms": 40,
            "chat_spacing_ms": 1000, "group_spacing_ms": 3000, "max_rate_limit_retries": 2,
            "max_upload_bytes": 100000, "compatibility_digest": "sha256:" + "a" * 64,
            "retryable_methods": ["sendMessage", "editMessageText"],
            "repairable_methods": ["sendMessage", "editMessageText", "sendRichMessage", "sendPhoto"], **changes}


@contextmanager
def protected_fixture():
    # Only root-owned/private ancestor checks are substituted for scratch /tmp.
    # SQLite/fsync/flock/sealed files and process deaths stay actual.
    with ExitStack() as stack:
        for name in ("relay_core.outbox.protected_path", "relay_core.identity.protected_path", "relay_core.telegram_outbound.protected_path", "relay_core.telegram_authority.protected_path"):
            stack.enter_context(mock.patch(name, side_effect=lambda path, **_: Path(path)))
        yield


def open_telegram(folder, *, now=lambda: 1790913600000, checkpoint=lambda _: None, fields=None):
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with protected_fixture():
        return TelegramLedger(folder, owner_uid=os.geteuid(), policy=OutboundPolicy(fields or policy_fields()),
                              clock_ms=now, checkpoint=checkpoint)


def asset_store(folder, max_bytes=100000):
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return AssetStore(folder, owner_uid=os.geteuid(), max_bytes=max_bytes)


def reply(bundle_id="reply-1", *, count=1, chat_id=-1003, thread_id=5, cursor=None, lane="reply", coalesce_key=None,
          source_kind=None, operations=None):
    operations = operations or [{"method": "sendMessage", "args": {"chat_id": chat_id,
                   **({"message_thread_id": thread_id} if thread_id not in {None, 1} else {}), "text": "Invented chunk " + str(i)}, "assets": {}} for i in range(count)]
    return bundle(bundle_id=bundle_id, root_task_id="root-1", session_id="builder.fixture", chat_id=chat_id,
                  thread_id=thread_id, lane=lane, content="Invented original " + bundle_id, operations=operations,
                  source_kind=source_kind or ("owner_reply" if lane == "reply" else lane), native_session_id="native-1",
                  turn_id="turn-1", submission_id="submission-1", cursor=cursor, coalesce_key=coalesce_key)


def rejected(code=429, retry_after=30):
    return Response(code, canonical_bytes({"ok": False, "error_code": code, "description": "Invented failure",
                                          "parameters": {"retry_after": retry_after} if code == 429 else {}}))


class FakeOutbound:
    dispatch_contract = "ccrelay.guarded_telegram_request.v1"
    """Non-idempotent provider: each accepted call creates a new remote effect."""
    def __init__(self, path, *, checkpoint=lambda _: None):
        self.path, self.checkpoint = Path(path), checkpoint
        if not self.path.resolve().is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
            raise RuntimeError("fake outbound must stay inside isolated scratch")
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (method TEXT, args BLOB)")
            db.execute("CREATE TABLE IF NOT EXISTS effects (method TEXT, args BLOB, response BLOB)")
        self.responses = []
        self.bot_id, self.username = 1002, "SyntheticKhadang"
        self.lost_ack = False

    def request(self, method, args, assets, store, *, before_send=None):
        if method != "getMe":
            if before_send is None or before_send() is not True:
                raise AssertionError("fake provider requires final source permission")
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO calls VALUES (?,?)", (method, canonical_bytes(args)))
        if method == "getMe":
            return Response(200, canonical_bytes({"ok": True, "result": {"id": self.bot_id, "is_bot": True, "username": self.username}}))
        scripted = self.responses.pop(0) if self.responses else None
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is not None and (scripted.status != 200 or provider_json(scripted.body).get("ok") is False):
            return scripted
        with sqlite3.connect(self.path) as db:
            next_id = db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] + 101
            def message(mid):
                return {"message_id": mid, "date": 1790913600, "chat": {"id": args.get("chat_id"), "type": "supergroup"},
                        "from": {"id": 1002, "is_bot": True}, **({"message_thread_id": args["message_thread_id"]} if "message_thread_id" in args else {})}
            result = True if method in {"answerCallbackQuery", "sendChatAction", "deleteMessage"} else \
                [message(next_id + i) for i in range(len(args["media"]))] if method == "sendMediaGroup" else message(args.get("message_id", next_id))
            response = scripted or Response(200, canonical_bytes({"ok": True, "result": result}))
            db.execute("INSERT INTO effects VALUES (?,?,?)", (method, canonical_bytes(args), response.body))
        self.checkpoint("after_fake_telegram_effect")
        if self.lost_ack:
            raise TimeoutError("invented lost response after remote acceptance")
        return response

    def count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]

    def calls(self, method=None):
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT method,args FROM calls ORDER BY rowid").fetchall()
        return [(name, provider_json(args)) for name, args in rows if method is None or name == method]
