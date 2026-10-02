"""Pure retry planning fixtures, not live capacity classification/admission."""
import copy
import unittest

from contract_fixtures import DIGEST
from relay_core.contracts import canonical_bytes
from relay_core.identity import Denied, strict_json
from relay_core.capacity_retry import RetryPolicy, cancel, new_state, request_due, schedule, validate_state


def policy(**changes):
    # Invented numbers for deterministic tests, NOT production settings.
    return RetryPolicy(**{"base_delay_ms": 1000, "max_delay_ms": 8000, "jitter_per_mille": 250,
                          "max_retries": 3, "max_elapsed_ms": 60000, **changes})


def scope(**changes):
    return {"work_id": "work-1", "root_task_id": "root-1", "session_id": "session-1", "provider": "fixture",
            "account_id": "account-1", "model_id": "fixture/model", "native_session_id": "native-1",
            "runtime_digest": DIGEST, "adapter_digest": DIGEST, "mode": "start", "expected_turn_id": None, **changes}


def failure(state, **changes):
    return {"schema": "ccrelay.capacity_failure.v1", "id": "failure-1", "scope_digest": state["scope_digest"],
            "classification": "temporary_capacity", "outcome": "not_accepted", "evidence_id": "evidence-1",
            "retry_after_ms": 0, "native_retry_pending": False, "retry_intent_id":
            None if state["proposal"] is None else state["proposal"]["intent_id"], **changes}


