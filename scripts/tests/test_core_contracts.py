import copy
import json
import unittest

from relay_core.contracts import (
    ContractError, FIELDS, MAX_RECORD_BYTES, RECOVERY_RULES, Record, StaleRevision, UnsupportedSchema,
    create, decode, fingerprint, recovered, transition,
)
from contract_fixtures import DIGEST, TIME, example


class ContractTests(unittest.TestCase):
    def test_every_record_round_trips_and_has_a_recovery_rule(self):
        self.assertEqual(set(FIELDS), set(RECOVERY_RULES))
        for kind in FIELDS:
            with self.subTest(kind=kind):
                record = example(kind)
                self.assertEqual(decode(record.encode()), record)
                self.assertEqual(decode(record.to_dict()), record)

    def test_every_record_rejects_missing_extra_and_invalid_common_fields(self):
        for kind, fields in FIELDS.items():
            for field in fields | {"schema", "id", "revision"}:
                with self.subTest(kind=kind, field=field):
                    raw = example(kind).to_dict()
                    del raw[field]
                    with self.assertRaises(ContractError):
                        decode(raw)
            for patch in ({"unexpected": True}, {"revision": True}, {"revision": -1}, {"id": "../reviewer"}):
                raw = dict(example(kind).to_dict(), **patch)
                with self.assertRaises(ContractError):
                    decode(raw)

    def test_versions_do_not_default_to_current_or_mutate_source(self):
        for kind in FIELDS:
            for schema in (None, f"ccrelay.{kind}.v0", f"ccrelay.{kind}.v2", f"ccrelay.{kind}.v01", "legacy"):
                raw = dict(example(kind).to_dict(), schema=schema)
                before = copy.deepcopy(raw)
                with self.assertRaises(UnsupportedSchema):
                    decode(raw)
                self.assertEqual(before, raw)

    def test_duplicate_keys_and_nonfinite_or_malformed_json_fail(self):
        for raw in ('{"schema":"ccrelay.role.v1","schema":"ccrelay.approval.v1"}',
                    '{"x":NaN}', '{"x":Infinity}', b"\xff", '{"unfinished":', '[]'):
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                decode(raw)

    def test_record_is_deeply_immutable_and_detached_from_input(self):
        raw = example("external_action").to_dict()
        record = decode(raw)
        raw["parameters"]["to"] = "changed@example.invalid"
        self.assertEqual(record.fields["parameters"]["to"], "fixture@example.invalid")
        with self.assertRaises(TypeError):
            record.fields["parameters"]["to"] = "changed"
        thawed = record.to_dict()
        thawed["parameters"]["to"] = "changed"
        self.assertEqual(decode(record.encode()), record)

    def test_direct_constructor_has_the_same_validation_boundary(self):
        raw = dict(example("role").to_dict(), enabled="yes")
        with self.assertRaises(ContractError):
            Record("role", raw)

    def test_role_has_explicit_known_capabilities_and_nonroot_uid(self):
        for patch in ({"uid": 0}, {"uid": True}, {"capabilities": ["admin_everything"]},
                      {"capabilities": ["message", "message"]}, {"enabled": 1}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                example("role", **patch)

    def test_session_desired_pause_does_not_claim_observed_pause(self):
        record = example("session", desired_state="paused")
        self.assertEqual(record.fields["observed_state"], "running")
        restarted = recovered(record)
        self.assertEqual(restarted.fields["desired_state"], "paused")
        self.assertEqual(restarted.fields["observed_state"], "unknown")
        self.assertFalse(restarted.fields["ready"])
        self.assertEqual(restarted.fields["provider_session_id"], "provider-1")
        self.assertEqual(restarted.fields["active_turn_id"], "turn-1")
        self.assertEqual(recovered(restarted), restarted)

    def test_readiness_needs_verified_running_contract_and_observation(self):
        for patch in ({"observed_state": "unknown"}, {"observation_id": None}, {"provider_session_id": None},
                      {"runtime_digest": None}, {"tool_contract_digest": None}, {"permission_digest": None},
                      {"provider": "default"}, {"worktree": "/"}, {"worktree": "/tmp/../Users"}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                example("session", **patch)

    def test_root_requires_finite_limits_and_completion_evidence(self):
        for patch in ({"limits": dict(turns=0, delegations=4, diagnoses=1, checkpoint_deadline=TIME)},
                      {"limits": dict(turns=1, delegations=4, diagnoses=2, checkpoint_deadline=TIME)},
                      {"acceptance_criteria": []}, {"state": "completed"}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                example("root_task", **patch)
        example("root_task", state="completed", verified_evidence_ids=["evidence-1"])

    def test_root_counters_cannot_reset_or_change_policy(self):
        root = example("root_task")
        for patch in ({"limits": {}}, {"root_task_id": "new-root"},
                      {"usage": dict(turns=0, delegations=1, diagnoses=0, no_progress_handoffs=1)},
                      {"usage": dict(turns=1, delegations=1, diagnoses=0, no_progress_handoffs=0)}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                transition(root, "held", expected_revision=0, **patch)
        progressed = transition(root, "active", expected_revision=0,
                                usage=dict(turns=2, delegations=1, diagnoses=0, no_progress_handoffs=0),
                                verified_evidence_ids=["verified-experiment-1"])
        self.assertEqual(progressed.revision, 1)
        with self.assertRaises(ContractError):
            transition(progressed, "held", expected_revision=1, verified_evidence_ids=[])
        self.assertEqual(recovered(progressed), progressed)

    def test_execution_start_intent_and_process_survive_unknown_recovery(self):
        queued = example("execution")
        starting = transition(queued, "starting", expected_revision=0)
        process = dict(pid=100, start_identity="synthetic-kernel-start-1", unit="fixture-session.scope")
        running = transition(starting, "running", expected_revision=1, process=process, observation_id="obs-1")
        restarted = recovered(running)
        self.assertEqual(restarted.fields["state"], "unknown")
        self.assertEqual(restarted.fields["process"]["start_identity"], process["start_identity"])
        self.assertEqual(restarted.fields["fencing_token"], 1)
        self.assertEqual(recovered(starting).fields["state"], "unknown")
        with self.assertRaises(ContractError):
            transition(restarted, "stopped", expected_revision=restarted.revision)
        stopped = transition(restarted, "stopped", expected_revision=restarted.revision, observation_id="new-stop-proof")
        self.assertEqual(stopped.fields["state"], "stopped")

    def test_message_steering_requires_exact_turn_and_intent_is_bound(self):
        for patch in ({"expected_turn_id": None}, {"mode": "start"}, {"mode": "automatic"},
                      {"expected_turn_id": "turn\nspoof"}, {"intent_digest": DIGEST}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                example("message", **patch)
        message = example("message")
        raw = message.to_dict()
        raw["body"] = "different action"
        with self.assertRaises(ContractError):
            decode(raw)

    def test_submission_is_not_confirmation_and_cannot_reset_to_stored(self):
        intent = example("message")
        delivering = transition(intent, "delivering", expected_revision=0, attempt_id="attempt-1")
        submitted = transition(delivering, "submitted", expected_revision=1)
        unknown = recovered(submitted)
        self.assertEqual(unknown.fields["state"], "unknown")
        self.assertEqual(unknown.fields["attempt_id"], "attempt-1")
        for target in ("stored", "delivering", "confirmed", "failed"):
            with self.subTest(target=target), self.assertRaises(ContractError):
                transition(unknown, target, expected_revision=unknown.revision)
        confirmed = transition(unknown, "confirmed", expected_revision=unknown.revision,
                               receipt_id="receipt-1", outcome_evidence_id="query-proof-1")
        self.assertEqual(recovered(confirmed), confirmed)
        self.assertIs(transition(confirmed, "confirmed", expected_revision=confirmed.revision), confirmed)

    def test_attempt_binding_cannot_be_swapped_and_confirmation_needs_receipt(self):
        delivering = transition(example("message"), "delivering", expected_revision=0, attempt_id="attempt-1")
        for patch in ({}, {"receipt_id": "receipt-1", "attempt_id": "attempt-2"}, {"body": "changed"}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                transition(delivering, "confirmed", expected_revision=1, **patch)
        with self.assertRaises(StaleRevision):
            transition(delivering, "submitted", expected_revision=0)

    def test_external_action_requires_broker_authorization(self):
        action = example("external_action")
        with self.assertRaises(ContractError):
            transition(action, "delivering", expected_revision=0, attempt_id="attempt-1")
        admitted = transition(action, "delivering", expected_revision=0, attempt_id="attempt-1", authorization_id="auth-1")
        with self.assertRaises(ContractError):
            transition(admitted, "submitted", expected_revision=1, authorization_id="auth-2")

    def test_approval_consumption_is_single_use_bound_to_exact_attempt(self):
        pending = example("approval")
        with self.assertRaises(ContractError):
            transition(pending, "granted", expected_revision=0)
        granted = transition(pending, "granted", expected_revision=0,
                             owner_auth_reference="trusted-ingress-1", decided_at="2050-01-01T03:04:05Z")
        with self.assertRaises(ContractError):
            transition(granted, "consumed", expected_revision=1)
        consumed = transition(granted, "consumed", expected_revision=1, consumed_attempt_id="attempt-1")
        self.assertEqual(recovered(consumed), consumed)
        for target in ("granted", "pending"):
            with self.assertRaises(ContractError):
                transition(consumed, target, expected_revision=2)

    def test_snapshot_cannot_claim_complete_or_escape_capture_root(self):
        for patch in ({"artifacts": []}, {"incomplete_reasons": ["database inconsistent"]},
                      {"state": "absent"}, {"state": "incomplete"}):
            with self.subTest(patch=patch), self.assertRaises(ContractError):
                example("component_snapshot", **patch)
        for path in ("../outside", "/tmp/secret", "a/../b", "a//b", "a/./b", "C:secret", "a\\b"):
            with self.subTest(path=path), self.assertRaises(ContractError):
                example("component_snapshot", artifacts=[dict(path=path, digest=DIGEST, size_bytes=1)])

    def test_canonical_fingerprints_use_parameter_order_not_dict_order(self):
        self.assertEqual(fingerprint({"a": 1, "b": ["سلام"]}), fingerprint({"b": ["سلام"], "a": 1}))
        self.assertNotEqual(fingerprint({"a": 1}), fingerprint({"a": True}))
        for value in (float("nan"), float("inf"), 0.1, {1: "not a JSON key"}):
            with self.subTest(value=value), self.assertRaises(ContractError):
                fingerprint(value)

    def test_unbounded_or_invalid_unicode_json_is_rejected(self):
        with self.assertRaises(ContractError):
            decode(b" " * (MAX_RECORD_BYTES + 1))
        with self.assertRaises(ContractError):
            fingerprint({"body": "x" * (MAX_RECORD_BYTES + 1)})
        with self.assertRaises(ContractError):
            fingerprint({"body": "\ud800"})
        nested = None
        for _ in range(66):
            nested = [nested]
        with self.assertRaises(ContractError):
            fingerprint(nested)
        raw = example("external_action").to_dict()
        raw["parameters"] = {"nested": nested}
        with self.assertRaises(ContractError):
            decode(raw)

    def test_approval_cannot_claim_a_grant_at_or_after_expiry(self):
        for decided in (TIME, "2050-01-03T03:04:05Z"):
            with self.subTest(decided=decided), self.assertRaises(ContractError):
                example("approval", state="granted", owner_auth_reference="trusted-ingress-1", decided_at=decided)

    def test_counters_cannot_reset_through_bool_or_negative_values(self):
        root = example("root_task")
        for value in (True, -1, "zero"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                transition(root, "held", expected_revision=0,
                           usage=dict(turns=1, delegations=1, diagnoses=0, no_progress_handoffs=value))

    def test_reordered_evidence_is_not_new_verified_progress(self):
        root = example("root_task", verified_evidence_ids=["evidence-1", "evidence-2"])
        with self.assertRaises(ContractError):
            transition(root, "held", expected_revision=0, verified_evidence_ids=["evidence-2", "evidence-1"],
                       usage=dict(turns=1, delegations=1, diagnoses=0, no_progress_handoffs=0))

    def test_factory_cannot_silently_upgrade_a_supplied_schema(self):
        raw = example("role").to_dict()
        with self.assertRaises(ContractError):
            create("role", **raw)


if __name__ == "__main__":
    unittest.main()
