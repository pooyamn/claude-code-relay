"""Real captured reads/registry, explicitly synthetic loaded-context/kernel facts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from native_epoch_fixtures import enroll_epochs, establish_baseline, open_epochs, settings_event
from native_rpc_fixtures import RPCFixture
from native_ws_fixtures import WSRPCFixture
from native_session_fixtures import CONTROLLER, enrollment, native_fixture
from owner_fixtures import writable_fixture_tree
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied
from relay_core.native_observe import CONTEXT_SCHEMA, CodexNativeObserver, NativeContextReceipt, thread_state


class ObserveTests(unittest.TestCase):
    wire_type = RPCFixture

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.fixture = native_fixture(self.folder)
        self.registry, self.authority = self.fixture.__enter__()
        self.addCleanup(lambda: self.fixture.__exit__(None, None, None))
        self.registry.enroll(CONTROLLER, enrollment())
        self.controls = open_epochs(self.folder / "epochs", policy_digest=self.authority.policy.digest)
        self.addCleanup(self.controls.close)
        self.wire = self.wire_type()
        self.addCleanup(self.wire.close)
        enroll_epochs(self.controls, self.wire, self.folder / "artifacts")
        self.wire.initialize()
        establish_baseline(self.controls, self.wire)
        self.change_context = lambda context: context
        self.context_calls = []
        self.observer = CodexNativeObserver(self.wire.rpc, self.controls, inspect_loaded_context=self.context)
        self.registry.observe_runtime = self.observer

    def context(self, binding, record, probe_id, ticket, read_reference):
        # These values are synthetic fixture measurements, NOT copied-native
        # runtime/provenance proof. The artifact ownership/bytes/sealing is real.
        context = {"schema": CONTEXT_SCHEMA, "probe_id": probe_id, "binding_digest": fingerprint(binding),
                   "source_digest": ticket.source_digest, "connection_id": ticket.connection_id, "control_epoch": ticket.epoch,
                   "read_artifact_digest": read_reference["artifact_digest"], "provider": "codex",
                   "provider_session_id": "native-thread-1", "worktree": "/fixture/worktree",
                   "runtime_digest": "sha256:" + "a" * 64, "tool_contract_digest": "sha256:" + "b" * 64,
                   "permission_digest": "sha256:" + "c" * 64, "capabilities": ["read", "exact_resume"]}
        self.context_calls.append(context)
        context = self.change_context(deepcopy(context))
        artifact = self.wire.rpc.capture.store.install("native-context", [
            {"path": "context.json", "content": canonical_bytes(context), "executable": False}])
        return NativeContextReceipt(artifact)

    def thread(self, status="idle", active=False):
        return {"id": "native-thread-1", "sessionId": "different-tree-root", "cwd": "/fixture/worktree",
                "status": {"type": status, **({"activeFlags": []} if status == "active" else {})},
                "turns": [{"id": "prior-turn", "status": "completed", "items": [{"id": "tool-1", "type": "mcpToolCall", "arguments": {"duration": 1.5}}]}] +
                         ([{"id": "active-turn", "status": "inProgress", "items": []}] if active else [])}

    def refresh(self, thread=None, *, event=None):
        def provider(peer):
            request = peer.receive()
            self.assertEqual(request["method"], "thread/read")
            self.assertEqual(request["params"], {"threadId": "native-thread-1", "includeTurns": True})
            if event:
                peer.write(event)
            peer.write({"id": request["id"], "result": {"thread": thread if thread is not None else self.thread()}})
        self.wire.peer.start(provider)
        try:
            return self.registry.refresh(CONTROLLER, "builder.task", expected_revision=self.registry.cached("builder.task").revision)
        finally:
            self.wire.peer.finish()

    def test_registry_joins_exact_captured_read_epochs_and_sealed_context_without_start_or_resume(self):
        observed = self.refresh(self.thread("active", True))
        self.assertTrue(observed.fields["ready"])  # Synthetic context only, not real target readiness.
        self.assertEqual(observed.fields["active_turn_id"], "active-turn")
        row = self.registry.connection.execute("SELECT body FROM native_history WHERE revision=?", (observed.revision,)).fetchone()
        evidence = json.loads(row[0])["observation"]["evidence"]
        self.assertEqual(evidence["schema"], "ccrelay.codex_observation.v1")
        self.assertEqual(evidence["control_epoch"]["connection_id"], self.wire.rpc.connection_id)
        self.assertEqual([call[0] for call in self.wire.authorized], ["thread/resume", "thread/read"])
        self.wire.peer.assert_quiet()

    def test_idle_not_loaded_system_error_and_incomplete_active_do_not_claim_pause_or_stop(self):
        for status, active, expected in (("idle", False, "running"), ("notLoaded", False, "unknown"),
                                          ("systemError", True, "failed"), ("active", False, "unknown")):
            with self.subTest(status=status):
                observed = self.refresh(self.thread(status, active))
                self.assertEqual(observed.fields["observed_state"], expected)
                self.assertEqual(observed.fields["ready"], expected == "running")
                self.assertNotIn(observed.fields["observed_state"], {"paused", "stopped"})

    def test_matching_settings_event_during_read_rejects_snapshot_before_context_verification(self):
        with self.assertRaises(Denied):
            self.refresh(event=settings_event())
        self.assertEqual(self.context_calls, [])
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_wrong_exact_thread_worktree_or_missing_native_status_never_confirms(self):
        for change in ({"id": "different-tree-root"}, {"cwd": "/different"}, {"status": {}}, {"turns": None}):
            with self.subTest(change=change), self.assertRaises(Denied):
                self.refresh({**self.thread(), **change})
        self.assertEqual(self.context_calls, [])
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_copied_dict_or_missing_context_verifier_has_no_default_permission_fallback(self):
        with self.assertRaises(Denied):
            CodexNativeObserver(self.wire.rpc, self.controls, inspect_loaded_context=None)
        self.observer.inspect_loaded_context = lambda *args: {"runtime_digest": "sha256:" + "a" * 64}
        with self.assertRaises(Denied):
            self.refresh()
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_context_verifier_cannot_rewrite_the_captured_read_scope(self):
        def rewrite(binding, record, probe_id, ticket, read_reference):
            read_reference["artifact_digest"] = "sha256:" + "d" * 64
            return self.context(binding, record, probe_id, ticket, read_reference)
        self.observer.inspect_loaded_context = rewrite
        with self.assertRaises(Denied):
            self.refresh()
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_context_receipt_must_match_probe_read_source_epoch_provider_worktree_and_measured_contract(self):
        for change in ({"probe_id": "old-probe"}, {"read_artifact_digest": "sha256:" + "d" * 64},
                       {"source_digest": "sha256:" + "d" * 64}, {"connection_id": "foreign"}, {"control_epoch": True},
                       {"provider": "claude"}, {"provider_session_id": "different-tree-root"}, {"worktree": "/different"},
                       {"runtime_digest": "sha256:" + "d" * 64}, {"tool_contract_digest": "sha256:" + "d" * 64},
                       {"permission_digest": "sha256:" + "d" * 64}):
            self.change_context = lambda context: {**context, **change}
            with self.subTest(change=change), self.assertRaises(Denied):
                self.refresh()
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_control_or_owner_pause_during_context_inspection_invalidates_commit(self):
        for owner_pause in (False, True):
            def change(context):
                if owner_pause:
                    old = self.registry.cached("builder.task")
                    self.registry.desired(CONTROLLER, old.id, "paused", expected_revision=old.revision)
                else:
                    self.controls.invalidate(self.wire.rpc, expected_epoch=context["control_epoch"], reason="control_requested")
                return context
            self.change_context = change
            with self.assertRaises(Denied):
                self.refresh()
            self.assertFalse(self.registry.cached("builder.task").fields["ready"])
            if not owner_pause:
                establish_baseline(self.controls, self.wire, "resume-2")

    def test_restore_retains_read_and_context_evidence_but_not_current_readiness(self):
        observed = self.refresh()
        history = self.registry.connection.execute("SELECT body FROM native_history WHERE revision=?", (observed.revision,)).fetchone()[0]
        self.registry.recover_inflight()
        recovered = self.registry.cached("builder.task")
        self.assertFalse(recovered.fields["ready"])
        self.assertEqual(recovered.fields["provider_session_id"], "native-thread-1")
        self.assertEqual(self.registry.connection.execute("SELECT body FROM native_history WHERE revision=?", (observed.revision,)).fetchone()[0], history)
        self.wire.peer.assert_quiet()


class WSObserveTests(ObserveTests):
    wire_type = WSRPCFixture


class StateTests(unittest.TestCase):
    def test_duplicate_multiple_active_unknown_flags_and_idle_with_active_turn_are_not_guessed(self):
        active = {"id": "turn-1", "status": "inProgress", "items": []}
        thread = {"id": "native-1", "cwd": "/worktree", "status": {"type": "active", "activeFlags": []}, "turns": [active]}
        variants = ({**thread, "turns": [active, active]}, {**thread, "turns": [active, {**active, "id": "turn-2"}]},
                    {**thread, "status": {"type": "active", "activeFlags": ["futureFlag"]}}, {**thread, "status": {"type": "idle"}},
                    {**thread, "turns": [{**active, "status": "futureState"}]})
        for value in variants:
            with self.assertRaises(Denied):
                thread_state(value, thread_id="native-1", worktree="/worktree")


if __name__ == "__main__":
    unittest.main()
