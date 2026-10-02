"""Resume/control/outbox fencing with real SQLite/deaths and synthetic runtime."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from native_resume_fixtures import FakeResume, SETTINGS_DIGEST
from native_session_fixtures import CONTROLLER, enrollment, native_fixture, observation
from outbox_fixtures import CONTEXT, open_outbox
from relay_core.identity import Denied, Peer
from relay_core.contracts import decode, fingerprint, intent_payload
from relay_core.native_resume import CodexExactResume, resume_action
from relay_core.runtime_delivery import evidence_for


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.observed = []
        self.change_observation = lambda value: value
        def inspect(binding, record, probe_id):
            self.observed.append(record)
            return self.change_observation(observation(binding, record, probe_id))
        self.fixture = native_fixture(self.folder, observer=inspect)
        self.registry, self.authority = self.fixture.__enter__()
        self.addCleanup(lambda: self.fixture.__exit__(None, None, None))
        self.registry.enroll(CONTROLLER, enrollment())
        self.ledger = open_outbox(self.folder / "ledger", policy_digest=self.authority.policy.digest)
        self.addCleanup(lambda: self.ledger.close())
        self.native = FakeResume(self.folder / "provider.sqlite")
        self.addCleanup(self.native.close)
        self.adapter = CodexExactResume(self.native.rpc, authorize=lambda *_: "fixture-admission", resume_supported=True)

    def store(self, action_id="resume-1"):
        action = resume_action(self.registry._row("builder.task"), action_id, settings_digest=SETTINGS_DIGEST)
        self.ledger.store(action, CONTEXT)
        return action

    def deliver(self, action_id="resume-1", peer=CONTROLLER):
        attempt_id = "resume-attempt" if action_id == "resume-1" else "resume-attempt-" + action_id
        return self.adapter.deliver(self.ledger, action_id, attempt_id, self.registry, peer)

    def independent_outbox_case(self, suffix):
        self.ledger.close()
        self.ledger = open_outbox(self.folder / suffix, policy_digest=self.authority.policy.digest)

    def test_exact_id_and_worktree_resume_once_with_independent_fresh_observation(self):
        self.store()
        result = self.deliver()
        self.assertEqual(result["state"], "confirmed")
        self.assertEqual(self.native.count(), 1)
        self.assertEqual(len(self.observed), 1)
        self.assertFalse(self.observed[0].fields["ready"])
        self.assertEqual(self.registry.cached("builder.task").fields["provider_session_id"], "native-thread-1")
        plan = self.ledger.load("resume-1")["plan"]
        self.assertEqual(plan["parameters"], {"threadId": "native-thread-1", "cwd": "/fixture/worktree"})
        self.assertEqual(self.deliver()["state"], "confirmed")
        self.assertEqual(self.native.count(), 1)

    def test_old_readiness_is_invalidated_before_rpc_and_ack_alone_does_not_restore_it(self):
        old = self.registry.refresh(CONTROLLER, "builder.task", expected_revision=0)
        self.assertTrue(old.fields["ready"])
        self.store()
        def rpc(method, parameters, *, request_id):
            record = self.registry.cached("builder.task")
            self.assertFalse(record.fields["ready"])
            self.assertEqual(record.fields["observed_state"], "unknown")
            self.assertIsNone(self.registry._row("builder.task")["probe_id"])
            return self.native.rpc(method, parameters, request_id=request_id)
        self.adapter.rpc = rpc
        self.change_observation = lambda value: replace(value, permission_digest="sha256:" + "d" * 64)
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(self.native.count(), 1)

    def test_lost_reply_is_unknown_not_a_retry_or_fresh_thread(self):
        self.store()
        def rpc(method, parameters, *, request_id):
            self.native.rpc(method, parameters, request_id=request_id)
            raise TimeoutError("fixture lost ACK")
        self.adapter.rpc = rpc
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(self.native.count(), 1)
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_reported_settings_mismatch_is_unknown_before_observer_and_never_retried(self):
        self.registry.refresh(CONTROLLER, "builder.task", expected_revision=0)
        self.observed.clear()
        self.store()
        def rpc(method, parameters, *, request_id):
            response = self.native.rpc(method, parameters, request_id=request_id)
            response["result"]["sandbox"]["networkAccess"] = True
            return response
        self.adapter.rpc = rpc
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(self.observed, [])
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(self.native.count(), 1)
        self.store("resume-replacement")
        self.assertEqual(self.deliver("resume-replacement")["state"], "held")
        self.assertEqual(self.native.count(), 1)

    def test_legacy_resume_without_reviewed_settings_pin_is_held_without_rpc(self):
        action = resume_action(self.registry._row("builder.task"), "resume-1", settings_digest=SETTINGS_DIGEST)
        fields = {key: value for key, value in action.to_dict().items() if key in action.fields}
        del fields["parameters"]["settings_digest"]
        fields["intent_digest"] = fingerprint(intent_payload("external_action", {"id": action.id, **fields}))
        self.ledger.store(decode(fields), CONTEXT)
        before = self.registry.cached("builder.task")
        self.assertEqual(self.deliver()["state"], "held")
        self.assertEqual(self.native.count(), 0)
        self.assertEqual(self.registry.cached("builder.task"), before)

    def test_reviewed_settings_pin_changes_the_intent_but_never_native_overrides(self):
        row = self.registry._row("builder.task")
        first = resume_action(row, "resume-1", settings_digest=SETTINGS_DIGEST)
        different = resume_action(row, "resume-1", settings_digest="sha256:" + "d" * 64)
        self.assertNotEqual(first.fields["intent_digest"], different.fields["intent_digest"])
        self.ledger.store(first, CONTEXT)
        with self.assertRaises(Denied):
            self.ledger.store(different, CONTEXT)
        self.assertEqual(self.deliver()["state"], "confirmed")
        self.assertEqual(self.ledger.load("resume-1")["plan"]["parameters"], {"threadId": "native-thread-1", "cwd": "/fixture/worktree"})

    def test_wrong_rpc_id_thread_tree_root_errors_and_malformed_ack_never_confirm(self):
        variants = [lambda rid: {"id": "foreign", "result": {"thread": {"id": "native-thread-1"}}},
                    lambda rid: {"id": rid, "result": {"thread": {"id": "different-tree-root", "sessionId": "native-thread-1"}}},
                    lambda rid: {"id": rid, "error": {"code": -1}},
                    lambda rid: {"id": rid, "result": {"thread": {"id": "native-thread-1"}}, "error": {}},
                    lambda rid: {"id": rid, "result": {"thread": []}},
                    lambda rid: {"id": rid, "jsonrpc": "unknown", "result": {"thread": {"id": "native-thread-1"}}}]
        for index, make in enumerate(variants):
            self.independent_outbox_case("envelope-" + str(index))
            action_id = "resume-" + str(index + 10)
            self.store(action_id)
            self.adapter.rpc = lambda method, parameters, *, request_id: make(request_id)
            with self.subTest(index=index):
                self.assertEqual(self.deliver(action_id)["state"], "unknown")
                self.assertFalse(self.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.observed, [])

    def test_unsupported_or_unadmitted_resume_stays_held_without_changing_native_state(self):
        self.store()
        before = self.registry.cached("builder.task")
        self.adapter.resume_supported = False
        self.assertEqual(self.deliver()["state"], "held")
        self.adapter.resume_supported = True
        def denied(*_):
            raise Denied("fixture quota/writer/context gate")
        self.adapter.authorize = denied
        self.assertEqual(self.deliver()["state"], "held")
        self.assertEqual(self.native.count(), 0)
        self.assertEqual(self.registry.cached("builder.task"), before)

    def test_worker_peer_and_changed_native_revision_cannot_resume(self):
        self.store()
        self.assertEqual(self.deliver(peer=Peer(11, 101, 121))["state"], "held")
        self.registry.refresh(CONTROLLER, "builder.task", expected_revision=0)
        self.assertEqual(self.deliver()["state"], "held")
        self.assertEqual(self.native.count(), 0)

    def test_pause_during_admission_or_after_submission_prevents_rpc(self):
        self.store()
        def pause(action, row):
            self.registry.desired(CONTROLLER, "builder.task", "paused", expected_revision=row["record"].revision)
            return "fixture-admission"
        self.adapter.authorize = pause
        self.assertEqual(self.deliver()["state"], "unknown")
        self.assertEqual(self.native.count(), 0)
        record = self.registry.cached("builder.task")
        self.registry.desired(CONTROLLER, "builder.task", "running", expected_revision=record.revision)
        self.independent_outbox_case("submission-race")
        self.store("resume-2")
        self.adapter.authorize = lambda *_: "fixture-admission"
        def checkpoint(name):
            if name == "after_submit_commit":
                record = self.registry.cached("builder.task")
                self.registry.desired(CONTROLLER, "builder.task", "paused", expected_revision=record.revision)
        self.ledger.checkpoint = checkpoint
        self.assertEqual(self.deliver("resume-2")["state"], "unknown")
        self.assertEqual(self.native.count(), 0)

    def test_pause_or_binding_revocation_during_rpc_cannot_restore_readiness(self):
        for index, revoke in enumerate((False, True)):
            if index:
                record = self.registry.cached("builder.task")
                self.registry.desired(CONTROLLER, "builder.task", "running", expected_revision=record.revision)
                self.independent_outbox_case("revocation-race")
            action_id = "resume-race-" + str(index)
            self.store(action_id)
            def rpc(method, parameters, *, request_id):
                response = self.native.rpc(method, parameters, request_id=request_id)
                if revoke:
                    self.authority.registry.revoke("builder.task")
                else:
                    record = self.registry.cached("builder.task")
                    self.registry.desired(CONTROLLER, "builder.task", "paused", expected_revision=record.revision)
                return response
            self.adapter.rpc = rpc
            self.assertEqual(self.deliver(action_id)["state"], "unknown")
            self.assertFalse(self.registry.cached("builder.task").fields["ready"])
        self.assertEqual(self.native.count(), 2)

    def test_new_action_id_cannot_bypass_unknown_resume_and_release_requires_reconciliation(self):
        self.store()
        def lost(method, parameters, *, request_id):
            self.native.rpc(method, parameters, request_id=request_id)
            raise TimeoutError("fixture lost ACK")
        self.adapter.rpc = lost
        self.assertEqual(self.deliver()["state"], "unknown")
        self.store("resume-replacement")
        self.adapter.rpc = self.native.rpc
        self.assertEqual(self.deliver("resume-replacement")["state"], "held")
        self.assertEqual(self.native.count(), 1)
        current = self.ledger.load("resume-1")
        # Invented trusted reconciliation evidence, not production provenance.
        proof = evidence_for(current["record"], "resume-attempt", current["plan"], outcome="accepted",
                             provider_reference="native-thread-1", payload={"fixture_verified_prior_effect": True})
        self.ledger.reconcile(proof)
        self.assertEqual(self.deliver("resume-replacement")["state"], "confirmed")
        self.assertEqual(self.native.count(), 2)

    def test_missing_resume_capability_and_claude_are_not_codex_resume_targets(self):
        self.registry.enroll(CONTROLLER, enrollment("builder.other", provider="claude", native_id="native-claude-1"))
        self.ledger.store(resume_action(self.registry._row("builder.other"), "claude-resume", settings_digest=SETTINGS_DIGEST), CONTEXT)
        self.assertEqual(self.deliver("claude-resume")["state"], "held")
        native = enrollment("reviewer.task", native_id="native-reviewer-1")
        native["capabilities"] = ["read"]
        self.registry.enroll(CONTROLLER, native)
        self.ledger.store(resume_action(self.registry._row("reviewer.task"), "read-only-resume", settings_digest=SETTINGS_DIGEST), CONTEXT)
        self.assertEqual(self.deliver("read-only-resume")["state"], "held")
        self.assertEqual(self.native.count(), 0)

    def test_control_invalidation_rejects_a_late_previous_probe(self):
        first = self.registry.cached("builder.task")
        def interleaved(value):
            record = self.registry.cached("builder.task")
            self.registry.prepare_resume(CONTROLLER, "builder.task", expected_revision=record.revision)
            return value
        self.change_observation = interleaved
        with self.assertRaises(Denied):
            self.registry.refresh(CONTROLLER, first.id, expected_revision=first.revision)
        self.assertFalse(self.registry.cached(first.id).fields["ready"])
        self.assertIsNone(self.registry._row(first.id)["probe_id"])

    def test_actual_process_deaths_retain_attempt_and_never_repeat_resume_rpc(self):
        points = ("after_claim_commit", "after_native_resume_control_commit", "after_resume_control_commit", "after_submit_commit",
                  "after_resume_rpc", "after_resume_settings_verified", "after_resume_fresh_observation", "before_receipt_commit", "after_receipt_commit")
        for point in points:
            folder = self.folder / point
            with native_fixture(folder) as (registry, authority):
                registry.enroll(CONTROLLER, enrollment())
                ledger = open_outbox(folder / "ledger", policy_digest=authority.policy.digest)
                ledger.store(resume_action(registry._row("builder.task"), "resume-1", settings_digest=SETTINGS_DIGEST), CONTEXT)
                ledger.close()
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_resume_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, point + ": " + result.stderr.decode())
            with native_fixture(folder) as (registry, authority):
                ledger = open_outbox(folder / "ledger", policy_digest=authority.policy.digest)
                provider = FakeResume(folder / "provider.sqlite")
                try:
                    before = provider.count()
                    adapter = CodexExactResume(provider.rpc, authorize=lambda *_: "fixture-admission", resume_supported=True)
                    recovered = adapter.deliver(ledger, "resume-1", "resume-attempt", registry, CONTROLLER)
                    self.assertEqual(recovered["state"], "confirmed" if point == "after_receipt_commit" else "unknown")
                    self.assertEqual(provider.count(), before)
                    self.assertLessEqual(before, 1)
                    self.assertFalse(registry.cached("builder.task").fields["ready"])
                    self.assertEqual(registry.cached("builder.task").fields["provider_session_id"], "native-thread-1")
                finally:
                    provider.close()
                    ledger.close()


if __name__ == "__main__":
    unittest.main()
