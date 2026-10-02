"""Lossless protected native-frame artifacts, not financial JSON or UI text.

The launcher supplies the current kernel/binding/runtime source digest. This
does not establish that provenance from worker headers or create a live driver.
Complete payloads and scoped receipts use the existing sealed ArtifactStore;
partial/orphan artifacts remain forensic evidence, never permission to resend.
"""
from dataclasses import dataclass
import re
import uuid

from .artifacts import ArtifactStore, digest
from .contracts import canonical_bytes
from .identity import Denied, exact, identifier, strict_json
from .native_rpc import _decode, _encode, _hash, _request_id


SCHEMA = "ccrelay.native_frame.v1"
MAX_FRAME_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class NativeFrameReceipt:
    artifact_digest: str


def validate_reference(value):
    exact(value, {"schema", "artifact_digest", "source_digest", "connection_id", "frame_id", "raw_digest", "raw_size"})
    if value["schema"] != "ccrelay.native_frame_receipt.v1" or type(value["raw_size"]) is not int or \
            not 1 <= value["raw_size"] <= MAX_FRAME_BYTES or type(value["frame_id"]) is not str or \
            not re.fullmatch(r"native-frame-[a-f0-9]{32}", value["frame_id"]):
        raise Denied("compact native capture reference differs")
    identifier(value["connection_id"])
    for key in ("artifact_digest", "source_digest", "raw_digest"):
        _hash(value[key])
    canonical_bytes(value)
    return value  # Shape only: provenance still requires the protected capture.


class NativeCapture:
    def __init__(self, store, *, source_digest, connection_id, current_source,
                 notify=None, checkpoint=lambda _: None):
        if type(store) is not ArtifactStore or not callable(current_source) or not callable(checkpoint) or \
                notify is not None and not callable(notify):
            raise Denied("protected artifact store and current native source required")
        self.store, self.source_digest = store, _hash(source_digest)
        self.connection_id = identifier(connection_id)
        self.current_source, self.notify, self.checkpoint = current_source, notify, checkpoint

    def _current(self):
        if self.current_source() != self.source_digest:
            raise Denied("native capture source no longer current")

    @staticmethod
    def _kind(message, kind):
        if type(kind) is not str:
            raise Denied("native capture kind required")
        if kind == "response":
            if "method" in message or "params" in message or ("result" in message) == ("error" in message):
                raise Denied("native response capture envelope differs")
            return _request_id(message.get("id"))
        if kind not in {"notification", "server_request"} or \
                type(message.get("method")) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_/]{0,127}", message["method"]) or \
                set(message) & {"result", "error"} or ("id" in message) != (kind == "server_request"):
            raise Denied("native event capture envelope differs")
        return _request_id(message["id"]) if kind == "server_request" else None

    def __call__(self, message, *, raw, kind, connection_id):
        self._current()
        if connection_id != self.connection_id or type(raw) is not bytes or not 1 <= len(raw) <= MAX_FRAME_BYTES:
            raise Denied("bounded exact-connection native capture required")
        decoded = _decode(raw)
        if _encode(decoded) != _encode(message):
            raise Denied("native capture message differs from received bytes")
        request_id = self._kind(decoded, kind)
        self.checkpoint("before_native_payload_commit")
        # Separate metadata leaves the existing store's full 8 MiB tree budget
        # available to raw native data, without relaxing deployment limits.
        payload = self.store.install("native-payload", [
            {"path": f"frame.{index:04d}", "content": raw[offset:offset + CHUNK_BYTES], "executable": False}
            for index, offset in enumerate(range(0, len(raw), CHUNK_BYTES))])
        self.checkpoint("after_native_payload_commit")
        metadata = {"schema": SCHEMA, "source_digest": self.source_digest,
                    "connection_id": self.connection_id, "frame_id": "native-frame-" + uuid.uuid4().hex,
                    "kind": kind, "request_id": request_id, "payload_digest": payload,
                    "raw_digest": digest(raw), "raw_size": len(raw)}
        artifact = self.store.install("native-frame", [
            {"path": "frame.json", "content": canonical_bytes(metadata), "executable": False}])
        self.checkpoint("after_native_frame_commit")
        self._current()
        receipt = NativeFrameReceipt(artifact)
        # Keep existing demultiplexing/UI behavior, but only after durability.
        # The listener receives a detached parse, never the RPC return object.
        if self.notify is not None:
            self.notify(_decode(raw), raw=raw, kind=kind, connection_id=connection_id)
        self._current()
        return receipt

    def read(self, receipt):
        """Verify stored bytes/scope; historical inspection grants no authority."""
        if type(receipt) is not NativeFrameReceipt:
            raise Denied("sealed native-frame receipt required")
        manifest, contents = self.store.verify(_hash(receipt.artifact_digest))
        if manifest["component"] != "native-frame" or set(contents) != {"frame.json"} or \
                any(entry["executable"] for entry in manifest["files"]):
            raise Denied("native-frame receipt artifact differs")
        metadata = strict_json(contents["frame.json"])
        exact(metadata, {"schema", "source_digest", "connection_id", "frame_id", "kind", "request_id",
                         "payload_digest", "raw_digest", "raw_size"})
        if metadata["schema"] != SCHEMA or metadata["source_digest"] != self.source_digest or \
                metadata["connection_id"] != self.connection_id or \
                type(metadata["raw_size"]) is not int or not 1 <= metadata["raw_size"] <= MAX_FRAME_BYTES or \
                type(metadata["frame_id"]) is not str or not re.fullmatch(r"native-frame-[a-f0-9]{32}", metadata["frame_id"]):
            raise Denied("native-frame source/connection/size differs")
        payload_manifest, chunks = self.store.verify(_hash(metadata["payload_digest"]))
        names = [f"frame.{index:04d}" for index in range((metadata["raw_size"] + CHUNK_BYTES - 1) // CHUNK_BYTES)]
        if payload_manifest["component"] != "native-payload" or set(chunks) != set(names) or \
                any(entry["executable"] for entry in payload_manifest["files"]) or \
                any(len(chunks[name]) != CHUNK_BYTES for name in names[:-1]):
            raise Denied("native payload chunk layout differs")
        raw = b"".join(chunks[name] for name in names)
        if len(raw) != metadata["raw_size"] or digest(raw) != _hash(metadata["raw_digest"]):
            raise Denied("native payload digest/size differs")
        message = _decode(raw)
        request_id = self._kind(message, metadata["kind"])
        if type(request_id) is not type(metadata["request_id"]) or request_id != metadata["request_id"]:
            raise Denied("native capture typed request ID differs")
        return metadata, message, raw

    def response_evidence(self, receipt, *, response, request_id):
        self._current()
        metadata, message, _ = self.read(receipt)
        _request_id(request_id)
        if metadata["kind"] != "response" or type(message["id"]) is not type(request_id) or \
                message["id"] != request_id or _encode(message) != _encode(response):
            raise Denied("native response differs from durable captured acknowledgment")
        self._current()
        return {"schema": "ccrelay.native_frame_receipt.v1", "artifact_digest": receipt.artifact_digest,
                "source_digest": metadata["source_digest"], "connection_id": metadata["connection_id"],
                "frame_id": metadata["frame_id"], "raw_digest": metadata["raw_digest"], "raw_size": metadata["raw_size"]}
