"""Protected owner decisions and durable single-use attempt claims.

Peer arguments are KERNEL observations from broker_wire, never request fields.
The credentialed ingress is trusted to obtain raw updates over the Bot API and
verify getMe. This module does not authenticate a caller-supplied Telegram JSON
blob by itself. Only bootstrap enrollment is enabled until PR 11 publication.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sqlite3

from .contracts import canonical_bytes, create, decode, fingerprint, recovered, transition
from .identity import Denied, exact, identifier, integer, protected_path, strict_json


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", value):
        raise Denied("strict UTC timestamp required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise Denied("invalid UTC timestamp") from error


def stamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise Denied("trusted UTC clock required")
    return value.isoformat().replace("+00:00", "Z")


class OwnerPolicy:
    def __init__(self, raw, broker_policy):
        exact(raw, {"schema", "enabled", "gate_uid", "ingress_uid", "owner_id", "bot_id", "chat_id", "thread_id"})
        if raw["schema"] != "ccrelay.owner_policy.v1" or type(raw["enabled"]) is not bool:
            raise Denied("unsupported owner policy")
        self.enabled = raw["enabled"]
        self.gate_uid = integer(raw["gate_uid"])
        self.ingress_uid = integer(raw["ingress_uid"])
        excluded = {0, broker_policy.broker_uid, *broker_policy.controllers,
                    *[r.fields["uid"] for r in broker_policy.roles.values()]}
        if self.gate_uid == self.ingress_uid or {self.gate_uid, self.ingress_uid} & excluded:
            raise Denied("owner ingress/gate must be isolated from workers and broker")
        self.owner_id = integer(raw["owner_id"])
        self.bot_id = integer(raw["bot_id"])
        if type(raw["chat_id"]) is not int or raw["chat_id"] == 0:
            raise Denied("pinned chat ID required")
        self.chat_id = raw["chat_id"]
        self.thread_id = None if raw["thread_id"] is None else integer(raw["thread_id"])
        self.digest = fingerprint({"owner": raw, "broker_policy": broker_policy.digest})

    @classmethod
    def load(cls, path, broker_policy):
        protected_path(path, owners={0})
        return cls(strict_json(Path(path).read_bytes()), broker_policy)

    def require(self, peer, uid):
        if not self.enabled or peer.uid != uid:
            raise Denied("operation requires the configured protected identity")


class OwnerLedger:
    SCHEMA = "ccrelay.owner_ledger.v1"

    def __init__(self, directory, policy, *, clock=utc_now):
        if os.geteuid() != policy.gate_uid:
            raise Denied("owner ledger must run as its protected identity")
        folder = protected_path(directory, owners={0, policy.gate_uid}, directory=True, private=True)
        if folder.lstat().st_uid != policy.gate_uid:
            raise Denied("wrong owner ledger directory owner")
        self.path = folder / "owner.sqlite"
        self.policy, self.clock = policy, clock
        new = not self.path.exists() and not self.path.is_symlink()
        if new:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        protected_path(self.path, owners={0, policy.gate_uid}, private=True)
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
        try:
            if new:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE metadata (schema TEXT, policy TEXT, last_time TEXT, audit_head TEXT);
                    CREATE TABLE intents (id TEXT PRIMARY KEY, original BLOB NOT NULL, body BLOB NOT NULL,
                        approval_id TEXT UNIQUE NOT NULL, approval BLOB NOT NULL, nonce TEXT UNIQUE NOT NULL,
                        prompt BLOB);
                    CREATE TABLE decisions (update_id INTEGER PRIMARY KEY, callback_id TEXT UNIQUE NOT NULL,
                        digest TEXT NOT NULL, approval_id TEXT NOT NULL);
                    CREATE TABLE attempts (id TEXT PRIMARY KEY, action_id TEXT UNIQUE NOT NULL);
                    CREATE TABLE audit (sequence INTEGER PRIMARY KEY, body BLOB NOT NULL, digest TEXT NOT NULL);
                """)
                self.db.execute("INSERT INTO metadata VALUES (?,?,NULL,NULL)", (self.SCHEMA, policy.digest))
                self.db.execute("COMMIT")
            if self.db.execute("SELECT schema,policy FROM metadata").fetchall() != [(self.SCHEMA, policy.digest)]:
                raise Denied("unknown ledger schema/policy; preserve for explicit migration")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.verify_audit()
            if new:
                fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now = self.clock()
            encoded = stamp(now)
            previous = self.db.execute("SELECT last_time FROM metadata").fetchone()[0]
            if previous is not None and now < timestamp(previous):
                raise Denied("clock moved backwards; owner authorization held")
            self.db.execute("UPDATE metadata SET last_time=?", (encoded,))
            yield now
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def audit(self, event, subject, evidence):
        head = self.db.execute("SELECT audit_head FROM metadata").fetchone()[0]
        seq = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM audit").fetchone()[0]
        body = {"sequence": seq, "previous": head, "event": event, "subject": subject,
                "evidence": evidence, "time": self.db.execute("SELECT last_time FROM metadata").fetchone()[0]}
        digest = fingerprint(body)
        self.db.execute("INSERT INTO audit VALUES (?,?,?)", (seq, canonical_bytes(body), digest))
        self.db.execute("UPDATE metadata SET audit_head=?", (digest,))

    def verify_audit(self):
        head = None
        for expected, row in enumerate(self.db.execute("SELECT sequence,body,digest FROM audit ORDER BY sequence"), 1):
            body = strict_json(row[1])
            if row[0] != expected or body.get("sequence") != expected or body.get("previous") != head or fingerprint(body) != row[2]:
                raise Denied("audit chain mismatch; preserve for inspection")
            head = row[2]
        if self.db.execute("SELECT audit_head FROM metadata").fetchone()[0] != head:
            raise Denied("audit head mismatch")

    def _row(self, action_id):
        row = self.db.execute("SELECT id,original,body,approval_id,approval,nonce,prompt FROM intents WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise Denied("unknown owner-gated action")
        action, approval = decode(row[2]), decode(row[4])
        original = decode(row[1])
        if action.kind != "external_action" or original.kind != "external_action" or original.fields["state"] != "stored" or \
                approval.kind != "approval" or row[0] != action.id or row[3] != approval.id or \
                approval.fields["action_id"] != action.id or approval.fields["action_digest"] != action.fields["intent_digest"] or \
                original.fields["intent_digest"] != action.fields["intent_digest"] or original.id != action.id or \
                approval.fields["owner_id"] != "telegram:" + str(self.policy.owner_id):
            raise Denied("owner ledger indexes and immutable intent disagree")
        if action.fields["state"] != "stored":
            attempt = action.fields["attempt_id"]
            if approval.fields["state"] != "consumed" or approval.fields["consumed_attempt_id"] != attempt or \
                    action.fields["authorization_id"] != approval.id or \
                    self.db.execute("SELECT action_id FROM attempts WHERE id=?", (attempt,)).fetchall() != [(action.id,)]:
                raise Denied("attempt and consumed approval bindings disagree")
        elif approval.fields["state"] == "consumed":
            raise Denied("consumed approval cannot have an unattempted action")
        return action, approval, row[5], None if row[6] is None else strict_json(row[6])

    def load(self, action_id):
        return self._row(action_id)[:2]

    def enroll(self, peer, action, approval_id, expires_at):
        self.policy.require(peer, 0)  # Reviewed bootstrap only, NOT a worker claim.
        identifier(approval_id)
        action = decode(action)
        if action.kind != "external_action" or action.revision != 0 or action.fields["state"] != "stored":
            raise Denied("new immutable stored intent required")
        with self.transaction() as now:
            existing = self.db.execute("SELECT original,approval_id,approval FROM intents WHERE id=?", (action.id,)).fetchone()
            if existing:
                if existing[0] != action.encode() or existing[1] != approval_id or decode(existing[2]).fields["expires_at"] != expires_at:
                    raise Denied("replay changed action, approval or expiry")
                return self.prompt(action.id)
            if timestamp(expires_at) <= now:
                raise Denied("approval must expire in the future")
            approval = create("approval", id=approval_id, action_id=action.id,
                              action_digest=action.fields["intent_digest"], owner_id="telegram:" + str(self.policy.owner_id),
                              state="pending", owner_auth_reference=None, decided_at=None, expires_at=expires_at,
                              consumed_attempt_id=None)
            nonce = secrets.token_urlsafe(24)
            self.db.execute("INSERT INTO intents VALUES (?,?,?,?,?,?,NULL)",
                            (action.id, action.encode(), action.encode(), approval.id, approval.encode(), nonce))
            self.audit("enrolled", action.id, action.fields["intent_digest"])
            return self.prompt(action.id)

    def prompt(self, action_id):
        action, approval, nonce, _ = self._row(action_id)
        # Caller must display the EXACT parameters/digest/expiry, not agent prose.
        return {"action": action.to_dict(), "approval": approval.to_dict(),
                "approve_data": "cc1:" + nonce + ":a", "deny_data": "cc1:" + nonce + ":d"}

    def read_prompt(self, peer, action_id):
        """Protected ingress only; decoded prompts do not authenticate callers."""
        self.policy.require(peer, self.policy.ingress_uid)
        identifier(action_id)
        _, _, _, receipt = self._row(action_id)
        return {"schema": "ccrelay.owner_prompt_view.v1", "policy_digest": self.policy.digest,
                "prompt": self.prompt(action_id), "receipt": receipt}

    def bind_prompt(self, peer, action_id, receipt):
        self.policy.require(peer, self.policy.ingress_uid)
        exact(receipt, {"bot_id", "chat_id", "thread_id", "message_id"})
        integer(receipt["message_id"])
        for key, expected in (("bot_id", self.policy.bot_id), ("chat_id", self.policy.chat_id), ("thread_id", self.policy.thread_id)):
            if type(receipt[key]) is not type(expected) or receipt[key] != expected:
                raise Denied("prompt receipt is not from the pinned owner channel")
        with self.transaction() as now:
            action, approval, _, old = self._row(action_id)
            if old is not None:
                if old != receipt:
                    raise Denied("cannot rebind an approval prompt")
                return
            if approval.fields["state"] != "pending" or now >= timestamp(approval.fields["expires_at"]):
                raise Denied("approval no longer pending or has expired")
            self.db.execute("UPDATE intents SET prompt=? WHERE id=?", (canonical_bytes(receipt), action_id))
            self.audit("prompt_confirmed", action.id, fingerprint(receipt))

    def decide(self, peer, update):
        self.policy.require(peer, self.policy.ingress_uid)
        if type(update) is not dict or set(update) != {"update_id", "callback_query"}:
            raise Denied("raw owner callback update required, not approval prose")
        update_id = integer(update["update_id"], 0)
        callback = update["callback_query"]
        if type(callback) is not dict or "inline_message_id" in callback or "game_short_name" in callback:
            raise Denied("pinned message callback required")
        callback_id = callback.get("id")
        if type(callback_id) is not str or not callback_id or len(callback_id) > 256:
            raise Denied("invalid callback ID")
        sender, message = callback.get("from"), callback.get("message")
        if type(sender) is not dict or type(sender.get("id")) is not int or sender["id"] != self.policy.owner_id or sender.get("is_bot") is not False:
            raise Denied("callback sender is not the configured human owner")
        if type(message) is not dict or type(message.get("date")) is not int or message["date"] <= 0 or \
                any(key in message for key in ("forward_origin", "forward_from", "forward_from_chat", "via_bot")):
            raise Denied("accessible original approval message required")
        author = message.get("from")
        if type(author) is not dict or type(author.get("id")) is not int or author["id"] != self.policy.bot_id or author.get("is_bot") is not True:
            raise Denied("approval message did not originate from the pinned bot")
        chat = message.get("chat")
        if type(chat) is not dict or type(chat.get("id")) is not int:
            raise Denied("pinned approval chat required")
        receipt = {"bot_id": author["id"], "chat_id": chat["id"], "thread_id": message.get("message_thread_id"),
                   "message_id": integer(message.get("message_id"))}
        data = callback.get("data")
        match = re.fullmatch(r"cc1:([A-Za-z0-9_-]{32}):([ad])", data) if type(data) is str else None
        if not match:
            raise Denied("opaque approval decision required")
        event_digest = fingerprint(update)
        with self.transaction() as now:
            row = self.db.execute("SELECT id FROM intents WHERE nonce=?", (match[1],)).fetchone()
            if row is None:
                raise Denied("unknown approval nonce")
            action, approval, _, prompt = self._row(row[0])
            if prompt is None or canonical_bytes(receipt) != canonical_bytes(prompt):
                raise Denied("callback does not match the confirmed approval prompt")
            old = self.db.execute("SELECT update_id,callback_id,digest,approval_id FROM decisions WHERE update_id=? OR callback_id=?",
                                  (update_id, callback_id)).fetchall()
            if old:
                if old != [(update_id, callback_id, event_digest, approval.id)]:
                    raise Denied("conflicting callback/update replay")
                return approval.to_dict()  # Retains consumed/terminal state; never grants twice.
            revoke = approval.fields["state"] == "granted" and match[2] == "d"
            if not revoke and (approval.fields["state"] != "pending" or now >= timestamp(approval.fields["expires_at"])):
                raise Denied("approval already decided or expired")
            auth = "owner-event-" + fingerprint({"bot": self.policy.bot_id, "update": update_id, "callback": callback_id})[7:]
            if revoke:
                next_approval = transition(approval, "revoked", expected_revision=approval.revision)
            else:
                next_approval = transition(approval, "granted" if match[2] == "a" else "denied",
                                           expected_revision=approval.revision, owner_auth_reference=auth, decided_at=stamp(now))
            self.db.execute("INSERT INTO decisions VALUES (?,?,?,?)", (update_id, callback_id, event_digest, approval.id))
            self.db.execute("UPDATE intents SET approval=? WHERE id=?", (next_approval.encode(), action.id))
            self.audit("owner_decision", action.id, event_digest)
            return next_approval.to_dict()

    def claim(self, peer, action_id, digest, attempt_id):
        self.policy.require(peer, self.policy.gate_uid)
        identifier(attempt_id)
        with self.transaction() as now:
            action, approval, _, _ = self._row(action_id)
            if action.fields["intent_digest"] != digest:
                raise Denied("changed action parameters")
            if action.fields["state"] != "stored":
                if action.fields["attempt_id"] == attempt_id and approval.fields["consumed_attempt_id"] == attempt_id:
                    return {"may_execute": False, "action": action.to_dict()}
                raise Denied("action already attempted; reconcile, never blind retry")
            if approval.fields["state"] != "granted" or now >= timestamp(approval.fields["expires_at"]):
                raise Denied("authenticated unexpired owner decision required")
            consumed = transition(approval, "consumed", expected_revision=approval.revision, consumed_attempt_id=attempt_id)
            delivering = transition(action, "delivering", expected_revision=action.revision, attempt_id=attempt_id,
                                     authorization_id=approval.id)
            if self.db.execute("SELECT 1 FROM attempts WHERE id=?", (attempt_id,)).fetchone():
                raise Denied("attempt identity already belongs to another action")
            self.db.execute("INSERT INTO attempts VALUES (?,?)", (attempt_id, action.id))
            self.db.execute("UPDATE intents SET body=?,approval=? WHERE id=?", (delivering.encode(), consumed.encode(), action.id))
            self.audit("attempt_claimed", action.id, fingerprint({"attempt": attempt_id, "intent": digest}))
            return {"may_execute": True, "action": delivering.to_dict()}

    def recover(self, peer, action_id):
        self.policy.require(peer, self.policy.gate_uid)
        with self.transaction():
            action, _, _, _ = self._row(action_id)
            result = recovered(action)
            if result != action:
                self.db.execute("UPDATE intents SET body=? WHERE id=?", (result.encode(), action.id))
                self.audit("outcome_unknown", action.id, action.fields["intent_digest"])
            return result

    def confirm(self, peer, action_id, attempt_id, receipt_id, evidence_id):
        self.policy.require(peer, self.policy.gate_uid)
        with self.transaction():
            action, _, _, _ = self._row(action_id)
            if action.fields["attempt_id"] != attempt_id:
                raise Denied("receipt binds another attempt")
            result = transition(action, "confirmed", expected_revision=action.revision,
                                receipt_id=receipt_id, outcome_evidence_id=evidence_id)
            self.db.execute("UPDATE intents SET body=? WHERE id=?", (result.encode(), action.id))
            self.audit("outcome_confirmed", action.id, fingerprint({"receipt": receipt_id, "evidence": evidence_id}))
            return result

    def snapshot(self, destination):
        destination = Path(destination)
        protected_path(destination.parent, owners={0, self.policy.gate_uid}, directory=True, private=True)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        target = sqlite3.connect(str(destination))
        try:
            self.db.backup(target)
        finally:
            target.close()
