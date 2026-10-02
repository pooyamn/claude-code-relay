"""Pure capacity-retry policy preparation for PR 9's durable admission owner.

No sleeps, provider calls, SDK retries, model changes or execution grants. The
caller must atomically persist state before consuming a returned proposal, then
use ordinary admission and the PR 5 outbox. Normalized failure provenance and
negative/reconciliation evidence MUST come from a pinned protected adapter; a
JSON object or the words 'at capacity' do not establish permission to retry.
Policy values are explicit inputs, not production defaults.
"""
import copy
from dataclasses import dataclass

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer


@dataclass(frozen=True)
class RetryPolicy:
    base_delay_ms: int
    max_delay_ms: int
    jitter_per_mille: int
    max_retries: int
    max_elapsed_ms: int

    def __post_init__(self):
        for key in ("base_delay_ms", "max_delay_ms", "max_retries", "max_elapsed_ms"):
            integer(getattr(self, key))
        integer(self.jitter_per_mille, 0)
        if self.max_delay_ms < self.base_delay_ms or self.jitter_per_mille > 1000 or self.max_retries > 50:
            raise Denied("invalid retry bounds; at most 50 retained automatic retries supported")

    def body(self):
        return {"schema": "ccrelay.capacity_retry_policy.v1", **self.__dict__}


SCOPE_KEYS = {"work_id", "root_task_id", "session_id", "provider", "account_id", "model_id",
              "native_session_id", "runtime_digest", "adapter_digest", "mode", "expected_turn_id"}
STATE_KEYS = {"schema", "scope", "scope_digest", "policy_digest", "root_deadline_ms", "status", "reason",
              "retry_count", "first_failure_ms", "last_checked_ms", "next_eligible_ms", "failures", "proposal"}
FAILURE_KEYS = {"schema", "id", "scope_digest", "classification", "outcome", "evidence_id",
                "retry_after_ms", "native_retry_pending", "retry_intent_id"}


def _scope(scope):
    exact(scope, SCOPE_KEYS)
    for key in ("work_id", "root_task_id", "session_id", "account_id"):
        identifier(scope[key])
    for key in ("provider", "model_id", "native_session_id", "runtime_digest", "adapter_digest"):
        if type(scope[key]) is not str or not scope[key]:
            raise Denied("pinned provider/account/model/session/adapter scope required")
    for key in ("runtime_digest", "adapter_digest"):
        digest = scope[key]
        if len(digest) != 71 or not digest.startswith("sha256:") or any(c not in "0123456789abcdef" for c in digest[7:]):
            raise Denied("reviewed runtime/adapter SHA256 digests required")
    if type(scope["mode"]) is not str or scope["mode"] not in {"start", "steer", "continue"}:
        raise Denied("explicit retry operation mode required")
    if scope["mode"] == "steer":
        if type(scope["expected_turn_id"]) is not str or not scope["expected_turn_id"]:
            raise Denied("steering retry must keep the exact expected turn")
    elif scope["expected_turn_id"] is not None:
        raise Denied("expected turn applies only to steering")
    canonical_bytes(scope)


def new_state(scope, policy, *, now_ms, root_deadline_ms):
    _scope(scope)
    integer(now_ms, 0)
    integer(root_deadline_ms)
    if root_deadline_ms <= now_ms:
        raise Denied("retry work requires an unexpired root deadline")
    state = {"schema": "ccrelay.capacity_retry.v1", "scope": copy.deepcopy(scope),
            "scope_digest": fingerprint(scope), "policy_digest": fingerprint(policy.body()),
            "root_deadline_ms": root_deadline_ms, "status": "idle", "reason": None,
            "retry_count": 0, "first_failure_ms": None, "last_checked_ms": now_ms,
            "next_eligible_ms": None, "failures": [], "proposal": None}
    return validate_state(state, policy)


