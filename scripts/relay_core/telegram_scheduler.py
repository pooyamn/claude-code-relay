"""One protected durable Telegram send owner, with receipt-bound reply cursors.

Uses the PR 5 outbox in a SEPARATE private state directory. Atomic component
tables, queue bundles and verified retry/cursor updates share its SQLite WAL.
No worker RPC, credential discovery, model turn or live service activation.
"""
import hashlib
import os
import re
import time
import uuid

from .contracts import canonical_bytes, create, fingerprint, intent_payload
from .identity import Denied, exact, identifier, integer, strict_json
from .intake import provider_json
from .outbox import DeliveryLedger, fsync_directory
from .runtime_delivery import evidence_for
from .telegram_outbound import EDIT_METHODS, LANES, SEND_METHODS, Response, receipt, verify_bot


def stable_id(prefix, value):
    return prefix + fingerprint(value)[7:]


class TelegramLedger(DeliveryLedger):
    def __init__(self, directory, *, owner_uid, policy, clock_ms=lambda: int(time.time() * 1000), checkpoint=lambda _: None):
        self.policy, self.clock_ms = policy, clock_ms
        super().__init__(directory, owner_uid=owner_uid, policy_digest=policy.digest, checkpoint=checkpoint)
        try:
            self.responses = self.folder / "responses"
            if not self.responses.exists():
                self.responses.mkdir(mode=0o700)
                fsync_directory(self.folder)
            from .identity import protected_path
            protected_path(self.responses, owners={owner_uid}, directory=True, private=True)
        except Exception:
            self.close()
            raise

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE telegram_metadata (schema TEXT,bot_id INTEGER,last_clock_ms INTEGER,global_after_ms INTEGER)")
        self.connection.execute("INSERT INTO telegram_metadata VALUES (?,?,0,0)", ("ccrelay.telegram_queue.v1", self.policy.bot_id))
        self.connection.execute("""CREATE TABLE telegram_bundles (
            id TEXT PRIMARY KEY,body BLOB NOT NULL,digest TEXT NOT NULL,priority INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,coalesce_key TEXT,superseded_by TEXT,cursor_committed INTEGER NOT NULL)""")
        self.connection.execute("""CREATE TABLE telegram_operations (
            bundle_id TEXT NOT NULL,position INTEGER NOT NULL,intent_id TEXT UNIQUE NOT NULL,
            retries INTEGER NOT NULL,PRIMARY KEY(bundle_id,position))""")
        self.connection.execute("CREATE TABLE telegram_cooldowns (operation_key TEXT PRIMARY KEY,eligible_ms INTEGER NOT NULL)")
        self.connection.execute("CREATE TABLE telegram_chats (chat_id INTEGER PRIMARY KEY,eligible_ms INTEGER NOT NULL)")
        self.connection.execute("CREATE INDEX telegram_pending_intents ON intents(state)")
        self.connection.execute("""CREATE TABLE telegram_streams (
            id TEXT PRIMARY KEY,session_id TEXT NOT NULL,native_session_id TEXT NOT NULL,
            initial_cursor INTEGER NOT NULL,committed_cursor INTEGER NOT NULL,tail_cursor INTEGER NOT NULL,
            evidence_id TEXT NOT NULL,last_bundle_id TEXT)""")

    def _validate_component(self):
        metadata = self.connection.execute("SELECT schema,bot_id,last_clock_ms,global_after_ms FROM telegram_metadata").fetchall()
        if len(metadata) != 1 or metadata[0][:2] != ("ccrelay.telegram_queue.v1", self.policy.bot_id):
            raise Denied("unsupported Telegram queue schema/bot; preserve for migration")
        integer(metadata[0][2], 0)
        integer(metadata[0][3], 0)

    def now(self):
        value = integer(self.clock_ms(), 0)
        last = self.connection.execute("SELECT last_clock_ms FROM telegram_metadata").fetchone()[0]
        if value < last:
            raise Denied("clock moved backwards; retain Telegram queue until time reconciliation")
        return value

    def _tick(self, value):
        self.connection.execute("UPDATE telegram_metadata SET last_clock_ms=?", (value,))

    def register_stream(self, stream_id, *, session_id, native_session_id, initial_cursor, evidence_id):
        """Trusted watcher registration; not permission to invent a fresh offset."""
        for value in (stream_id, session_id, evidence_id):
            identifier(value)
        if type(native_session_id) is not str or not native_session_id:
            raise Denied("exact native stream incarnation required")
        integer(initial_cursor, 0)
        with self._transaction():
            row = self.connection.execute("SELECT session_id,native_session_id,initial_cursor,evidence_id FROM telegram_streams WHERE id=?", (stream_id,)).fetchone()
            binding = (session_id, native_session_id, initial_cursor, evidence_id)
            if row is not None and row != binding:
                raise Denied("stream registration cannot replace identity or reset its cursor")
            if row is None:
                self.connection.execute("INSERT INTO telegram_streams VALUES (?,?,?,?,?,?,?,NULL)", (
                    stream_id, session_id, native_session_id, initial_cursor, initial_cursor, initial_cursor, evidence_id))
            self._tick(self.now())

    def stream(self, stream_id):
        row = self.connection.execute("SELECT session_id,native_session_id,initial_cursor,committed_cursor,tail_cursor,evidence_id,last_bundle_id FROM telegram_streams WHERE id=?", (identifier(stream_id),)).fetchone()
        if row is None:
            raise Denied("unregistered watcher stream")
        for index in (2, 3, 4):
            integer(row[index], 0)
        identifier(row[0])
        identifier(row[5])
        if not row[2] <= row[3] <= row[4]:
            raise Denied("stream cursor ordering changed")
        return dict(zip(("session_id", "native_session_id", "initial_cursor", "committed_cursor", "tail_cursor", "evidence_id", "last_bundle_id"), row))

    def validate_bundle(self, bundle):
        exact(bundle, {"schema", "id", "root_task_id", "session_id", "chat_id", "thread_id", "lane", "source", "operations", "cursor", "coalesce_key"})
        if bundle["schema"] != "ccrelay.telegram_bundle.v1" or type(bundle["lane"]) is not str or bundle["lane"] not in LANES:
            raise Denied("known bundle schema/lane required")
        for key in ("id", "root_task_id", "session_id"):
            identifier(bundle[key])
        chat_id = bundle["chat_id"]
        if type(chat_id) is not int or chat_id not in self.policy.raw["allowed_chats"]:
            raise Denied("bundle destination denied")
        if bundle["thread_id"] is not None:
            integer(bundle["thread_id"])
        source = bundle["source"]
        exact(source, {"native_session_id", "turn_id", "submission_id", "content_digest", "source_kind", "content"})
        if type(source["source_kind"]) is not str or source["source_kind"] not in {"owner_reply", "native_app", "approval", "alert", "bus", "status", "callback"}:
            raise Denied("source attribution required")
        for key in ("native_session_id", "turn_id", "submission_id"):
            if source[key] is not None and (type(source[key]) is not str or not source[key]):
                raise Denied("exact source references required")
        if type(source["content_digest"]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", source["content_digest"]):
            raise Denied("frozen source content digest required")
        if fingerprint(source["content"]) != source["content_digest"] or bundle["lane"] != \
                {"owner_reply": "reply", "native_app": "reply", "approval": "approval", "alert": "alert", "bus": "bus", "status": "status", "callback": "callback"}[source["source_kind"]]:
            raise Denied("retained original source or priority attribution changed")
        if bundle["lane"] == "reply" and any(source[key] is None for key in ("native_session_id", "turn_id", "submission_id")):
            raise Denied("reply must bind native session, turn and submission")
        operations = bundle["operations"]
        if type(operations) is not list or not operations or len(operations) > 1000:
            raise Denied("bounded nonempty ordered operation manifest required")
        for operation in operations:
            self.policy.operation(operation, chat_id)
            if operation["method"] != "answerCallbackQuery":
                expected = None if bundle["thread_id"] in {None, 1} else bundle["thread_id"]
                # Edits identify the message rather than a topic parameter.
                if operation["method"] in SEND_METHODS and operation["args"].get("message_thread_id") != expected:
                    raise Denied("operation and bundle topic disagree")
        if bundle["cursor"] is not None:
            exact(bundle["cursor"], {"stream_id", "expected", "new"})
            cursor = bundle["cursor"]
            identifier(cursor["stream_id"])
            integer(cursor["expected"], 0)
            integer(cursor["new"], 0)
            if cursor["new"] <= cursor["expected"] or bundle["lane"] != "reply":
                raise Denied("only required reply content advances a positive cursor")
        key = bundle["coalesce_key"]
        if key is not None:
            identifier(key)
            if bundle["lane"] != "status" or bundle["cursor"] is not None or len(operations) != 1 or operations[0]["method"] not in EDIT_METHODS:
                raise Denied("only a disposable unsent status edit may coalesce")
        canonical_bytes(bundle)
        return bundle

    def bundle(self, bundle_id):
        row = self.connection.execute("SELECT body,digest,priority,chat_id,coalesce_key,superseded_by,cursor_committed FROM telegram_bundles WHERE id=?", (identifier(bundle_id),)).fetchone()
        if row is None:
            return None
        bundle = self.validate_bundle(provider_json(row[0]))
        if bundle["id"] != bundle_id or fingerprint(bundle) != row[1] or (LANES[bundle["lane"]], bundle["chat_id"]) != row[2:4] or \
                row[6] not in {0, 1} or row[4] != self.coalescing_key(bundle) or (row[6] == 1 and bundle["cursor"] is None):
            raise Denied("bundle index/source changed")
        if row[5] is not None:
            identifier(row[5])
            if bundle["lane"] != "status":
                raise Denied("required content cannot be superseded")
        return {"body": bundle, "superseded_by": row[5], "cursor_committed": bool(row[6])}

    def coalescing_key(self, bundle):
        if bundle["coalesce_key"] is None:
            return None
        operation = bundle["operations"][0]
        return fingerprint({"key": bundle["coalesce_key"], "session": bundle["session_id"], "chat": bundle["chat_id"],
                            "method": operation["method"], "message": operation["args"]["message_id"]})

    def _action(self, bundle, position, retry, *, previous=None, negative_evidence=None):
        operation = bundle["operations"][position]
        fields = {"id": stable_id("tg-intent-", {"bundle": bundle["id"], "position": position, "retry": retry}),
                  "root_task_id": bundle["root_task_id"], "requested_by_session_id": bundle["session_id"],
                  "action_kind": "telegram", "parameters": {"bot_id": self.policy.bot_id, **operation}}
        record = create("external_action", id=fields.pop("id"), **fields,
                        intent_digest=fingerprint(intent_payload("external_action", {**fields, "id": stable_id("tg-intent-", {"bundle": bundle["id"], "position": position, "retry": retry})})),
                        state="stored", attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
        context = {"schema": "ccrelay.telegram_operation.v1", "bundle_id": bundle["id"], "position": position,
                   "retry": retry, "policy_digest": self.policy.digest, "previous_intent_id": previous,
                   "negative_evidence_id": negative_evidence}
        self._enroll(record, context)
        return record.id

    def enqueue(self, bundle):
        self.validate_bundle(bundle)
        with self._transaction():
            current = self.bundle(bundle["id"])
            if current is not None:
                if canonical_bytes(current["body"]) != canonical_bytes(bundle):
                    raise Denied("stable bundle ID reused for changed content/source")
                return self.status(bundle["id"])
            now = self.now()
            cursor = bundle["cursor"]
            if cursor is not None:
                stream = self.stream(cursor["stream_id"])
                if (stream["session_id"], stream["native_session_id"], stream["tail_cursor"]) != \
                        (bundle["session_id"], bundle["source"]["native_session_id"], cursor["expected"]):
                    raise Denied("reply source/queued cursor changed; no offset reset or overlapping reply")
                self.connection.execute("UPDATE telegram_streams SET tail_cursor=? WHERE id=?", (cursor["new"], cursor["stream_id"]))
            key = self.coalescing_key(bundle)
            if key is not None:
                for (older,) in self.connection.execute("SELECT id FROM telegram_bundles WHERE coalesce_key=? AND superseded_by IS NULL", (key,)).fetchall():
                    items = self.items(older)
                    if all(item["retry"] == 0 and item["current"]["record"].fields["state"] == "stored" for item in items):
                        self.connection.execute("UPDATE telegram_bundles SET superseded_by=? WHERE id=?", (bundle["id"], older))
            self.connection.execute("INSERT INTO telegram_bundles VALUES (?,?,?,?,?,?,NULL,0)", (
                bundle["id"], canonical_bytes(bundle), fingerprint(bundle), LANES[bundle["lane"]], bundle["chat_id"], key))
            for position in range(len(bundle["operations"])):
                intent_id = self._action(bundle, position, 0)
                self.connection.execute("INSERT INTO telegram_operations VALUES (?,?,?,0)", (bundle["id"], position, intent_id))
            self._tick(now)
            self.checkpoint("before_bundle_commit")
        self.checkpoint("after_bundle_commit")
        return self.status(bundle["id"])

    def items(self, bundle_id):
        bundle = self.bundle(bundle_id)
        if bundle is None:
            raise Denied("unknown outbound bundle")
        body = bundle["body"]
        rows = self.connection.execute("SELECT position,intent_id,retries FROM telegram_operations WHERE bundle_id=? ORDER BY position", (bundle_id,)).fetchall()
        if len(rows) != len(body["operations"]) or [row[0] for row in rows] != list(range(len(rows))):
            raise Denied("ordered operation manifest changed")
        result = []
        for position, intent_id, retry in rows:
            integer(retry, 0)
            if retry > self.policy.raw["max_rate_limit_retries"]:
                raise Denied("retry counter exceeds policy")
            current = self.load(intent_id)
            previous = None if retry == 0 else self.load(stable_id("tg-intent-", {"bundle": bundle_id, "position": position, "retry": retry - 1}))
            previous_evidence = None if previous is None or previous["record"].fields["outcome_evidence_id"] is None else self._evidence(previous["record"].fields["outcome_evidence_id"])
            if retry and (previous is None or previous["record"].fields["state"] != "failed" or previous_evidence is None or previous_evidence["outcome"] != "rejected" or
                          previous_evidence["payload"].get("receipt", {}).get("code") != 429):
                raise Denied("replacement lacks retained negative rate-limit evidence")
            if current is None or current["record"].kind != "external_action" or current["record"].fields["action_kind"] != "telegram" or \
                    intent_id != stable_id("tg-intent-", {"bundle": bundle_id, "position": position, "retry": retry}) or \
                    current["record"].to_dict()["parameters"] != {"bot_id": self.policy.bot_id, **body["operations"][position]} or \
                    (current["record"].fields["root_task_id"], current["record"].fields["requested_by_session_id"]) != \
                    (body["root_task_id"], body["session_id"]) or current["context"] != {
                        "schema": "ccrelay.telegram_operation.v1", "bundle_id": bundle_id, "position": position,
                        "retry": retry, "policy_digest": self.policy.digest,
                        "previous_intent_id": None if previous is None else previous["record"].id,
                        "negative_evidence_id": None if previous is None else previous["record"].fields["outcome_evidence_id"]}:
                raise Denied("outbound operation and authenticated intent disagree")
            result.append({"bundle_id": bundle_id, "position": position, "retry": retry, "current": current,
                           "operation": body["operations"][position]})
        return result

    def status(self, bundle_id):
        bundle = self.bundle(bundle_id)
        if bundle is None:
            raise Denied("unknown bundle")
        items = self.items(bundle_id)
        states = [item["current"]["record"].fields["state"] for item in items]
        return {"id": bundle_id, "state": "superseded" if bundle["superseded_by"] else "confirmed" if all(state == "confirmed" for state in states) else
                "unknown" if "unknown" in states else "failed" if "failed" in states else "pending",
                "operation_states": states, "cursor_committed": bundle["cursor_committed"],
                "meaning": "receipts_not_model_completion", "superseded_by": bundle["superseded_by"],
                "source": bundle["body"]["source"],
                "message_ids": [None if item["current"]["record"].fields["outcome_evidence_id"] is None else
                                self._evidence(item["current"]["record"].fields["outcome_evidence_id"])["payload"]["receipt"]["message_ids"] for item in items]}

    def operation_key(self, bundle, operation):
        return fingerprint({"bot": self.policy.bot_id, "method": operation["method"], "chat": bundle["chat_id"],
                            "message": operation["args"].get("message_id")})

    def choose(self, now):
        self._check_lock()
        integer(now, 0)
        if now < self.connection.execute("SELECT last_clock_ms FROM telegram_metadata").fetchone()[0]:
            raise Denied("clock moved backwards")
        global_after = integer(self.connection.execute("SELECT global_after_ms FROM telegram_metadata").fetchone()[0], 0)
        if now < global_after:
            return None
        candidates = self.connection.execute("""SELECT DISTINCT b.id,b.priority,b.rowid FROM intents i
            JOIN telegram_operations o ON o.intent_id=i.id JOIN telegram_bundles b ON b.id=o.bundle_id
            WHERE i.state='stored' AND b.superseded_by IS NULL ORDER BY b.priority,b.rowid""").fetchall()
        for bundle_id, _, _ in candidates:
            body = self.bundle(bundle_id)["body"]
            if body["cursor"] is not None and self.stream(body["cursor"]["stream_id"])["committed_cursor"] != body["cursor"]["expected"]:
                continue
            items = self.items(bundle_id)
            for item in items:
                state = item["current"]["record"].fields["state"]
                if state == "confirmed":
                    continue
                if state != "stored" or item["current"]["hold_reason"] is not None:
                    break
                operation = item["operation"]
                cooldown = self.connection.execute("SELECT eligible_ms FROM telegram_cooldowns WHERE operation_key=?", (self.operation_key(body, operation),)).fetchone()
                chat_after = self.connection.execute("SELECT eligible_ms FROM telegram_chats WHERE chat_id=?", (body["chat_id"],)).fetchone()
                if cooldown:
                    integer(cooldown[0], 0)
                if chat_after:
                    integer(chat_after[0], 0)
                if (cooldown and now < cooldown[0]) or (operation["method"] != "answerCallbackQuery" and chat_after and now < chat_after[0]):
                    break
                # Unknown older edits may still take effect remotely after a
                # timeout. Do not let a later edit race their reconciliation.
                if operation["method"] in EDIT_METHODS | {"deleteMessage"} and self._older_unknown_edit(item, body):
                    break
                return {**item, "bundle": body}
        return None

    def _older_unknown_edit(self, item, body):
        older_ids = self.connection.execute("""SELECT DISTINCT b.id FROM intents i
            JOIN telegram_operations o ON o.intent_id=i.id JOIN telegram_bundles b ON b.id=o.bundle_id
            WHERE i.state IN ('delivering','submitted','unknown') AND b.chat_id=? AND b.superseded_by IS NULL
              AND b.rowid<(SELECT rowid FROM telegram_bundles WHERE id=?)""", (body["chat_id"], body["id"])).fetchall()
        for (old_id,) in older_ids:
            for older in self.items(old_id):
                if older["operation"]["method"] in EDIT_METHODS | {"deleteMessage"} and older["operation"]["args"]["message_id"] == item["operation"]["args"]["message_id"] and \
                        older["current"]["record"].fields["state"] in {"delivering", "submitted", "unknown"}:
                    return True
        return False

    def reserve(self, record, plan):
        now, body, operation = plan["target"]["dispatch_ms"], self.bundle(plan["target"]["bundle_id"])["body"], plan["parameters"]
        context = self.load(record.id)["context"]
        if not self.connection.in_transaction or plan["target"] != {"bot_id": self.policy.bot_id, "chat_id": body["chat_id"],
                "bundle_id": body["id"], "position": context["position"], "dispatch_ms": now} or \
                operation != body["operations"][context["position"]] or integer(now, 0) > self.now() or \
                now < self.connection.execute("SELECT last_clock_ms FROM telegram_metadata").fetchone()[0]:
            raise Denied("pacing reservation does not match the exact authorized operation/time")
        now = self.now()
        self._tick(now)
        self.connection.execute("UPDATE telegram_metadata SET global_after_ms=?", (now + self.policy.raw["global_spacing_ms"],))
        if operation["method"] != "answerCallbackQuery":
            spacing = self.policy.raw["group_spacing_ms"] if body["chat_id"] < 0 else self.policy.raw["chat_spacing_ms"]
            self.connection.execute("INSERT OR REPLACE INTO telegram_chats VALUES (?,?)", (body["chat_id"], now + spacing))

    def finish(self, record, evidence):
        """Receipt hook: negative proof, cooldown and replacement commit together."""
        context = self.load(record.id)["context"]
        body = self.bundle(context["bundle_id"])["body"]
        if not self.connection.in_transaction or evidence != self.captured_evidence(record.id):
            raise Denied("receipt lacks protected captured attempt provenance")
        payload = evidence["payload"]
        now = payload["received_at_ms"]
        self._tick(self.now())
        if record.fields["state"] == "failed" and payload["receipt"]["code"] == 429:
            retry_at = now + payload["receipt"]["retry_after"] * 1000
            key = self.operation_key(body, body["operations"][context["position"]])
            self.connection.execute("INSERT INTO telegram_cooldowns VALUES (?,?) ON CONFLICT(operation_key) DO UPDATE SET eligible_ms=MAX(eligible_ms,excluded.eligible_ms)", (key, retry_at))
            if context["retry"] < self.policy.raw["max_rate_limit_retries"] and \
                    body["operations"][context["position"]]["method"] in self.policy.raw["retryable_methods"]:
                next_id = self._action(body, context["position"], context["retry"] + 1,
                                       previous=record.id, negative_evidence=evidence["id"])
                self.connection.execute("UPDATE telegram_operations SET intent_id=?,retries=? WHERE bundle_id=? AND position=?", (
                    next_id, context["retry"] + 1, body["id"], context["position"]))
        if record.fields["state"] == "confirmed":
            self._advance_cursor(body)

    def _advance_cursor(self, body):
        cursor = body["cursor"]
        if cursor is None or not all(item["current"]["record"].fields["state"] == "confirmed" for item in self.items(body["id"])):
            return
        stream = self.stream(cursor["stream_id"])
        if stream["committed_cursor"] != cursor["expected"]:
            raise Denied("reply cursor changed before complete receipt set")
        self.checkpoint("before_cursor_commit")
        self.connection.execute("UPDATE telegram_streams SET committed_cursor=?,last_bundle_id=? WHERE id=?", (cursor["new"], body["id"], cursor["stream_id"]))
        self.connection.execute("UPDATE telegram_bundles SET cursor_committed=1 WHERE id=?", (body["id"],))

    def _write_spool(self, path, raw):
        if path.exists() or path.is_symlink():
            if self._read_spool(path, len(raw)) != raw:
                raise Denied("immutable captured response changed")
            return
        temporary = self.responses / (uuid.uuid4().hex + ".pending")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o400)
            os.fsync(handle.fileno())
        self.checkpoint("before_response_publish")
        os.replace(temporary, path)
        fsync_directory(self.responses)

    def capture_response(self, intent_id, response):
        """Bind original bytes/status/time to the claimed attempt BEFORE receipt TX.

        Content-addressed body alone does not authenticate an attempt. The
        protected single send owner also seals its exact plan/attempt envelope.
        This local provenance still requires target OS isolation and a trusted
        transport; no worker receipt or arbitrary remote acknowledgment qualifies.
        """
        self._check_lock()
        current = self.load(intent_id)
        if not isinstance(response, Response) or current is None or current["record"].fields["state"] != "submitted":
            raise Denied("original response requires an exact submitted attempt")
        digest = hashlib.sha256(response.body).hexdigest()
        self._write_spool(self.responses / (digest + ".body"), response.body)
        self.checkpoint("after_response_body")
        binding = {"schema": "ccrelay.telegram_response.v1", "intent_id": intent_id,
                   "attempt_id": current["record"].fields["attempt_id"], "plan_digest": current["plan_digest"],
                   "body_digest": digest, "http_status": response.status, "received_at_ms": self.now()}
        self._write_spool(self.responses / (intent_id + ".receipt"), canonical_bytes(binding))
        self.checkpoint("after_response_spool")
        return binding

    def _read_spool(self, path, limit):
        from .identity import protected_path
        path = protected_path(path, owners={self.owner_uid}, private=True)
        metadata = path.lstat()
        if metadata.st_nlink != 1 or metadata.st_size > limit or metadata.st_mode & 0o222:
            raise Denied("response spool links/size/sealed mode changed")
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise Denied("oversized captured response")
        return raw

    def read_response(self, intent_id):
        current = self.load(intent_id)
        if current is None or current["plan"] is None:
            raise Denied("claimed exact attempt required")
        binding = strict_json(self._read_spool(self.responses / (intent_id + ".receipt"), 65536))
        exact(binding, {"schema", "intent_id", "attempt_id", "plan_digest", "body_digest", "http_status", "received_at_ms"})
        if binding["schema"] != "ccrelay.telegram_response.v1" or \
                (binding["intent_id"], binding["attempt_id"], binding["plan_digest"]) != \
                (intent_id, current["record"].fields["attempt_id"], current["plan_digest"]) or \
                type(binding["body_digest"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", binding["body_digest"]):
            raise Denied("captured response belongs to a different attempt/plan")
        integer(binding["received_at_ms"], 0)
        if binding["received_at_ms"] > self.now():
            raise Denied("captured time is in the future; preserve for reconciliation")
        raw = self._read_spool(self.responses / (binding["body_digest"] + ".body"), 8 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != binding["body_digest"]:
            raise Denied("original response changed")
        return binding, Response(binding["http_status"], raw)

    def captured_evidence(self, intent_id):
        current = self.load(intent_id)
        binding, response = self.read_response(intent_id)
        record, context = current["record"], current["context"]
        body = self.bundle(context["bundle_id"])["body"]
        outcome = receipt(response, body["operations"][context["position"]], self.policy, body["chat_id"])
        return evidence_for(record, record.fields["attempt_id"], current["plan"], outcome=outcome["outcome"],
                            provider_reference=binding["body_digest"],
                            payload={"raw_digest": binding["body_digest"], "http_status": response.status,
                                     "received_at_ms": binding["received_at_ms"], "receipt": outcome})


class TelegramScheduler:
    def __init__(self, ledger, bot, store, *, ownership_check):
        # Target wiring must supply a host-wide protected numeric-bot-ID lock.
        # Outbox's lock alone only fences owners of this exact state directory.
        if not callable(ownership_check):
            raise Denied("verified host-wide send ownership required")
        self.ledger, self.bot, self.store, self.ownership_check = ledger, bot, store, ownership_check
        self.verified = False

    def verify(self):
        self.ownership_check()
        verify_bot(self.bot.request("getMe", {}, {}, self.store), self.ledger.policy)
        self.verified = True

    def step(self):
        self.ownership_check()
        if not self.verified:
            raise Denied("pinned bot verification required before first send")
        now = self.ledger.now()
        item = self.ledger.choose(now)
        if item is None:
            return {"submitted": False, "state": "waiting_or_empty"}
        record, body = item["current"]["record"], item["bundle"]
        # Validate immutable uploads BEFORE claiming, then the transport reads
        # verified bytes again before forming its bounded multipart request.
        for reference in item["operation"]["assets"].values():
            self.store.read(reference)
        plan = {"schema": "ccrelay.delivery_plan.v1", "intent_id": record.id,
                "intent_digest": record.fields["intent_digest"], "adapter_id": "telegram-outbound.v1",
                "authorization_id": stable_id("tg-authority-", {"policy": self.ledger.policy.digest, "bundle": body["id"]}),
                "target": {"bot_id": self.ledger.policy.bot_id, "chat_id": body["chat_id"], "bundle_id": body["id"],
                           "position": item["position"], "dispatch_ms": now}, "parameters": item["operation"]}
        attempt = stable_id("tg-attempt-", {"intent": record.id})
        claim = self.ledger.claim(record.id, attempt, plan, expected_revision=record.revision, commit_hook=self.ledger.reserve)
        if not claim["may_execute"]:
            return {"submitted": False, "state": claim["record"].fields["state"]}
        self.ledger.submitted(record.id, attempt)
        try:
            self.ownership_check()  # revalidate after asset checks and durable claim
            operation = item["operation"]
            response = self.bot.request(operation["method"], operation["args"], operation["assets"], self.store)
            self.ledger.checkpoint("after_telegram_effect")
            if not isinstance(response, Response):
                raise Denied("protected adapter response required")
            self.ledger.capture_response(record.id, response)
            evidence = self.ledger.captured_evidence(record.id)
            self.ledger.reconcile(evidence, commit_hook=self.ledger.finish)
            self.ledger.checkpoint("after_outbound_commit")
        except Exception:
            state = self.ledger.load(record.id)["record"].fields["state"]
            if state in {"delivering", "submitted"}:
                self.ledger.unknown(record.id, attempt)
            return {"submitted": True, "state": self.ledger.load(record.id)["record"].fields["state"], "reason": "inspect_durable_outcome"}
        return {"submitted": True, "state": self.ledger.status(body["id"])["state"], "bundle_id": body["id"]}

    def reconcile_spooled(self, intent_id):
        """Protected driver only; no network send, caller receipt or offset reset."""
        self.ownership_check()
        current = self.ledger.load(intent_id)
        if current is None or current["record"].fields["state"] != "unknown":
            raise Denied("unknown exact attempt required for reconciliation")
        return self.ledger.reconcile(self.ledger.captured_evidence(intent_id), commit_hook=self.ledger.finish)
