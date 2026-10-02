"""Joined diagnostic scheduling with synthetic source/provider/material facts."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from capacity_journal_fixtures import initial, journal
from model_admission_fixtures import plan, request, scheduler
from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from task_diagnosis_fixtures import diagnoses, diagnostic_plan, stalled_root
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import fingerprint
from relay_core.identity import Denied, Peer
from relay_core.model_admission import QuotaWindow
from relay_core.runtime_delivery import evidence_for


def metadata(session="builder.task", *, estimate=1):
    raw = request(session=session, origin="support", estimate=estimate)
    del raw["id"]
    return raw


class DiagnosticAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = work_fixture(self.folder)
        self.f = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.f.ledger.enroll_root(CONTROLLER, root_record(self.f.authority.policy.digest))
        self.admission = scheduler(self.f)
        self.admission.initialize(CONTROLLER)
        self.guard = diagnoses(self.f, model_admission=self.admission)

    def prepare(self, *, session="builder.task", estimate=1):
        stalled_root(self.f)
        root = self.f.ledger.root("root-builder")
        prepared = self.guard.prepare(CONTROLLER, root.id, session, expected_revision=root.revision, model_request=metadata(session, estimate=estimate))
        return self.f.ledger.load(prepared["diagnosis_id"])["record"]

    def claim(self, action, attempt="diagnostic-attempt"):
        return self.guard.claim_attempt(CONTROLLER, action.id, attempt, plan(self.f.ledger, action), expected_revision=0)

    def test_original_diagnosis_intent_charges_both_counters_and_shared_slot_once(self):
        action = self.prepare()
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)
        self.assertTrue(self.claim(action)["may_execute"])
        self.assertFalse(self.claim(action)["may_execute"])
        root = self.f.ledger.root("root-builder")
        self.assertEqual((root.fields["state"], root.fields["usage"]["turns"], root.fields["usage"]["diagnoses"]), ("held", 1, 1))
        rows = self.admission._attempts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["intent_id"], action.id)
        self.assertTrue(rows[0]["leased"])
        actions = [self.f.ledger.load(intent_id)["record"] for (intent_id,) in self.f.ledger.connection.execute("SELECT id FROM intents WHERE kind='external_action'")]
        self.assertFalse(any(row.fields["action_kind"] == "model_turn" for row in actions))
        with self.assertRaises(Denied):
            self.claim(action, "another-attempt")

    def test_standalone_receipt_cannot_bypass_an_installed_shared_scheduler(self):
        action = self.prepare()
        legacy = diagnoses(self.f)
        old_plan = diagnostic_plan(legacy, action)
        legacy.admit_attempt = lambda *_: self.fail("standalone callback must not authorize execution")
        with self.assertRaises(Denied):
            legacy.claim_attempt(CONTROLLER, action.id, "bypass-attempt", old_plan, expected_revision=0)
        self.assertFalse(self.admission._attempts())

    def test_shared_admission_cannot_use_a_different_root_ledger(self):
        with work_fixture(self.folder / "foreign") as other:
            foreign = scheduler(other)
            with self.assertRaises(Denied):
                diagnoses(self.f, model_admission=foreign)

    def test_changed_material_still_cannot_exceed_the_root_diagnostic_allowance(self):
        first = self.prepare()
        self.assertTrue(self.claim(first)["may_execute"])
        material = self.guard.inspect_material
        self.guard.inspect_material = lambda snapshot: replace(material(snapshot), blocker_digest=fingerprint({"synthetic_blocker": "second"}))
        second = self.prepare(session="builder.other")
        wait = self.claim(second, "second-diagnostic-attempt")
        self.assertEqual(wait["reason"], "account_pacing_wait")
        self.f.clock[0] = wait["next_eligible_ms"]
        self.assertTrue(self.claim(second, "second-diagnostic-attempt")["may_execute"])
        self.guard.inspect_material = lambda snapshot: replace(material(snapshot), blocker_digest=fingerprint({"synthetic_blocker": "third"}))
        root = self.f.ledger.root("root-builder")
        result = self.guard.prepare(CONTROLLER, root.id, "builder.task", expected_revision=root.revision, model_request=metadata())
        self.assertEqual(result["state"], "diagnostic_budget_exhausted")
        self.assertFalse(result["prepared_now"])
        self.assertEqual((root.fields["usage"]["turns"], root.fields["usage"]["diagnoses"]), (2, 2))

    def test_unpinned_legacy_proposal_and_normal_entry_point_cannot_execute_diagnosis(self):
        action = self.prepare()
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "wrong-entry", plan(self.f.ledger, action), expected_revision=0)
        with work_fixture(self.folder / "legacy") as f:
            f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
            admission = scheduler(f)
            admission.initialize(CONTROLLER)
            guard = diagnoses(f, model_admission=admission)
            stalled_root(f)
            result = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision)
            old = f.ledger.load(result["diagnosis_id"])["record"]
            with self.assertRaises(Denied):
                guard.claim_attempt(CONTROLLER, old.id, "old-attempt", diagnostic_plan(guard, old), expected_revision=0)

    def test_three_active_sessions_block_a_diagnosis_without_spending_its_reservation(self):
        action = self.prepare()
        inspect = self.admission.observe_activity
        self.admission.observe_activity = lambda scope: replace(inspect(scope), active_sessions=("app-1", "app-2", "app-3"))
        self.assertEqual(self.claim(action)["reason"], "global_activity_cap")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
        self.assertFalse(self.admission._attempts())
        self.admission.observe_activity = inspect
        self.assertTrue(self.claim(action)["may_execute"])

    def test_original_session_lease_requires_verified_stop_before_diagnosis_can_start(self):
        ordinary = self.admission.enqueue(CONTROLLER, request(estimate=1))["record"]
        self.admission.claim(CONTROLLER, ordinary.id, "ordinary-attempt", plan(self.f.ledger, ordinary), expected_revision=0)
        action = self.prepare()
        self.assertEqual(self.claim(action)["reason"], "session_busy")
        inspect = self.admission.verify_stop
        self.admission.verify_stop = lambda row: replace(inspect(row), all_tools_quiesced=False)
        with self.assertRaises(Denied):
            self.admission.release(CONTROLLER, "ordinary-attempt")
        self.admission.verify_stop = inspect
        self.admission.release(CONTROLLER, "ordinary-attempt")
        wait = self.claim(action)
        self.assertEqual(wait["reason"], "account_pacing_wait")
        self.f.clock[0] = wait["next_eligible_ms"]
        self.assertTrue(self.claim(action)["may_execute"])

    def test_missing_quota_wait_does_not_consume_budget_or_clear_the_watchdog(self):
        action = self.prepare()
        self.admission.observe_quota = lambda _: None
        self.assertEqual(self.claim(action)["reason"], "quota_telemetry_unavailable")
        root = self.f.ledger.root("root-builder")
        self.assertEqual((root.fields["usage"]["turns"], root.fields["usage"]["diagnoses"], root.fields["usage"]["no_progress_handoffs"]), (0, 0, 3))
        self.assertEqual(self.f.ledger.load(action.id)["record"].fields["state"], "stored")

    def test_diagnosis_preserves_owner_reserve_unless_exact_action_has_a_verified_grant(self):
        action = self.prepare(estimate=6)
        quota = self.admission.observe_quota
        self.admission.observe_quota = lambda scope: replace(quota(scope), windows=(QuotaWindow("window-1", "account", 100, 85, NOW + 100000, ()),))
        self.assertEqual(self.claim(action)["reason"], "owner_reserve_or_quota_wait")
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        with self.assertRaises(Denied):
            self.claim(action)
        self.admission.verify_source = lambda scope: replace(source(scope), owner_reserve_granted=True)
        self.assertTrue(self.claim(action)["may_execute"])

    def test_other_sessions_and_diagnoses_share_one_account_pacing_history(self):
        ordinary = self.admission.enqueue(CONTROLLER, request(session="builder.other", estimate=1))["record"]
        self.admission.claim(CONTROLLER, ordinary.id, "ordinary-attempt", plan(self.f.ledger, ordinary), expected_revision=0)
        action = self.prepare()
        wait = self.claim(action)
        self.assertEqual(wait["reason"], "account_pacing_wait")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)
        self.f.clock[0] = wait["next_eligible_ms"]
        self.assertTrue(self.claim(action)["may_execute"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 2)

    def test_capacity_cooldown_blocks_diagnosis_on_the_same_model_account(self):
        admission, original = initial(self.f)
        retry = journal(self.f, admission)
        retry.initialize(CONTROLLER)
        job = retry.enroll(CONTROLLER, original.id)
        retry.record_failure(CONTROLLER, job["id"], original.id, jitter_ms=0)
        self.admission = admission
        self.guard = diagnoses(self.f, model_admission=admission)
        action = self.prepare(session="builder.other")
        self.assertEqual(self.claim(action)["reason"], "shared_capacity_wait")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)

    def test_changed_model_metadata_plan_and_worker_controller_are_refused(self):
        action = self.prepare()
        changed = metadata()
        changed["model_id"] = "different/model"
        with self.assertRaises(Denied):
            self.guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=self.f.ledger.root("root-builder").revision, model_request=changed)
        wrong = plan(self.f.ledger, action)
        wrong["target"]["model_id"] = "different/model"
        with self.assertRaises(Denied):
            self.guard.claim_attempt(CONTROLLER, action.id, "wrong-attempt", wrong, expected_revision=0)
        with self.assertRaises(Denied):
            self.guard.claim_attempt(Peer(11, 101, 121), action.id, "worker-attempt", plan(self.f.ledger, action), expected_revision=0)

    def test_material_changes_during_quota_probe_invalidate_the_original_proposal(self):
        action = self.prepare()
        quota = self.admission.observe_quota
        material = self.guard.inspect_material
        def change_during_probe(scope):
            self.guard.inspect_material = lambda snapshot: replace(material(snapshot), blocker_digest=fingerprint({"synthetic_new_blocker": True}))
            return quota(scope)
        self.admission.observe_quota = change_during_probe
        with self.assertRaises(Denied):
            self.claim(action)
        self.assertFalse(self.admission._attempts())
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["diagnoses"], 0)

    def test_owner_pause_during_quota_probe_revokes_diagnostic_execution(self):
        action = self.prepare()
        quota = self.admission.observe_quota
        def pause_during_probe(scope):
            root = self.f.ledger.root("root-builder")
            self.f.ledger.control_root(CONTROLLER, root.id, "held", expected_revision=root.revision)
            return quota(scope)
        self.admission.observe_quota = pause_during_probe
        with self.assertRaises(Denied):
            self.claim(action)
        self.assertFalse(self.admission._attempts())

    def test_confirmed_diagnostic_input_is_not_task_recovery_or_activity_release(self):
        action = self.prepare()
        frozen_plan = plan(self.f.ledger, action)
        self.assertTrue(self.claim(action)["may_execute"])
        self.f.ledger.submitted(action.id, "diagnostic-attempt")
        self.f.ledger.reconcile(evidence_for(action, "diagnostic-attempt", frozen_plan, outcome="accepted", provider_reference="synthetic-input-acceptance", payload={"synthetic_not_native": True}))
        self.guard.validate_result(CONTROLLER, action.id)
        root = self.f.ledger.root("root-builder")
        self.assertEqual((root.fields["state"], root.fields["usage"]["no_progress_handoffs"]), ("held", 3))
        self.assertTrue(self.admission._attempts()[0]["leased"])

    def test_actual_joined_commit_deaths_preserve_counter_slot_and_outbox_cohort(self):
        for point in ("before_model_admission_commit", "after_model_admission_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                guard = diagnoses(f, model_admission=admission)
                stalled_root(f)
                result = guard.prepare(CONTROLLER, "root-builder", "builder.task", expected_revision=f.ledger.root("root-builder").revision, model_request=metadata())
            death = subprocess.run([sys.executable, str(Path(__file__).with_name("diagnostic_admission_fault_fixture.py")), str(folder), point, result["diagnosis_id"]], capture_output=True, timeout=10)
            self.assertEqual(death.returncode, 73, death.stderr.decode())
            with work_fixture(folder) as f:
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                guard = diagnoses(f, model_admission=admission)
                committed = point.startswith("after")
                root = f.ledger.root("root-builder")
                self.assertEqual((root.fields["usage"]["turns"], root.fields["usage"]["diagnoses"]), (int(committed), int(committed)))
                self.assertEqual(len(admission._attempts()), int(committed))
                if committed:
                    self.assertEqual(admission._attempts()[0]["state"], "held")
                action = f.ledger.load(result["diagnosis_id"])["record"]
                claimed = guard.claim_attempt(CONTROLLER, action.id, "diagnostic-attempt", plan(f.ledger, action), expected_revision=0)
                self.assertEqual(claimed["may_execute"], not committed)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["diagnoses"], 1)