def validate_state(state, policy):
    exact(state, STATE_KEYS)
    _scope(state["scope"])
    if state["schema"] != "ccrelay.capacity_retry.v1" or state["scope_digest"] != fingerprint(state["scope"]) or \
            state["policy_digest"] != fingerprint(policy.body()):
        raise Denied("unsupported retry state, changed scope or policy; preserve for migration")
    if type(state["status"]) is not str or state["status"] not in {"idle", "waiting", "requested", "held", "exhausted", "cancelled"}:
        raise Denied("unsupported retry status")
    for key in ("root_deadline_ms", "retry_count", "last_checked_ms"):
        integer(state[key], 0)
    for key in ("first_failure_ms", "next_eligible_ms"):
        if state[key] is not None:
            integer(state[key], 0)
    if state["reason"] is not None:
        identifier(state["reason"])
    if type(state["failures"]) is not list or len(state["failures"]) > 100 or state["retry_count"] > policy.max_retries:
        raise Denied("retry counters/history exceed explicit bounds")
    seen = set()
    for item in state["failures"]:
        exact(item, {"id", "digest", "evidence_id"})
        identifier(item["id"])
        identifier(item["evidence_id"])
        if item["id"] in seen or type(item["digest"]) is not str or len(item["digest"]) != 71 or \
                not item["digest"].startswith("sha256:") or any(c not in "0123456789abcdef" for c in item["digest"][7:]):
            raise Denied("duplicate or invalid failure history")
        seen.add(item["id"])
    if state["retry_count"] > len(state["failures"]) or (state["first_failure_ms"] is None) != (len(state["failures"]) == 0):
        raise Denied("retry history and counters disagree")
    if (state["status"] == "waiting") != (state["next_eligible_ms"] is not None):
        raise Denied("retry timer belongs only to waiting state")
    if (state["status"] == "requested") != (state["proposal"] is not None):
        raise Denied("retry proposal belongs only to requested state")
    if state["status"] in {"waiting", "requested"} and state["retry_count"] == 0:
        raise Denied("active retry requires retained failure and retry counter")
    if state["proposal"] is not None and state["proposal"] != _proposal(state):
        raise Denied("retry proposal no longer matches its exact source/scope")
    if state["first_failure_ms"] is not None and state["first_failure_ms"] > state["last_checked_ms"]:
        raise Denied("retry history has a future failure")
    if state["status"] == "waiting" and (state["next_eligible_ms"] <= state["last_checked_ms"] or
            state["next_eligible_ms"] >= _deadline(state, policy)):
        raise Denied("retry timer is outside its retained time window")
    if len(canonical_bytes(state)) > 65536:
        raise Denied("retry state exceeds protected frame size")
    return state


def _at(state, policy, now_ms):
    validate_state(state, policy)
    integer(now_ms, 0)
    if now_ms < state["last_checked_ms"]:
        raise Denied("wall clock moved backwards; retain retry state and reconcile time")
    candidate = copy.deepcopy(state)
    candidate["last_checked_ms"] = now_ms
    return candidate


def _deadline(state, policy):
    return min(state["root_deadline_ms"], state["first_failure_ms"] + policy.max_elapsed_ms)


def _proposal(state):
    proposal = {"schema": "ccrelay.capacity_retry_proposal.v1", "scope_digest": state["scope_digest"],
                "root_task_id": state["scope"]["root_task_id"], "source_failure_id": state["failures"][-1]["id"],
                "source_evidence_id": state["failures"][-1]["evidence_id"],
                "retry_number": state["retry_count"], "operation": "continue_unfinished_work" if state["scope"]["mode"] == "continue" else
                "retry_rejected_input", "expected_turn_id": state["scope"]["expected_turn_id"]}
    proposal["intent_id"] = "capacity-retry-" + fingerprint(proposal)[7:]
    return proposal


