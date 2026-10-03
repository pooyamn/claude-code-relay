"""Real custody/SQLite/crash tests; native, source, fences and grants synthetic."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from model_admission_fixtures import plan, request
from native_session_fixtures import CONTROLLER
from native_workspace_fixtures import fixture_fields, git, open_workspace
from owner_fixtures import writable_fixture_tree
from tool_switch_fixtures import BUILDER, OTHER, context, snapshot, switch_fixture
from relay_core.contracts import create, fingerprint, intent_payload
from relay_core.identity import Denied
from relay_core.tool_switches import SwitchCheckpoint, ToolSwitches
from relay_core.worktree_checkpoints import CheckpointPolicy, WorktreeCheckpoints


class ToolSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = switch_fixture(self.folder)
        self.s = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.engine, self.ledger = self.s.engine, self.s.ledger
        self.original = self.ledger.work("work-1")
        self.root = self.ledger.root("root-builder")

    def start(self):
        return self.engine.request(CONTROLLER, "switch-1", "work-1", "builder.other", expected_revision=self.original["revision"])

    def attach(self):
        return self.engine.attach(CONTROLLER, "switch-1", snapshot=snapshot(), context=context())

    def ready(self):
        self.start()
        self.attach()

    def unchanged_custody(self):
        work = self.ledger.work("work-1")
        self.assertEqual(work["binding"], self.original["binding"])
        self.assertEqual(work["fencing_token"], self.original["fencing_token"])
        self.assertEqual(self.ledger.root("root-builder").fields["state"], "held")

    def action(self, key="pending-action"):
        fields = {"id": key, "root_task_id": "root-builder", "requested_by_session_id": "builder.task",
                  "action_kind": "request_action", "parameters": {"operation": "synthetic_only_never_delivered"}}
        record = create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                        attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
        self.ledger.store(record, {"binding": self.original["binding"], "purpose": "synthetic-action"})
        return record

    def unknown_action(self):
        action = self.action()
        delivery = {"schema": "ccrelay.delivery_plan.v1", "intent_id": action.id, "intent_digest": action.fields["intent_digest"],
                    "adapter_id": "synthetic-no-effects", "authorization_id": "synthetic-action-grant",
                    "parameters": action.to_dict()["parameters"], "target": {"session_id": "builder.task"}}
        self.ledger.claim(action.id, "original-action-attempt", delivery, expected_revision=0)
        self.ledger.submitted(action.id, "original-action-attempt")
        self.ledger.unknown(action.id, "original-action-attempt")
        return action, delivery

    def test_request_retains_writer_and_original_task_limits_usage_and_deadline(self):
        self.assertTrue(self.start()["requested_now"])
        self.unchanged_custody()
        body = self.engine.load("switch-1")
        self.assertEqual(body["phase"], "checkpoint_pending")
        self.assertEqual(body["source_native"]["provider_session_id"], "claude-original")
        self.assertEqual(body["destination_native"]["provider_session_id"], "codex-destination")
        root = self.ledger.root("root-builder")
        self.assertEqual(root.fields["usage"], self.root.fields["usage"])
        self.assertEqual(root.fields["limits"], self.root.fields["limits"])
        self.assertFalse(self.s.admission._attempts())

    def test_exact_duplicate_coalesces_and_same_id_cannot_retarget(self):
        self.start()
        self.assertFalse(self.start()["requested_now"])
        with self.assertRaises(Denied):
            self.engine.request(CONTROLLER, "switch-1", "work-1", "builder.task", expected_revision=0)
        self.assertEqual(self.engine.load("switch-1")["revision"], 0)

    def test_pending_switch_cannot_be_released_or_taken_by_another_worker(self):
        self.start()
        work = self.ledger.work("work-1")
        with self.assertRaises(Denied):
            self.ledger.release(CONTROLLER, work["id"], expected_revision=work["revision"])
        with self.assertRaises(Denied):
            self.ledger.checkout(OTHER, work["id"], "other-claim", expected_revision=work["revision"])
        with self.assertRaises(Denied):
            self.ledger.validate_fence(BUILDER, work["id"], work["fencing_token"])
        self.unchanged_custody()

    def test_worker_cannot_request_attach_transfer_cancel_or_report_as_controller(self):
        with self.assertRaises(Denied):
            self.engine.request(BUILDER, "switch-1", "work-1", "builder.other", expected_revision=0)
        self.ready()
        for operation in (lambda: self.engine.attach(BUILDER, "switch-1", snapshot=snapshot(), context=context()),
                          lambda: self.engine.finish(BUILDER, "switch-1"), lambda: self.engine.cancel(BUILDER, "switch-1"),
                          lambda: self.engine.report_failure(BUILDER, "switch-1", "destination_unverified")):
            with self.assertRaises(Denied):
                operation()

    def test_incomplete_checkpoint_preserves_source_and_cannot_transfer(self):
        self.start()
        verify = self.engine.verify_checkpoint
        self.engine.verify_checkpoint = lambda scope: replace(verify(scope), complete=False)
        with self.assertRaises(Denied):
            self.attach()
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.assertIsNone(self.engine.load("switch-1")["capsule"])
        self.unchanged_custody()

    def test_missing_semantic_fields_or_changed_worktree_cannot_attach(self):
        self.start()
        partial = context()
        del partial["pending_inputs"]
        for snap, ctx in ((snapshot(), partial), (snapshot("/different/worktree"), context())):
            with self.assertRaises(Denied):
                self.engine.attach(CONTROLLER, "switch-1", snapshot=snap, context=ctx)

    def test_capsule_retains_unfinished_operations_questions_and_no_approval_inheritance(self):
        self.ready()
        capsule = self.engine.load("switch-1")["capsule"]["data"]
        self.assertEqual(capsule["context"], context())
        self.assertEqual(capsule["snapshot"], snapshot())
        self.assertFalse(self.s.admission._attempts())
        self.unchanged_custody()

    def test_changed_pending_action_digest_requires_new_verified_attachment(self):
        self.ready()
        self.action()
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()
        self.attach()
        self.assertTrue(self.engine.finish(CONTROLLER, "switch-1")["transferred_now"])

    def test_uncertain_original_action_and_attempt_are_preserved_without_replay(self):
        action, delivery = self.unknown_action()
        self.ready()
        before = self.ledger.load(action.id)
        self.engine.finish(CONTROLLER, "switch-1")
        self.assertEqual(self.ledger.load(action.id), before)
        self.assertFalse(self.ledger.claim(action.id, "original-action-attempt", delivery, expected_revision=0)["may_execute"])
        self.assertEqual(before["record"].fields["state"], "unknown")

    def test_transfer_advances_fence_atomically_but_does_not_resume_or_reset_task(self):
        self.ready()
        result = self.engine.finish(CONTROLLER, "switch-1")
        self.assertTrue(result["transferred_now"])
        self.assertEqual(result["work"]["binding"]["session_id"], "builder.other")
        self.assertGreater(result["work"]["fencing_token"], self.original["fencing_token"])
        with self.assertRaises(Denied):
            self.ledger.validate_fence(BUILDER, "work-1", self.original["fencing_token"])
        self.ledger.validate_fence(OTHER, "work-1", result["work"]["fencing_token"])
        root = self.ledger.root("root-builder")
        self.assertEqual(root.fields["state"], "held")
        self.assertEqual(root.fields["usage"], self.root.fields["usage"])
        self.assertEqual(root.fields["limits"], self.root.fields["limits"])
        self.assertFalse(self.engine.finish(CONTROLLER, "switch-1")["transferred_now"])
        self.assertFalse(self.s.admission._attempts())

    def test_existing_model_tool_lease_blocks_transfer_until_independent_stop_receipt(self):
        action = self.s.admission.enqueue(CONTROLLER, request())["record"]
        self.assertTrue(self.s.admission.claim(CONTROLLER, action.id, "attempt-1", plan(self.ledger, action), expected_revision=0)["may_execute"])
        self.ready()
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()
        self.assertTrue(self.s.admission._attempts()[0]["leased"])
        self.s.admission.release(CONTROLLER, "attempt-1")
        self.engine.finish(CONTROLLER, "switch-1")
        self.assertEqual(self.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_synthetic_claude_codex_claude_custody_keeps_same_task_context_and_budget(self):
        self.ready()
        forward = self.engine.finish(CONTROLLER, "switch-1")["work"]
        root = self.ledger.root("root-builder")
        # Explicit protected revalidation, not automatic execution on transfer.
        self.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
        self.engine.request(CONTROLLER, "switch-2", "work-1", "builder.task", expected_revision=forward["revision"])
        self.engine.attach(CONTROLLER, "switch-2", snapshot=snapshot(), context=context())
        backward = self.engine.finish(CONTROLLER, "switch-2")["work"]
        self.assertEqual(backward["binding"], self.original["binding"])
        self.assertGreater(backward["fencing_token"], forward["fencing_token"])
        self.assertEqual(self.engine.load("switch-2")["capsule"]["data"]["context"], context())
        self.assertEqual(self.ledger.root(root.id).fields["limits"], self.root.fields["limits"])
        self.assertEqual(self.ledger.root(root.id).fields["usage"], self.root.fields["usage"])
        self.assertFalse(self.s.admission._attempts())

    def test_old_reader_proof_cannot_hide_changed_checkpoint_bytes_or_contracts(self):
        self.ready()
        verify = self.engine.verify_checkpoint
        self.engine.verify_checkpoint = lambda scope: replace(verify(scope), source_digest=fingerprint({"changed_bytes": True}))
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()

    def test_destination_wrong_native_active_turn_or_missing_read_only_fence_denied(self):
        self.ready()
        verify = self.engine.verify_loaded
        for change in ({"native_session_id": "fresh-native-thread"}, {"active_turn_id": "still-running"}, {"read_only_fenced": False},
                       {"capsule_digest": fingerprint({"different_context": True})},
                       {"runtime_digest": fingerprint({"different_runtime": True})},
                       {"tool_contract_digest": fingerprint({"different_contract": True})},
                       {"permission_digest": fingerprint({"different_permissions": True})}):
            self.engine.verify_loaded = lambda scope, change=change: replace(verify(scope), **change)
            with self.assertRaises(Denied):
                self.engine.finish(CONTROLLER, "switch-1")
            self.unchanged_custody()

    def test_writer_guard_must_keep_both_old_descendants_and_destination_fenced(self):
        self.ready()
        guard = self.engine.writer_guard
        for change in ({"all_old_writers_stopped": False}, {"destination_read_only": False}):
            @contextmanager
            def changed(scope, change=change):
                with guard(scope) as receipt:
                    yield replace(receipt, **change)
            self.engine.writer_guard = changed
            with self.assertRaises(Denied):
                self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()

    def test_revoked_binding_during_destination_loading_denies_transfer(self):
        self.ready()
        verify = self.engine.verify_loaded
        def revoke(scope):
            self.s.f.authority.registry.revoke("builder.other")
            return verify(scope)
        self.engine.verify_loaded = revoke
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()

    def test_owner_pause_during_destination_loading_cannot_transfer(self):
        self.ready()
        verify = self.engine.verify_loaded
        def pause(scope):
            root = self.ledger.root("root-builder")
            self.ledger.set_owner_control(CONTROLLER, root.id, "paused", expected_revision=root.revision)
            return verify(scope)
        self.engine.verify_loaded = pause
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()

    def test_authority_revocation_during_checkpoint_verification_cannot_attach(self):
        self.start()
        verify = self.engine.verify_checkpoint
        def revoke(scope):
            self.engine.authorize = lambda _: None
            return verify(scope)
        self.engine.verify_checkpoint = revoke
        with self.assertRaises(Denied):
            self.attach()
        self.assertEqual(self.engine.load("switch-1")["phase"], "checkpoint_pending")

    def test_loaded_context_change_during_final_checkpoint_read_cannot_transfer(self):
        self.ready()
        verify = self.engine.verify_checkpoint
        calls = []
        def change_loading(scope):
            calls.append(True)
            if len(calls) == 2:
                self.engine.verify_loaded = lambda _: None
            return verify(scope)
        self.engine.verify_checkpoint = change_loading
        with self.assertRaises(Denied):
            result = self.engine.finish(CONTROLLER, "switch-1")
            self.assertFalse(result["transferred_now"], "stale loaded-context proof transferred custody")
        self.unchanged_custody()

    def test_deadline_expiring_during_loaded_verification_preserves_original_task(self):
        self.ready()
        verify = self.engine.verify_loaded
        def expire(scope):
            self.s.f.clock[0] += 7 * 86400000
            return verify(scope)
        self.engine.verify_loaded = expire
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()

    def test_cancellation_retains_source_and_never_resumes_a_native_turn(self):
        self.ready()
        self.engine.cancel(CONTROLLER, "switch-1")
        self.assertEqual(self.engine.cancel(CONTROLLER, "switch-1")["state"], "cancelled")
        with self.assertRaises(Denied):
            self.engine.finish(CONTROLLER, "switch-1")
        self.unchanged_custody()
        self.assertFalse(self.s.admission._attempts())

    def test_unchanged_bug_notice_coalesces_without_model_repair_or_execution_grant(self):
        self.ready()
        first = self.engine.report_failure(CONTROLLER, "switch-1", "destination_unverified")
        self.assertEqual(self.engine.report_failure(CONTROLLER, "switch-1", "destination_unverified"), first)
        self.assertEqual(self.ledger.load(first["intent_id"])["record"].fields["state"], "stored")
        self.assertEqual(self.ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 1)
        self.assertFalse(self.s.admission._attempts())
        self.assertTrue(self.engine.finish(CONTROLLER, "switch-1")["transferred_now"])

    def test_unknown_switch_failure_is_classified_without_type_error(self):
        with self.assertRaises(Denied):
            self.engine.report_failure(CONTROLLER, "missing-switch", "checkpoint_incomplete")

    def test_missing_protected_readers_and_different_native_authority_denied(self):
        for kwargs in ({"authorize": None}, {"verify_checkpoint": None}, {"verify_loaded": None}, {"writer_guard": None}):
            readers = {key: getattr(self.engine, key) for key in ("authorize", "verify_checkpoint", "verify_loaded", "writer_guard")}
            with self.assertRaises(Denied):
                ToolSwitches(self.s.admission, self.s.registry, **{**readers, **kwargs})

    def test_unknown_schema_or_missing_history_refuses_switch_authorization(self):
        self.start()
        self.ledger.connection.execute("DELETE FROM tool_switch_history WHERE id='switch-1'")
        with self.assertRaises(Denied):
            self.engine.load("switch-1")
        self.ledger.connection.execute("UPDATE tool_switch_metadata SET schema='future-switch.v99'")
        with self.assertRaises(Denied):
            self.engine.initialize(CONTROLLER)

    def test_six_actual_process_deaths_recover_original_or_transferred_custody_without_replay(self):
        points = ("before_switch_request_commit", "after_switch_request_commit", "before_switch_checkpoint_commit",
                  "after_switch_checkpoint_commit", "before_switch_transfer_commit", "after_switch_transfer_commit")
        for point in points:
            folder = self.folder / point
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("tool_switch_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with switch_fixture(folder) as s:
                work = s.ledger.work("work-1")
                self.assertEqual(work["state"], "held")
                self.assertEqual(s.ledger.root("root-builder").fields["usage"]["turns"], 0)
                self.assertEqual(s.ledger.root("root-builder").fields["limits"], self.root.fields["limits"])
                self.assertFalse(s.admission._attempts())
                body = s.engine.load("switch-1")
                if point == "before_switch_request_commit":
                    self.assertIsNone(body)
                    self.assertEqual(work["binding"]["session_id"], "builder.task")
                elif point == "after_switch_transfer_commit":
                    self.assertEqual(body["phase"], "completed")
                    self.assertEqual(work["binding"]["session_id"], "builder.other")
                    self.assertFalse(s.engine.finish(CONTROLLER, "switch-1")["transferred_now"])
                else:
                    self.assertEqual(work["binding"]["session_id"], "builder.task")
                    expected = "checkpoint_pending" if point in {"after_switch_request_commit", "before_switch_checkpoint_commit"} else "checkpointed"
                    self.assertEqual(body["phase"], expected)
                    if expected == "checkpoint_pending":
                        s.engine.attach(CONTROLLER, "switch-1", snapshot=snapshot(), context=context())
                    self.assertTrue(s.engine.finish(CONTROLLER, "switch-1")["transferred_now"])

    def test_real_worktree_checkpoint_join_rejects_changed_uncommitted_bytes_then_preserves_repair(self):
        folder = self.folder / "physical-checkpoint"
        policy, spec, home, common, contract = fixture_fields(folder)
        target = home / "worktrees/builder.task"
        with open_workspace(policy, home, contract) as workspace:
            workspace.prepare(spec)
            (target / "src/main.py").write_bytes(b"staged work\n")
            git(["-C", str(target), "add", "src/main.py"])
            (target / "src/main.py").write_bytes(b"unfinished later bytes\n")
            (target / "notes").write_bytes(b"untracked task context\n")
            with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)), \
                    WorktreeCheckpoints(workspace, CheckpointPolicy(128, 8 * 1024 * 1024)) as checkpoints, \
                    switch_fixture(folder / "controller", worktree=str(target)) as s:
                sealed = checkpoints.capture("checkpoint-1", spec)["checkpoint"]
                def actual_bytes(scope):
                    capsule = scope["proposed_capsule"]
                    ref = capsule["snapshot"]
                    current = checkpoints.inspect(ref["checkpoint_id"])
                    complete = fingerprint(current) == ref["checkpoint_digest"] and current["spec_digest"] == ref["spec_digest"] and checkpoints.current(ref["checkpoint_id"])
                    return SwitchCheckpoint(fingerprint(scope), fingerprint({"real_manifest": current, "semantic_fixture": capsule["context"]}),
                                            fingerprint(capsule), complete)
                s.engine.verify_checkpoint = actual_bytes
                s.engine.request(CONTROLLER, "switch-1", "work-1", "builder.other", expected_revision=s.ledger.work("work-1")["revision"])
                ref = {**snapshot(str(target)), "checkpoint_digest": fingerprint(sealed), "spec_digest": sealed["spec_digest"]}
                s.engine.attach(CONTROLLER, "switch-1", snapshot=ref, context=context())
                (target / "notes").write_bytes(b"changed while awaiting cutover\n")
                with self.assertRaises(Denied):
                    s.engine.finish(CONTROLLER, "switch-1")
                self.assertEqual(s.ledger.work("work-1")["binding"]["session_id"], "builder.task")
                repaired = checkpoints.capture("checkpoint-2", spec)["checkpoint"]
                ref = {**ref, "checkpoint_id": "checkpoint-2", "checkpoint_digest": fingerprint(repaired)}
                s.engine.attach(CONTROLLER, "switch-1", snapshot=ref, context=context())
                self.assertTrue(s.engine.finish(CONTROLLER, "switch-1")["transferred_now"])
                self.assertEqual(checkpoints.read_file("checkpoint-1", "worktree", "notes"), b"untracked task context\n")
                self.assertEqual(checkpoints.read_file("checkpoint-2", "worktree", "notes"), b"changed while awaiting cutover\n")
                self.assertEqual(git(["-C", str(target), "show", ":src/main.py"]), b"staged work\n")
                self.assertEqual((target / "src/main.py").read_bytes(), b"unfinished later bytes\n")
