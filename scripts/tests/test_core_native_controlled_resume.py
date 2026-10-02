"""Joined control/observation with real wires and explicitly synthetic native facts."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from controlled_resume_fixtures import controlled_fixture, resume_count, run_resume, store_resume
from native_epoch_fixtures import settings_event
from native_session_fixtures import CONTROLLER, enrollment
from native_ws_fixtures import WSRPCFixture
from outbox_fixtures import CONTEXT
from owner_fixtures import writable_fixture_tree
from relay_core.identity import Denied
from relay_core.native_controlled_resume import ADAPTER, CodexControlledResume
from relay_core.native_resume import resume_action
from native_resume_fixtures import SETTINGS_DIGEST


class ControlledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = controlled_fixture(self.folder)
        self.fixture = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        store_resume(self.fixture)

    def deliver(self, action_id="resume-1"):
        f = self.fixture
        return f.adapter.deliver(f.ledger, action_id, "resume-attempt", f.registry, CONTROLLER)

    def test_exact_resume_establishes_baseline_then_reads_independently_and_confirms_once(self):
        f = self.fixture
        with self.assertRaises(Denied):
            f.controls.ticket(f.wire.rpc)
        self.assertEqual(run_resume(f)["state"], "confirmed")
        ticket = f.controls.ticket(f.wire.rpc)
        self.assertTrue(f.registry.cached("builder.task").fields["ready"])  # Synthetic fixture only.
        stored = f.ledger.load("resume-1")
        self.assertEqual(stored["plan"]["adapter_id"], ADAPTER)
        body = f.ledger.connection.execute("SELECT body FROM evidence WHERE id=?", (stored["record"].fields["outcome_evidence_id"],)).fetchone()[0]
        self.assertEqual(json.loads(body)["payload"]["native_control_epoch"], asdict(ticket))
        self.assertEqual([item[0] for item in f.wire.authorized], ["thread/resume", "thread/read"])
        self.assertEqual(self.deliver()["state"], "confirmed")
        self.assertEqual(resume_count(self.folder), 1)
        f.wire.peer.assert_quiet()

    def test_events_during_resume_or_read_cannot_confirm_or_retry(self):
        self.assertEqual(run_resume(self.fixture, event=settings_event(), expect_read=False)["state"], "unknown")
        self.assertFalse(self.fixture.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.deliver()["state"], "unknown")
        store_resume(self.fixture, "replacement")
        self.assertEqual(self.deliver("replacement")["state"], "held")
        self.assertEqual(resume_count(self.folder), 1)
        with controlled_fixture(self.folder / "read-race") as f:
            store_resume(f)
            self.assertEqual(run_resume(f, read_event=settings_event())["state"], "unknown")
            self.assertFalse(f.registry.cached("builder.task").fields["ready"])
            self.assertEqual(resume_count(f.folder), 1)

    def test_settings_mismatch_stays_unknown_before_context_inspection(self):
        def mismatch(response):
            response["result"]["sandbox"]["networkAccess"] = True
            return response
        self.assertEqual(run_resume(self.fixture, expect_read=False, change_response=mismatch)["state"], "unknown")
        with self.assertRaises(Denied):
            self.fixture.controls.ticket(self.fixture.wire.rpc)
        self.assertFalse(self.fixture.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(resume_count(self.folder), 1)

    def test_wrong_policy_settings_cohort_or_observer_is_held_before_native_submission(self):
        f = self.fixture
        original = f.controls.policy_digest
        f.controls.policy_digest = "sha256:" + "d" * 64
        self.assertEqual(self.deliver()["state"], "held")
        f.controls.policy_digest = original
        store_resume(f, "wrong-settings", settings_digest="sha256:" + "d" * 64)
        self.assertEqual(self.deliver("wrong-settings")["state"], "held")
        self.assertEqual(resume_count(self.folder), 0)
        f.wire.peer.assert_quiet()
        with self.assertRaises(Denied):
            CodexControlledResume(f.wire.rpc.rpc, f.controls, f.observer, authorize=lambda *_: "fixture", resume_supported=True)

    def test_changed_observer_is_held_before_any_control_or_effect(self):
        f = self.fixture
        f.registry.observe_runtime = lambda *_: None
        self.assertEqual(self.deliver()["state"], "held")
        self.assertEqual(f.controls._row(f.wire.rpc.connection_id)["epoch"], 0)
        self.assertEqual(resume_count(self.folder), 0)

    def test_another_native_mapping_cannot_use_this_connections_control_cohort(self):
        f = self.fixture
        f.registry.enroll(CONTROLLER, enrollment("builder.other", native_id="foreign-thread"))
        action = resume_action(f.registry._row("builder.other"), "other-resume", settings_digest=SETTINGS_DIGEST)
        f.ledger.store(action, CONTEXT)
        self.assertEqual(self.deliver("other-resume")["state"], "held")
        self.assertEqual(f.controls._row(f.wire.rpc.connection_id)["epoch"], 0)
        self.assertEqual(resume_count(self.folder), 0)
        f.wire.peer.assert_quiet()

    def test_reply_and_baseline_without_independent_context_never_confirm(self):
        f = self.fixture
        f.observer.inspect_loaded_context = lambda *_: None
        self.assertEqual(run_resume(f)["state"], "unknown")
        self.assertFalse(f.registry.cached("builder.task").fields["ready"])
        # The settings baseline is real fixture evidence, not task readiness.
        f.controls.ticket(f.wire.rpc)
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(resume_count(self.folder), 1)
        f.wire.peer.assert_quiet()

    def test_pause_at_epoch_commit_prevents_submission(self):
        f = self.fixture
        def checkpoint(point):
            if point == "after_resume_epoch_invalidation":
                record = f.registry.cached("builder.task")
                f.registry.desired(CONTROLLER, record.id, "paused", expected_revision=record.revision)
        f.ledger.checkpoint = checkpoint
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(resume_count(self.folder), 0)
        self.assertFalse(f.registry.cached("builder.task").fields["ready"])
        with self.assertRaises(Denied):
            f.controls.ticket(f.wire.rpc)
        f.wire.peer.assert_quiet()

    def test_control_change_after_observation_clears_cached_readiness_and_cannot_confirm(self):
        f = self.fixture
        def checkpoint(point):
            if point == "after_resume_fresh_observation":
                ticket = f.controls.ticket(f.wire.rpc)
                f.controls.invalidate(f.wire.rpc, expected_epoch=ticket.epoch, reason="fixture_control_change")
        f.ledger.checkpoint = checkpoint
        self.assertEqual(run_resume(f)["state"], "unknown")
        self.assertFalse(f.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(resume_count(self.folder), 1)

    def test_unix_ws_uses_same_joined_flow_without_transport_fallback(self):
        with controlled_fixture(self.folder / "ws", wire_type=WSRPCFixture) as f:
            store_resume(f)
            self.assertEqual(run_resume(f)["state"], "confirmed")
            self.assertEqual(resume_count(f.folder), 1)
            self.assertTrue(f.registry.cached("builder.task").fields["ready"])
            f.wire.peer.assert_quiet()

    def test_actual_driver_deaths_retain_both_ledgers_without_repeating_native_resume(self):
        for point in ("after_resume_epoch_invalidation", "after_resume_epoch_baseline", "before_receipt_commit", "after_receipt_commit"):
            folder = self.folder / point
            with controlled_fixture(folder) as f:
                store_resume(f)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("controlled_resume_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, point + ": " + result.stderr.decode())
            before = resume_count(folder)
            self.assertEqual(before, 0 if point == "after_resume_epoch_invalidation" else 1)
            with controlled_fixture(folder) as f:
                recovered = f.adapter.deliver(f.ledger, "resume-1", "resume-attempt", f.registry, CONTROLLER)
                self.assertEqual(recovered["state"], "confirmed" if point == "after_receipt_commit" else "unknown")
                self.assertEqual(resume_count(folder), before)
                self.assertFalse(f.registry.cached("builder.task").fields["ready"])
                with self.assertRaises(Denied):
                    f.controls.ticket(f.wire.rpc)
                f.wire.peer.assert_quiet()


if __name__ == "__main__":
    unittest.main()
