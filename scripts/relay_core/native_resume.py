"""Durable exact-ID Codex resume; no transport discovery, start/fork or retry.

Only a protected driver may supply kernel controller identity, initialized pinned
RPC and authorization covering source/current context, writer and all-source
admission (including possible native goal continuations). No live driver exists.
Registry observations must independently verify runtime/worktree/permissions.
"""
from .contracts import create, fingerprint, intent_payload
from .identity import Denied, exact, identifier, integer
from .runtime_delivery import evidence_for
from .native_settings import verify_resume_permissions
from .native_capture import validate_reference


ADAPTER = "codex-app-server-exact-resume.v3"


def resume_action(row, action_id, *, settings_digest):
    """Protected planning only; the returned record grants no execution permission."""
    record = row["record"]
    from .native_rpc import _hash
    _hash(settings_digest)
    fields = {"id": identifier(action_id), "root_task_id": record.fields["root_task_id"],
              "requested_by_session_id": record.id, "action_kind": "native_resume",
              "parameters": {"session_id": record.id, "expected_revision": record.revision,
                             "binding_digest": row["binding_digest"], "enrollment_digest": fingerprint(row["enrollment"]),
                             "settings_digest": settings_digest}}
    return create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                  attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)


def resume_plan(action, row, authorization_id):
    identifier(authorization_id)
    if action.kind != "external_action" or action.fields["action_kind"] != "native_resume":
        raise Denied("exact native-resume action required")
    parameters = action.to_dict()["parameters"]
    exact(parameters, {"session_id", "expected_revision", "binding_digest", "enrollment_digest", "settings_digest"})
    from .native_rpc import _hash
    _hash(parameters["settings_digest"])
    session = row["record"]
    native = row["enrollment"]
    if action.fields["root_task_id"] != session.fields["root_task_id"] or action.fields["requested_by_session_id"] != session.id or \
            parameters["session_id"] != session.id or integer(parameters["expected_revision"], 0) != session.revision or \
            parameters["binding_digest"] != row["binding_digest"] or parameters["enrollment_digest"] != fingerprint(native) or \
            native["provider"] != "codex" or "exact_resume" not in native["capabilities"] or session.fields["desired_state"] != "running":
        raise Denied("resume action differs from current exact native mapping/control")
    return {"schema": "ccrelay.delivery_plan.v1", "intent_id": action.id, "intent_digest": action.fields["intent_digest"],
            "adapter_id": ADAPTER, "authorization_id": authorization_id,
            "target": {"session_id": session.id, "binding_digest": row["binding_digest"],
                       "enrollment_digest": fingerprint(native), "expected_revision": session.revision,
                       "provider_session_id": native["provider_session_id"], "worktree": native["worktree"],
                       "expected": native["expected"], "settings_digest": parameters["settings_digest"]},
            "parameters": {"threadId": native["provider_session_id"], "cwd": native["worktree"]}}


