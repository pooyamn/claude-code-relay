"""Bounded quota estimates joined to admission; no provider probe or runtime.

A retained verified baseline is required. Protected readers must bound usage
not covered by retained reservations while holding the all-source launch fence.
Synthetic receipts in tests do not establish that real-world guarantee.
"""
from dataclasses import asdict, dataclass

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact, identifier, integer, strict_json
from .model_admission import ModelAdmission, QuotaReceipt, QuotaWindow, receipt_body
from .work_ownership import _digest


SCHEMA = "ccrelay.quota_estimates.v1"


@dataclass(frozen=True)
class EstimatePolicy:
    anchor_max_age_ms: int
    usage_bound_max_age_ms: int
    max_starts: int
    minimum_gap_ms: int

    def __post_init__(self):
        for value in asdict(self).values():
            integer(value)

    def body(self):
        return {"schema": SCHEMA, **asdict(self)}


@dataclass(frozen=True)
class UsageBoundReceipt:
    scope_digest: str
    source_digest: str
    anchor_digest: str
    observed_ms: int
    unreserved_units: dict
    all_sources_bounded: bool


@dataclass(frozen=True)
class EstimatedQuotaReceipt:
    scope_digest: str
    source_digest: str
    provider: str
    account_id: str
    model_id: str
    observed_ms: int
    windows: tuple
    complete: bool
    provider_observed_ms: int
    anchor_digest: str
    usage_bound: dict
    policy_digest: str
    mode: str = "conservative_estimate"


