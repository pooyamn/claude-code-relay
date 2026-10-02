"""Epoch races/recovery over real pipes and UnixWS; no live native/OS proof."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from native_epoch_fixtures import enroll_epochs, establish_baseline, open_epochs, settings_event
from native_resume_fixtures import resume_settings
from native_rpc_fixtures import RPCFixture
from native_ws_fixtures import WSRPCFixture
from owner_fixtures import writable_fixture_tree
from relay_core.contracts import fingerprint
from relay_core.identity import Denied


class EpochTests(unittest.TestCase):
    wire_type = RPCFixture

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        patch = mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path))
        patch.start()
        self.addCleanup(patch.stop)
        self.ledger = open_epochs(self.folder / "epochs")
        self.addCleanup(lambda: self.ledger.close())
        self.wire = self.wire_type()
        self.addCleanup(self.wire.close)
        enroll_epochs(self.ledger, self.wire, self.folder / "artifacts")
        self.wire.initialize()

    def event(self, value):
        self.wire.peer.write(value)
        self.assertTrue(self.wire.rpc.poll(timeout_ms=100))

    def test_initialization_and_unsolicited_matching_settings_cannot_create_a_baseline(self):
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        self.event(settings_event())
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        establish_baseline(self.ledger, self.wire)
        ticket = self.ledger.ticket(self.wire.rpc)
        self.assertEqual(ticket, self.ledger.validate(self.wire.rpc, ticket))
        self.assertEqual(len(list(self.ledger.frames(self.wire.rpc.capture))), 3)

    def test_matching_settings_event_invalidates_old_ticket_but_preserves_reviewed_baseline(self):
        establish_baseline(self.ledger, self.wire)
        old = self.ledger.ticket(self.wire.rpc)
        self.event(settings_event())
        with self.assertRaises(Denied):
            self.ledger.validate(self.wire.rpc, old)
        new = self.ledger.ticket(self.wire.rpc)
        self.assertEqual(new.epoch, old.epoch + 1)
        self.assertEqual(new.settings_digest, old.settings_digest)
        self.assertFalse(hasattr(new, "ready"))

    def test_settings_event_in_flight_cannot_be_overwritten_by_a_delayed_resume_baseline(self):
        epoch = self.ledger.invalidate(self.wire.rpc, expected_epoch=0, reason="resume_requested")
        def resume(peer):
            request = peer.receive()
            peer.write(settings_event())
            peer.write({"id": request["id"], "result": {**resume_settings(), "thread": {"id": "native-thread-1"}}})
        self.wire.peer.start(resume)
        response = self.wire.rpc.rpc("thread/resume", {"threadId": "native-thread-1", "cwd": "/fixture/worktree"}, request_id="resume-race")
        self.wire.peer.finish()
        with self.assertRaises(Denied):
            self.ledger.accept_resume(self.wire.rpc, expected_epoch=epoch, request_id="resume-race", response=response)
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        self.assertEqual(len(list(self.ledger.frames(self.wire.rpc.capture))), 3)

    def test_missing_control_scope_and_permission_requests_invalidate_settings_evidence(self):
        establish_baseline(self.ledger, self.wire)
        self.event({"method": "thread/settings/updated", "params": {"threadSettings": {}}})
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        establish_baseline(self.ledger, self.wire, "resume-2")
        self.event({"id": 20, "method": "item/permissions/requestApproval", "params": {"threadId": "native-thread-1"}})
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        self.assertEqual(self.wire.authorized_replies, [])
        self.wire.peer.assert_quiet()

    def test_permission_baseline_artifact_damage_and_boolean_epoch_alias_are_rejected(self):
        establish_baseline(self.ledger, self.wire)
        old = self.ledger.ticket(self.wire.rpc)
        with self.assertRaises(Denied):
            replace(old, epoch=True)
        from relay_core.native_capture import NativeFrameReceipt
        reference = self.ledger._row(old.connection_id)["baseline_reference"]
        metadata = self.wire.rpc.capture.read(NativeFrameReceipt(reference["artifact_digest"]))[0]
        payload = self.wire.rpc.capture.store._directory(metadata["payload_digest"]) / "frame.0000"
        import os
        os.chmod(payload, 0o600)
        payload.write_bytes(b"corrupted fixture bytes")
        os.chmod(payload, 0o400)
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)

    def test_unreviewed_or_unsupported_settings_cannot_be_repaired_by_a_delayed_matching_event(self):
        establish_baseline(self.ledger, self.wire)
        self.event(settings_event(sandboxPolicy={"type": "readOnly", "networkAccess": True}))
        self.event(settings_event())
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        self.assertEqual(self.ledger._row(self.wire.rpc.connection_id)["state"], "unknown")
        establish_baseline(self.ledger, self.wire, "resume-2")
        self.event(settings_event(activePermissionProfile={"id": "unreviewed-profile"}))
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)

    def test_foreign_thread_and_tool_updates_are_retained_without_changing_control_epoch(self):
        establish_baseline(self.ledger, self.wire)
        old = self.ledger.ticket(self.wire.rpc)
        foreign = settings_event(sandboxPolicy={"type": "dangerFullAccess"})
        foreign["params"]["threadId"] = "foreign-thread"
        self.event(foreign)
        self.event({"method": "item/agentMessage/delta", "params": {"threadId": "native-thread-1", "delta": "work", "duration": 1.5}})
        self.assertEqual(old, self.ledger.validate(self.wire.rpc, old))
        frames = list(self.ledger.frames(self.wire.rpc.capture))
        self.assertEqual([frame[0] for frame in frames], list(range(1, 5)))
        self.assertEqual(json.loads(frames[-1][2])["params"]["duration"], 1.5)
        position, receipt, _ = frames[-1]
        self.assertEqual(self.ledger.observe(self.wire.rpc.capture, receipt), position)
        self.assertEqual(len(list(self.ledger.frames(self.wire.rpc.capture))), 4)

    def test_lifecycle_event_between_native_read_request_and_reply_rejects_the_observation_ticket(self):
        establish_baseline(self.ledger, self.wire)
        old = self.ledger.ticket(self.wire.rpc)
        def read(peer):
            request = peer.receive()
            peer.write({"method": "turn/started", "params": {"threadId": "native-thread-1", "turn": {"id": "turn-2", "status": "inProgress"}}})
            peer.write({"id": request["id"], "result": {"thread": {"id": "native-thread-1", "status": {"type": "active"}}}})
        self.wire.peer.start(read)
        self.wire.rpc.rpc("thread/read", {"threadId": "native-thread-1"}, request_id="read-1")
        self.wire.peer.finish()
        with self.assertRaises(Denied):
            self.ledger.validate(self.wire.rpc, old)
        self.assertGreater(self.ledger.ticket(self.wire.rpc).epoch, old.epoch)

    def test_wrong_consumer_source_ticket_or_control_revision_cannot_supply_freshness(self):
        establish_baseline(self.ledger, self.wire)
        old = self.ledger.ticket(self.wire.rpc)
        for ticket in (replace(old, connection_id="foreign-connection"), replace(old, epoch=old.epoch + 1),
                       replace(old, source_digest=fingerprint({"foreign": True})), {"epoch": old.epoch}):
            with self.assertRaises(Denied):
                self.ledger.validate(self.wire.rpc, ticket)
        with self.assertRaises(Denied):
            self.ledger.invalidate(self.wire.rpc, expected_epoch=old.epoch - 1, reason="control_requested")
        self.ledger.current_source = lambda _: fingerprint({"revoked": True})
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        self.ledger.current_source = lambda _: old.source_digest
        self.wire.rpc.capture.observe_receipt = None
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)

    def test_closed_thread_cannot_be_revived_by_a_matching_notification_or_enrollment_replay(self):
        establish_baseline(self.ledger, self.wire)
        self.event({"method": "thread/closed", "params": {"threadId": "native-thread-1"}})
        with self.assertRaises(Denied):
            self.ledger.ticket(self.wire.rpc)
        row = self.ledger.enroll(self.wire.rpc, thread_id="native-thread-1", worktree="/fixture/worktree",
                                 settings_digest=self.ledger._row(self.wire.rpc.connection_id)["settings_digest"])
        self.assertEqual(row["state"], "closed")
        with self.assertRaises(Denied):
            self.event(settings_event())
        self.assertTrue(self.wire.peer.channel.closed)

    def test_restart_preserves_frames_and_baseline_but_invalidates_current_epoch(self):
        establish_baseline(self.ledger, self.wire)
        old = self.ledger.ticket(self.wire.rpc)
        reference = self.ledger._row(old.connection_id)["baseline_reference"]
        frames = list(self.ledger.frames(self.wire.rpc.capture))
        self.ledger.close()
        self.ledger = open_epochs(self.folder / "epochs")
        row = self.ledger._row(old.connection_id)
        self.assertEqual(row["state"], "unknown")
        self.assertGreater(row["epoch"], old.epoch)
        self.assertEqual(row["baseline_reference"], reference)
        self.assertEqual(list(self.ledger.frames(self.wire.rpc.capture)), frames)
        with self.assertRaises(Denied):
            self.ledger.validate(self.wire.rpc, old)
        self.wire.peer.assert_quiet()

    def test_missing_or_changed_ordered_frame_and_incompatible_schema_are_rejected(self):
        establish_baseline(self.ledger, self.wire)
        self.ledger.connection.execute("DELETE FROM native_frames WHERE position=1")
        with self.assertRaises(Denied):
            list(self.ledger.frames(self.wire.rpc.capture))
        self.ledger.connection.execute("UPDATE native_epoch_metadata SET schema='future'")
        self.ledger.close()
        with self.assertRaises(Denied):
            open_epochs(self.folder / "epochs")


class WSEpochTests(EpochTests):
    wire_type = WSRPCFixture


class EpochDeathTests(unittest.TestCase):
    def test_actual_driver_deaths_keep_artifacts_and_invalidate_settings_without_repeating_resume(self):
        for point in ("before_native_epoch_commit", "before_native_frame_order_commit", "after_native_frame_order_commit"):
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                try:
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_epoch_fault_fixture.py")), str(folder), point],
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 73, point + ": " + result.stderr.decode())
                    ledger = open_epochs(folder / "epochs")
                    try:
                        rows = ledger.connection.execute("SELECT id FROM native_connections").fetchall()
                        self.assertEqual(len(rows), 1)
                        row = ledger._row(rows[0][0])
                        self.assertEqual(row["state"], "unknown")
                        self.assertIsNotNone(row["baseline_reference"])
                        self.assertEqual(ledger.connection.execute("SELECT COUNT(*) FROM native_frames").fetchone()[0],
                                         3 if point == "after_native_frame_order_commit" else 2)
                        import sqlite3
                        with sqlite3.connect(str(folder / "provider.sqlite")) as provider:
                            self.assertEqual(provider.execute("SELECT COUNT(*) FROM resumes").fetchone()[0], 1)
                        self.assertEqual(sum(p.is_dir() for p in (folder / "artifacts").iterdir()), 6)
                    finally:
                        ledger.close()
                finally:
                    writable_fixture_tree(folder)


if __name__ == "__main__":
    unittest.main()
