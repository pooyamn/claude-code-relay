"""Invented contract data only; numerical limits are NOT production defaults."""
from relay_core.contracts import create, fingerprint, intent_payload

DIGEST = fingerprint({"fixture": "reviewed contract"})
TIME = "2050-01-02T03:04:05Z"


def example(kind, **changes):
    fields = {
        "role": dict(uid=4001, enabled=True, capabilities=["message", "report_issue"], policy_digest=DIGEST),
        "session": dict(root_task_id="root-1", role_id="builder", provider="codex",
                        provider_session_id="provider-1", worktree="/tmp/fixture/worktree",
                        desired_state="running", observed_state="running", observation_id="observation-1",
                        ready=True, runtime_digest=DIGEST, tool_contract_digest=DIGEST,
                        permission_digest=DIGEST, active_turn_id="turn-1"),
        "root_task": dict(owner_role_id="builder", acceptance_criteria=["A reproducible fixture result"],
                          policy_digest=DIGEST, state="active",
                          limits=dict(turns=7, delegations=4, diagnoses=1, checkpoint_deadline=TIME),
                          usage=dict(turns=1, delegations=1, diagnoses=0, no_progress_handoffs=1),
                          verified_evidence_ids=[]),
        "execution": dict(root_task_id="root-1", work_item_id="item-1", session_id="session-1",
                          state="queued", fencing_token=1, process=None, observation_id=None),
        "message": dict(root_task_id="root-1", from_session_id="session-1", to_session_id="session-2",
                        body="Synthetic hello — سلام", mode="steer", expected_turn_id="turn-1",
                        state="stored", attempt_id=None, receipt_id=None, outcome_evidence_id=None,
                        intent_digest=DIGEST),
        "external_action": dict(root_task_id="root-1", requested_by_session_id="session-1",
                                action_kind="email", parameters={"to": "fixture@example.invalid", "body": "Synthetic"},
                                state="stored", attempt_id=None, receipt_id=None, outcome_evidence_id=None,
                                authorization_id=None, intent_digest=DIGEST),
        "approval": dict(action_id="external_action-1", action_digest=DIGEST, owner_id="synthetic-owner",
                         state="pending", owner_auth_reference=None, decided_at=None,
                         expires_at=TIME, consumed_attempt_id=None),
        "component_snapshot": dict(component="fixture-ledger", component_schema="fixture-ledger.v1",
                                   captured_at=TIME, state="complete", required=True,
                                   artifacts=[dict(path="ledger.sqlite", digest=DIGEST, size_bytes=100)],
                                   exclusions=[], incomplete_reasons=[], runtime_versions={"python": "fixture"}),
    }[kind]
    fields.update(changes)
    id = fields.pop("id", kind + "-1")
    revision = fields.pop("revision", 0)
    if kind in {"message", "external_action"} and "intent_digest" not in changes:
        fields["intent_digest"] = fingerprint(intent_payload(kind, dict(fields, id=id)))
    return create(kind, id=id, revision=revision, **fields)