def enabled(ledger):
    return bool(ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quota_estimate_metadata'").fetchone())


def metadata(ledger):
    stored = ledger.connection.execute("SELECT schema,policy_digest,body FROM quota_estimate_metadata").fetchall()
    if len(stored) != 1:
        raise Denied("quota estimate metadata missing or duplicated")
    schema, digest, raw = stored[0]
    body = strict_json(raw)
    exact(body, {"schema", "anchor_max_age_ms", "usage_bound_max_age_ms", "max_starts", "minimum_gap_ms"})
    policy = EstimatePolicy(**{key: body[key] for key in body if key != "schema"})
    if schema != SCHEMA or body != policy.body() or digest != fingerprint(body):
        raise Denied("unsupported quota estimate policy; preserve history")
    return policy


def rows(admission):
    result = []
    attempts = {row["attempt_id"]: row for row in admission._attempts()}
    for attempt_id, intent_id, raw, digest in admission.ledger.connection.execute("SELECT * FROM quota_estimate_attempts ORDER BY attempt_id"):
        body = strict_json(raw)
        exact(body, {"attempt_id", "intent_id", "quota"})
        identifier(attempt_id)
        identifier(intent_id)
        attempt = attempts.get(attempt_id)
        if fingerprint(body) != digest or (body["attempt_id"], body["intent_id"]) != (attempt_id, intent_id) or \
                attempt is None or (attempt["intent_id"], attempt["quota"]) != (intent_id, body["quota"]) or \
                body["quota"].get("mode") != "conservative_estimate":
            raise Denied("quota estimate history differs from the joined original attempt")
        result.append(body)
    if {row["attempt_id"] for row in result} != {key for key, row in attempts.items() if row["quota"].get("mode") == "conservative_estimate"}:
        raise Denied("quota estimate attempt history missing; counters cannot reset")
    return result


def start_bound_hit(admission, request, anchor):
    policy = metadata(admission.ledger)
    history = rows(admission)
    for window in anchor["windows"]:
        count = sum(any((prior["window_id"], prior["pool"], prior["reset_ms"]) == (window["window_id"], window["pool"], window["reset_ms"])
                        for prior in row["quota"]["windows"]) for row in history if
                    (row["quota"]["provider"], row["quota"]["account_id"]) == (request["provider"], request["account_id"]))
        if count >= policy.max_starts:
            return True
    return False


def known_bound_blocked(admission, request, now):
    if not enabled(admission.ledger):
        return False
    account = admission._account(request["provider"], request["account_id"])
    if account is None or account["quota"]["model_id"] != request["model_id"]:
        return False
    anchor = account["quota"]
    # Fresh provider telemetry uses normal admission, not the fallback counter.
    return now - anchor["observed_ms"] > admission.policy.quota_max_age_ms and start_bound_hit(admission, request, anchor)


def resolve(admission, scope, unavailable, now):
    """Return a labeled estimate or a hold; never manufacture provider telemetry."""
    guard = getattr(admission, "quota_estimates", None)
    if not enabled(admission.ledger) or type(guard) is not QuotaEstimates or guard.admission is not admission:
        return None, "quota_telemetry_unavailable"
    policy = metadata(admission.ledger)
    if guard.policy != policy:
        raise Denied("pinned quota estimate policy required")
    request = scope["model_request"]
    account = admission._account(request["provider"], request["account_id"])
    if account is None:
        return None, "quota_estimate_baseline_missing"
    anchor = account["quota"]
    if unavailable is not None:
        if type(unavailable) is not QuotaReceipt or unavailable.scope_digest != fingerprint(scope) or \
                receipt_body(unavailable) != {**anchor, "scope_digest": fingerprint(scope)} or \
                now - unavailable.observed_ms <= admission.policy.quota_max_age_ms:
            return None, "quota_telemetry_unavailable"  # Mismatch/incomplete/new negative is not an outage.
    if anchor["model_id"] != request["model_id"] or anchor["complete"] is not True or \
            not now - policy.anchor_max_age_ms <= anchor["observed_ms"] <= now or \
            {window["window_id"] for window in anchor["windows"]} != set(request["estimated_units"]) or \
            any(window["reset_ms"] <= now for window in anchor["windows"]):
        return None, "quota_estimate_baseline_expired_or_mismatched"
    if start_bound_hit(admission, request, anchor):
        return None, "quota_estimate_start_bound"
    observed_scope = {"model_scope": scope, "anchor": anchor, "policy_digest": fingerprint(policy.body())}
    bound = guard.verify_usage_bound(strict_json(canonical_bytes(observed_scope)))
    if type(bound) is not UsageBoundReceipt or bound.scope_digest != fingerprint(observed_scope) or bound.anchor_digest != fingerprint(anchor) or \
            bound.all_sources_bounded is not True or not now - policy.usage_bound_max_age_ms <= integer(bound.observed_ms, 0) <= now or \
            type(bound.unreserved_units) is not dict or set(bound.unreserved_units) != set(request["estimated_units"]):
        return None, "quota_estimate_usage_unbounded"
    _digest(bound.source_digest)
    for units in bound.unreserved_units.values():
        integer(units, 0)
    windows = tuple(QuotaWindow(window["window_id"], window["pool"], window["allowance"],
                               window["used"] + bound.unreserved_units[window["window_id"]], window["reset_ms"], tuple(window["accounted_attempts"]))
                    for window in anchor["windows"])
    return EstimatedQuotaReceipt(fingerprint(scope), fingerprint({"anchor": fingerprint(anchor), "bound": asdict(bound)}),
        request["provider"], request["account_id"], request["model_id"], bound.observed_ms, windows, True,
        anchor["observed_ms"], fingerprint(anchor), asdict(bound), fingerprint(policy.body())), None


def committed(admission, intent_id, attempt_id, quota):
    if type(quota) is not EstimatedQuotaReceipt:
        return
    body = {"intent_id": intent_id, "attempt_id": attempt_id, "quota": receipt_body(quota)}
    admission.ledger.connection.execute("INSERT INTO quota_estimate_attempts VALUES (?,?,?,?)", (attempt_id, intent_id, canonical_bytes(body), fingerprint(body)))


class QuotaEstimates:
    def __init__(self, admission, policy, *, verify_usage_bound):
        if type(admission) is not ModelAdmission or type(policy) is not EstimatePolicy or not callable(verify_usage_bound):
            raise Denied("shared admission, explicit estimate policy and protected usage bound reader required")
        self.admission, self.ledger, self.policy = admission, admission.ledger, policy
        self.verify_usage_bound = verify_usage_bound

    def initialize(self, peer):
        roles = self.ledger.authority.policy.controllers.get(peer.uid, frozenset())
        if not roles:
            raise Denied("protected controller required for quota estimate enrollment")
        self.ledger._controller(peer, sorted(roles)[0])
        self.admission._check()
        with self.ledger._transaction():
            if not enabled(self.ledger):
                self.ledger.connection.execute("CREATE TABLE quota_estimate_metadata (schema TEXT,policy_digest TEXT,body BLOB)")
                self.ledger.connection.execute("INSERT INTO quota_estimate_metadata VALUES (?,?,?)", (SCHEMA, fingerprint(self.policy.body()), canonical_bytes(self.policy.body())))
                self.ledger.connection.execute("CREATE TABLE quota_estimate_attempts (attempt_id TEXT PRIMARY KEY,intent_id TEXT UNIQUE,body BLOB,digest TEXT)")
                self.ledger.connection.execute("UPDATE model_metadata SET policy_digest=?", (self.admission._policy_digest(),))
            if metadata(self.ledger) != self.policy:
                raise Denied("quota estimate policy changed; reviewed migration required")
            self.admission._check()
            rows(self.admission)
        self.admission.quota_estimates = self
