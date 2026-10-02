"""Guarded native adapter preparation. No process/socket/login discovery.

The RPC callable must be an initialized, pinned, no-auto-retry protected
transport. PR 7 supplies that transport and exact-session observations; PR 9
supplies admission. This module never starts/resumes/forks or queues a turn.
OpenAI app-server's expectedTurnId guard fences completion races remotely.
An RPC acknowledgment confirms input acceptance, NOT completed model work.
"""
from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier


ADAPTER = "codex-app-server-steer.v1"


def steering_plan(record, session, authorization_id):
    """Pure plan from trusted session evidence, not a worker's runtime claims."""
    identifier(authorization_id)
    if record.kind != "message" or record.fields["mode"] != "steer" or session.kind != "session":
        raise Denied("exact steering message/session required")
    observed = session.to_dict()
    if record.fields["to_session_id"] != session.id or observed["provider"] != "codex" or \
            observed["desired_state"] != "running" or observed["observed_state"] != "running" or \
            not observed["ready"] or observed["active_turn_id"] != record.fields["expected_turn_id"]:
        raise Denied("steering target is unavailable or its exact active turn changed")
    return {"schema": "ccrelay.delivery_plan.v1", "intent_id": record.id,
            "intent_digest": record.fields["intent_digest"], "adapter_id": ADAPTER,
            "authorization_id": authorization_id,
            "target": {key: observed[key] for key in (
                "id", "root_task_id", "provider", "provider_session_id", "active_turn_id", "observation_id",
                "runtime_digest", "tool_contract_digest", "permission_digest")},
            "parameters": {"threadId": observed["provider_session_id"],
                           "expectedTurnId": record.fields["expected_turn_id"],
                           "input": [{"type": "text", "text": record.fields["body"]}]}}


def evidence_for(record, attempt_id, plan, *, outcome, provider_reference, payload):
    """Called only after the protected adapter verified provenance and semantics."""
    data = {"schema": "ccrelay.delivery_evidence.v1", "intent_id": record.id,
            "intent_digest": record.fields["intent_digest"], "attempt_id": attempt_id,
            "plan_digest": fingerprint(plan), "outcome": outcome,
            "provider_reference": provider_reference, "payload": payload}
    return {**data, "id": "evidence-" + fingerprint(data)[7:]}


class CodexSteering:
    def __init__(self, rpc, *, authorize, steer_supported):
        if not callable(rpc) or not callable(authorize) or type(steer_supported) is not bool:
            raise Denied("protected transport, authorization gate and compatibility evidence required")
        self.rpc, self.authorize, self.steer_supported = rpc, authorize, steer_supported

    def deliver(self, ledger, intent_id, attempt_id, session):
        current = ledger.load(intent_id)
        if current is None:
            raise Denied("unknown message")
        record = current["record"]
        if record.fields["state"] != "stored":
            # No RPC, including for delivering/submitted/unknown. The ledger's
            # lifetime lock/recovery protocol owns these states, not this call.
            return {"state": record.fields["state"], "submitted_now": False}
        if not self.steer_supported:
            ledger.hold(intent_id, "steering_unsupported")
            return {"state": "held", "reason": "steering_unsupported", "submitted_now": False}
        try:
            authorization_id = self.authorize(record, session)
            plan = steering_plan(record, session, authorization_id)
        except Denied:
            ledger.hold(intent_id, "target_or_authorization_not_ready")
            return {"state": "held", "reason": "target_or_authorization_not_ready", "submitted_now": False}
        # Only this freshly validated plan may release an unsubmitted hold.
        ledger.release_hold(intent_id)
        claim = ledger.claim(intent_id, attempt_id, plan, expected_revision=record.revision)
        if not claim["may_execute"]:
            return {"state": claim["record"].fields["state"], "submitted_now": False}
        ledger.submitted(intent_id, attempt_id)
        try:
            response = self.rpc("turn/steer", plan["parameters"], request_id=attempt_id)
            ledger.checkpoint("after_adapter_call")
            # Transport may NOT synthesize an acknowledgment from socket write,
            # daemon exit status, log text, timeout or a different RPC response.
            canonical_bytes(response)
            if type(response) is not dict or response.get("id") != attempt_id or \
                    ("result" in response) == ("error" in response) or \
                    set(response) - {"jsonrpc", "id", "result", "error"} or \
                    ("jsonrpc" in response and response["jsonrpc"] != "2.0"):
                raise Denied("ambiguous steering response")
            if "error" in response:
                # Even a matched error is not negative evidence until this exact
                # installed version's errors are characterized. Conservatively
                # retain unknown, not failed/retried and never turn/start.
                raise Denied("steering rejected; exact effect remains unreconciled")
            exact(response["result"], {"turnId"})
            if response["result"]["turnId"] != record.fields["expected_turn_id"]:
                raise Denied("steering receipt belongs to another turn")
            evidence = evidence_for(record, attempt_id, plan, outcome="accepted",
                                    provider_reference=record.fields["expected_turn_id"], payload=response)
            ledger.reconcile(evidence)
        except Exception:
            # Never log raw provider errors, private content or transport paths.
            # If receipt persistence failed, keep the original exact attempt.
            state = ledger.load(intent_id)["record"].fields["state"]
            if state == "confirmed":
                return {"state": "confirmed", "meaning": "input_accepted_not_task_completed", "submitted_now": True}
            if state in {"delivering", "submitted"}:
                ledger.unknown(intent_id, attempt_id)
            return {"state": "unknown", "reason": "steering_outcome_unreconciled", "submitted_now": True}
        return {"state": "confirmed", "meaning": "input_accepted_not_task_completed", "submitted_now": True}
