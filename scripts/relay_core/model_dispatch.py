"""Durable owner-first admission offers; no payload dispatch or polling loop.

All priority evidence is reread through the protected source verifier. This is
not owner authentication, a native pre-turn fence or a subscription probe.
"""
from dataclasses import asdict, dataclass

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, strict_json
from .model_admission import ModelAdmission
from .work_ownership import _deadline, _digest


SCHEMA = "ccrelay.model_dispatch.v1"


@dataclass(frozen=True)
class DispatchPolicy:
    max_pending: int

    def __post_init__(self):
        if integer(self.max_pending) > 128:
            raise Denied("bounded dispatch offers required")

    def body(self):
        return {"schema": SCHEMA, **asdict(self)}


def metadata(ledger):
    rows = ledger.connection.execute("SELECT schema,policy_digest,body,next_sequence FROM model_dispatch_metadata").fetchall()
    if len(rows) != 1:
        raise Denied("dispatch metadata missing or duplicated")
    schema, digest, raw, next_sequence = rows[0]
    body = strict_json(raw)
    exact(body, {"schema", "max_pending"})
    policy = DispatchPolicy(body["max_pending"])
    if schema != SCHEMA or body != policy.body() or fingerprint(body) != digest:
        raise Denied("unsupported dispatch schema/policy; preserve history")
    integer(next_sequence)
    return policy, next_sequence


def rows(ledger):
    result = []
    for intent_id, attempt_id, sequence, state, raw, digest in ledger.connection.execute("SELECT * FROM model_dispatch_offers ORDER BY sequence"):
        body = strict_json(raw)
        exact(body, {"intent_id", "attempt_id", "sequence", "state", "plan", "expected_revision", "binding", "model_request", "initial_source", "initial_scope_digest", "offered_ms"})
        if fingerprint(body) != digest or (body["intent_id"], body["attempt_id"], body["sequence"], body["state"]) != (intent_id, attempt_id, sequence, state) or state not in {"pending", "attempted", "cancelled"}:
            raise Denied("dispatch offer index/provenance changed")
        identifier(intent_id)
        identifier(attempt_id)
        integer(sequence)
        integer(body["expected_revision"], 0)
        integer(body["offered_ms"], 0)
        _digest(body["initial_scope_digest"])
        source = body["initial_source"]
        exact(source, {"scope_digest", "source_digest", "origin", "owner_requested", "owner_reserve_granted"})
        if source["scope_digest"] != body["initial_scope_digest"] or type(source["owner_requested"]) is not bool or type(source["owner_reserve_granted"]) is not bool:
            raise Denied("dispatch source receipt changed")
        _digest(source["source_digest"])
        current = ledger.load(intent_id)
        request = current["context"].get("model_request", current["record"].to_dict()["parameters"]) if current else None
        if current is None or current["context"].get("binding") != body["binding"] or request != body["model_request"] or \
                body["plan"]["intent_digest"] != current["record"].fields["intent_digest"] or \
                state == "attempted" and current["record"].fields["attempt_id"] != attempt_id:
            raise Denied("dispatch offer differs from its retained original intent")
        result.append(body)
    policy, next_sequence = metadata(ledger)
    if next_sequence <= max((row["sequence"] for row in result), default=0) or sum(row["state"] == "pending" for row in result) > policy.max_pending:
        raise Denied("dispatch sequence regressed or pending bound changed")
    return result


def save(ledger, body):
    ledger.connection.execute("INSERT OR REPLACE INTO model_dispatch_offers VALUES (?,?,?,?,?,?)", (
        body["intent_id"], body["attempt_id"], body["sequence"], body["state"], canonical_bytes(body), fingerprint(body)))


def runnable(admission, current, scope, now, active):
    root, request, control = scope["root"], scope["model_request"], scope["owner_control"]
    deadline = current["record"].fields["parameters"]["deadline"] if scope["diagnostic"] else current["context"]["deadline"]
    if current["record"].fields["state"] != "stored" or current["hold_reason"] is not None or \
            root["state"] not in ({"held"} if scope["diagnostic"] else {"open", "active"}) or \
            not control["known"] or control["desired_state"] != "running" or _deadline(deadline) <= now or \
            scope["binding"]["session_id"] in active:
        return False
    usage, limits = root["usage"], root["limits"]
    exhausted = (usage["turns"] >= limits["turns"] or usage["diagnoses"] >= limits["diagnoses"]) if scope["diagnostic"] else \
        usage["turns"] + limits["diagnoses"] - usage["diagnoses"] >= limits["turns"] or usage["no_progress_handoffs"] >= admission.ledger.threshold(root["id"])
    if exhausted:
        return False
    from .capacity_journal import admission_gate
    if now < admission_gate(admission.ledger, current, now, request=request):
        return False
    return True


