"""Joined durable retries; provider/source/tool-fence facts remain synthetic."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from capacity_journal_fixtures import initial, journal, rejected
from model_admission_fixtures import plan, request, scheduler
from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.capacity_journal import load_job
from relay_core.capacity_retry import RetryPolicy
from relay_core.identity import Denied
from relay_core.runtime_delivery import evidence_for


class CapacityJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = work_fixture(self.folder)
        self.f = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.f.ledger.enroll_root(CONTROLLER, root_record(self.f.authority.policy.digest))
        self.admission, self.original = initial(self.f)
        self.retry = journal(self.f, self.admission)
        self.retry.initialize(CONTROLLER)
        self.job = self.retry.enroll(CONTROLLER, self.original.id)

    def record(self):
        return self.retry.record_failure(CONTROLLER, self.job["id"], self.original.id, jitter_ms=0)

    def due(self):
        self.record()
        self.f.clock[0] += 1000
        return self.retry.advance(CONTROLLER, self.job["id"])

    def test_wait_and_one_due_proposal_are_atomic_and_charge_no_new_turn(self):
        waiting = self.record()
        self.assertEqual(waiting["state"]["status"], "waiting")
        self.assertEqual(waiting["state"]["retry_count"], 1)
        self.assertIsNone(self.retry.advance(CONTROLLER, self.job["id"])["proposal"])
        self.f.clock[0] += 1000
        due = self.retry.advance(CONTROLLER, self.job["id"])
        proposal = due["proposal"]
        self.assertEqual(self.f.ledger.load(proposal["intent_id"])["record"].fields["state"], "stored")
        self.assertIsNone(self.retry.advance(CONTROLLER, self.job["id"])["proposal"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_actual_retry_requires_old_tools_stopped_and_fresh_shared_admission(self):
        due = self.due()
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        self.assertEqual(self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)["reason"], "session_busy")
        self.admission.release(CONTROLLER, "attempt-1")
        self.assertTrue(self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)["may_execute"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 2)
        self.assertEqual(self.retry.enroll(CONTROLLER, action.id)["id"], self.job["id"])
        self.assertEqual(load_job(self.f.ledger, self.job["id"])["state"]["retry_count"], 1)

    def test_duplicate_and_changed_failure_provenance_never_reset_the_timer(self):
        first = self.record()
        inspect = self.retry.verify_failure
        self.f.clock[0] += 500
        self.retry.verify_failure = lambda scope: replace(inspect(scope), observed_ms=NOW)
        self.assertEqual(self.record(), first)
        self.retry.verify_failure = lambda scope: replace(inspect(scope), observed_ms=NOW, retry_after_ms=5000)
        with self.assertRaises(Denied):
            self.record()

    def test_model_cooldown_applies_to_other_roles_but_not_an_unaffected_model(self):
        self.record()
        other = request("turn-2", "builder.other", estimate=1)
        action = self.admission.enqueue(CONTROLLER, other)["record"]
        wait = self.admission.claim(CONTROLLER, action.id, "attempt-2", plan(self.f.ledger, action), expected_revision=0)
        self.assertEqual(wait["reason"], "shared_capacity_wait")
        other["id"], other["model_id"] = "turn-3", "unaffected/model"
        action = self.admission.enqueue(CONTROLLER, other)["record"]
        self.assertTrue(self.admission.claim(CONTROLLER, action.id, "attempt-3", plan(self.f.ledger, action), expected_revision=0)["may_execute"])

    def test_account_wide_provider_wait_cannot_be_bypassed_by_a_model_change(self):
        inspect = self.retry.verify_failure
        self.retry.verify_failure = lambda scope: replace(inspect(scope), cooldown_pool="account", retry_after_ms=15000)
        waiting = self.record()
        self.assertEqual(waiting["state"]["next_eligible_ms"], NOW + 15000)
        other = request("turn-2", "builder.other", estimate=1)
        other["model_id"] = "another/model"
        action = self.admission.enqueue(CONTROLLER, other)["record"]
        self.assertEqual(self.admission.claim(CONTROLLER, action.id, "attempt-2", plan(self.f.ledger, action), expected_revision=0)["next_eligible_ms"], NOW + 15000)

    def test_native_retry_quota_authentication_and_unreconciled_terminal_work_are_held(self):
        inspect = self.retry.verify_failure
        for index, (change, reason) in enumerate((({"native_retry_pending": True}, "native_retry_in_progress"),
                               ({"classification": "quota_exhausted"}, "not_a_capacity_rejection"),
                               ({"classification": "authentication"}, "not_a_capacity_rejection"),
                               ({"outcome": "terminal_reconciled"}, "failed_turn_requires_checkpoint_continuation"))):
            # Separate real scratch ledgers; never reset a retained retry state.
            with work_fixture(self.folder / (str(index) + "-" + reason)) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                admission, original = initial(f)
                retry = journal(f, admission, changes=change)
                retry.initialize(CONTROLLER)
                job = retry.enroll(CONTROLLER, original.id)
                held = retry.record_failure(CONTROLLER, job["id"], original.id, jitter_ms=0)
                self.assertEqual(held["state"]["reason"], reason)
                self.assertEqual(held["state"]["retry_count"], 0)
                self.assertIsNone(retry.advance(CONTROLLER, job["id"])["proposal"])

    def test_unknown_delivery_cannot_be_forged_into_a_negative_retry(self):
        with work_fixture(self.folder / "unknown") as f:
            f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
            admission, original = initial(f, unknown=True)
            retry = journal(f, admission)
            retry.initialize(CONTROLLER)
            job = retry.enroll(CONTROLLER, original.id)
            with self.assertRaises(Denied):
                retry.record_failure(CONTROLLER, job["id"], original.id, jitter_ms=0)
            inspect = retry.verify_failure
            retry.verify_failure = lambda scope: replace(inspect(scope), outcome="unknown")
            held = retry.record_failure(CONTROLLER, job["id"], original.id, jitter_ms=0)
            self.assertEqual(held["state"]["reason"], "submission_requires_reconciliation")

    def test_owner_pause_cancellation_and_expired_elapsed_time_block_a_stored_retry(self):
        due = self.due()
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        root = self.f.ledger.root("root-builder")
        self.f.ledger.control_root(CONTROLLER, root.id, "held", expected_revision=root.revision)
        self.assertIsNone(self.retry.advance(CONTROLLER, self.job["id"])["proposal"])
        self.retry.cancel(CONTROLLER, self.job["id"])
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_automatic_retry_cannot_inherit_a_fresh_owner_request_flag_to_spend_reserve(self):
        due = self.due()
        self.admission.release(CONTROLLER, "attempt-1")
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        inspect = self.admission.verify_source
        self.admission.verify_source = lambda scope: replace(inspect(scope), owner_requested=True)
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)

    def test_recovered_notice_means_exact_input_acceptance_not_task_completion_or_slot_release(self):
        due = self.due()
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        with self.assertRaises(Denied):
            self.retry.observe_acceptance(CONTROLLER, self.job["id"])
        self.admission.release(CONTROLLER, "attempt-1")
        current_plan = plan(self.f.ledger, action)
        self.admission.claim(CONTROLLER, action.id, "retry-attempt", current_plan, expected_revision=0)
        self.f.ledger.submitted(action.id, "retry-attempt")
        self.f.ledger.reconcile(evidence_for(action, "retry-attempt", current_plan, outcome="accepted", provider_reference="synthetic-acceptance", payload={"synthetic_not_runtime": True}))
        first = self.retry.observe_acceptance(CONTROLLER, self.job["id"])
        self.assertEqual(self.retry.observe_acceptance(CONTROLLER, self.job["id"]), first)
        self.assertEqual(first["meaning"], "input_accepted_not_task_completed")
        self.assertEqual(self.f.ledger.root("root-builder").fields["state"], "active")
        self.assertTrue(next(row for row in self.admission._attempts() if row["attempt_id"] == "retry-attempt")["leased"])

    def test_actual_failure_and_proposal_deaths_do_not_reset_limits_or_duplicate_intents(self):
        points = ("before_capacity_failure_commit", "after_capacity_failure_commit", "before_capacity_proposal_commit", "after_capacity_proposal_commit")
        for point in points:
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                admission, original = initial(f)
                retry = journal(f, admission)
                retry.initialize(CONTROLLER)
                job = retry.enroll(CONTROLLER, original.id)
                if "proposal" in point:
                    retry.record_failure(CONTROLLER, job["id"], original.id, jitter_ms=0)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("capacity_journal_fault_fixture.py")), str(folder), point, job["id"]], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with work_fixture(folder) as f:
                admission = scheduler(f)
                admission.initialize(CONTROLLER)
                retry = journal(f, admission)
                retry.initialize(CONTROLLER)
                # Restart the synthetic wall clock at the retained high-water
                # value, not before it. Production regression refusal stays on.
                f.clock[0] = f.ledger.connection.execute("SELECT last_wall_ms FROM work_metadata").fetchone()[0]
                root = f.ledger.root("root-builder")
                f.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
                state = load_job(f.ledger, job["id"])["state"]
                if "failure" in point:
                    self.assertEqual(state["retry_count"], int(point.startswith("after")))
                    retry.record_failure(CONTROLLER, job["id"], "turn-1", jitter_ms=0)
                f.clock[0] += 1000
                due = retry.advance(CONTROLLER, job["id"])
                restored = load_job(f.ledger, job["id"])["state"]
                self.assertEqual(restored["retry_count"], 1)
                self.assertEqual(restored["first_failure_ms"], NOW)
                self.assertEqual(restored["status"], "requested")
                self.assertEqual(f.ledger.connection.execute("SELECT COUNT(*) FROM intents WHERE kind='external_action' AND id=?", (restored["proposal"]["intent_id"],)).fetchone()[0], 1)
                self.assertEqual(f.ledger.root("root-builder").fields["usage"]["turns"], 1)
                self.assertIsNone(retry.advance(CONTROLLER, job["id"])["proposal"])

    def test_each_rejected_replacement_inherits_one_job_until_its_finite_retry_allowance_is_exhausted(self):
        job = self.record()
        previous_attempt = "attempt-1"
        for number in (1, 2):
            self.f.clock[0] = job["state"]["next_eligible_ms"]
            due = self.retry.advance(CONTROLLER, self.job["id"])
            action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
            self.admission.release(CONTROLLER, previous_attempt)
            attempt_id = "retry-attempt-" + str(number)
            rejected(self.f, self.admission, action, attempt_id)
            job = self.retry.record_failure(CONTROLLER, self.job["id"], action.id, jitter_ms=0)
            previous_attempt = attempt_id
        self.assertEqual(job["state"]["status"], "exhausted")
        self.assertEqual(job["state"]["retry_count"], 2)
        self.assertEqual(job["state"]["first_failure_ms"], NOW)
        self.assertIsNone(self.retry.advance(CONTROLLER, self.job["id"])["proposal"])
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 3)

    def test_cancellation_during_quota_observation_is_rechecked_before_attempt_commit(self):
        due = self.due()
        self.admission.release(CONTROLLER, "attempt-1")
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        inspect = self.admission.observe_quota
        def cancel_during_probe(scope):
            self.retry.cancel(CONTROLLER, self.job["id"])
            return inspect(scope)
        self.admission.observe_quota = cancel_during_probe
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)
        self.assertEqual(self.f.ledger.load(action.id)["record"].fields["state"], "stored")
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_elapsed_deadline_also_exhausts_an_unsubmitted_stored_proposal(self):
        due = self.due()
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        self.f.clock[0] = NOW + 20000
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)
        expired = self.retry.advance(CONTROLLER, self.job["id"])
        self.assertEqual(expired["job"]["state"]["status"], "exhausted")
        self.assertEqual(self.f.ledger.load(action.id)["hold_reason"], "capacity_retry_deadline")

    def test_elapsed_deadline_crossing_during_final_admission_cannot_charge_or_execute(self):
        due = self.due()
        self.admission.release(CONTROLLER, "attempt-1")
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        # Cross by one millisecond while quota/activity observations stay fresh;
        # an unrelated telemetry-expiry hold must not mask the retry boundary.
        self.f.clock[0] = NOW + 19999
        clock = self.f.ledger._clock
        reads = 0
        def cross_elapsed_deadline():
            nonlocal reads
            reads += 1
            if reads == 3:
                self.f.clock[0] = NOW + 20000
            return clock()
        self.f.ledger._clock = cross_elapsed_deadline
        with self.assertRaises(Denied):
            result = self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)
            self.assertFalse(result["may_execute"], "expired retry received an execution grant")
        self.assertGreaterEqual(reads, 3)
        self.assertEqual(self.f.ledger.root("root-builder").fields["usage"]["turns"], 1)
        self.assertEqual(self.f.ledger.load(action.id)["record"].fields["state"], "stored")
        self.assertFalse(any(row["attempt_id"] == "retry-attempt" for row in self.admission._attempts()))

    def test_edited_cooldown_or_forged_receipt_is_refused_without_another_proposal(self):
        inspect = self.retry.verify_failure
        self.retry.verify_failure = lambda scope: replace(inspect(scope), scope_digest="sha256:" + "f" * 64)
        with self.assertRaises(Denied):
            self.record()
        self.retry.verify_failure = inspect
        self.record()
        self.f.ledger.connection.execute("UPDATE capacity_cooldowns SET eligible_ms=0")
        action = self.admission.enqueue(CONTROLLER, request("turn-2", "builder.other", estimate=1))["record"]
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "attempt-2", plan(self.f.ledger, action), expected_revision=0)

    def test_changed_retry_policy_or_unknown_component_cannot_reinitialize_counters(self):
        self.record()
        from relay_core.capacity_journal import CapacityJournal
        changed = CapacityJournal(self.admission, RetryPolicy(1001, 4000, 250, 2, 20000), verify_failure=self.retry.verify_failure)
        with self.assertRaises(Denied):
            changed.initialize(CONTROLLER)
        with self.assertRaises(Denied):
            changed.enroll(CONTROLLER, self.original.id)
        self.assertEqual(load_job(self.f.ledger, self.job["id"])["state"]["retry_count"], 1)
        self.f.ledger.connection.execute("UPDATE capacity_metadata SET schema='future'")
        with self.assertRaises(Denied):
            self.retry.initialize(CONTROLLER)

    def test_revoked_execution_cannot_dispatch_a_stored_retry_or_create_a_fresh_job(self):
        due = self.due()
        action = self.f.ledger.load(due["proposal"]["intent_id"])["record"]
        self.f.authority.registry.revoke("builder.task")
        with self.assertRaises(Denied):
            self.admission.claim(CONTROLLER, action.id, "retry-attempt", plan(self.f.ledger, action), expected_revision=0)
        with self.assertRaises(Denied):
            self.retry.advance(CONTROLLER, self.job["id"])
        self.assertEqual(load_job(self.f.ledger, self.job["id"])["state"]["retry_count"], 1)
