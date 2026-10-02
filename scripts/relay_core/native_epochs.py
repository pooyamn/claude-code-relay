"""Protected Codex settings/control epochs and ordered sealed-frame references.

A current settings epoch is not readiness, a stopped writer or loaded-context
proof. Protected launcher/observer integration and all-source admission remain
required. No RPC discovery, model turn, retry or worker endpoint exists here.
"""
from dataclasses import dataclass

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, strict_json
from .native_capture import NativeCapture, validate_reference
from .native_rpc import CodexRPC, _hash
from .native_settings import _path, permission_contract, verify_resume_permissions
from .outbox import DeliveryLedger


SCHEMA = "ccrelay.native_control_epochs.v1"


@dataclass(frozen=True)
class NativeEpochTicket:
    connection_id: str
    source_digest: str
    epoch: int
    settings_digest: str

    def __post_init__(self):
        identifier(self.connection_id)
        _hash(self.source_digest)
        integer(self.epoch, 0)
        _hash(self.settings_digest)


class _EpochSink:
    def __init__(self, ledger, capture, previous):
        self.ledger, self.capture, self.previous = ledger, capture, previous

    def __call__(self, receipt):
        self.ledger.observe(self.capture, receipt)
        if self.previous is not None:
            self.previous(receipt)


class NativeControlEpochs(DeliveryLedger):
    def __init__(self, directory, *, owner_uid, policy_digest, current_source, checkpoint=lambda _: None):
        if not callable(current_source):
            raise Denied("protected current native source observer required")
        self.current_source = current_source
        super().__init__(directory, owner_uid=owner_uid, policy_digest=policy_digest, checkpoint=checkpoint)

    def _initialize_component(self):
        self.connection.execute("CREATE TABLE native_epoch_metadata (schema TEXT NOT NULL)")
        self.connection.execute("INSERT INTO native_epoch_metadata VALUES (?)", (SCHEMA,))
        self.connection.execute("CREATE TABLE native_connections (id TEXT PRIMARY KEY,body BLOB NOT NULL,digest TEXT NOT NULL)")
        self.connection.execute("""CREATE TABLE native_epoch_history (
            connection_id TEXT NOT NULL,epoch INTEGER NOT NULL,body BLOB NOT NULL,digest TEXT NOT NULL,
            PRIMARY KEY(connection_id,epoch))""")
        self.connection.execute("""CREATE TABLE native_frames (
            connection_id TEXT NOT NULL,position INTEGER NOT NULL,artifact_digest TEXT UNIQUE NOT NULL,
            body BLOB NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(connection_id,position))""")

    def _validate_component(self):
        if self.connection.execute("SELECT schema FROM native_epoch_metadata").fetchall() != [(SCHEMA,)]:
            raise Denied("unsupported native control epoch schema; preserve for migration")
        self.connection.execute("SELECT connection_id,position,artifact_digest,body,digest FROM native_frames LIMIT 0")
        for (connection_id,) in self.connection.execute("SELECT id FROM native_connections").fetchall():
            self._row(connection_id)

    def _row(self, connection_id):
        self._check_lock()
        row = self.connection.execute("SELECT body,digest FROM native_connections WHERE id=?", (identifier(connection_id),)).fetchone()
        if row is None:
            raise Denied("native control connection not enrolled")
        value = strict_json(row[0])
        exact(value, {"schema", "connection_id", "source_digest", "thread_id", "worktree", "settings_digest",
                      "epoch", "state", "permissions", "baseline_reference"})
        if value["schema"] != SCHEMA or value["connection_id"] != connection_id or fingerprint(value) != row[1] or \
                value["state"] not in {"unverified", "current", "unknown", "closed"}:
            raise Denied("native control epoch record differs")
        identifier(value["thread_id"])
        _path(value["worktree"])
        _hash(value["source_digest"])
        _hash(value["settings_digest"])
        integer(value["epoch"], 0)
        if (value["permissions"] is None) != (value["baseline_reference"] is None):
            raise Denied("native settings baseline is incomplete")
        if value["baseline_reference"] is not None:
            reference = validate_reference(value["baseline_reference"])
            if reference["connection_id"] != connection_id or reference["source_digest"] != value["source_digest"] or \
                    fingerprint(value["permissions"]) != value["settings_digest"]:
                raise Denied("native settings baseline source/pin differs")
        elif value["state"] == "current":
            raise Denied("current epoch has no native settings baseline")
        history = self.connection.execute("SELECT body,digest FROM native_epoch_history WHERE connection_id=? AND epoch=?",
                                          (connection_id, value["epoch"])).fetchone()
        count, maximum = self.connection.execute("SELECT COUNT(*),MAX(epoch) FROM native_epoch_history WHERE connection_id=?",
                                                (connection_id,)).fetchone()
        if history is None or count != value["epoch"] + 1 or maximum != value["epoch"]:
            raise Denied("native control epoch history incomplete")
        event = strict_json(history[0])
        exact(event, {"schema", "record", "reason"})
        if event["schema"] != "ccrelay.native_epoch_event.v1" or event["record"] != value or fingerprint(event) != history[1]:
            raise Denied("native control epoch and history disagree")
        identifier(event["reason"])
        return value

    def _source(self, row):
        if self.current_source(row["connection_id"]) != row["source_digest"]:
            raise Denied("native control source no longer current")

    def _rpc(self, rpc, row, *, initialized=True):
        if type(rpc) is not CodexRPC or type(rpc.capture) is not NativeCapture or rpc.connection_id != row["connection_id"] or \
                rpc.capture.connection_id != row["connection_id"] or rpc.capture.source_digest != row["source_digest"] or \
                initialized and not rpc.initialized:
            raise Denied("exact current pinned captured native RPC required")
        if initialized and (type(rpc.capture.observe_receipt) is not _EpochSink or \
                            rpc.capture.observe_receipt.ledger is not self or rpc.capture.observe_receipt.capture is not rpc.capture):
            raise Denied("current native control receipt consumer required")
        rpc._current()
        rpc.capture._current()
        self._source(row)

    def _save(self, row, reason, *, initial=False):
        identifier(reason)
        if not initial:
            row = {**row, "epoch": row["epoch"] + 1}
            self.connection.execute("UPDATE native_connections SET body=?,digest=? WHERE id=?",
                                    (canonical_bytes(row), fingerprint(row), row["connection_id"]))
        else:
            self.connection.execute("INSERT INTO native_connections VALUES (?,?,?)",
                                    (row["connection_id"], canonical_bytes(row), fingerprint(row)))
        event = {"schema": "ccrelay.native_epoch_event.v1", "record": row, "reason": reason}
        self.connection.execute("INSERT INTO native_epoch_history VALUES (?,?,?,?)",
                                (row["connection_id"], row["epoch"], canonical_bytes(event), fingerprint(event)))
        self.checkpoint("before_native_epoch_commit")
        return row

    def enroll(self, rpc, *, thread_id, worktree, settings_digest):
        if type(rpc) is not CodexRPC or type(rpc.capture) is not NativeCapture:
            raise Denied("captured native connection required before enrollment")
        row = {"schema": SCHEMA, "connection_id": rpc.connection_id, "source_digest": rpc.capture.source_digest,
               "thread_id": identifier(thread_id), "worktree": _path(worktree), "settings_digest": _hash(settings_digest),
               "epoch": 0, "state": "unverified", "permissions": None, "baseline_reference": None}
        self._rpc(rpc, row, initialized=False)
        previous = rpc.capture.observe_receipt
        if type(previous) is _EpochSink and (previous.ledger is not self or previous.capture is not rpc.capture):
            raise Denied("old native receipt consumer requires a fresh connection")
        with self._transaction():
            if self.connection.execute("SELECT 1 FROM native_connections WHERE id=?", (rpc.connection_id,)).fetchone():
                old = self._row(rpc.connection_id)
                if any(old[key] != row[key] for key in ("source_digest", "thread_id", "worktree", "settings_digest")):
                    raise Denied("native control connection cannot be rebound")
                if type(previous) is not _EpochSink:
                    rpc.capture.observe_receipt = _EpochSink(self, rpc.capture, previous)
                return old
            self._source(row)
            saved = self._save(row, "enrolled", initial=True)
        self.checkpoint("after_native_epoch_commit")
        rpc.capture.observe_receipt = _EpochSink(self, rpc.capture, previous)
        return saved

    def invalidate(self, rpc, *, expected_epoch, reason):
        with self._transaction():
            row = self._row(rpc.connection_id)
            self._rpc(rpc, row)
            if row["epoch"] != integer(expected_epoch, 0) or row["state"] == "closed":
                raise Denied("native control epoch changed or closed")
            saved = self._save({**row, "state": "unknown"}, reason)
        self.checkpoint("after_native_epoch_commit")
        return saved["epoch"]

    def accept_resume(self, rpc, *, expected_epoch, request_id, response):
        row = self._row(rpc.connection_id)
        self._rpc(rpc, row)
        parameters = {"threadId": row["thread_id"], "cwd": row["worktree"]}
        reference = rpc.response_evidence("thread/resume", parameters, request_id=request_id, response=response)
        validate_reference(reference)
        if reference["source_digest"] != row["source_digest"] or "error" in response or not self.connection.execute(
                "SELECT 1 FROM native_frames WHERE artifact_digest=? AND connection_id=?", (reference["artifact_digest"], rpc.connection_id)).fetchone():
            raise Denied("native resume baseline source/response differs")
        permissions = verify_resume_permissions(response.get("result"), thread_id=row["thread_id"],
                                                 worktree=row["worktree"], expected_digest=row["settings_digest"])
        with self._transaction():
            if self._row(rpc.connection_id) != row or row["epoch"] != integer(expected_epoch, 0) or row["state"] == "closed":
                raise Denied("native resume baseline became stale")
            self._rpc(rpc, row)
            saved = self._save({**row, "state": "current", "permissions": permissions, "baseline_reference": reference}, "resume_baseline")
        self.checkpoint("after_native_epoch_commit")
        return saved["epoch"]

    def observe(self, capture, receipt):
        if type(capture) is not NativeCapture:
            raise Denied("sealed native capture source required")
        capture._current()
        metadata, message, _ = capture.read(receipt)
        connection_id = metadata["connection_id"]
        with self._transaction():
            row = self._row(connection_id)
            self._source(row)
            if row["source_digest"] != metadata["source_digest"] or row["state"] == "closed":
                raise Denied("native frame control source changed or closed")
            existing = self.connection.execute("SELECT position FROM native_frames WHERE artifact_digest=?", (receipt.artifact_digest,)).fetchone()
            if existing:
                return existing[0]  # Journal ACK replay, never replay a native action.
            position = self.connection.execute("SELECT COALESCE(MAX(position),0)+1 FROM native_frames WHERE connection_id=?", (connection_id,)).fetchone()[0]
            frame = {"schema": "ccrelay.native_ordered_frame.v1", "metadata": metadata, "artifact_digest": receipt.artifact_digest}
            self.connection.execute("INSERT INTO native_frames VALUES (?,?,?,?,?)",
                                    (connection_id, position, receipt.artifact_digest, canonical_bytes(frame), fingerprint(frame)))
            params = message.get("params") or {}
            method = message.get("method")
            scoped_controls = {"thread/settings/updated", "turn/started", "turn/completed", "thread/status/changed",
                               "thread/closed", "thread/archived", "item/permissions/requestApproval"}
            if method in scoped_controls and (type(params) is not dict or type(params.get("threadId")) is not str):
                self._save({**row, "state": "unknown"}, "unsupported_native_control_scope")
            elif type(params) is dict and params.get("threadId") == row["thread_id"]:
                if method == "thread/settings/updated":
                    try:
                        settings = params["threadSettings"]
                        required = {"cwd", "approvalPolicy", "approvalsReviewer", "sandboxPolicy", "model", "modelProvider", "collaborationMode"}
                        allowed = required | {"activePermissionProfile", "disabledPluginIds", "effort", "personality", "serviceTier", "summary"}
                        if type(settings) is not dict or not required <= set(settings) or set(settings) - allowed or \
                                settings.get("activePermissionProfile") is not None:
                            raise Denied("unsupported native settings event")
                        permissions = permission_contract(cwd=settings["cwd"], approval_policy=settings["approvalPolicy"],
                                                          approvals_reviewer=settings["approvalsReviewer"], sandbox=settings["sandboxPolicy"])
                        if fingerprint(permissions) != row["settings_digest"]:
                            raise Denied("unreviewed native settings change")
                        updated, reason = row, "matching_settings_event"
                    except (Denied, KeyError, TypeError, ValueError):
                        updated, reason = {**row, "state": "unknown"}, "unsupported_or_unreviewed_settings"
                    # A notification cannot establish the first baseline or
                    # revive invalidated/recovered state. Storage failures must
                    # propagate, not be mistaken for unsupported settings.
                    self._save(updated, reason)
                elif method in {"turn/started", "turn/completed", "thread/status/changed"}:
                    self._save(row, "native_lifecycle_changed")
                elif method in {"thread/closed", "thread/archived"}:
                    self._save({**row, "state": "closed"}, "native_thread_closed")
                elif method == "item/permissions/requestApproval":
                    self._save({**row, "state": "unknown"}, "native_permissions_requested")
            self.checkpoint("before_native_frame_order_commit")
            capture._current()
            self._source(row)
        self.checkpoint("after_native_frame_order_commit")
        return position

    def ticket(self, rpc):
        row = self._row(rpc.connection_id)
        self._rpc(rpc, row)
        if row["state"] != "current":
            raise Denied("fresh native settings/control baseline required")
        from .native_capture import NativeFrameReceipt
        reference = row["baseline_reference"]
        receipt = NativeFrameReceipt(reference["artifact_digest"])
        metadata, message, _ = rpc.capture.read(receipt)
        if rpc.capture.response_evidence(receipt, response=message, request_id=metadata["request_id"]) != reference:
            raise Denied("native settings baseline capture differs")
        self._rpc(rpc, row)
        if self._row(rpc.connection_id) != row:
            raise Denied("native control epoch changed during baseline verification")
        return NativeEpochTicket(row["connection_id"], row["source_digest"], row["epoch"], row["settings_digest"])

    def validate(self, rpc, ticket):
        if type(ticket) is not NativeEpochTicket or self.ticket(rpc) != ticket:
            raise Denied("native observation settings/control epoch became stale")
        return ticket  # Necessary freshness condition only, never readiness.

    def frames(self, capture):
        """Verify a historical ordered prefix, not permission to replay events."""
        if type(capture) is not NativeCapture:
            raise Denied("protected captured-frame reader required")
        from .native_capture import NativeFrameReceipt
        self._row(capture.connection_id)
        maximum = self.connection.execute("SELECT COALESCE(MAX(position),0) FROM native_frames WHERE connection_id=?",
                                          (capture.connection_id,)).fetchone()[0]
        expected = 1
        for position, artifact, body, stored_digest in self.connection.execute(
                "SELECT position,artifact_digest,body,digest FROM native_frames WHERE connection_id=? AND position<=? ORDER BY position",
                (capture.connection_id, maximum)):
            frame = strict_json(body)
            exact(frame, {"schema", "metadata", "artifact_digest"})
            if position != expected or frame["schema"] != "ccrelay.native_ordered_frame.v1" or \
                    frame["artifact_digest"] != artifact or fingerprint(frame) != stored_digest:
                raise Denied("native captured-frame order/checksum differs")
            receipt = NativeFrameReceipt(artifact)
            metadata, _, raw = capture.read(receipt)
            if frame["metadata"] != metadata:
                raise Denied("native captured-frame metadata differs from sealed bytes")
            yield position, receipt, raw
            expected += 1
        if expected != maximum + 1:
            raise Denied("native captured-frame journal has a gap")

    def recover_inflight(self):
        super().recover_inflight()
        with self._transaction():
            for (connection_id,) in self.connection.execute("SELECT id FROM native_connections").fetchall():
                row = self._row(connection_id)
                if row["state"] != "closed":
                    self._save({**row, "state": "unknown"}, "recovery_requires_fresh_native_baseline")