def known_quota_blocked(admission, request, source, now):
    """Only a fresh retained negative can exclude an owner, never invent quota."""
    from .quota_estimates import known_bound_blocked
    if known_bound_blocked(admission, request, now):
        return True
    account = admission._account(request["provider"], request["account_id"])
    if account is None:
        return False
    quota = account["quota"]
    if quota["model_id"] != request["model_id"] or not now - admission.policy.quota_max_age_ms <= quota["observed_ms"] <= now or \
            {window["window_id"] for window in quota["windows"]} != set(request["estimated_units"]):
        return False
    attempts = admission._attempts()
    for window in quota["windows"]:
        if window["reset_ms"] <= now:
            return False
        pending = sum(row["allocations"][window["window_id"]]["units"] for row in attempts if
                      (row["provider"], row["account_id"]) == (request["provider"], request["account_id"]) and
                      window["window_id"] in row["allocations"] and row["allocations"][window["window_id"]]["reset_ms"] == window["reset_ms"] and
                      row["allocations"][window["window_id"]]["pool"] == window["pool"] and row["attempt_id"] not in window["accounted_attempts"])
        reserve = 0 if source.owner_requested or source.owner_reserve_granted else (window["allowance"] + 9) // 10
        if request["estimated_units"][window["window_id"]] > window["allowance"] - window["used"] - pending - reserve:
            return True
    return False


def gate(admission, peer, current, scope, source, activity, expected_revision, diagnoses, now):
    ledger = admission.ledger
    if not ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_dispatch_metadata'").fetchone():
        return None
    offers = rows(ledger)
    own = next((row for row in offers if row["intent_id"] == current["record"].id), None)
    if own is None or own["state"] != "pending" or (own["attempt_id"], own["plan"], own["expected_revision"]) != (scope["attempt_id"], scope["plan"], expected_revision):
        raise Denied("enrolled exact pending dispatch offer required; direct claim cannot bypass priority")
    active = {row["session_id"] for row in admission._attempts() if row["leased"]} | set(activity.active_sessions)
    eligible = []
    for offer in offers:
        if offer["state"] != "pending":
            continue
        if offer == own:
            candidate, candidate_scope, candidate_source = current, scope, source
        else:
            binding = ledger.authority.registry.session(offer["binding"]["session_id"])
            if binding["revoked"]:
                continue
            try:
                offered = ledger.load(offer["intent_id"])
                candidate, candidate_scope = admission._scope(peer, offer["intent_id"], offer["attempt_id"], offer["plan"], diagnoses if offered["record"].fields["action_kind"] == "diagnostic_turn" else None)
                if not runnable(admission, candidate, candidate_scope, now, active):
                    continue
                candidate_source = admission._source(candidate_scope)
            except Denied:
                if offer["initial_source"]["owner_requested"] and not source.owner_requested:
                    return "owner_priority_unverified"
                continue  # Retain the offer; unverified input receives no grant.
        if not runnable(admission, candidate, candidate_scope, now, active):
            continue
        if known_quota_blocked(admission, candidate_scope["model_request"], candidate_source, now):
            continue
        if not candidate_source.owner_requested:
            account = admission._account(candidate_scope["model_request"]["provider"], candidate_scope["model_request"]["account_id"])
            if account and now < account["next_auto_ms"]:
                continue
        eligible.append((0 if candidate_source.owner_requested else 1, offer["sequence"], offer["intent_id"]))
    if eligible and min(eligible)[2] != own["intent_id"]:
        return "owner_priority_wait" if min(eligible)[0] == 0 else "dispatch_fifo_wait"
    return None


def committed(ledger, intent_id, attempt_id):
    if not ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_dispatch_metadata'").fetchone():
        return
    offer = next((row for row in rows(ledger) if row["intent_id"] == intent_id), None)
    if offer is None or offer["state"] != "pending" or offer["attempt_id"] != attempt_id:
        raise Denied("exact dispatch offer must join the model attempt commit")
    save(ledger, {**offer, "state": "attempted"})


