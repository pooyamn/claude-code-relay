"""Offline model admission conformance, not native/provider/OS acceptance."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest

from model_admission_fixtures import plan, request, scheduler
from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import fingerprint
from relay_core.identity import Denied, Peer, Process, expected_cgroup
from relay_core.model_admission import ModelAdmission, PacingPolicy, QuotaWindow


class ModelAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = work_fixture(self.folder)
        self.f = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.f.ledger.enroll_root(CONTROLLER, root_record(self.f.authority.policy.digest))
        self.guard = scheduler(self.f)
        self.guard.initialize(CONTROLLER)

    def enqueue(self, key="turn-1", session="builder.task", **kwargs):
        return self.guard.enqueue(CONTROLLER, request(key, session, **kwargs))["record"]

    def claim(self, action, attempt="attempt-1"):
        return self.guard.claim(CONTROLLER, action.id, attempt, plan(self.f.ledger, action), expected_revision=0)

    def test_joined_admission_charges_once_and_replay_never_grants_execution(self):
        action = self.enqueue()
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)
        self.assertTrue(self.claim(action)["may_execute"])
        self.assertFalse(self.claim(action)["may_execute"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)
        self.assertEqual(len(self.guard._attempts()), 1)
        with self.assertRaises(Denied):
            self.claim(action, "another-attempt")

    def test_worker_cannot_initialize_enroll_or_claim_as_a_controller(self):
        worker = Peer(11, 101, 121)
        action = self.enqueue()
        for operation in (lambda: self.guard.initialize(worker), lambda: self.guard.enqueue(worker, request("worker-turn")),
                          lambda: self.guard.claim(worker, action.id, "worker-attempt", plan(self.f.ledger, action), expected_revision=0)):
            with self.assertRaises(Denied):
                operation()

    def test_fourth_session_is_blocked_by_combined_retained_and_observed_activity(self):
        action = self.enqueue()
        self.assertTrue(self.claim(action)["may_execute"])
        inspect = self.guard.observe_activity
        self.guard.observe_activity = lambda scope: replace(inspect(scope), active_sessions=("external-app", "external-maintenance"))
        pending = self.enqueue("turn-2", "builder.other")
        self.assertEqual(self.claim(pending, "attempt-2")["reason"], "global_activity_cap")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_shared_account_pacing_wait_never_charges_a_turn_or_refreshes_progress(self):
        self.assertTrue(self.claim(self.enqueue())["may_execute"])
        pending = self.enqueue("turn-2", "builder.other")
        wait = self.claim(pending, "attempt-2")
        self.assertEqual(wait["reason"], "account_pacing_wait")
        self.assertGreater(wait["next_eligible_ms"], NOW)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)
        self.assertEqual(self.f.ledger.load(pending.id)["record"].fields["state"], "stored")
        self.f.clock[0] = wait["next_eligible_ms"]
        self.assertTrue(self.claim(pending, "attempt-2")["may_execute"])

    def test_account_pacing_is_independent_between_accounts_but_not_roles(self):
        self.claim(self.enqueue())
        pending = self.enqueue("turn-2", "builder.other", account="another-account")
        self.assertTrue(self.claim(pending, "attempt-2")["may_execute"])

    def test_owner_reserve_uses_the_allowance_not_a_fraction_of_the_remaining_amount(self):
        inspect = self.guard.observe_quota
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=(QuotaWindow("window-1", "account", 100, 85, NOW + 100000, ()),))
        action = self.enqueue(estimate=6)
        self.assertEqual(self.claim(action)["reason"], "owner_reserve_or_quota_wait")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)
        source = self.guard.verify_source
        self.guard.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        self.assertTrue(self.claim(action)["may_execute"])

    def test_autonomous_support_source_cannot_use_reserve_without_an_explicit_verified_grant(self):
        inspect = self.guard.observe_quota
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=(QuotaWindow("window-1", "account", 100, 85, NOW + 100000, ()),))
        action = self.enqueue(origin="support", estimate=6)
        self.assertFalse(self.claim(action)["may_execute"])
        source = self.guard.verify_source
        self.guard.verify_source = lambda scope: replace(source(scope), owner_reserve_granted=True)
        self.assertTrue(self.claim(action)["may_execute"])

    def test_owner_new_turn_bypasses_automated_pacing_but_not_the_activity_cap(self):
        self.claim(self.enqueue())
        source = self.guard.verify_source
        self.guard.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        pending = self.enqueue("owner-turn", "builder.other")
        self.assertTrue(self.claim(pending, "owner-attempt")["may_execute"])
        self.guard.release(CONTROLLER, "owner-attempt")
        inspect = self.guard.observe_activity
        self.guard.observe_activity = lambda scope: replace(inspect(scope), active_sessions=("external-1", "external-2"))
        next_turn = self.enqueue("owner-turn-2", "builder.other")
        self.assertEqual(self.claim(next_turn, "owner-attempt-2")["reason"], "global_activity_cap")

    def test_missing_stale_or_incomplete_quota_holds_without_inventing_available_capacity(self):
        action = self.enqueue()
        inspect = self.guard.observe_quota
        for reader in (lambda scope: None, lambda scope: replace(inspect(scope), observed_ms=NOW - 60001),
                       lambda scope: replace(inspect(scope), complete=False), lambda scope: replace(inspect(scope), account_id="wrong-account")):
            self.guard.observe_quota = reader
            self.assertEqual(self.claim(action)["reason"], "quota_telemetry_unavailable")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)

    def test_every_applicable_window_and_model_pool_is_enforced(self):
        raw = request()
        raw["estimated_units"]["model-pool"] = 1
        action = self.guard.enqueue(CONTROLLER, raw)["record"]
        inspect = self.guard.observe_quota
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=inspect(scope).windows +
            (QuotaWindow("model-pool", "fixture/model", 10, 9, NOW + 100000, ()),))
        self.assertEqual(self.claim(action)["reason"], "owner_reserve_or_quota_wait")

    def test_uncovered_reservations_remain_after_activity_release_until_provider_coverage(self):
        first = self.enqueue(estimate=50)
        self.claim(first)
        self.guard.release(CONTROLLER, "attempt-1")
        self.f.clock[0] += 10000
        inspect = self.guard.observe_quota
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=(QuotaWindow("window-1", "account", 100, 30, NOW + 100000, ()),))
        second = self.enqueue("turn-2", "builder.other", estimate=20)
        self.assertFalse(self.claim(second, "attempt-2")["may_execute"])
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=(QuotaWindow("window-1", "account", 100, 30, NOW + 100000, ("attempt-1",)),))
        wait = self.claim(second, "attempt-2")
        if not wait["may_execute"]:
            self.assertEqual(wait["reason"], "account_pacing_wait")
            self.f.clock[0] = wait["next_eligible_ms"]
        self.assertTrue(self.claim(second, "attempt-2")["may_execute"] if not wait["may_execute"] else wait["may_execute"])

    def test_release_requires_all_tools_quiescent_and_does_not_release_worktree_custody(self):
        f = self.f
        f.ledger.enroll_work(CONTROLLER, work_id="work-1", root_id="root-builder", criteria=["Gate"], dependencies=[],
                            assignee_role_id="builder", resource_id="fixture-resource")
        f.ledger.checkout(Peer(11, 101, 121), "work-1", "checkout-1", expected_revision=0)
        self.claim(self.enqueue())
        inspect = self.guard.verify_stop
        self.guard.verify_stop = lambda row: replace(inspect(row), all_tools_quiesced=False)
        with self.assertRaises(Denied):
            self.guard.release(CONTROLLER, "attempt-1")
        self.assertTrue(self.guard._attempts()[0]["leased"])
        self.guard.verify_stop = inspect
        self.guard.release(CONTROLLER, "attempt-1")
        self.assertIsNotNone(f.ledger.work("work-1")["binding"])

    def test_pause_binding_or_source_changes_during_observation_refuse_execution(self):
        action = self.enqueue()
        inspect = self.guard.observe_quota
        def pause(scope):
            root = self.f.ledger.root("root-builder")
            self.f.ledger.control_root(CONTROLLER, root.id, "held", expected_revision=root.revision)
            return inspect(scope)
        self.guard.observe_quota = pause
        with self.assertRaises(Denied):
            self.claim(action)
        self.assertEqual(self.f.ledger.load(action.id)["record"].fields["state"], "stored")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)

    def test_without_verified_all_source_pre_turn_fence_no_slot_is_granted(self):
        action = self.enqueue()
        inspect = self.guard.observe_activity
        self.guard.observe_activity = lambda scope: replace(inspect(scope), pre_turn_fenced=False)
        self.assertEqual(self.claim(action)["reason"], "all_source_activity_unverified")
        self.assertEqual(len(self.guard._attempts()), 0)

    def test_forged_source_and_changed_target_or_plan_are_rejected(self):
        action = self.enqueue()
        inspect = self.guard.verify_source
        self.guard.verify_source = lambda scope: replace(inspect(scope), scope_digest="sha256:" + "d" * 64)
        with self.assertRaises(Denied):
            self.claim(action)
        self.guard.verify_source = inspect
        wrong = plan(self.f.ledger, action)
        wrong["target"]["account_id"] = "other-account"
        with self.assertRaises(Denied):
            self.guard.claim(CONTROLLER, action.id, "attempt-1", wrong, expected_revision=0)

    def test_clock_regression_expiry_and_root_diagnostic_reserve_stop_new_work(self):
        action = self.enqueue()
        self.f.clock[0] = NOW - 1
        with self.assertRaises(Denied):
            self.claim(action)
        self.f.clock[0] = NOW + 7 * 86400000
        self.assertEqual(self.claim(action)["reason"], "root_held_or_expired")

    def test_actual_process_deaths_preserve_atomic_attempt_root_account_and_activity_state(self):
        for point in ("before_model_admission_commit", "after_model_admission_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                guard = scheduler(f)
                guard.initialize(CONTROLLER)
                guard.enqueue(CONTROLLER, request())
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("model_admission_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with work_fixture(folder) as f:
                guard = scheduler(f)
                guard.initialize(CONTROLLER)
                committed = point == "after_model_admission_commit"
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], int(committed))
                self.assertEqual(len(guard._attempts()), int(committed))
                account = guard._account("synthetic-native-provider", "shared-account")
                self.assertEqual(account is not None, committed)
                if committed:
                    self.assertEqual(account["last_auto_ms"], NOW)
                    self.assertGreater(account["next_auto_ms"], NOW)
                action = f.ledger.load("turn-1")["record"]
                self.assertEqual(action.fields["state"], "unknown" if committed else "stored")
                claimed = guard.claim(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
                self.assertEqual(claimed["may_execute"], not committed)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 1)
                if committed:
                    self.assertTrue(guard._attempts()[0]["leased"])
                    self.assertEqual(guard._attempts()[0]["state"], "held")

    def test_changed_policy_or_component_schema_preserves_pending_admission_state(self):
        self.enqueue()
        wrong = ModelAdmission(self.f.ledger, PacingPolicy(101, 60000, 1000), verify_source=self.guard.verify_source,
            observe_activity=self.guard.observe_activity, observe_quota=self.guard.observe_quota, verify_stop=self.guard.verify_stop)
        with self.assertRaises(Denied):
            wrong.initialize(CONTROLLER)
        self.f.ledger.connection.execute("UPDATE model_metadata SET schema='future'")
        with self.assertRaises(Denied):
            self.guard.initialize(CONTROLLER)
        self.assertEqual(self.f.ledger.load("turn-1")["record"].fields["state"], "stored")

    def test_falling_allowance_increases_spacing_without_resetting_last_admission(self):
        self.claim(self.enqueue())
        old = self.guard._account("synthetic-native-provider", "shared-account")
        self.f.clock[0] += 2000
        inspect = self.guard.observe_quota
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=(QuotaWindow("window-1", "account", 100, 60, NOW + 100000, ()),))
        pending = self.enqueue("turn-2", "builder.other")
        wait = self.claim(pending, "attempt-2")
        self.assertEqual(wait["reason"], "account_pacing_wait")
        self.assertGreater(wait["next_eligible_ms"], old["next_auto_ms"])
        self.assertEqual(self.guard._account("synthetic-native-provider", "shared-account")["last_auto_ms"], NOW)

    def test_persisted_account_clock_index_cannot_be_lowered_to_evade_pacing(self):
        self.claim(self.enqueue())
        self.f.ledger.connection.execute("UPDATE model_accounts SET next_auto_ms=0")
        pending = self.enqueue("turn-2", "builder.other")
        with self.assertRaises(Denied):
            self.claim(pending, "attempt-2")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_spent_ordinary_budget_preserves_the_same_root_diagnostic_subset(self):
        for index in range(3):
            self.f.ledger.charge(Peer(11, 101, 121), "fixture-budget-" + str(index), "turn", expected_revision=self.f.ledger.root("root-builder").revision)
        pending = self.enqueue()
        self.assertEqual(self.claim(pending)["reason"], "root_execution_budget")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 3)
        self.assertEqual(len(self.guard._attempts()), 0)

    def test_quota_coverage_cannot_claim_another_account_or_unknown_attempt(self):
        action = self.enqueue()
        inspect = self.guard.observe_quota
        self.guard.observe_quota = lambda scope: replace(inspect(scope), windows=(QuotaWindow("window-1", "account", 100, 0, NOW + 100000, ("not-an-admitted-attempt",)),))
        with self.assertRaises(Denied):
            self.claim(action)
        self.assertEqual(len(self.guard._attempts()), 0)

    def test_pacing_policy_has_no_implicit_gap_or_observation_age_and_missing_observers_are_rejected(self):
        for values in ((0, 60000, 1000), (100, 0, 1000), (100, 60000, 0), (True, 60000, 1000)):
            with self.assertRaises(Denied):
                PacingPolicy(*values)
        with self.assertRaises(Denied):
            ModelAdmission(self.f.ledger, self.guard.policy, verify_source=None, observe_activity=self.guard.observe_activity,
                           observe_quota=self.guard.observe_quota, verify_stop=self.guard.verify_stop)

    def test_unknown_joined_admission_schema_is_refused_before_root_recovery_can_mutate_it(self):
        folder = self.folder / "unsupported-admission"
        with work_fixture(folder) as f:
            f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
            guard = scheduler(f)
            guard.initialize(CONTROLLER)
            action = guard.enqueue(CONTROLLER, request())["record"]
            guard.claim(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
            original = f.ledger.root("root-builder").encode()
            f.ledger.connection.execute("UPDATE model_metadata SET schema='future'")
        with self.assertRaises(Denied):
            with work_fixture(folder):
                pass
        with sqlite3.connect(str(folder / "ownership/outbox.sqlite")) as connection:
            self.assertEqual(connection.execute("SELECT body FROM roots WHERE id='root-builder'").fetchone()[0], original)