class CapacityRetryTests(unittest.TestCase):
    def setUp(self):
        self.policy = policy()
        self.state = new_state(scope(), self.policy, now_ms=10000, root_deadline_ms=100000)

    def schedule(self, state=None, **changes):
        state = self.state if state is None else state
        return schedule(state, failure(state, **changes), self.policy, now_ms=state["last_checked_ms"], jitter_ms=0)

    def restore(self, state):
        return validate_state(strict_json(canonical_bytes(state)), self.policy)

    def test_explicit_policy_rejects_bool_invalid_delay_jitter_and_unbounded_retries(self):
        for changes in ({"base_delay_ms": 0}, {"base_delay_ms": True}, {"max_delay_ms": 999},
                        {"max_retries": 0}, {"max_retries": 51}, {"jitter_per_mille": 1001}, {"max_elapsed_ms": -1}):
            with self.assertRaises(Denied):
                policy(**changes)

    def test_temporary_capacity_schedules_nonblocking_wait_then_one_proposal(self):
        waiting = self.schedule()
        self.assertEqual((waiting["status"], waiting["next_eligible_ms"], waiting["retry_count"]), ("waiting", 11000, 1))
        early, proposal = request_due(waiting, self.policy, now_ms=10999)
        self.assertIsNone(proposal)
        requested, proposal = request_due(early, self.policy, now_ms=11000)
        self.assertEqual(requested["status"], "requested")
        self.assertEqual(requested["reason"], "fresh_admission_required")
        self.assertEqual(proposal["root_task_id"], "root-1")
        self.assertEqual(proposal["source_evidence_id"], "evidence-1")
        self.assertEqual(proposal["operation"], "retry_rejected_input")
        self.assertIsNone(request_due(requested, self.policy, now_ms=12000)[1])

    def test_exponential_backoff_preserves_counters_across_serialized_restore(self):
        state = self.state
        for number, delay in enumerate((1000, 2000, 4000), 1):
            state = self.schedule(self.restore(state), id="failure-" + str(number), evidence_id="evidence-" + str(number))
            self.assertEqual(state["next_eligible_ms"] - state["last_checked_ms"], delay)
            self.assertEqual(state["first_failure_ms"], 10000)
            state, _ = request_due(self.restore(state), self.policy, now_ms=state["next_eligible_ms"])
        exhausted = self.schedule(self.restore(state), id="failure-4", evidence_id="evidence-4")
        self.assertEqual(exhausted["status"], "exhausted")
        self.assertEqual(exhausted["retry_count"], 3)
        self.assertIsNone(request_due(exhausted, self.policy, now_ms=30000)[1])

    def test_local_backoff_caps_but_provider_minimum_is_never_shortened(self):
        custom = policy(base_delay_ms=1000, max_delay_ms=1500)
        state = new_state(scope(), custom, now_ms=10000, root_deadline_ms=100000)
        state = schedule(state, failure(state, retry_after_ms=20000), custom, now_ms=10000, jitter_ms=250)
        self.assertEqual(state["next_eligible_ms"], 30000)
        state, _ = request_due(state, custom, now_ms=30000)
        state = schedule(state, failure(state, id="failure-2"), custom, now_ms=30000, jitter_ms=300)
        self.assertEqual(state["next_eligible_ms"], 31500)

    def test_jitter_is_validated_and_cannot_advance_a_server_minimum(self):
        waiting = schedule(self.state, failure(self.state, retry_after_ms=5000), self.policy, now_ms=10000, jitter_ms=100)
        self.assertEqual(waiting["next_eligible_ms"], 15000)
        for jitter in (-1, True, 251):
            with self.assertRaises(Denied):
                schedule(self.state, failure(self.state), self.policy, now_ms=10000, jitter_ms=jitter)

    def test_duplicate_failure_cannot_reset_deadline_counter_or_move_timer(self):
        event = failure(self.state)
        waiting = schedule(self.state, event, self.policy, now_ms=10000, jitter_ms=0)
        self.assertEqual(schedule(waiting, event, self.policy, now_ms=10500, jitter_ms=200), waiting)
        with self.assertRaises(Denied):
            schedule(waiting, {**event, "retry_after_ms": 5000}, self.policy, now_ms=10500, jitter_ms=0)

    def test_unknown_acceptance_never_retries_even_with_capacity_label(self):
        for outcome in ("unknown", "accepted", "running", "maybe_rejected"):
            held = self.schedule(outcome=outcome)
            self.assertEqual(held["status"], "held")
            self.assertEqual(held["reason"], "submission_requires_reconciliation")
            self.assertEqual(held["retry_count"], 0)
            self.assertIsNone(request_due(held, self.policy, now_ms=20000)[1])

    def test_quota_auth_rate_limit_and_unclassified_text_do_not_become_capacity(self):
        for classification in ("quota_exhausted", "authentication", "rate_limited", "network", "unclassified",
                               "Selected model is at capacity. Please try a different model."):
            held = self.schedule(classification=classification)
            self.assertEqual(held["status"], "held")
            self.assertEqual(held["reason"], "not_a_capacity_rejection")
            self.assertEqual(held["retry_count"], 0)

    def test_native_retry_is_not_multiplied_by_an_outer_retry_loop(self):
        held = self.schedule(native_retry_pending=True)
        self.assertEqual(held["reason"], "native_retry_in_progress")
        self.assertEqual(held["retry_count"], 0)
        self.assertIsNone(request_due(held, self.policy, now_ms=20000)[1])

    def test_terminal_failed_turn_needs_reconciled_checkpoint_continuation(self):
        held = self.schedule(outcome="terminal_reconciled")
        self.assertEqual(held["reason"], "failed_turn_requires_checkpoint_continuation")
        initial = new_state(scope(mode="continue"), self.policy, now_ms=10000, root_deadline_ms=100000)
        waiting = self.schedule(initial, outcome="terminal_reconciled")
        _, proposal = request_due(waiting, self.policy, now_ms=11000)
        self.assertEqual(proposal["operation"], "continue_unfinished_work")

    def test_steering_keeps_exact_turn_and_cannot_start_a_new_turn(self):
        state = new_state(scope(mode="steer", expected_turn_id="turn-1"), self.policy, now_ms=10000, root_deadline_ms=100000)
        waiting = self.schedule(state)
        _, proposal = request_due(waiting, self.policy, now_ms=11000)
        self.assertEqual(proposal["expected_turn_id"], "turn-1")
        self.assertEqual(proposal["operation"], "retry_rejected_input")
        self.assertEqual(waiting["scope"]["mode"], "steer")
        with self.assertRaises(Denied):
            new_state(scope(mode="steer"), self.policy, now_ms=10000, root_deadline_ms=100000)

    def test_serialized_requested_proposal_does_not_emit_it_again(self):
        waiting = self.schedule()
        requested, proposal = request_due(self.restore(waiting), self.policy, now_ms=11000)
        restored = self.restore(requested)
        again, duplicate = request_due(restored, self.policy, now_ms=12000)
        self.assertIsNone(duplicate)
        self.assertEqual(again["proposal"], proposal)
        self.assertEqual(again["retry_count"], 1)

    def test_further_failure_must_bind_the_exact_previously_requested_intent(self):
        waiting = self.schedule()
        requested, proposal = request_due(waiting, self.policy, now_ms=11000)
        for target in (None, "other-intent"):
            with self.assertRaises(Denied):
                self.schedule(requested, id="failure-2", retry_intent_id=target)
        following = self.schedule(requested, id="failure-2", retry_intent_id=proposal["intent_id"])
        self.assertEqual(following["retry_count"], 2)

    def test_provider_wait_exceeding_deadline_defers_without_early_retry(self):
        exhausted = self.schedule(retry_after_ms=61000)
        self.assertEqual(exhausted["status"], "exhausted")
        self.assertEqual(exhausted["reason"], "provider_wait_exceeds_retry_deadline")
        self.assertIsNone(exhausted["next_eligible_ms"])
        self.assertEqual(exhausted["retry_count"], 0)

    def test_elapsed_and_root_deadlines_never_reset(self):
        state = new_state(scope(), self.policy, now_ms=10000, root_deadline_ms=12000)
        waiting = self.schedule(state)
        expired, proposal = request_due(waiting, self.policy, now_ms=12000)
        self.assertIsNone(proposal)
        self.assertEqual(expired["status"], "exhausted")
        self.assertEqual(expired["root_deadline_ms"], 12000)
        elapsed, _ = request_due(self.schedule(), self.policy, now_ms=70000)
        self.assertEqual(elapsed["status"], "exhausted")

    def test_cancel_preserves_history_and_never_reactivates(self):
        waiting = self.schedule()
        stopped = cancel(waiting, self.policy, now_ms=10500)
        self.assertEqual(stopped["failures"], waiting["failures"])
        self.assertEqual(stopped["retry_count"], 1)
        self.assertIsNone(request_due(stopped, self.policy, now_ms=20000)[1])
        self.assertEqual(self.schedule(stopped, id="failure-2"), stopped)

    def test_clock_rollback_and_scope_policy_or_proposal_drift_fail_closed(self):
        with self.assertRaises(Denied):
            request_due(self.state, self.policy, now_ms=9999)
        for key in ("root_task_id", "model_id", "account_id", "native_session_id"):
            changed = copy.deepcopy(self.state)
            changed["scope"][key] = "different"
            with self.assertRaises(Denied):
                validate_state(changed, self.policy)
        with self.assertRaises(Denied):
            validate_state(self.state, policy(max_retries=4))
        requested, _ = request_due(self.schedule(), self.policy, now_ms=11000)
        requested["proposal"]["root_task_id"] = "changed"
        with self.assertRaises(Denied):
            validate_state(requested, self.policy)

    def test_wrong_schema_scope_and_boolean_fields_reject_without_mutation(self):
        original = copy.deepcopy(self.state)
        for changes in ({"schema": "ccrelay.capacity_failure.v99"}, {"scope_digest": DIGEST},
                        {"retry_after_ms": True}, {"native_retry_pending": 1}, {"classification": []}):
            with self.assertRaises(Denied):
                self.schedule(**changes)
        self.assertEqual(self.state, original)
        with self.assertRaises(Denied):
            self.schedule(self.schedule(), id="failure-2")


if __name__ == "__main__":
    unittest.main()
