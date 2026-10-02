"""Real joined diagnostic budgeting/outbox; explicitly synthetic material facts."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from task_diagnosis_fixtures import diagnoses, diagnostic_plan, stalled_root
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied, Peer
from relay_core.runtime_delivery import evidence_for


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = work_fixture(self.folder)
        self.f = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.f.ledger.enroll_root(CONTROLLER, root_record(self.f.authority.policy.digest))
        stalled_root(self.f)
        self.guard = diagnoses(self.f)

    def prepare(self):
        return self.guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=self.f.ledger.root("root-builder").revision)

    def test_held_root_reserves_one_bounded_diagnosis_and_one_passive_report(self):
        result = self.prepare()
        self.assertTrue(result["prepared_now"])
        root = self.f.ledger.root("root-builder")
        self.assertEqual(root.fields["state"], "held")
        self.assertEqual(root.fields["usage"]["turns"], 0)
        self.assertEqual(root.fields["usage"]["diagnoses"], 0)
        self.assertEqual(root.fields["usage"]["no_progress_handoffs"], 3)
        self.assertFalse(self.prepare()["prepared_now"])
        self.assertEqual(self.f.ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 2)
        self.guard.validate_action(CONTROLLER, result["diagnosis_id"])
        report = self.f.ledger.load(result["notice_id"])
        self.assertEqual(report["record"].fields["action_kind"], "passive_task_report")
        self.assertEqual(report["context"]["meaning"], "pending_protected_owner_report_not_sent")

    def test_owner_pause_already_held_is_persisted_and_blocks_diagnosis(self):
        result = self.prepare()
        root = self.f.ledger.root("root-builder")
        paused = self.f.ledger.control_root(CONTROLLER, root.id, "held", expected_revision=root.revision)
        self.assertGreater(paused.revision, root.revision)
        self.assertEqual(self.f.ledger.owner_control(root.id)["desired_state"], "paused")
        with self.assertRaises(Denied):
            self.prepare()
        with self.assertRaises(Denied):
            self.guard.validate_action(CONTROLLER, result["diagnosis_id"])
        self.f.ledger.set_owner_control(CONTROLLER, root.id, "running", expected_revision=paused.revision)
        with self.assertRaises(Denied):
            self.guard.validate_action(CONTROLLER, result["diagnosis_id"])
        self.assertEqual(self.f.ledger.root(root.id).fields["state"], "held")

    def test_observation_ids_and_bookkeeping_do_not_schedule_another_diagnosis(self):
        original = self.prepare()
        inspect = self.guard.inspect_material
        self.guard.inspect_material = lambda scope: replace(inspect(scope), observation_id="new-poll-id")
        self.assertEqual(self.prepare()["diagnosis_id"], original["diagnosis_id"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)

    def test_new_verified_evidence_invalidates_old_proposal_without_resetting_budget(self):
        original = self.prepare()
        root = self.f.ledger.root("root-builder")
        current = self.f.ledger.progress(CONTROLLER, root.id, "new-relevant-gate", expected_revision=root.revision)
        with self.assertRaises(Denied):
            self.guard.validate_action(CONTROLLER, original["diagnosis_id"])
        self.assertEqual(current.fields["usage"]["diagnoses"], 0)

    def test_verified_wait_and_unverified_or_forged_material_never_wake_model(self):
        inspect = self.guard.inspect_material
        self.guard.inspect_material = lambda scope: replace(inspect(scope), trigger="verified_wait")
        self.assertEqual(self.prepare()["state"], "verified_wait")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
        self.assertEqual(self.f.ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 0)
        self.guard.inspect_material = lambda scope: replace(inspect(scope), eligible=False)
        with self.assertRaises(Denied):
            self.prepare()
        self.guard.inspect_material = lambda scope: {"eligible": True}
        with self.assertRaises(Denied):
            self.prepare()

    def test_material_owner_or_execution_changes_during_inspection_refuse_reservation(self):
        inspect = self.guard.inspect_material
        def pause(scope):
            root = self.f.ledger.root("root-builder")
            self.f.ledger.control_root(CONTROLLER, root.id, "held", expected_revision=root.revision)
            return inspect(scope)
        self.guard.inspect_material = pause
        with self.assertRaises(Denied):
            self.prepare()
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)

    def test_deadline_expiry_keeps_work_reports_once_and_never_extends_budget(self):
        original = self.prepare()
        self.f.clock[0] = NOW + 7 * 86400000
        result = self.prepare()
        self.assertEqual(result["state"], "deadline_exhausted")
        self.assertEqual(self.prepare()["notice_id"], result["notice_id"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
        with self.assertRaises(Denied):
            self.guard.validate_action(CONTROLLER, original["diagnosis_id"])

    def test_ordinary_work_cannot_consume_the_diagnostic_subset(self):
        with work_fixture(self.folder / "reserve") as f:
            f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
            for index in range(3):
                f.ledger.charge(Peer(11, 101, 121), "ordinary-" + str(index), "turn", expected_revision=f.ledger.root("root-builder").revision)
            with self.assertRaises(Denied):
                f.ledger.charge(Peer(11, 101, 121), "over-reserve", "turn", expected_revision=f.ledger.root("root-builder").revision)
            guard = diagnoses(f)
            inspect = guard.inspect_material
            guard.inspect_material = lambda scope: replace(inspect(scope), trigger="budget_exhausted")
            self.assertTrue(guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)["prepared_now"])
            self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 3)

    def test_unknown_submission_cannot_replay_or_apply_unconfirmed_results(self):
        result = self.prepare()
        ledger = self.f.ledger
        current = ledger.load(result["diagnosis_id"])
        action = current["record"]
        plan = diagnostic_plan(self.guard, action)
        self.assertTrue(self.guard.claim_attempt(CONTROLLER, action.id, "diagnostic-attempt", plan, expected_revision=0)["may_execute"])
        self.assertFalse(self.guard.claim_attempt(CONTROLLER, action.id, "diagnostic-attempt", plan, expected_revision=0)["may_execute"])
        self.assertEqual(ledger.root("root-builder").fields["usage"]["diagnoses"], 1)
        ledger.submitted(action.id, "diagnostic-attempt")
        ledger.unknown(action.id, "diagnostic-attempt")
        self.assertEqual(self.prepare()["state"], "unknown")
        with self.assertRaises(Denied):
            self.guard.validate_action(CONTROLLER, action.id)
        with self.assertRaises(Denied):
            self.guard.validate_result(CONTROLLER, action.id)
        ledger.reconcile(evidence_for(action, "diagnostic-attempt", plan, outcome="accepted", provider_reference="synthetic-result", payload={"scope_only_not_real_provider": True}))
        self.guard.validate_result(CONTROLLER, action.id)
        inspect = self.guard.inspect_material
        self.guard.inspect_material = lambda scope: replace(inspect(scope), blocker_digest="sha256:" + "d" * 64)
        with self.assertRaises(Denied):
            self.guard.validate_result(CONTROLLER, action.id)

    def test_legacy_control_intent_is_unknown_until_explicit_reenrollment_of_owner_intent(self):
        ledger = self.f.ledger
        row = ledger.connection.execute("SELECT body FROM work_history WHERE kind='root' AND id='root-builder' AND revision=0").fetchone()
        import json
        event = json.loads(row[0])
        event["proof"] = {"watchdog_handoffs": 3}
        ledger.connection.execute("UPDATE work_history SET body=?,digest=? WHERE kind='root' AND id='root-builder' AND revision=0", (canonical_bytes(event), fingerprint(event)))
        self.assertFalse(ledger.owner_control("root-builder")["known"])
        with self.assertRaises(Denied):
            self.prepare()
        root = ledger.root("root-builder")
        ledger.set_owner_control(CONTROLLER, root.id, "running", expected_revision=root.revision)
        self.assertTrue(self.prepare()["prepared_now"])

    def test_real_new_blocker_can_allocate_once_more_but_cannot_exhaust_the_root_twice(self):
        self.prepare()
        inspect = self.guard.inspect_material
        self.guard.inspect_material = lambda scope: replace(inspect(scope), blocker_digest="sha256:" + "d" * 64)
        self.assertTrue(self.prepare()["prepared_now"])
        self.guard.inspect_material = lambda scope: replace(inspect(scope), blocker_digest="sha256:" + "e" * 64)
        exhausted = self.prepare()
        self.assertEqual(exhausted["state"], "diagnostic_capacity_reserved")
        self.assertEqual(self.prepare()["notice_id"], exhausted["notice_id"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)

    def test_missing_target_is_reported_passively_without_granting_its_identity_or_model_work(self):
        self.f.authority.registry.revoke("builder.task")
        result = self.prepare()
        self.assertEqual(result["state"], "target_unavailable")
        self.assertEqual(self.prepare()["notice_id"], result["notice_id"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
        self.assertEqual(self.f.ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 1)

    def test_expired_verified_wait_reports_the_deadline_without_model_wake(self):
        inspect = self.guard.inspect_material
        self.guard.inspect_material = lambda scope: replace(inspect(scope), trigger="verified_wait", eligible=False)
        self.f.clock[0] = NOW + 7 * 86400000
        result = self.prepare()
        self.assertEqual(result["state"], "deadline_exhausted")
        self.assertFalse(result["prepared_now"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)

    def test_recovery_writer_holds_do_not_mint_another_diagnosis(self):
        with work_fixture(self.folder / "writer-recovery") as f:
            f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
            f.ledger.enroll_work(CONTROLLER, work_id="work-1", root_id="root-builder", criteria=["Gate"], dependencies=[],
                                assignee_role_id="builder", resource_id="fixture-resource")
            f.ledger.checkout(Peer(11, 101, 121), "work-1", "claim-1", expected_revision=0)
            stalled_root(f)
            guard = diagnoses(f)
            before = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
            f.ledger.recover_inflight()
            after = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
            self.assertEqual(after["diagnosis_id"], before["diagnosis_id"])
            self.assertFalse(after["prepared_now"])
            self.assertEqual(f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)

    def test_actual_process_deaths_keep_reservation_proposal_and_report_atomic(self):
        for point in ("before_diagnostic_prepare_commit", "after_diagnostic_prepare_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                stalled_root(f)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("task_diagnosis_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with work_fixture(folder) as f:
                guard = diagnoses(f)
                prepared = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
                self.assertEqual(prepared["prepared_now"], point == "before_diagnostic_prepare_commit")
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
                self.assertEqual(f.ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 2)

    def test_actual_claim_deaths_keep_execution_charge_attempt_and_report_atomic(self):
        for point in ("before_claim_commit", "after_claim_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                stalled_root(f)
                diagnoses(f).prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("task_diagnosis_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with work_fixture(folder) as f:
                committed = point == "after_claim_commit"
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["diagnoses"], int(committed))
                f.ledger.recover_inflight()
                guard = diagnoses(f)
                prepared = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
                self.assertFalse(prepared["prepared_now"])
                action = f.ledger.load(prepared["diagnosis_id"])["record"]
                self.assertEqual(action.fields["state"], "unknown" if committed else "stored")
                plan = diagnostic_plan(guard, action)
                claimed = guard.claim_attempt(CONTROLLER, action.id, "diagnostic-attempt", plan, expected_revision=0)
                self.assertEqual(claimed["may_execute"], not committed)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["diagnoses"], 1)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 1)
                self.assertEqual(f.ledger.connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0], 3)

    def test_quota_or_pacing_wait_does_not_charge_execution_and_scope_is_rechecked_after_admission(self):
        prepared = self.prepare()
        action = self.f.ledger.load(prepared["diagnosis_id"])["record"]
        plan = diagnostic_plan(self.guard, action)
        def wait(*_):
            raise Denied("synthetic pacing wait")
        self.guard.admit_attempt = wait
        with self.assertRaises(Denied):
            self.guard.claim_attempt(CONTROLLER, action.id, "attempt-1", plan, expected_revision=0)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)
        self.assertEqual(self.f.ledger.load(action.id)["record"].fields["state"], "stored")
        diagnostic_plan(self.guard, action)
        admit = self.guard.admit_attempt
        def pause(*args):
            root = self.f.ledger.root("root-builder")
            self.f.ledger.control_root(CONTROLLER, root.id, "held", expected_revision=root.revision)
            return admit(*args)
        self.guard.admit_attempt = pause
        with self.assertRaises(Denied):
            self.guard.claim_attempt(CONTROLLER, action.id, "attempt-1", plan, expected_revision=0)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)
        self.assertEqual(self.f.ledger.load(action.id)["record"].fields["state"], "stored")
