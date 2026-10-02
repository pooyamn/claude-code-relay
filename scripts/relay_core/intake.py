"""Durable Telegram intake, independent of native/model/media execution.

Raw provider JSON may contain finite coordinates. It is kept separately from
strict action contracts: accepting a provider float cannot authorize an action.
Only the protected Bot API ingress may call this writer. Target UID/filesystem
enforcement must still be demonstrated on Linux/WSL.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time

from .artifacts import fsync_dir, write_new
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, protected_path, strict_json


MAX_RESPONSE = 8 * 1024 * 1024


def sha(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def provider_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Denied("duplicate provider JSON key")
            result[key] = value
        return result

    def validate(value, depth=0):
        if depth > 64:
            raise Denied("provider JSON nesting exceeds limit")
        if type(value) is str:
            value.encode("utf-8")
        elif type(value) is float:
            if not math.isfinite(value):
                raise Denied("nonfinite provider value")
        elif type(value) is list:
            for item in value:
                validate(item, depth + 1)
        elif type(value) is dict:
            for key, item in value.items():
                validate(key, depth + 1)
                validate(item, depth + 1)
        elif value is not None and type(value) not in {int, bool}:
            raise Denied("invalid provider value")
    if type(raw) is not bytes or len(raw) > MAX_RESPONSE:
        raise Denied("bounded raw provider response required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
        validate(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Denied("invalid provider JSON") from error


def provider_bytes(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    provider_json(body)
    return body


def update_id(value):
    integer(value, 0)
    if value >= (1 << 63) - 1:
        raise Denied("update ID exceeds storage range")
    return value


class IntakePolicy:
    def __init__(self, raw, owner_policy, broker_policy):
        exact(raw, {"schema", "bot_username", "allow_users", "allow_chats", "bindings"})
        if raw["schema"] != "ccrelay.intake_policy.v1":
            raise Denied("unsupported intake policy")
        self.bot_username = identifier(raw["bot_username"])
        for key in ("allow_users", "allow_chats"):
            if type(raw[key]) is not list or any(type(item) is not int for item in raw[key]) or len(set(raw[key])) != len(raw[key]):
                raise Denied("explicit unique intake allowlists required")
        self.allow_users = frozenset(integer(item) for item in raw["allow_users"])
        if owner_policy.owner_id not in self.allow_users:
            raise Denied("owner must be explicitly allowed; empty lists admit nobody")
        if any(type(item) is not int or item == 0 for item in raw["allow_chats"]):
            raise Denied("invalid allowed chat")
        self.allow_chats = frozenset(raw["allow_chats"])
        if type(raw["bindings"]) is not list:
            raise Denied("explicit bindings required")
        bindings = {}
        for item in raw["bindings"]:
            exact(item, {"chat_id", "thread_id", "role_id", "session_id"})
            if type(item["chat_id"]) is not int or item["chat_id"] == 0:
                raise Denied("invalid binding chat")
            thread = None if item["thread_id"] is None else integer(item["thread_id"])
            key = (item["chat_id"], thread)
            role_id, session = identifier(item["role_id"]), identifier(item["session_id"])
            if key in bindings or role_id not in broker_policy.roles or not broker_policy.roles[role_id].fields["enabled"]:
                raise Denied("unknown, disabled or duplicate route")
            bindings[key] = {"role_id": role_id, "session_id": session}
        self.bindings, self.owner = bindings, owner_policy
        self.digest = fingerprint({"intake": raw, "owner_policy": owner_policy.digest, "broker_policy": broker_policy.digest})

    @classmethod
    def load(cls, path, owner_policy, broker_policy):
        protected_path(path, owners={0})
        return cls(strict_json(Path(path).read_bytes()), owner_policy, broker_policy)

    def route(self, update):
        result = {"schema": "ccrelay.intake_route.v1", "policy_digest": self.digest, "decision": "held",
                  "reason": "unsupported_update", "lane": "none", "priority": 999, "operation": None,
                  "target": None, "mode": None, "chat_id": None, "thread_id": None, "sender_id": None,
                  "message_id": None, "callback_id": None, "media": []}
        if len(set(update) - {"update_id"}) != 1:
            return dict(result, reason="malformed_update")
        kind = "message" if "message" in update else "callback_query" if "callback_query" in update else None
        if kind is None:
            return result
        try:
            callback = update.get("callback_query") if kind == "callback_query" else None
            message = update["message"] if callback is None else callback.get("message")
            sender = message.get("from") if callback is None else callback.get("from")
            if type(message) is not dict or type(sender) is not dict:
                raise Denied("missing message/sender")
            uid = integer(sender.get("id"))
            chat = message.get("chat")
            if type(chat) is not dict or type(chat.get("id")) is not int or chat["id"] == 0:
                raise Denied("invalid chat")
            thread = message.get("message_thread_id")
            if thread is not None:
                integer(thread)
            elif chat.get("is_forum") is True:
                thread = 1  # Telegram general topic; no fallback to another topic.
            message_id = integer(message.get("message_id"))
            result.update(chat_id=chat["id"], thread_id=thread, sender_id=uid, message_id=message_id)
            if sender.get("is_bot") is not False or (uid not in self.allow_users and chat["id"] not in self.allow_chats):
                return dict(result, decision="rejected", reason="sender_not_allowed")
            target = self.bindings.get((chat["id"], thread)) or self.bindings.get((chat["id"], None))
            target = None if target is None else dict(target)
            result["target"] = target
            owner = uid == self.owner.owner_id
            if callback is not None:
                if type(callback.get("id")) is not str or not callback["id"] or len(callback["id"]) > 256:
                    raise Denied("invalid callback ID")
                result["callback_id"] = callback["id"]
                data = callback.get("data")
                if type(data) is not str or not 1 <= len(data.encode()) <= 64:
                    raise Denied("invalid callback data")
                if data.startswith("cc1:"):
                    if not owner:
                        return dict(result, decision="rejected", reason="owner_required")
                    # Exact nonce/prompt/provenance validation remains in PR 3's
                    # gate; this route never converts a claim into authorization.
                    return dict(result, decision="accept", reason="owner_gate_required", lane="owner_approval",
                                priority=0, operation="owner_callback", target=None)
                result.update(operation="selection", lane="owner_steer" if owner else "message",
                              priority=20 if owner else 100, mode="prefer_steer" if owner else "runtime_input")
            else:
                text = message.get("text", message.get("caption", ""))
                if type(text) is not str:
                    raise Denied("invalid message text")
                command = re.fullmatch(r"\s*/?(stop|pause|resume|cancel|interrupt|esc)(?:@([A-Za-z0-9_]+))?(?:\s+(all|[A-Za-z0-9_.-]+))?\s*", text, re.I)
                if command:
                    if not owner or any(key in message for key in ("forward_origin", "forward_from", "via_bot")):
                        return dict(result, decision="rejected", reason="direct_owner_control_required")
                    if command[2] is not None and command[2].lower() != self.bot_username.lower():
                        return dict(result, reason="control_addressed_to_other_bot")
                    operation = command[1].lower()
                    operation = "interrupt" if operation in {"cancel", "esc"} else operation
                    scope = command[3]
                    owner_channel = chat["id"] == self.owner.chat_id and thread == self.owner.thread_id
                    if scope is not None:
                        if not owner_channel:
                            return dict(result, decision="rejected", reason="owner_control_channel_required")
                        if scope.lower() == "all":
                            target = {"scope": "all"}
                        else:
                            sessions = {entry["session_id"]: entry for entry in self.bindings.values()}
                            selected = sessions.get(scope)
                            target = None if selected is None else dict(selected)
                    if target is None:
                        return dict(result, reason="control_target_unbound")
                    return dict(result, decision="accept", reason="owner_control", lane="owner_control",
                                priority=10, operation=operation, target=target)
                # Media references, including all photo variants, survive even
                # if download/transcription is unavailable. No I/O in routing.
                for media_kind in ("photo", "document", "video", "audio", "voice", "video_note", "animation", "sticker", "live_photo"):
                    media = message.get(media_kind)
                    if media is None:
                        continue
                    items = media if media_kind == "photo" and type(media) is list else [media]
                    for item in items:
                        if type(item) is not dict or type(item.get("file_id")) is not str or not item["file_id"]:
                            raise Denied("invalid media reference")
                        if any(item.get(key) is not None and type(item[key]) is not str for key in ("file_unique_id", "mime_type", "file_name")):
                            raise Denied("invalid media metadata")
                        result["media"].append({"kind": media_kind, "file_id": item["file_id"],
                                                "file_unique_id": item.get("file_unique_id"),
                                                "mime_type": item.get("mime_type"), "file_name": item.get("file_name")})
                result.update(operation="message", lane="owner_steer" if owner else "message",
                              priority=20 if owner else 100, mode="prefer_steer" if owner else "runtime_input")
            if target is None:
                return dict(result, reason="unbound", lane="none", priority=999)
            return dict(result, decision="accept", reason="bound")
        except (Denied, AttributeError, KeyError, UnicodeError):
            return dict(result, decision="held", reason="malformed_update", lane="none", priority=999)


class IntakeLedger:
    SCHEMA = "ccrelay.intake_ledger.v1"

    def __init__(self, directory, policy, *, clock=time.time, checkpoint=lambda _: None):
        self.uid = policy.owner.ingress_uid
        if os.geteuid() != self.uid:
            raise Denied("intake requires its protected ingress UID")
        self.folder = protected_path(directory, owners={0, self.uid}, directory=True, private=True)
        if self.folder.lstat().st_uid != self.uid:
            raise Denied("wrong intake state owner")
        if (self.folder / "offset").exists() or (self.folder / "offset").is_symlink():
            raise Denied("legacy offset requires reviewed migration; no empty-state fallback")
        self.policy, self.clock, self.checkpoint = policy, clock, checkpoint
        self.batches = self.folder / "batches"
        if not self.batches.exists() and not self.batches.is_symlink():
            self.batches.mkdir(mode=0o700)
            fsync_dir(self.folder)
        protected_path(self.batches, owners={0, self.uid}, directory=True, private=True)
        self.path = self.folder / "intake.sqlite"
        new = not self.path.exists() and not self.path.is_symlink()
        if new:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        protected_path(self.path, owners={0, self.uid}, private=True)
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
        try:
            if new:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE metadata (schema TEXT, bot_id INTEGER, policy TEXT,
                        next_offset INTEGER, last_batch TEXT, retry_at INTEGER, conflicts INTEGER);
                    CREATE TABLE responses (id TEXT PRIMARY KEY, raw_digest TEXT NOT NULL,
                        request_offset INTEGER NOT NULL, next_offset INTEGER NOT NULL, captured_at INTEGER NOT NULL);
                    CREATE TABLE events (id INTEGER PRIMARY KEY, digest TEXT NOT NULL, body BLOB NOT NULL,
                        route BLOB NOT NULL, priority INTEGER NOT NULL, state TEXT NOT NULL,
                        batch_id TEXT NOT NULL, dispatch_id TEXT UNIQUE, sequence INTEGER UNIQUE NOT NULL);
                    CREATE TABLE dispatches (id TEXT PRIMARY KEY, update_id INTEGER UNIQUE NOT NULL,
                        priority INTEGER NOT NULL, body BLOB NOT NULL, state TEXT NOT NULL);
                """)
                self.db.execute("INSERT INTO metadata VALUES (?,?,?,0,NULL,0,0)", (self.SCHEMA, policy.owner.bot_id, policy.digest))
                self.db.execute("COMMIT")
            if self.db.execute("SELECT schema,bot_id,policy FROM metadata").fetchall() != [(self.SCHEMA, policy.owner.bot_id, policy.digest)]:
                raise Denied("unknown intake schema/bot/policy; preserve for explicit migration")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=WAL")
            if new:
                fsync_dir(self.folder)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _read_batch(self, batch_id):
        if type(batch_id) is not str or not re.fullmatch(r"[a-f0-9]{64}", batch_id):
            raise Denied("invalid intake batch ID")
        path = self.batches / (batch_id + ".batch")
        protected_path(path, owners={0, self.uid}, private=True)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > MAX_RESPONSE + 65536:
                raise Denied("invalid intake spool file")
            with os.fdopen(fd, "rb", closefd=False) as source:
                body = source.read(MAX_RESPONSE + 65537)
        finally:
            os.close(fd)
        if sha(body)[7:] != batch_id:
            raise Denied("intake spool digest mismatch")
        header_raw, separator, raw = body.partition(b"\n")
        if not separator:
            raise Denied("incomplete intake spool")
        header = strict_json(header_raw)
        exact(header, {"schema", "bot_id", "policy_digest", "request_offset", "captured_at", "raw_digest"})
        if header["schema"] != "ccrelay.intake_batch.v1" or header["bot_id"] != self.policy.owner.bot_id or \
                header["policy_digest"] != self.policy.digest or header["raw_digest"] != sha(raw):
            raise Denied("spool schema/bot/policy/bytes mismatch")
        update_id(header["request_offset"])
        integer(header["captured_at"], 0)
        return header, raw

    def capture(self, raw, request_offset):
        update_id(request_offset)  # Negative offsets/drop-pending are never used.
        if type(raw) is not bytes or len(raw) > MAX_RESPONSE:
            raise Denied("oversized/invalid intake response; do not acknowledge")
        header = {"schema": "ccrelay.intake_batch.v1", "bot_id": self.policy.owner.bot_id,
                  "policy_digest": self.policy.digest, "request_offset": request_offset,
                  "captured_at": int(self.clock() * 1000), "raw_digest": sha(raw)}
        body = canonical_bytes(header) + b"\n" + raw
        batch_id = sha(body)[7:]
        target = self.batches / (batch_id + ".batch")
        if not target.exists() and not target.is_symlink():
            temporary = self.batches / ("pending-" + secrets.token_hex(16))
            write_new(temporary, body, 0o600)
            self.checkpoint("after_file_flush")
            os.rename(temporary, target)
            fsync_dir(self.batches)
        self.checkpoint("after_spool")
        return self._commit_batch(batch_id, poll_success=True)

    def _commit_batch(self, batch_id, *, poll_success=False):
        header, raw = self._read_batch(batch_id)
        response = provider_json(raw)
        if type(response) is not dict or response.get("ok") is not True or type(response.get("result")) is not list or len(response["result"]) > 100:
            raise Denied("invalid successful getUpdates response; do not acknowledge")
        updates = response["result"]
        ids, values = set(), []
        for update in updates:
            if type(update) is not dict or "update_id" not in update:
                raise Denied("update object and ID required")
            uid = update_id(update.get("update_id"))
            if uid in ids:
                raise Denied("duplicate update ID in provider batch")
            ids.add(uid)
            body = provider_bytes(update)
            route = self.policy.route(update)
            values.append((uid, sha(body), body, canonical_bytes(route), route))
        # IDs can restart randomly after a week of inactivity. This is the ACK
        # for this persisted batch, NOT a permanent numerical high-water mark.
        next_offset = max(ids) + 1 if ids else 0
        with self.transaction():
            if self.db.execute("SELECT 1 FROM responses WHERE id=?", (batch_id,)).fetchone():
                self.db.execute("UPDATE metadata SET next_offset=?,last_batch=?", (next_offset, batch_id))
                if poll_success:
                    self.db.execute("UPDATE metadata SET retry_at=0,conflicts=0")
                return next_offset
            for uid, digest, body, encoded_route, route in values:
                old = self.db.execute("SELECT digest,body FROM events WHERE id=?", (uid,)).fetchone()
                if old is not None:
                    if old != (digest, body):
                        raise Denied("conflicting replay; preserve both batches, do not acknowledge")
                    continue
                state = "stored" if route["decision"] == "accept" else route["decision"]
                sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events").fetchone()[0]
                self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,NULL,?)",
                                (uid, digest, body, encoded_route, route["priority"], state, batch_id, sequence))
            self.db.execute("INSERT INTO responses VALUES (?,?,?,?,?)", (batch_id, header["raw_digest"], header["request_offset"], next_offset, header["captured_at"]))
            self.db.execute("UPDATE metadata SET next_offset=?,last_batch=?", (next_offset, batch_id))
            if poll_success:
                self.db.execute("UPDATE metadata SET retry_at=0,conflicts=0")
            self.checkpoint("before_db_commit")
        self.checkpoint("after_db_commit")
        return next_offset

    def reconcile_spool(self):
        # Incomplete temporary files are retained but never interpreted as a
        # response. Reconcile fully fsynced orphans; committed batches keep their
        # original routes instead of being rerouted on every restart.
        orphans = []
        for path in self.batches.glob("*.batch"):
            header, _ = self._read_batch(path.stem)
            if not self.db.execute("SELECT 1 FROM responses WHERE id=?", (path.stem,)).fetchone():
                orphans.append((header["captured_at"], path.stem))
        for _, batch_id in sorted(orphans):
            self._commit_batch(batch_id)
        return len(orphans)

    def state(self):
        row = self.db.execute("SELECT next_offset,last_batch,retry_at,conflicts FROM metadata").fetchone()
        return dict(zip(("next_offset", "last_batch", "retry_at", "conflicts"), row))

    def event(self, uid, *, _batch_cache=None):
        row = self.db.execute("SELECT id,digest,body,route,priority,state,batch_id,dispatch_id FROM events WHERE id=?", (uid,)).fetchone()
        if row is None:
            raise Denied("unknown intake event")
        update, route = provider_json(row[2]), strict_json(row[3])
        if update.get("update_id") != row[0] or sha(row[2]) != row[1] or route.get("policy_digest") != self.policy.digest or route.get("priority") != row[4]:
            raise Denied("intake row/index disagreement")
        if _batch_cache is None or row[6] not in _batch_cache:
            _, raw = self._read_batch(row[6])
            response = provider_json(raw)
            if type(response) is not dict or response.get("ok") is not True or type(response.get("result")) is not list:
                raise Denied("event batch is not a successful provider response")
            batch_updates = {item.get("update_id"): provider_bytes(item) for item in response["result"] if type(item) is dict}
            if _batch_cache is not None:
                _batch_cache[row[6]] = batch_updates
        else:
            batch_updates = _batch_cache[row[6]]
        if batch_updates.get(row[0]) != row[2]:
            raise Denied("event bytes do not match their original provider batch")
        if route.get("schema") != "ccrelay.intake_route.v1" or row[5] not in {"stored", "held", "rejected", "ready"}:
            raise Denied("unsupported route or dispatch state")
        if (row[5] == "ready") != (row[7] is not None):
            raise Denied("dispatch identity and event state disagree")
        return {"update_id": row[0], "update_digest": row[1], "update": update, "route": route,
                "state": row[5], "batch_id": row[6], "dispatch_id": row[7]}

    def materialize(self, limit=100):
        integer(limit)
        if limit > 100:
            raise Denied("bounded dispatch batch required")
        created = []
        batch_cache = {}
        with self.transaction():
            ids = [row[0] for row in self.db.execute("SELECT id FROM events WHERE state='stored' ORDER BY priority,sequence LIMIT ?", (limit,))]
            for uid in ids:
                event = self.event(uid, _batch_cache=batch_cache)
                dispatch_id = "tg-" + str(self.policy.owner.bot_id) + "-" + str(uid)
                dispatch = {"schema": "ccrelay.inbound_dispatch.v1", "id": dispatch_id, "bot_id": self.policy.owner.bot_id,
                            "update_id": uid, "update_digest": event["update_digest"], "batch_id": event["batch_id"], "route": event["route"]}
                self.db.execute("INSERT INTO dispatches VALUES (?,?,?,?,?)", (dispatch_id, uid, event["route"]["priority"], canonical_bytes(dispatch), "pending"))
                self.db.execute("UPDATE events SET state='ready',dispatch_id=? WHERE id=?", (dispatch_id, uid))
                created.append(dispatch_id)
            self.checkpoint("before_dispatch_commit")
        self.checkpoint("after_dispatch_commit")
        return created

    def pending_dispatches(self):
        result, batch_cache = [], {}
        for row in self.db.execute("SELECT d.id,d.update_id,d.priority,d.body FROM dispatches d JOIN events e ON e.id=d.update_id WHERE d.state='pending' ORDER BY d.priority,e.sequence"):
            value = strict_json(row[3])
            exact(value, {"schema", "id", "bot_id", "update_id", "update_digest", "batch_id", "route"})
            event = self.event(row[1], _batch_cache=batch_cache)
            if value["schema"] != "ccrelay.inbound_dispatch.v1" or value["id"] != row[0] or value["id"] != event["dispatch_id"] or \
                    value["bot_id"] != self.policy.owner.bot_id or value["update_id"] != row[1] or \
                    value["update_digest"] != event["update_digest"] or value["batch_id"] != event["batch_id"] or \
                    canonical_bytes(value["route"]) != canonical_bytes(event["route"]) or value["route"]["priority"] != row[2]:
                raise Denied("dispatch indexes and original event disagree")
            result.append(value)
        return result

    def poll_failure(self, code, retry_after=0):
        integer(code, 0)
        integer(retry_after, 0)
        with self.transaction():
            if code == 409:
                self.db.execute("UPDATE metadata SET conflicts=conflicts+1")
            elif code == 429:
                if retry_after <= 0 or retry_after > 86400:
                    raise Denied("unsupported poll cooldown; operator inspection required")
                self.db.execute("UPDATE metadata SET retry_at=?", (int(self.clock()) + retry_after,))
        return self.state()

    def snapshot(self, destination):
        destination = Path(destination)
        protected_path(destination.parent, owners={0, self.uid}, directory=True, private=True)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        target = sqlite3.connect(str(destination))
        try:
            self.db.backup(target)
        finally:
            target.close()
        fsync_dir(destination.parent)
