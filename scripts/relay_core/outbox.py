"""Protected durable delivery ledger; storing an intent grants no authority.

Only a trusted driver may claim/submit/reconcile. None of those operations are
worker RPCs. A claim is committed BEFORE an adapter call, and a replay never
returns permission to execute. The lifetime lock fences local recovery against
a still-running submitter; it cannot fence another host or a native provider.
Evidence envelopes bind outcomes to the exact attempt and adapter plan, but
their provenance must be verified by the trusted adapter, not by JSON decoding.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3

from .contracts import (canonical_bytes, decode, fingerprint, intent_payload,
                        recovered, transition)
from .identity import Denied, exact, identifier, integer, protected_path


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_plan(plan, record):
    exact(plan, {"schema", "intent_id", "intent_digest", "adapter_id", "target",
                 "parameters", "authorization_id"})
    if plan["schema"] != "ccrelay.delivery_plan.v1" or plan["intent_id"] != record.id or \
            plan["intent_digest"] != record.fields["intent_digest"]:
        raise Denied("delivery plan is not bound to this intent")
    for key in ("adapter_id", "authorization_id"):
        identifier(plan[key])
    if type(plan["target"]) is not dict or not plan["target"] or type(plan["parameters"]) is not dict:
        raise Denied("exact target and parameter objects required")
    canonical_bytes(plan)
    return plan


class DeliveryLedger:
    def __init__(self, directory, *, owner_uid, policy_digest, checkpoint=lambda _: None):
        integer(owner_uid)
        if os.geteuid() != owner_uid:
            raise Denied("outbox must run as its protected owner")
        if type(policy_digest) is not str or len(policy_digest) != 71 or not policy_digest.startswith("sha256:") or \
                any(c not in "0123456789abcdef" for c in policy_digest[7:]):
            raise Denied("protected outbox policy digest required")
        self.owner_uid, self.policy_digest, self.checkpoint = owner_uid, policy_digest, checkpoint
        self.folder = protected_path(directory, owners={0, owner_uid}, directory=True, private=True)
        if self.folder.lstat().st_uid != owner_uid:
            raise Denied("outbox directory has wrong owner")
        self.lock_fd = os.open(self.folder / "outbox.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.connection = None
        try:
            protected_path(self.folder / "outbox.lock", owners={owner_uid}, private=True)
            if os.fstat(self.lock_fd).st_nlink != 1:
                raise Denied("linked outbox lock refused")
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.path = self.folder / "outbox.sqlite"
            new = not self.path.exists() and not self.path.is_symlink()
            if new:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            protected_path(self.path, owners={owner_uid}, private=True)
            if self.path.lstat().st_nlink != 1:
                raise Denied("linked outbox database refused")
            self.connection = sqlite3.connect(str(self.path), isolation_level=None)
            if new:
                with self._transaction():
                    self.connection.execute("CREATE TABLE metadata (schema TEXT NOT NULL, policy_digest TEXT NOT NULL)")
                    self.connection.execute("INSERT INTO metadata VALUES (?,?)", ("ccrelay.outbox.v1", policy_digest))
                    self.connection.execute("""CREATE TABLE intents (
                        id TEXT PRIMARY KEY, kind TEXT NOT NULL, root_id TEXT NOT NULL,
                        sender TEXT NOT NULL, recipient TEXT, state TEXT NOT NULL,
                        revision INTEGER NOT NULL, attempt_id TEXT UNIQUE,
                        record BLOB NOT NULL, context BLOB NOT NULL, context_digest TEXT NOT NULL,
                        plan BLOB, plan_digest TEXT, hold_reason TEXT)""")
                    self.connection.execute("""CREATE TABLE evidence (
                        id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                        digest TEXT NOT NULL, body BLOB NOT NULL)""")
            metadata = self.connection.execute("SELECT schema,policy_digest FROM metadata").fetchall()
            if metadata != [("ccrelay.outbox.v1", policy_digest)]:
                raise Denied("unsupported outbox schema/policy; preserve database for migration")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA journal_mode=WAL")
            if new:
                fsync_directory(self.folder)
            # Fenced by the lifetime lock, so this cannot recover a live local
            # adapter attempt. Unknown records are never reset for resubmission.
            self.recover_inflight()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    @contextmanager
    def _transaction(self):
        self._check_lock()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _check_lock(self):
        held = os.fstat(self.lock_fd)
        current = (self.folder / "outbox.lock").lstat()
        if (held.st_dev, held.st_ino, held.st_nlink) != (current.st_dev, current.st_ino, 1):
            raise Denied("outbox lifetime lock changed")

    def load(self, intent_id):
        self._check_lock()
        row = self.connection.execute("SELECT * FROM intents WHERE id=?", (identifier(intent_id),)).fetchone()
        if row is None:
            return None
        record = decode(row[8])
        data = record.to_dict()
        sender = data.get("from_session_id", data.get("requested_by_session_id"))
        if (record.id, record.kind, data["root_task_id"], sender, data.get("to_session_id"),
                data["state"], record.revision, data["attempt_id"]) != row[:8]:
            raise Denied("outbox index and record disagree")
        # decode() rejects duplicate keys, floats, unknown schemas and oversized
        # contracts. Context/plan/evidence are bounded canonical JSON too.
        from .identity import strict_json
        context = strict_json(row[9])
        if type(context) is not dict or fingerprint(context) != row[10]:
            raise Denied("outbox context changed")
        plan = None if row[11] is None else strict_json(row[11])
        if (plan is None) != (row[12] is None) or (data["attempt_id"] is None) != (plan is None):
            raise Denied("outbox attempt has no exact plan")
        if plan is not None:
            validate_plan(plan, record)
            if fingerprint(plan) != row[12] or (record.kind == "external_action" and
                    data["authorization_id"] != plan["authorization_id"]):
                raise Denied("outbox plan/authorization changed")
        if row[13] is not None:
            identifier(row[13])
            if data["state"] != "stored":
                raise Denied("only an unsubmitted intent may be held")
        for evidence_id in (data["receipt_id"], data["outcome_evidence_id"]):
            if evidence_id is not None:
                evidence = self._evidence(evidence_id)
                self._validate_evidence(evidence, record, row[12])
                expected = "accepted" if data["state"] == "confirmed" else "rejected"
                if evidence["outcome"] != expected:
                    raise Denied("record outcome disagrees with evidence")
        return {"record": record, "context": context, "plan": plan, "plan_digest": row[12], "hold_reason": row[13]}

    def store(self, record, context):
        if record.kind not in {"message", "external_action"} or record.fields["state"] != "stored" or record.revision != 0:
            raise Denied("only a new unsubmitted delivery intent may be enrolled")
        identifier(record.id)
        if type(context) is not dict or not context:
            raise Denied("protected provenance context required")
        canonical_bytes(context)
        data = record.to_dict()
        if record.kind == "external_action" and data["authorization_id"] is not None:
            raise Denied("new external intent has no consumed authorization yet")
        # Keep frame-size aligned with broker transport for every persisted part.
        if any(len(value) > 65536 for value in (record.encode(), canonical_bytes(context))):
            raise Denied("outbox intent/context exceeds protected frame size")
        with self._transaction():
            old = self.load(record.id)
            if old is not None:
                if intent_payload(record.kind, old["record"].fields) != intent_payload(record.kind, record.fields) or \
                        canonical_bytes(old["context"]) != canonical_bytes(context):
                    raise Denied("stable intent ID reused for different parameters/provenance")
                return old
            self.connection.execute("INSERT INTO intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                record.id, record.kind, data["root_task_id"],
                data.get("from_session_id", data.get("requested_by_session_id")), data.get("to_session_id"),
                "stored", 0, None, record.encode(), canonical_bytes(context), fingerprint(context), None, None, None))
            self.checkpoint("before_store_commit")
        self.checkpoint("after_store_commit")
        return self.load(record.id)

    def _update(self, record, *, plan=None, hold=None):
        old = self.load(record.id)
        chosen = old["plan"] if plan is None else plan
        self.connection.execute("UPDATE intents SET state=?,revision=?,attempt_id=?,record=?,plan=?,plan_digest=?,hold_reason=? WHERE id=?", (
            record.fields["state"], record.revision, record.fields["attempt_id"], record.encode(),
            None if chosen is None else canonical_bytes(chosen), None if chosen is None else fingerprint(chosen), hold, record.id))

    def hold(self, intent_id, reason):
        identifier(reason)
        with self._transaction():
            current = self.load(intent_id)
            if current is None or current["record"].fields["state"] != "stored":
                raise Denied("only unsubmitted intent may be retained on hold")
            self._update(current["record"], hold=reason)
        return self.load(intent_id)

    def release_hold(self, intent_id):
        """Trusted driver only, AFTER revalidating target and authorization."""
        with self._transaction():
            current = self.load(intent_id)
            if current is None or current["record"].fields["state"] != "stored":
                raise Denied("only unsubmitted intent may leave a hold")
            self._update(current["record"])
        return self.load(intent_id)

    def claim(self, intent_id, attempt_id, plan, *, expected_revision):
        """Trusted driver only, AFTER all gates. Replay returns may_execute=False."""
        identifier(attempt_id)
        with self._transaction():
            current = self.load(intent_id)
            if current is None:
                raise Denied("unknown intent")
            record = current["record"]
            validate_plan(plan, record)
            if len(canonical_bytes(plan)) > 65536:
                raise Denied("delivery plan too large")
            if record.fields["attempt_id"] is not None:
                if record.fields["attempt_id"] != attempt_id or fingerprint(plan) != current["plan_digest"]:
                    raise Denied("intent already has a different immutable attempt")
                return {"may_execute": False, **current}
            if record.fields["state"] != "stored" or current["hold_reason"] is not None:
                raise Denied("intent is terminal or held; driver must revalidate a hold")
            changes = {"attempt_id": attempt_id}
            if record.kind == "external_action":
                changes["authorization_id"] = plan["authorization_id"]
            claimed = transition(record, "delivering", expected_revision=expected_revision, **changes)
            self._update(claimed, plan=plan)
            self.checkpoint("before_claim_commit")
        self.checkpoint("after_claim_commit")
        return {"may_execute": True, **self.load(intent_id)}

    def submitted(self, intent_id, attempt_id):
        with self._transaction():
            current = self.load(intent_id)
            record = self._attempt(current, attempt_id)
            if record.fields["state"] != "delivering":
                raise Denied("only the freshly claimed attempt may be submitted")
            self._update(transition(record, "submitted", expected_revision=record.revision))
        self.checkpoint("after_submit_commit")

    @staticmethod
    def _attempt(current, attempt_id):
        identifier(attempt_id)
        if current is None or current["record"].fields["attempt_id"] != attempt_id:
            raise Denied("attempt does not match intent")
        return current["record"]

    def unknown(self, intent_id, attempt_id):
        with self._transaction():
            record = self._attempt(self.load(intent_id), attempt_id)
            if record.fields["state"] in {"delivering", "submitted"}:
                self._update(recovered(record))
            elif record.fields["state"] != "unknown":
                raise Denied("terminal outcome cannot become unknown")

    def recover_inflight(self):
        with self._transaction():
            for (intent_id,) in self.connection.execute("SELECT id FROM intents WHERE state IN ('delivering','submitted')").fetchall():
                self._update(recovered(self.load(intent_id)["record"]))

    def _evidence(self, evidence_id):
        from .identity import strict_json
        row = self.connection.execute("SELECT intent_id,attempt_id,digest,body FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        if row is None:
            raise Denied("missing outcome evidence")
        evidence = strict_json(row[3])
        exact(evidence, {"schema", "id", "intent_id", "intent_digest", "attempt_id", "plan_digest",
                         "outcome", "provider_reference", "payload"})
        if evidence["id"] != evidence_id or (evidence["intent_id"], evidence["attempt_id"], fingerprint(evidence)) != row[:3]:
            raise Denied("outcome evidence changed")
        return evidence

    @staticmethod
    def _validate_evidence(evidence, record, plan_digest):
        exact(evidence, {"schema", "id", "intent_id", "intent_digest", "attempt_id", "plan_digest",
                         "outcome", "provider_reference", "payload"})
        for key in ("id", "attempt_id"):
            identifier(evidence[key])
        if evidence["schema"] != "ccrelay.delivery_evidence.v1" or type(evidence["outcome"]) is not str or \
                evidence["outcome"] not in {"accepted", "rejected"} or \
                (evidence["intent_id"], evidence["intent_digest"], evidence["attempt_id"], evidence["plan_digest"]) != \
                (record.id, record.fields["intent_digest"], record.fields["attempt_id"], plan_digest):
            raise Denied("outcome evidence is not bound to this exact attempt/plan")
        if type(evidence["provider_reference"]) is not str or not evidence["provider_reference"] or \
                type(evidence["payload"]) is not dict or len(canonical_bytes(evidence)) > 65536:
            raise Denied("bounded provider evidence required")

    def reconcile(self, evidence):
        """Trusted adapter's verified evidence only; no worker-supplied receipt."""
        exact(evidence, {"schema", "id", "intent_id", "intent_digest", "attempt_id", "plan_digest",
                         "outcome", "provider_reference", "payload"})
        with self._transaction():
            current = self.load(evidence["intent_id"])
            record = self._attempt(current, evidence["attempt_id"])
            self._validate_evidence(evidence, record, current["plan_digest"])
            row = self.connection.execute("SELECT digest FROM evidence WHERE id=?", (evidence["id"],)).fetchone()
            if row is not None and row[0] != fingerprint(evidence):
                raise Denied("outcome evidence ID reused with changed content")
            state = "confirmed" if evidence["outcome"] == "accepted" else "failed"
            if record.fields["state"] in {"confirmed", "failed"}:
                if record.fields["state"] != state or record.fields["outcome_evidence_id"] != evidence["id"] or row is None:
                    raise Denied("terminal outcome cannot be replaced")
                return current
            if record.fields["state"] not in {"delivering", "submitted", "unknown"}:
                raise Denied("unsubmitted intent has no provider outcome")
            if row is None:
                self.connection.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", (
                    evidence["id"], record.id, evidence["attempt_id"], fingerprint(evidence), canonical_bytes(evidence)))
            # Contract v1 only allows negative submitted evidence through unknown.
            if state == "failed" and record.fields["state"] == "submitted":
                record = recovered(record)
            changes = {"outcome_evidence_id": evidence["id"]}
            if state == "confirmed":
                changes["receipt_id"] = evidence["id"]
            final = transition(record, state, expected_revision=record.revision, **changes)
            self._update(final)
            self.checkpoint("before_receipt_commit")
        self.checkpoint("after_receipt_commit")
        return self.load(record.id)

    def messages_for(self, session_id, limit, *, before_id=None):
        identifier(session_id)
        integer(limit)
        if limit > 100:
            raise Denied("message log limit exceeds 100")
        cursor = 9223372036854775807
        if before_id is not None:
            prior = self.load(before_id)
            if prior is None or prior["record"].kind != "message" or session_id not in {
                    prior["record"].fields["from_session_id"], prior["record"].fields["to_session_id"]}:
                raise Denied("message cursor is not visible to this participant")
            cursor = self.connection.execute("SELECT rowid FROM intents WHERE id=?", (before_id,)).fetchone()[0]
        ids = self.connection.execute("SELECT id FROM intents WHERE kind='message' AND (sender=? OR recipient=?) AND rowid<? ORDER BY rowid DESC LIMIT ?",
                                      (session_id, session_id, cursor, limit)).fetchall()
        return [self.load(row[0]) for row in ids]

    def snapshot(self, destination):
        self._check_lock()
        destination = Path(destination)
        protected_path(destination.parent, owners={0, self.owner_uid}, directory=True, private=True)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        target = sqlite3.connect(str(destination))
        try:
            self.connection.backup(target)
        finally:
            target.close()
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_directory(destination.parent)