class CodexExactResume:
    def __init__(self, rpc, *, response_evidence, authorize, resume_supported):
        if not all(callable(value) for value in (rpc, response_evidence, authorize)) or type(resume_supported) is not bool:
            raise Denied("initialized pinned RPC, durable capture, protected admission gate and compatibility proof required")
        self.rpc, self.authorize, self.resume_supported = rpc, authorize, resume_supported
        self.response_evidence = response_evidence

    def deliver(self, ledger, intent_id, attempt_id, registry, controller):
        current = ledger.load(intent_id)
        if current is None:
            raise Denied("unknown resume intent")
        action = current["record"]
        if action.fields["state"] != "stored":
            return {"state": action.fields["state"], "submitted_now": False}
        if not self.resume_supported:
            ledger.hold(intent_id, "resume_unsupported")
            return {"state": "held", "submitted_now": False}
        try:
            if action.kind != "external_action" or action.fields["action_kind"] != "native_resume":
                raise Denied("native resume action required")
            session_id = identifier(action.fields["parameters"].get("session_id"))
            if ledger.policy_digest != registry.policy_digest:
                raise Denied("resume outbox and native registry policy differ")
            binding = registry._controller(controller, session_id)
            row = registry._row(session_id)
            if row is None or row["binding"] != binding:
                raise Denied("resume mapping no longer current")
            # A new action ID cannot disguise a retry of an unresolved resume.
            # The protected driver uses the same authoritative outbox; writer
            # transfer must also reconcile older roots before reusing a mapping.
            for (prior_id,) in ledger.connection.execute(
                    "SELECT id FROM intents WHERE kind='external_action' AND state IN ('delivering','submitted','unknown') AND id<>?", (intent_id,)):
                prior = ledger.load(prior_id)["record"]
                if prior.fields["action_kind"] == "native_resume" and prior.fields["parameters"].get("session_id") == session_id:
                    raise Denied("prior resume for this session remains unreconciled")
            authorization = self.authorize(action, row)
            plan = resume_plan(action, row, authorization)
        except (Denied, ValueError, TypeError):
            ledger.hold(intent_id, "resume_target_or_admission_unavailable")
            return {"state": "held", "submitted_now": False}
        ledger.release_hold(intent_id)
        claim = ledger.claim(intent_id, attempt_id, plan, expected_revision=action.revision)
        if not claim["may_execute"]:
            return {"state": claim["record"].fields["state"], "submitted_now": False}
        try:
            pending = registry.prepare_resume(controller, session_id, expected_revision=row["record"].revision)
            ledger.checkpoint("after_resume_control_commit")
            # Never leave old readiness/probes usable across a mutating RPC.
            if registry._row(session_id)["record"] != pending or registry._controller(controller, session_id) != binding:
                raise Denied("resume control changed before submission")
            ledger.submitted(intent_id, attempt_id)
            if registry._row(session_id)["record"] != pending or registry._controller(controller, session_id) != binding:
                raise Denied("resume control changed before RPC")
            response = self.rpc("thread/resume", plan["parameters"], request_id=attempt_id)
            ledger.checkpoint("after_resume_rpc")
            captured = self.response_evidence("thread/resume", plan["parameters"], request_id=attempt_id, response=response)
            validate_reference(captured)
            ledger.checkpoint("after_resume_capture_verified")
            if type(response) is not dict or response.get("id") != attempt_id or \
                    set(response) - {"jsonrpc", "id", "result", "error"} or \
                    ("jsonrpc" in response and response["jsonrpc"] != "2.0") or "error" in response or \
                    type(response.get("result")) is not dict or type(response["result"].get("thread")) is not dict or \
                    response["result"]["thread"].get("id") != plan["parameters"]["threadId"]:
                raise Denied("ambiguous or wrong-thread resume acknowledgment")
            settings = verify_resume_permissions(response["result"], thread_id=plan["parameters"]["threadId"],
                                                 worktree=plan["parameters"]["cwd"], expected_digest=plan["target"]["settings_digest"])
            ledger.checkpoint("after_resume_settings_verified")
            # ACK alone is insufficient; the existing observer must independently
            # verify fresh identity, worktree, runtime/tool/permission hashes.
            observed = registry.refresh(controller, session_id, expected_revision=pending.revision)
            ledger.checkpoint("after_resume_fresh_observation")
            if not observed.fields["ready"] or registry._row(session_id)["record"] != observed or \
                    registry._controller(controller, session_id) != binding:
                raise Denied("resume remains unavailable or its fresh observation changed")
            evidence = evidence_for(action, attempt_id, plan, outcome="accepted", provider_reference=plan["parameters"]["threadId"],
                                    payload={"native_response": captured, "resume_permissions": settings,
                                             "observation_id": observed.fields["observation_id"],
                                             "observed_revision": observed.revision})
            ledger.reconcile(evidence)
        except Exception:
            state = ledger.load(intent_id)["record"].fields["state"]
            if state == "confirmed":
                return {"state": "confirmed", "submitted_now": True, "meaning": "resume_observed_not_task_completed"}
            if state in {"delivering", "submitted"}:
                ledger.unknown(intent_id, attempt_id)
            return {"state": "unknown", "submitted_now": True, "reason": "resume_outcome_unreconciled"}
        return {"state": "confirmed", "submitted_now": True, "meaning": "resume_observed_not_task_completed"}
