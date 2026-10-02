"""Epoch-fenced exact Codex reads joined to protected loaded-context evidence.

No launch, resume, control, discovery, model turn or default-context fallback.
The mandatory context verifier must independently measure loaded runtime/tools/
permissions and worktree under the current source; sealing a claim is not proof.
Target provenance/subscription/admission and Claude observation remain pending.
"""
from dataclasses import asdict, dataclass

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, strict_json, validate_binding
from .native_capture import NativeCapture
from .native_epochs import NativeControlEpochs
from .native_rpc import CodexRPC, _hash
from .native_sessions import NativeObservation, _capabilities, _digests


SCHEMA = "ccrelay.codex_observation.v1"
CONTEXT_SCHEMA = "ccrelay.native_loaded_context.v1"


@dataclass(frozen=True)
class NativeContextReceipt:
    artifact_digest: str


def thread_state(thread, *, thread_id, worktree):
    if type(thread) is not dict or thread.get("id") != thread_id or thread.get("cwd") != worktree or \
            type(thread.get("turns")) is not list:
        raise Denied("exact native read thread/worktree and full turn history required")
    status = thread.get("status")
    if type(status) is not dict or type(status.get("type")) is not str:
        raise Denied("native runtime status required")
    kind = status["type"]
    if kind == "active":
        exact(status, {"type", "activeFlags"})
        flags = status["activeFlags"]
        if type(flags) is not list or any(type(flag) is not str or flag not in {"waitingOnApproval", "waitingOnUserInput"} for flag in flags) or \
                len(flags) != len(set(flags)):
            raise Denied("unsupported native active flags")
    elif kind in {"notLoaded", "idle", "systemError"}:
        exact(status, {"type"})
    else:
        raise Denied("unsupported native runtime status")
    seen, active = set(), []
    for turn in thread["turns"]:
        if type(turn) is not dict or type(turn.get("status")) is not str or \
                turn["status"] not in {"inProgress", "completed", "interrupted", "failed"} or type(turn.get("items")) is not list:
            raise Denied("unsupported native turn snapshot")
        turn_id = identifier(turn.get("id"))
        if turn_id in seen:
            raise Denied("duplicate native turn ID")
        seen.add(turn_id)
        if turn["status"] == "inProgress":
            active.append(turn_id)
    if len(active) > 1 or kind == "idle" and active:
        raise Denied("contradictory native active-turn snapshot")
    if kind == "active":
        return ("running", active[0]) if active else ("unknown", None)
    if kind == "idle":
        return "running", None  # Available loaded thread, NOT stopped tools.
    if kind == "systemError":
        return "failed", active[0] if active else None  # NOT a writer-stop receipt.
    return "unknown", None  # notLoaded is NOT stopped/paused proof.


class CodexNativeObserver:
    def __init__(self, rpc, controls, *, inspect_loaded_context):
        if type(rpc) is not CodexRPC or type(controls) is not NativeControlEpochs or \
                type(rpc.capture) is not NativeCapture or not callable(inspect_loaded_context):
            raise Denied("captured native RPC, protected epochs and independent loaded-context verifier required")
        self.rpc, self.controls, self.inspect_loaded_context = rpc, controls, inspect_loaded_context

    def __call__(self, binding, record, probe_id):
        binding = strict_json(canonical_bytes(validate_binding(binding)))
        identifier(probe_id)
        if record.kind != "session" or record.fields["provider"] != "codex" or \
                binding["policy_digest"] != self.controls.policy_digest or \
                (record.id, record.fields["role_id"], record.fields["root_task_id"]) != \
                (binding["session_id"], binding["role_id"], binding["root_task_id"]):
            raise Denied("current exact Codex registry/binding required")
        ticket = self.controls.ticket(self.rpc)
        cohort = self.controls._row(self.rpc.connection_id)
        if (cohort["thread_id"], cohort["worktree"]) != (record.fields["provider_session_id"], record.fields["worktree"]):
            raise Denied("native observer connection belongs to another mapping")
        parameters = {"threadId": cohort["thread_id"], "includeTurns": True}
        response = self.rpc.rpc("thread/read", parameters, request_id=probe_id)
        read_reference = self.rpc.response_evidence("thread/read", parameters, request_id=probe_id, response=response)
        self.controls.validate(self.rpc, ticket)
        if "error" in response or type(response.get("result")) is not dict:
            raise Denied("native read unavailable; no observation fallback")
        state, active_turn = thread_state(response["result"].get("thread"), thread_id=cohort["thread_id"], worktree=cohort["worktree"])
        # The verifier cannot mutate the binding/read evidence against which
        # its result will be checked. It receives detached scope objects.
        receipt = self.inspect_loaded_context(strict_json(canonical_bytes(binding)), record, probe_id, ticket,
                                              strict_json(canonical_bytes(read_reference)))
        if type(receipt) is not NativeContextReceipt:
            raise Denied("independently verified protected loaded-context receipt required")
        manifest, contents = self.rpc.capture.store.verify(_hash(receipt.artifact_digest))
        if manifest["component"] != "native-context" or set(contents) != {"context.json"} or any(entry["executable"] for entry in manifest["files"]):
            raise Denied("loaded-context evidence artifact differs")
        context = strict_json(contents["context.json"])
        required = {"schema", "probe_id", "binding_digest", "source_digest", "connection_id", "control_epoch", "read_artifact_digest",
                    "provider", "provider_session_id", "worktree", "runtime_digest", "tool_contract_digest", "permission_digest", "capabilities"}
        exact(context, required)
        if context["schema"] != CONTEXT_SCHEMA or context["probe_id"] != probe_id or \
                context["binding_digest"] != fingerprint(binding) or context["source_digest"] != ticket.source_digest or \
                context["connection_id"] != ticket.connection_id or type(context["control_epoch"]) is not int or context["control_epoch"] != ticket.epoch or \
                context["read_artifact_digest"] != read_reference["artifact_digest"] or \
                (context["provider"], context["provider_session_id"], context["worktree"]) != \
                ("codex", cohort["thread_id"], cohort["worktree"]):
            raise Denied("loaded-context evidence differs from this fresh exact probe")
        digests = _digests({key: context[key] for key in ("runtime_digest", "tool_contract_digest", "permission_digest")})
        capabilities = tuple(_capabilities(context["capabilities"]))
        self.controls.validate(self.rpc, ticket)
        evidence = {"schema": SCHEMA, "read_reference": read_reference, "control_epoch": asdict(ticket),
                    "context_artifact_digest": receipt.artifact_digest}
        return NativeObservation(probe_id, "native-observation-" + fingerprint(evidence)[7:], fingerprint(binding),
                                 "codex", cohort["thread_id"], cohort["worktree"], state, active_turn,
                                 digests["runtime_digest"], digests["tool_contract_digest"], digests["permission_digest"], capabilities, evidence)
