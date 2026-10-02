"""Real priority ledger and deaths; all owner/source/provider facts synthetic."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from model_admission_fixtures import plan, request, scheduler
from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import fingerprint
from relay_core.identity import Denied, Peer
from relay_core.model_admission import QuotaWindow
from relay_core.model_dispatch import DispatchPolicy, ModelDispatch, rows


class ModelDispatchTests(unittest.TestCase):
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
        self.owners = set()
        source = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(source(scope), owner_requested=scope["action"]["id"] in self.owners,
            source_digest=fingerprint({"synthetic_ingress_not_real_owner": scope["action"]["id"], "owner": scope["action"]["id"] in self.owners}))
        self.dispatch = ModelDispatch(self.admission, DispatchPolicy(8))
        self.dispatch.initialize(CONTROLLER)

    def enqueue(self, key="turn-1", session="builder.task", **kwargs):
        return self.admission.enqueue(CONTROLLER, request(key, session, estimate=1, **kwargs))["record"]

    def offer(self, action, attempt=None):
        return self.dispatch.offer(CONTROLLER, action.id, attempt or "attempt-" + action.id, plan(self.f.ledger, action), expected_revision=0)

    def claim(self, action, attempt=None):
        return self.admission.claim(CONTROLLER, action.id, attempt or "attempt-" + action.id, plan(self.f.ledger, action), expected_revision=0)

    def test_offer_reserves_no_execution_and_exact_duplicates_keep_original_sequence(self):
        action = self.enqueue()
        self.assertTrue(self.offer(action)["offered_now"])
        self.assertFalse(self.offer(action)["offered_now"])
        self.assertEqual(len(rows(self.f.ledger)), 1)
        self.assertEqual(rows(self.f.ledger)[0]["sequence"], 1)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)
        self.assertFalse(self.admission._attempts())

    def test_later_verified_owner_turn_precedes_older_automation_without_erasing_it(self):
        auto = self.enqueue()
        owner = self.enqueue("owner-turn", "builder.other")
        self.owners.add(owner.id)
        self.offer(auto)
        self.offer(owner)
        self.assertEqual(self.claim(auto)["reason"], "owner_priority_wait")
        self.assertTrue(self.claim(owner)["may_execute"])
        self.assertEqual([row["state"] for row in rows(self.f.ledger)], ["pending", "attempted"])
        self.assertEqual(self.f.ledger.load(auto.id)["record"].fields["state"], "stored")

    def test_automatic_fifo_is_durable_and_attempt_replay_never_gets_a_second_grant(self):
        first = self.enqueue()
        second = self.enqueue("turn-2", "builder.other")
        self.offer(first)
        self.offer(second)
        self.assertEqual(self.claim(second)["reason"], "dispatch_fifo_wait")
        self.assertTrue(self.claim(first)["may_execute"])
        self.assertFalse(self.claim(first)["may_execute"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_unoffered_direct_claim_cannot_bypass_an_installed_priority_boundary(self):
        action = self.enqueue()
        with self.assertRaises(Denied):
            self.claim(action)
        self.assertFalse(self.admission._attempts())

    def test_offer_cannot_retarget_attempt_plan_or_source_and_worker_cannot_enroll(self):
        action = self.enqueue()
        self.offer(action)
        with self.assertRaises(Denied):
            self.offer(action, "replacement-attempt")
        changed = plan(self.f.ledger, action)
        changed["authorization_id"] = "replacement-authority"
        with self.assertRaises(Denied):
            self.dispatch.offer(CONTROLLER, action.id, "attempt-" + action.id, changed, expected_revision=0)
        with self.assertRaises(Denied):
            self.dispatch.offer(Peer(11, 101, 121), action.id, "worker-attempt", plan(self.f.ledger, action), expected_revision=0)

    def test_source_priority_changes_are_reread_not_trusted_from_the_stored_flag(self):
        auto = self.enqueue()
        owner = self.enqueue("owner-turn", "builder.other")
        self.owners.add(owner.id)
        self.offer(auto)
        self.offer(owner)
        self.owners.remove(owner.id)
        self.assertTrue(self.claim(auto)["may_execute"])

    def test_owner_arriving_during_quota_probe_is_seen_before_automation_commit(self):
        auto = self.enqueue()
        owner = self.enqueue("owner-turn", "builder.other")
        self.owners.add(owner.id)
        self.offer(auto)
        quota = self.admission.observe_quota
        def arrive_during_probe(scope):
            self.offer(owner)
            return quota(scope)
        self.admission.observe_quota = arrive_during_probe
        self.assertEqual(self.claim(auto)["reason"], "owner_priority_wait")
        self.assertFalse(self.admission._attempts())
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)

    def test_source_revocation_during_quota_probe_denies_even_a_previously_verified_owner(self):
        owner = self.enqueue("owner-turn")
        self.owners.add(owner.id)
        self.offer(owner)
        quota = self.admission.observe_quota
        def revoke_during_probe(scope):
            self.owners.remove(owner.id)
            return quota(scope)
        self.admission.observe_quota = revoke_during_probe
        with self.assertRaises(Denied):
            self.claim(owner)
        self.assertFalse(self.admission._attempts())

    def test_source_revocation_during_other_offer_priority_read_cannot_grant_execution(self):
        first = self.enqueue("owner-first")
        later = self.enqueue("owner-later", "builder.other")
        self.owners.update((first.id, later.id))
        self.offer(first)
        self.offer(later)
        source = self.admission.verify_source
        def revoke_while_reading_other_offer(scope):
            if scope["action"]["id"] == later.id:
                self.owners.discard(first.id)
            return source(scope)
        self.admission.verify_source = revoke_while_reading_other_offer
        with self.assertRaises(Denied):
            result = self.claim(first)
            self.assertFalse(result["may_execute"], "revoked owner grant received execution permission")
        self.assertFalse(self.admission._attempts())
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 0)

    def test_busy_owner_session_does_not_block_runnable_automation_in_another_session(self):
        busy = self.enqueue("running-turn", "builder.other")
        self.offer(busy)
        self.assertTrue(self.claim(busy)["may_execute"])
        auto = self.enqueue("later-auto", account="different-account")
        owner = self.enqueue("owner-turn", "builder.other")
        self.owners.add(owner.id)
        self.offer(auto)
        self.offer(owner)
        self.assertTrue(self.claim(auto)["may_execute"])

    def test_cancelled_or_revoked_owner_offer_does_not_block_automation(self):
        auto = self.enqueue()
        owner = self.enqueue("owner-turn", "builder.other")
        self.owners.add(owner.id)
        self.offer(auto)
        self.offer(owner)
        self.dispatch.cancel(CONTROLLER, owner.id)
        self.assertEqual(self.f.ledger.load(owner.id)["hold_reason"], "dispatch_cancelled")
        self.assertTrue(self.claim(auto)["may_execute"])
        with self.assertRaises(Denied):
            self.claim(owner)

    def test_known_owner_quota_exhaustion_does_not_block_an_unaffected_account(self):
        auto = self.enqueue(account="unaffected-account")
        owner = self.enqueue("owner-turn", "builder.other", account="exhausted-account")
        self.owners.add(owner.id)
        self.offer(auto)
        self.offer(owner)
        quota = self.admission.observe_quota
        self.admission.observe_quota = lambda scope: replace(quota(scope), windows=(QuotaWindow("window-1", "account", 100, 100 if scope["action"]["id"] == owner.id else 0, NOW + 100000, ()),))
        self.assertEqual(self.claim(owner)["reason"], "owner_reserve_or_quota_wait")
        self.assertTrue(self.claim(auto)["may_execute"])

    def test_owner_priority_does_not_override_the_global_three_session_cap(self):
        owner = self.enqueue("owner-turn")
        self.owners.add(owner.id)
        self.offer(owner)
        activity = self.admission.observe_activity
        self.admission.observe_activity = lambda scope: replace(activity(scope), active_sessions=("external-1", "external-2", "external-3"))
        self.assertEqual(self.claim(owner)["reason"], "global_activity_cap")
        self.assertFalse(self.admission._attempts())

    def test_bounded_queue_retains_unoffered_work_and_cancellation_does_not_reset_history(self):
        for number in range(8):
            self.offer(self.enqueue("turn-" + str(number)))
        ninth = self.enqueue("ninth")
        self.assertEqual(self.offer(ninth)["state"], "dispatch_capacity_wait")
        self.assertEqual(self.f.ledger.load(ninth.id)["record"].fields["state"], "stored")
        self.dispatch.cancel(CONTROLLER, "turn-0")
        self.assertTrue(self.offer(ninth)["offered_now"])
        self.assertEqual(rows(self.f.ledger)[-1]["sequence"], 9)

    def test_policy_sequence_corruption_and_older_admission_digest_cannot_remove_priority(self):
        action = self.enqueue()
        self.offer(action)
        legacy_digest = fingerprint(self.admission.policy.body())
        self.assertNotEqual(self.f.ledger.connection.execute("SELECT policy_digest FROM model_metadata").fetchone()[0], legacy_digest)
        self.f.ledger.connection.execute("UPDATE model_metadata SET policy_digest=?", (legacy_digest,))
        with self.assertRaises(Denied):
            self.claim(action)
        self.f.ledger.connection.execute("UPDATE model_metadata SET policy_digest=?", (self.admission._policy_digest(),))
        self.f.ledger.connection.execute("UPDATE model_dispatch_metadata SET next_sequence=1")
        with self.assertRaises(Denied):
            self.offer(self.enqueue("another-turn"))

    def test_actual_offer_and_admission_deaths_preserve_order_and_once_only_execution(self):
        for point in ("before_dispatch_offer_commit", "after_dispatch_offer_commit", "before_model_admission_commit", "after_model_admission_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                dispatch = ModelDispatch(admission, DispatchPolicy(8))
                dispatch.initialize(CONTROLLER)
                action = admission.enqueue(CONTROLLER, request(estimate=1))["record"]
                if "admission" in point:
                    dispatch.offer(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
            died = subprocess.run([sys.executable, str(Path(__file__).with_name("model_dispatch_fault_fixture.py")), str(folder), point], capture_output=True, timeout=10)
            self.assertEqual(died.returncode, 73, died.stderr.decode())
            with work_fixture(folder) as f:
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                dispatch = ModelDispatch(admission, DispatchPolicy(8))
                dispatch.initialize(CONTROLLER)
                retained = rows(f.ledger)
                committed = point == "after_model_admission_commit"
                self.assertEqual(len(retained), int(point != "before_dispatch_offer_commit"))
                if "offer" in point:
                    action = f.ledger.load("turn-1")["record"]
                    dispatch.offer(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)
                self.assertEqual(rows(f.ledger)[0]["sequence"], 1)
                root = f.ledger.root("root-builder")
                self.assertEqual(root.fields["usage"]["turns"], int(committed))
                if committed:
                    self.assertEqual((rows(f.ledger)[0]["state"], admission._attempts()[0]["state"]), ("attempted", "held"))
                action = f.ledger.load("turn-1")["record"]
                if not committed:
                    f.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
                self.assertEqual(admission.claim(CONTROLLER, action.id, "attempt-1", plan(f.ledger, action), expected_revision=0)["may_execute"], not committed)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 1)