class ModelDispatch:
    def __init__(self, admission, policy):
        if type(admission) is not ModelAdmission or type(policy) is not DispatchPolicy:
            raise Denied("shared model admission and explicit bounded dispatch policy required")
        self.admission, self.ledger, self.policy = admission, admission.ledger, policy

    def initialize(self, peer):
        roles = self.ledger.authority.policy.controllers.get(peer.uid, frozenset())
        if not roles:
            raise Denied("protected dispatcher controller required")
        self.ledger._controller(peer, sorted(roles)[0])
        self.admission._check()
        with self.ledger._transaction():
            if not self.ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_dispatch_metadata'").fetchone():
                self.ledger.connection.execute("CREATE TABLE model_dispatch_metadata (schema TEXT,policy_digest TEXT,body BLOB,next_sequence INTEGER)")
                self.ledger.connection.execute("INSERT INTO model_dispatch_metadata VALUES (?,?,?,1)", (SCHEMA, fingerprint(self.policy.body()), canonical_bytes(self.policy.body())))
                self.ledger.connection.execute("CREATE TABLE model_dispatch_offers (intent_id TEXT PRIMARY KEY,attempt_id TEXT UNIQUE,sequence INTEGER UNIQUE,state TEXT,body BLOB,digest TEXT)")
                self.ledger.connection.execute("UPDATE model_metadata SET policy_digest=?", (self.admission._policy_digest(),))
            if metadata(self.ledger)[0] != self.policy:
                raise Denied("dispatch policy changed; reviewed migration required")
            self.admission._check()
            rows(self.ledger)

    def offer(self, peer, intent_id, attempt_id, plan, *, expected_revision, diagnoses=None):
        self.admission._check()
        if metadata(self.ledger)[0] != self.policy:
            raise Denied("pinned dispatch policy required")
        current, scope = self.admission._scope(peer, intent_id, attempt_id, plan, diagnoses)
        action = current["record"]
        frozen = {"intent_id": action.id, "attempt_id": attempt_id, "plan": plan, "expected_revision": integer(expected_revision, 0),
                  "binding": scope["binding"], "model_request": scope["model_request"]}
        source = self.admission._source(scope)
        with self.ledger._transaction():
            if self.admission._scope(peer, intent_id, attempt_id, plan, diagnoses)[1] != scope:
                raise Denied("offer authority or root changed during source verification")
            retained = rows(self.ledger)
            prior = next((row for row in retained if row["intent_id"] == intent_id), None)
            if prior:
                if {key: prior[key] for key in frozen} != frozen:
                    raise Denied("dispatch offer cannot replace attempt/plan/target")
                return {"offered_now": False, "state": prior["state"], "intent_id": intent_id}
            if action.fields["state"] != "stored" or action.fields["attempt_id"] is not None or action.revision != expected_revision or current["hold_reason"] is not None:
                raise Denied("an unsubmitted unheld exact model intent is required")
            if sum(row["state"] == "pending" for row in retained) >= self.policy.max_pending:
                return {"offered_now": False, "state": "dispatch_capacity_wait", "meaning": "original_intent_retained_not_dropped"}
            now = self.ledger._clock()
            sequence = metadata(self.ledger)[1]
            save(self.ledger, {**frozen, "sequence": sequence, "state": "pending", "initial_source": asdict(source), "initial_scope_digest": fingerprint(scope), "offered_ms": now})
            self.ledger.connection.execute("UPDATE model_dispatch_metadata SET next_sequence=?", (sequence + 1,))
            self.ledger.checkpoint("before_dispatch_offer_commit")
        self.ledger.checkpoint("after_dispatch_offer_commit")
        return {"offered_now": True, "state": "pending", "intent_id": intent_id, "meaning": "not_model_execution"}

    def cancel(self, peer, intent_id):
        self.admission._check()
        current = self.ledger.load(identifier(intent_id))
        if current is None:
            raise Denied("unknown dispatch intent")
        self.admission._binding(peer, current["record"].fields["requested_by_session_id"])
        with self.ledger._transaction():
            offer = next((row for row in rows(self.ledger) if row["intent_id"] == intent_id), None)
            if offer is None or offer["state"] == "attempted":
                raise Denied("only an unattempted dispatch offer may be cancelled; running tools require separate controls")
            save(self.ledger, {**offer, "state": "cancelled"})
            self.ledger._update(current["record"], hold="dispatch_cancelled")
        return {"state": "cancelled", "meaning": "no_interrupt_or_activity_release"}