def schedule(state, failure, policy, *, now_ms, jitter_ms):
    """Trusted normalized negative evidence, NOT a worker-reported error string."""
    candidate = _at(state, policy, now_ms)
    exact(failure, FAILURE_KEYS)
    for key in ("id", "evidence_id"):
        identifier(failure[key])
    if failure["retry_intent_id"] is not None:
        identifier(failure["retry_intent_id"])
    if failure["schema"] != "ccrelay.capacity_failure.v1" or failure["scope_digest"] != state["scope_digest"]:
        raise Denied("failure does not belong to this pinned retry scope")
    integer(failure["retry_after_ms"], 0)
    integer(jitter_ms, 0)
    if type(failure["native_retry_pending"]) is not bool or type(failure["classification"]) is not str or \
            type(failure["outcome"]) is not str:
        raise Denied("typed failure classification/outcome required")
    digest = fingerprint(failure)
    for item in state["failures"]:
        if item["id"] == failure["id"]:
            if item["digest"] != digest:
                raise Denied("failure ID replayed with changed evidence")
            return copy.deepcopy(state)  # Duplicate cannot postpone/reset a timer.
    if state["status"] in {"cancelled", "exhausted"}:
        return copy.deepcopy(state)
    if state["status"] == "waiting":
        raise Denied("a retry is already waiting; shared scheduler must reconcile new observations")
    if state["status"] == "requested" and failure["retry_intent_id"] != state["proposal"]["intent_id"]:
        raise Denied("retry failure must reference the exact previously requested intent")
    if len(state["failures"]) >= 100:
        raise Denied("failure history bound reached; retain state for owner review")
    candidate["failures"].append({"id": failure["id"], "digest": digest, "evidence_id": failure["evidence_id"]})
    if candidate["first_failure_ms"] is None:
        candidate["first_failure_ms"] = now_ms
    candidate.update(proposal=None, next_eligible_ms=None)
    reason = None
    if failure["classification"] != "temporary_capacity":
        reason = "not_a_capacity_rejection"
    elif failure["native_retry_pending"]:
        reason = "native_retry_in_progress"
    elif failure["outcome"] not in {"not_accepted", "terminal_reconciled"}:
        reason = "submission_requires_reconciliation"
    elif failure["outcome"] == "terminal_reconciled" and state["scope"]["mode"] != "continue":
        reason = "failed_turn_requires_checkpoint_continuation"
    if reason:
        candidate.update(status="held", reason=reason)
        return validate_state(candidate, policy)
    if candidate["retry_count"] >= policy.max_retries or now_ms >= _deadline(candidate, policy):
        candidate.update(status="exhausted", reason="retry_budget_or_deadline")
        return validate_state(candidate, policy)
    delay = min(policy.max_delay_ms, policy.base_delay_ms * (2 ** candidate["retry_count"]))
    if jitter_ms > delay * policy.jitter_per_mille // 1000:
        raise Denied("jitter exceeds configured bound")
    delay = max(min(policy.max_delay_ms, delay + jitter_ms), failure["retry_after_ms"])
    next_eligible = now_ms + delay
    if next_eligible >= _deadline(candidate, policy):
        candidate.update(status="exhausted", reason="provider_wait_exceeds_retry_deadline")
        return validate_state(candidate, policy)
    candidate.update(status="waiting", reason="model_at_capacity", next_eligible_ms=next_eligible,
                     retry_count=candidate["retry_count"] + 1)
    return validate_state(candidate, policy)


def request_due(state, policy, *, now_ms):
    """Return one stable retry proposal. Caller must persist BEFORE using it.

    This is NOT admission. Recheck cancellation, target/turn, approvals, root
    budgets, global concurrency, shared cooldowns/quota and owner reserve.
    Following a crash, inspect the stored proposal/outbox; do not emit again.
    """
    candidate = _at(state, policy, now_ms)
    if state["status"] != "waiting":
        return candidate, None
    if now_ms >= _deadline(state, policy):
        candidate.update(status="exhausted", reason="retry_budget_or_deadline", next_eligible_ms=None)
        return validate_state(candidate, policy), None
    if now_ms < state["next_eligible_ms"]:
        return candidate, None
    proposal = _proposal(state)
    candidate.update(status="requested", reason="fresh_admission_required", next_eligible_ms=None, proposal=proposal)
    return validate_state(candidate, policy), proposal


def cancel(state, policy, *, now_ms):
    candidate = _at(state, policy, now_ms)
    candidate.update(status="cancelled", reason="owner_or_task_cancelled", next_eligible_ms=None, proposal=None)
    return validate_state(candidate, policy)
