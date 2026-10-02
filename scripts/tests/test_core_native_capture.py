"""Real sealed frame bytes; synthetic source pins and Mac ancestor observations."""
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from native_resume_fixtures import fixture_capture
from owner_fixtures import writable_fixture_tree
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied
from relay_core.native_capture import MAX_FRAME_BYTES, NativeCapture, NativeFrameReceipt
from relay_core.native_rpc import _decode, _encode


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        patch = mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path))
        patch.start()
        self.addCleanup(patch.stop)
        self.capture = fixture_capture(self.folder / "artifacts", "native-connection-fixture")

    def save(self, raw=b'{"id":7,"result":{"ok":true}}', kind="response"):
        return self.capture(_decode(raw), raw=raw, kind=kind, connection_id=self.capture.connection_id)

    def test_original_bytes_floats_whitespace_and_large_history_survive_reopen(self):
        raw = b'{ "id": 7, "result": { "duration": 1.5000, "history": "' + b'x' * 70000 + b'" } }'
        receipt = self.save(raw)
        reopened = NativeCapture(self.capture.store, source_digest=self.capture.source_digest,
                                 connection_id=self.capture.connection_id, current_source=self.capture.current_source)
        metadata, message, recovered = reopened.read(receipt)
        self.assertEqual(raw, recovered)
        self.assertEqual(message["result"]["duration"], 1.5)
        evidence = reopened.response_evidence(receipt, response=message, request_id=7)
        self.assertLess(len(canonical_bytes(evidence)), 1024)
        self.assertEqual(evidence["raw_size"], len(raw))
        self.assertEqual(metadata["kind"], "response")

    def test_full_transport_size_uses_complete_ordered_nonexecutable_chunks(self):
        empty = _encode({"id": 7, "result": {"text": ""}})
        raw = _encode({"id": 7, "result": {"text": "x" * (MAX_FRAME_BYTES - len(empty))}})
        self.assertEqual(len(raw), MAX_FRAME_BYTES)
        metadata, _, restored = self.capture.read(self.save(raw))
        self.assertEqual(restored, raw)
        manifest, chunks = self.capture.store.verify(metadata["payload_digest"])
        self.assertEqual(len(chunks), 8)
        self.assertTrue(all(not entry["executable"] for entry in manifest["files"]))
        with self.assertRaises(Denied):
            self.capture({}, raw=raw + b" ", kind="response", connection_id=self.capture.connection_id)

    def test_events_keep_distinct_receipts_and_shared_payloads_without_approval(self):
        raw = b'{"method":"thread/goal/updated","params":{"threadId":"foreign-thread","goal":null}}'
        first, second = self.save(raw, "notification"), self.save(raw, "notification")
        a, b = self.capture.read(first)[0], self.capture.read(second)[0]
        self.assertNotEqual(first, second)
        self.assertNotEqual(a["frame_id"], b["frame_id"])
        self.assertEqual(a["payload_digest"], b["payload_digest"])
        request = b'{"id":"7","method":"item/commandExecution/requestApproval","params":{}}'
        metadata, message, stored = self.capture.read(self.save(request, "server_request"))
        self.assertEqual(stored, request)
        self.assertEqual(metadata["request_id"], "7")
        self.assertEqual(message["method"], "item/commandExecution/requestApproval")
        with self.assertRaises(Denied):
            self.capture.response_evidence(first, response=_decode(raw), request_id=7)

    def test_kind_typed_ids_raw_message_mismatch_and_malformed_bytes_are_rejected(self):
        for raw, kind in ((b'{"id":true,"result":{}}', "response"),
                          (b'{"id":7,"result":{},"error":{}}', "response"),
                          (b'{"id":7,"method":"warning"}', "notification"),
                          (b'{"method":"warning"}', "server_request"),
                          (b'{"method":"bad event"}', "notification"),
                          (b'{"id":7,"result":{}}', "invented"),
                          (b'{"id":7,"id":7,"result":{}}', "response"),
                          (b'{"id":7,"result":{"value":NaN}}', "response")):
            with self.subTest(raw=raw), self.assertRaises(Denied):
                self.save(raw, kind)
        raw = b'{"id":7,"result":{"ok":true}}'
        with self.assertRaises(Denied):
            self.capture({"id": 7, "result": {"ok": 1}}, raw=raw, kind="response", connection_id=self.capture.connection_id)
        self.assertEqual(list(self.capture.store.root.iterdir()), [])

    def test_foreign_source_connection_receipt_or_response_cannot_become_evidence(self):
        receipt = self.save()
        for source, connection in ((fingerprint({"foreign": True}), self.capture.connection_id),
                                   (self.capture.source_digest, "foreign-connection")):
            foreign = NativeCapture(self.capture.store, source_digest=source, connection_id=connection, current_source=lambda: source)
            with self.assertRaises(Denied):
                foreign.read(receipt)
        for request_id in (True, "7", 8):
            with self.assertRaises(Denied):
                self.capture.response_evidence(receipt, response={"id": 7, "result": {"ok": True}}, request_id=request_id)
        with self.assertRaises(Denied):
            self.capture.response_evidence(receipt, response={"id": 7, "result": {"ok": 1}}, request_id=7)
        with self.assertRaises((Denied, OSError)):
            self.capture.read(replace(receipt, artifact_digest="sha256:" + "0" * 64))
        with self.assertRaises(Denied):
            self.capture.read({"artifact_digest": receipt.artifact_digest})

    def test_source_revoked_during_publish_keeps_forensics_but_returns_no_receipt(self):
        for index, point in enumerate(("before_native_payload_commit", "after_native_payload_commit", "after_native_frame_commit")):
            capture = fixture_capture(self.folder / str(index), "connection-fixture")
            def checkpoint(name):
                if name == point:
                    capture.current_source = lambda: fingerprint({"revoked": True})
            capture.checkpoint = checkpoint
            with self.assertRaises(Denied):
                capture({"id": 7, "result": {}}, raw=b'{"id":7,"result":{}}', kind="response", connection_id=capture.connection_id)
            self.assertTrue(any(path.is_dir() for path in capture.store.root.iterdir()))
        self.capture.current_source = lambda: fingerprint({"revoked": True})
        with self.assertRaises(Denied):
            self.save()
        self.assertEqual(list(self.capture.store.root.iterdir()), [])

    def test_modified_or_missing_payload_is_not_a_valid_durable_receipt(self):
        receipt = self.save()
        metadata = self.capture.read(receipt)[0]
        payload = self.capture.store._directory(metadata["payload_digest"]) / "frame.0000"
        os.chmod(payload, 0o600)
        payload.write_bytes(b'{"id":7,"result":{"ok":false}}')
        os.chmod(payload, 0o400)
        with self.assertRaises(Denied):
            self.capture.read(receipt)
        os.chmod(payload.parent, 0o700)
        payload.unlink()
        os.chmod(payload.parent, 0o500)
        with self.assertRaises((Denied, OSError)):
            self.capture.read(receipt)

    def test_listener_runs_after_sealing_and_cannot_modify_stored_message(self):
        def listener(message, **_):
            self.assertEqual(sum(p.is_dir() for p in self.capture.store.root.iterdir()), 2)
            message["result"]["ok"] = False
        self.capture.notify = listener
        receipt = self.save()
        self.assertTrue(self.capture.read(receipt)[1]["result"]["ok"])
        self.capture.current_source = lambda: fingerprint({"changed": True})
        self.assertTrue(self.capture.read(receipt)[1]["result"]["ok"])  # Historical bytes, not current authority.
        with self.assertRaises(Denied):
            self.capture.response_evidence(receipt, response={"id": 7, "result": {"ok": True}}, request_id=7)


if __name__ == "__main__":
    unittest.main()
