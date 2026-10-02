"""Real bounded estimate ledger; all quota/usage/source facts synthetic."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from model_admission_fixtures import plan, request, scheduler
from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from quota_estimate_fixtures import estimates
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import fingerprint
from relay_core.identity import Denied, Peer
from relay_core.model_admission import QuotaReceipt, QuotaWindow
from relay_core.model_dispatch import DispatchPolicy, ModelDispatch
from relay_core.quota_estimates import EstimatePolicy, rows


class QuotaEstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = work_fixture(self.folder)
        self.f = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.f.ledger.enroll_root(CONTROLLER, root_record(self.f.authority.policy.digest, turns=20))
        self.admission = scheduler(self.f)
        self.admission.initialize(CONTROLLER)
        self.estimates = estimates(self.admission, self.f, policy=EstimatePolicy(90000, 100, 2, 5000))
        self.estimates.initialize(CONTROLLER)

    def enqueue(self, key="estimated-turn", session="builder.other", **kwargs):
        return self.admission.enqueue(CONTROLLER, request(key, session, estimate=1, **kwargs))["record"]

    def claim(self, action, attempt="estimated-attempt"):
        return self.admission.claim(CONTROLLER, action.id, attempt, plan(self.f.ledger, action), expected_revision=0)

    def baseline(self):
        action = self.enqueue("baseline-turn", "builder.task")
        self.assertTrue(self.claim(action, "baseline-attempt")["may_execute"])
        self.admission.release(CONTROLLER, "baseline-attempt")
        self.f.clock[0] = NOW + 61000
        self.admission.observe_quota = lambda _: None
        return self.admission._account("synthetic-native-provider", "shared-account")["quota"]

    def test_missing_quota_uses_labeled_bound_without_refreshing_provider_baseline(self):
        anchor = self.baseline()
        self.assertTrue(self.claim(self.enqueue())["may_execute"])
        estimated = rows(self.admission)[0]["quota"]
        self.assertEqual(estimated["mode"], "conservative_estimate")
        self.assertEqual((estimated["provider_observed_ms"], estimated["observed_ms"]), (NOW, NOW + 61000))
        self.assertEqual(self.admission._account("synthetic-native-provider", "shared-account")["quota"], anchor)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 2)

    def test_absent_baseline_holds_without_inventing_allowance_or_charging(self):
        self.admission.observe_quota = lambda _: None
        self.assertEqual(self.claim(self.enqueue())["reason"], "quota_estimate_baseline_missing")
        self.assertFalse(rows(self.admission))
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)

    def test_estimated_attempt_replay_never_replenishes_count_or_grants_execution(self):
        self.baseline()
        action = self.enqueue()
        self.assertTrue(self.claim(action)["may_execute"])
        self.assertFalse(self.claim(action)["may_execute"])
        self.assertEqual(len(rows(self.admission)), 1)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 2)

    def test_all_applicable_windows_include_unreserved_usage_and_their_owner_reserve(self):
        provider = self.admission.observe_quota
        self.admission.observe_quota = lambda scope: replace(provider(scope), windows=provider(scope).windows +
            (QuotaWindow("model-pool", "fixture/model", 10, 8, NOW + 100000, ()),))
        raw = request("baseline-turn", estimate=1)
        raw["estimated_units"]["model-pool"] = 1
        action = self.admission.enqueue(CONTROLLER, raw)["record"]
        self.assertTrue(self.claim(action, "baseline-attempt")["may_execute"])
        self.admission.release(CONTROLLER, "baseline-attempt")
        self.f.clock[0] = NOW + 61000
        self.admission.observe_quota = lambda _: None
        raw = request("estimated-turn", "builder.other", estimate=1)
        raw["estimated_units"]["model-pool"] = 1
        pending = self.admission.enqueue(CONTROLLER, raw)["record"]
        self.assertEqual(self.claim(pending)["reason"], "owner_reserve_or_quota_wait")
        self.assertFalse(rows(self.admission))

    def test_usage_bound_expiring_after_the_final_reader_cannot_grant_execution(self):
        self.baseline()
        source = self.admission.verify_source
        calls = [0]
        def expire_after_usage_recheck(scope):
            calls[0] += 1
            if calls[0] == 3:
                self.f.clock[0] += 101
            return source(scope)
        self.admission.verify_source = expire_after_usage_recheck
        result = self.claim(self.enqueue())
        self.assertFalse(result["may_execute"], "expired usage ceiling received execution permission")
        self.assertEqual(result["reason"], "admission_observation_expired")
        self.assertFalse(rows(self.admission))

    def test_changing_model_does_not_reset_shared_account_window_start_bound(self):
        fresh = self.admission.observe_quota
        self.baseline()
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        for number in range(2):
            self.claim(self.enqueue("estimate-" + str(number)), "attempt-" + str(number))
            self.admission.release(CONTROLLER, "attempt-" + str(number))
        raw = request("another-model-baseline", "builder.other", estimate=1)
        raw["model_id"] = "fixture/another-model"
        action = self.admission.enqueue(CONTROLLER, raw)["record"]
        self.admission.observe_quota = fresh
        self.assertTrue(self.claim(action, "another-model-baseline-attempt")["may_execute"])
        self.admission.release(CONTROLLER, "another-model-baseline-attempt")
        raw["id"] = "another-model-estimate"
        pending = self.admission.enqueue(CONTROLLER, raw)["record"]
        self.admission.observe_quota = lambda _: None
        self.assertEqual(self.claim(pending, "another-model-estimate-attempt")["reason"], "quota_estimate_start_bound")
        self.assertEqual(len(rows(self.admission)), 2)

    def test_stale_exact_baseline_can_be_estimated_but_changed_stale_observation_cannot(self):
        anchor = self.baseline()
        def stale(scope):
            return QuotaReceipt(**{**anchor, "scope_digest": fingerprint(scope), "windows": tuple(QuotaWindow(**{**w, "accounted_attempts": tuple(w["accounted_attempts"])}) for w in anchor["windows"])})
        self.admission.observe_quota = lambda scope: replace(stale(scope), account_id="different-account")
        action = self.enqueue()
        self.assertEqual(self.claim(action)["reason"], "quota_telemetry_unavailable")
        self.admission.observe_quota = stale
        self.assertTrue(self.claim(action)["may_execute"])

    def test_expired_anchor_or_elapsed_reset_cannot_create_a_new_quota_window(self):
        self.baseline()
        action = self.enqueue()
        for elapsed in (90001, 100000):
            self.f.clock[0] = NOW + elapsed
            self.assertEqual(self.claim(action)["reason"], "quota_estimate_baseline_expired_or_mismatched")
        self.assertFalse(rows(self.admission))

    def test_external_unreserved_usage_and_pending_estimates_preserve_ten_percent_reserve(self):
        self.baseline()
        reader = self.estimates.verify_usage_bound
        self.estimates.verify_usage_bound = lambda scope: replace(reader(scope), unreserved_units={"window-1": 89})
        action = self.enqueue()
        self.assertEqual(self.claim(action)["reason"], "owner_reserve_or_quota_wait")
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        self.assertTrue(self.claim(action)["may_execute"])

    def test_unknown_outside_usage_or_incomplete_bounds_hold_without_spending(self):
        self.baseline()
        reader = self.estimates.verify_usage_bound
        action = self.enqueue()
        for override in ({"all_sources_bounded": False}, {"unreserved_units": {}}, {"observed_ms": NOW}, {"anchor_digest": fingerprint({"wrong": True})}):
            self.estimates.verify_usage_bound = lambda scope, override=override: replace(reader(scope), **override)
            self.assertEqual(self.claim(action)["reason"], "quota_estimate_usage_unbounded")
        self.assertFalse(rows(self.admission))

    def test_estimated_starts_are_bounded_across_sessions_even_for_owner_requests(self):
        self.baseline()
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        for number in range(2):
            action = self.enqueue("estimated-" + str(number))
            self.assertTrue(self.claim(action, "attempt-" + str(number))["may_execute"])
            self.admission.release(CONTROLLER, "attempt-" + str(number))
        third = self.enqueue("estimated-third", "builder.task")
        self.assertEqual(self.claim(third, "attempt-third")["reason"], "quota_estimate_start_bound")
        self.assertEqual(len(rows(self.admission)), 2)

    def test_estimate_gap_is_shared_and_wait_spends_neither_budget_nor_progress(self):
        self.baseline()
        self.assertTrue(self.claim(self.enqueue())["may_execute"])
        self.admission.release(CONTROLLER, "estimated-attempt")
        next_turn = self.enqueue("later", "builder.task")
        result = self.claim(next_turn, "later-attempt")
        self.assertEqual(result["reason"], "account_pacing_wait")
        self.assertGreaterEqual(result["next_eligible_ms"], NOW + 66000)
        self.assertEqual(len(rows(self.admission)), 1)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["no_progress_handoffs"], 0)
        self.f.clock[0] = result["next_eligible_ms"]
        self.assertTrue(self.claim(next_turn, "later-attempt")["may_execute"])

    def test_fresh_provider_evidence_is_not_limited_by_fallback_starts_or_replaces_history(self):
        fresh = self.admission.observe_quota
        self.baseline()
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        for number in range(2):
            self.assertTrue(self.claim(self.enqueue("estimated-" + str(number)), "attempt-" + str(number))["may_execute"])
            self.admission.release(CONTROLLER, "attempt-" + str(number))
        self.admission.observe_quota = fresh
        self.assertTrue(self.claim(self.enqueue("fresh-turn"), "fresh-attempt")["may_execute"])
        self.assertEqual(len(rows(self.admission)), 2)
        self.admission.release(CONTROLLER, "fresh-attempt")
        self.admission.observe_quota = lambda _: None
        self.assertEqual(self.claim(self.enqueue("missing-again"), "missing-attempt")["reason"], "quota_estimate_start_bound")

    def test_fresh_known_exhaustion_cannot_invoke_the_estimate_reader(self):
        self.baseline()
        self.estimates.verify_usage_bound = lambda _: self.fail("negative provider evidence was bypassed")
        self.admission.observe_quota = lambda scope: QuotaReceipt(fingerprint(scope), fingerprint({"negative": True}),
            "synthetic-native-provider", "shared-account", "fixture/model", self.f.clock[0],
            (QuotaWindow("window-1", "account", 100, 100, NOW + 100000, ()),), True)
        self.assertEqual(self.claim(self.enqueue())["reason"], "owner_reserve_or_quota_wait")
        self.admission.observe_quota = lambda _: None
        self.estimates.verify_usage_bound = estimates(self.admission, self.f).verify_usage_bound
        self.assertEqual(self.claim(self.enqueue("after-negative"), "after-negative-attempt")["reason"], "owner_reserve_or_quota_wait")

    def test_usage_ceiling_change_during_priority_read_cannot_grant_execution(self):
        self.baseline()
        dispatch = ModelDispatch(self.admission, DispatchPolicy(8))
        dispatch.initialize(CONTROLLER)
        first, other = self.enqueue(), self.enqueue("other-offer", "builder.task")
        for action in (first, other):
            dispatch.offer(CONTROLLER, action.id, action.id + "-attempt", plan(self.f.ledger, action), expected_revision=0)
        source = self.admission.verify_source
        reader = self.estimates.verify_usage_bound
        def change_during_priority(scope):
            if scope["action"]["id"] == other.id:
                self.estimates.verify_usage_bound = lambda evidence: replace(reader(evidence), unreserved_units={"window-1": 5})
            return source(scope)
        self.admission.verify_source = change_during_priority
        with self.assertRaises(Denied):
            self.claim(first, first.id + "-attempt")
        self.assertFalse(rows(self.admission))

    def test_priority_counter_exhaustion_on_stale_baseline_does_not_block_another_account(self):
        self.baseline()
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=True)
        for number in range(2):
            self.assertTrue(self.claim(self.enqueue("estimated-" + str(number)), "attempt-" + str(number))["may_execute"])
            self.admission.release(CONTROLLER, "attempt-" + str(number))
        dispatch = ModelDispatch(self.admission, DispatchPolicy(8))
        dispatch.initialize(CONTROLLER)
        owner = self.enqueue("blocked-owner")
        auto = self.enqueue("another-account-turn", "builder.task", account="another-account")
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=scope["action"]["id"] == owner.id)
        for action in (owner, auto):
            dispatch.offer(CONTROLLER, action.id, action.id + "-attempt", plan(self.f.ledger, action), expected_revision=0)
        self.admission.observe_quota = scheduler(self.f).observe_quota
        self.assertTrue(self.claim(auto, auto.id + "-attempt")["may_execute"])

    def test_global_activity_cap_still_applies_to_estimated_owner_turns(self):
        self.baseline()
        reader = self.admission.observe_activity
        self.admission.observe_activity = lambda scope: replace(reader(scope), active_sessions=("external-1", "external-2", "external-3"))
        self.assertEqual(self.claim(self.enqueue())["reason"], "global_activity_cap")
        self.assertFalse(rows(self.admission))

    def test_policy_changes_and_worker_enrollment_are_denied(self):
        for operation in (lambda: self.estimates.initialize(Peer(11, 101, 121)),
                          lambda: estimates(self.admission, self.f, policy=EstimatePolicy(90000, 1000, 3, 5000)).initialize(CONTROLLER)):
            with self.assertRaises(Denied):
                operation()
        for values in ((0, 1, 1, 1), (1, 1, False, 1), (1, -1, 1, 1)):
            with self.assertRaises(Denied):
                EstimatePolicy(*values)

    def test_deleted_counter_history_is_detected_from_retained_model_attempts(self):
        self.baseline()
        self.claim(self.enqueue())
        self.f.ledger.connection.execute("DELETE FROM quota_estimate_attempts")
        with self.assertRaises(Denied):
            self.admission._check()

    def test_actual_commit_deaths_keep_estimate_count_and_root_charge_together(self):
        for point in ("before_model_admission_commit", "after_model_admission_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest, turns=20))
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                estimates(admission, f).initialize(CONTROLLER)
                baseline = admission.enqueue(CONTROLLER, request("baseline", estimate=1))["record"]
                admission.claim(CONTROLLER, baseline.id, "baseline-attempt", plan(f.ledger, baseline), expected_revision=0)
                admission.release(CONTROLLER, "baseline-attempt")
                admission.enqueue(CONTROLLER, request("estimated-turn", "builder.other", estimate=1))
            died = subprocess.run([sys.executable, str(Path(__file__).with_name("quota_estimate_fault_fixture.py")), str(folder), point], capture_output=True, timeout=10)
            self.assertEqual(died.returncode, 73, died.stderr.decode())
            with work_fixture(folder) as f:
                f.clock[0] = NOW + 61000
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                estimates(admission, f).initialize(CONTROLLER)
                committed = point == "after_model_admission_commit"
                self.assertEqual(len(rows(admission)), int(committed))
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 1 + int(committed))
                action = f.ledger.load("estimated-turn")["record"]
                if not committed:
                    root = f.ledger.root("root-builder")
                    f.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
                admission.observe_quota = lambda _: None
                self.assertEqual(admission.claim(CONTROLLER, action.id, "estimated-attempt", plan(f.ledger, action), expected_revision=0)["may_execute"], not committed)
                self.assertEqual(len(rows(admission)), 1)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 2)
