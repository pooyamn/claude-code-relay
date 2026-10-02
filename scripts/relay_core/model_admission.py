"""Durable shared model admission joined to the root/action transaction.

No runtime, quota probe, worker endpoint or paid fallback. Mandatory protected
observers must establish all-source pre-turn fencing and account provenance;
typed receipts alone do not supply those physical/authority guarantees.
"""
from dataclasses import asdict, dataclass

from .contracts import canonical_bytes, create, fingerprint, intent_payload, transition
from .identity import Denied, exact, identifier, integer, strict_json, validate_binding
from .outbox import validate_plan
from .work_ownership import WorkOwnership, _deadline, _digest


SCHEMA = "ccrelay.model_admission.v1"
ORIGINS = {"native_app", "telegram", "mcp", "recovery", "curation", "support"}


@dataclass(frozen=True)
class PacingPolicy:
    minimum_gap_ms: int
    quota_max_age_ms: int
    activity_max_age_ms: int

    def __post_init__(self):
        integer(self.minimum_gap_ms)
        integer(self.quota_max_age_ms)
        integer(self.activity_max_age_ms)

    def body(self):
        return {"schema": SCHEMA, **asdict(self), "active_cap": 3, "owner_reserve_percent": 10}


@dataclass(frozen=True)
class SourceReceipt:
    scope_digest: str
    source_digest: str
    origin: str
    owner_requested: bool
    owner_reserve_granted: bool


@dataclass(frozen=True)
class ActivityReceipt:
    scope_digest: str
    source_digest: str
    observed_ms: int
    active_sessions: tuple
    pre_turn_fenced: bool


@dataclass(frozen=True)
class QuotaWindow:
    window_id: str
    pool: str
    allowance: int
    used: int
    reset_ms: int
    accounted_attempts: tuple


@dataclass(frozen=True)
class QuotaReceipt:
    scope_digest: str
    source_digest: str
    provider: str
    account_id: str
    model_id: str
    observed_ms: int
    windows: tuple
    complete: bool


@dataclass(frozen=True)
class StopReceipt:
    scope_digest: str
    source_digest: str
    all_tools_quiesced: bool
    pre_turn_fenced: bool


def receipt_body(receipt):
    from .quota_estimates import EstimatedQuotaReceipt
    body = asdict(receipt)
    if type(receipt) in {QuotaReceipt, EstimatedQuotaReceipt}:
        body["windows"] = [{**asdict(window), "accounted_attempts": list(window.accounted_attempts)} for window in receipt.windows]
    elif type(receipt) is ActivityReceipt:
        body["active_sessions"] = list(receipt.active_sessions)
    return body


def validate_request(request):
    exact(request, {"id", "session_id", "provider", "account_id", "model_id", "native_session_id", "runtime_digest", "adapter_digest", "origin", "estimated_units"})
    for key in ("id", "session_id", "account_id"):
        identifier(request[key])
    for key in ("provider", "model_id", "native_session_id"):
        if type(request[key]) is not str or not 1 <= len(request[key]) <= 256:
            raise Denied("exact pinned provider/model/native identity required")
    for key in ("runtime_digest", "adapter_digest"):
        _digest(request[key])
    if type(request["origin"]) is not str or request["origin"] not in ORIGINS or type(request["estimated_units"]) is not dict or not 1 <= len(request["estimated_units"]) <= 16:
        raise Denied("known source and finite per-window conservative estimates required")
    for key, value in request["estimated_units"].items():
        identifier(key)
        integer(value)
    return strict_json(canonical_bytes(request))


class ModelAdmission:
    def __init__(self, ledger, policy, *, verify_source, observe_activity, observe_quota, verify_stop):
        if type(ledger) is not WorkOwnership or type(policy) is not PacingPolicy or not all(
                callable(value) for value in (verify_source, observe_activity, observe_quota, verify_stop)):
            raise Denied("protected root ledger, explicit policy and independent source/activity/quota/stop observers required")
        self.ledger, self.policy = ledger, policy
        self.verify_source, self.observe_activity, self.observe_quota, self.verify_stop = verify_source, observe_activity, observe_quota, verify_stop

    def initialize(self, peer):
        """Explicit component enrollment, never a worker action or migration."""
        roles = self.ledger.authority.policy.controllers.get(peer.uid, frozenset())
        if not roles:
            raise Denied("protected controller required to initialize shared admission")
        self.ledger._controller(peer, sorted(roles)[0])
        with self.ledger._transaction():
            exists = self.ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_metadata'").fetchone()
            if not exists:
                self.ledger.connection.execute("CREATE TABLE model_metadata (schema TEXT NOT NULL,policy_digest TEXT NOT NULL)")
                self.ledger.connection.execute("INSERT INTO model_metadata VALUES (?,?)", (SCHEMA, fingerprint(self.policy.body())))
                self.ledger.connection.execute("CREATE TABLE model_accounts (provider TEXT,account_id TEXT,last_auto_ms INTEGER,next_auto_ms INTEGER NOT NULL,body BLOB,digest TEXT,PRIMARY KEY(provider,account_id))")
                self.ledger.connection.execute("CREATE TABLE model_attempts (attempt_id TEXT PRIMARY KEY,intent_id TEXT UNIQUE NOT NULL,session_id TEXT NOT NULL,leased INTEGER NOT NULL,body BLOB NOT NULL,digest TEXT NOT NULL)")
                self.ledger.connection.execute("CREATE UNIQUE INDEX exclusive_model_session ON model_attempts(session_id) WHERE leased=1")
                self.ledger.connection.execute("CREATE TABLE model_waits (intent_id TEXT PRIMARY KEY,body BLOB NOT NULL,digest TEXT NOT NULL)")
            self._check()
            # Recovery is not stop evidence. Retain every activity/quota lease.
            for row in self._attempts():
                if row["state"] == "active":
                    self._save_attempt({**row, "state": "held"})

    def _check(self):
        self.ledger._check_lock()
        if self.ledger.connection.execute("SELECT schema,policy_digest FROM model_metadata").fetchall() != [(SCHEMA, self._policy_digest())]:
            raise Denied("unsupported admission component/policy; preserve state for reviewed migration")
        from .quota_estimates import enabled, rows
        if enabled(self.ledger):
            rows(self)

    def _policy_digest(self):
        body = self.policy.body()
        if self.ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_dispatch_metadata'").fetchone():
            from .model_dispatch import metadata
            body = {"pacing_policy": body, "dispatch_policy": metadata(self.ledger)[0].body()}
        from .quota_estimates import enabled, metadata
        if enabled(self.ledger):
            body = {"base_policy": body, "quota_estimate_policy": metadata(self.ledger).body()}
        return fingerprint(body)

    def _source(self, scope):
        source = self.verify_source(strict_json(canonical_bytes(scope)))
        if type(source) is not SourceReceipt or source.scope_digest != fingerprint(scope) or source.origin != scope["model_request"]["origin"] or \
                type(source.owner_requested) is not bool or type(source.owner_reserve_granted) is not bool:
            raise Denied("independent current source/owner grant required")
        _digest(source.source_digest)
        if (scope["diagnostic"] or scope["context"].get("capacity_retry") is not None) and source.owner_requested:
            raise Denied("automatic diagnosis/retry is not a fresh owner request; explicit reserve grant required")
        return source

    def _attempts(self):
        result = []
        for attempt_id, intent_id, session_id, leased, body, digest in self.ledger.connection.execute("SELECT * FROM model_attempts ORDER BY attempt_id"):
            row = strict_json(body)
            exact(row, {"attempt_id", "intent_id", "session_id", "leased", "state", "provider", "account_id", "binding", "allocations", "admitted_ms", "source", "activity", "quota", "stop"})
            if fingerprint(row) != digest or (row["attempt_id"], row["intent_id"], row["session_id"], int(row["leased"])) != (attempt_id, intent_id, session_id, leased) or \
                    type(row["leased"]) is not bool or row["state"] not in {"active", "held", "released"} or row["leased"] != (row["state"] != "released"):
                raise Denied("admission activity/reservation index changed")
            if row["leased"] and row["stop"] is not None or not row["leased"] and row["stop"] is None:
                raise Denied("activity release lacks its retained stop proof")
            if row["stop"] is not None:
                stop = row["stop"]
                exact(stop, {"receipt", "prior_state"})
                exact(stop["receipt"], {"scope_digest", "source_digest", "all_tools_quiesced", "pre_turn_fenced"})
                original = {**row, "state": stop["prior_state"], "leased": True, "stop": None}
                if stop["prior_state"] not in {"active", "held"} or stop["receipt"]["scope_digest"] != fingerprint(original) or \
                        stop["receipt"]["all_tools_quiesced"] is not True or stop["receipt"]["pre_turn_fenced"] is not True:
                    raise Denied("retained activity stop proof differs from the exact generation")
                _digest(stop["receipt"]["source_digest"])
            action = self.ledger.load(intent_id)
            if action is None or action["record"].fields["attempt_id"] != attempt_id or action["context"].get("binding") != row["binding"]:
                raise Denied("admission attempt differs from joined outbox/binding")
            result.append(row)
        return result

    def _save_attempt(self, row):
        self.ledger.connection.execute("INSERT OR REPLACE INTO model_attempts VALUES (?,?,?,?,?,?)", (
            row["attempt_id"], row["intent_id"], row["session_id"], int(row["leased"]), canonical_bytes(row), fingerprint(row)))

    def _account(self, provider, account_id):
        stored = self.ledger.connection.execute("SELECT last_auto_ms,next_auto_ms,body,digest FROM model_accounts WHERE provider=? AND account_id=?", (provider, account_id)).fetchone()
        if stored is None:
            return None
        body = strict_json(stored[2])
        exact(body, {"provider", "account_id", "last_auto_ms", "next_auto_ms", "quota"})
        if fingerprint(body) != stored[3] or (body["provider"], body["account_id"], body["last_auto_ms"], body["next_auto_ms"]) != (provider, account_id, stored[0], stored[1]):
            raise Denied("account pacing/reservation index changed")
        if body["last_auto_ms"] is not None:
            integer(body["last_auto_ms"], 0)
        integer(body["next_auto_ms"], 0)
        return body

    def _save_account(self, provider, account_id, last, eligible, quota):
        from .quota_estimates import EstimatedQuotaReceipt
        quota_body = receipt_body(quota)
        if type(quota) is EstimatedQuotaReceipt:
            account = self._account(provider, account_id)
            if account is None or fingerprint(account["quota"]) != quota.anchor_digest:
                raise Denied("verified estimate baseline changed; do not replace it with an estimate")
            quota_body = account["quota"]
        body = {"provider": provider, "account_id": account_id, "last_auto_ms": last, "next_auto_ms": eligible, "quota": quota_body}
        self.ledger.connection.execute("INSERT OR REPLACE INTO model_accounts VALUES (?,?,?,?,?,?)", (
            provider, account_id, last, eligible, canonical_bytes(body), fingerprint(body)))

    def _binding(self, peer, session_id):
        binding = validate_binding(self.ledger.authority.registry.session(identifier(session_id)))
        self.ledger._controller(peer, binding["role_id"])
        observed = self.ledger.authority.observer(binding["leader_pid"])
        if binding["revoked"] or binding["policy_digest"] != self.ledger.policy_digest or \
                (observed.uid, observed.start_identity, observed.cgroup) != (binding["uid"], binding["leader_start"], binding["cgroup"]):
            raise Denied("current authenticated exact execution binding required")
        return binding

    def enqueue(self, peer, request):
        request = validate_request(request)
        binding = self._binding(peer, request["session_id"])
        root = self.ledger.root(binding["root_task_id"])
        fields = {"id": request["id"], "root_task_id": root.id, "requested_by_session_id": binding["session_id"], "action_kind": "model_turn", "parameters": request}
        action = create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                        attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
        with self.ledger._transaction():
            self._check()
            if self._binding(peer, binding["session_id"]) != binding:
                raise Denied("binding changed during model intent enrollment")
            result = self.ledger._enroll(action, {"schema": SCHEMA, "binding": binding, "deadline": root.fields["limits"]["checkpoint_deadline"]})
        return result

    def _scope(self, peer, intent_id, attempt_id, plan, diagnoses=None):
        current = self.ledger.load(identifier(intent_id))
        if current is None:
            raise Denied("enrolled model intent required")
        action = current["record"]
        diagnostic = action.fields.get("action_kind") == "diagnostic_turn"
        if diagnostic:
            from .task_diagnosis import SCHEMA as DIAGNOSIS_SCHEMA, TaskDiagnoses
            if type(diagnoses) is not TaskDiagnoses or diagnoses.ledger is not self.ledger or \
                    current["context"].get("schema") != DIAGNOSIS_SCHEMA or "model_request" not in current["context"]:
                raise Denied("same-ledger diagnostic guard and pinned model request required")
            request = validate_request(current["context"]["model_request"])
            if (request["id"], request["session_id"]) != (action.id, action.fields["requested_by_session_id"]):
                raise Denied("diagnostic model request differs from its original intent/target")
            if action.fields["attempt_id"] is None:
                diagnoses.validate_action(peer, intent_id)
        else:
            if action.fields.get("action_kind") != "model_turn" or current["context"].get("schema") != SCHEMA or diagnoses is not None:
                raise Denied("enrolled model intent required")
            request = action.to_dict()["parameters"]
        validate_plan(plan, action)
        binding = self._binding(peer, action.fields["requested_by_session_id"])
        if binding != current["context"]["binding"] or plan["parameters"] != action.fields["parameters"] or plan["target"] != {
                "session_id": binding["session_id"], "binding_digest": fingerprint(binding), "provider": request["provider"],
                "account_id": request["account_id"], "model_id": request["model_id"], "native_session_id": request["native_session_id"],
                "runtime_digest": request["runtime_digest"], "adapter_digest": request["adapter_digest"]}:
            raise Denied("model plan differs from the exact source/account/runtime binding")
        root = self.ledger.root(action.fields["root_task_id"])
        return current, {"action": action.to_dict(), "attempt_id": identifier(attempt_id), "plan": plan, "root": root.to_dict(),
                         "binding": binding, "context": current["context"], "model_request": request, "diagnostic": diagnostic,
                         "owner_control": self.ledger.owner_control(root.id), "policy_digest": self._policy_digest()}

    def _wait(self, action, reason, now, eligible=None):
        body = {"intent_id": action.id, "reason": reason, "observed_ms": now, "next_eligible_ms": eligible,
                "deadline": action.fields["parameters"]["deadline"] if action.fields["action_kind"] == "diagnostic_turn" else self.ledger.load(action.id)["context"]["deadline"],
                "meaning": "no_execution_or_budget_charge"}
        self.ledger.connection.execute("INSERT OR REPLACE INTO model_waits VALUES (?,?,?)", (action.id, canonical_bytes(body), fingerprint(body)))
        return {"may_execute": False, "state": "waiting", **body}

    def claim(self, peer, intent_id, attempt_id, plan, *, expected_revision, diagnoses=None):
        self._check()
        current, scope = self._scope(peer, intent_id, attempt_id, plan, diagnoses)
        action = current["record"]
        request, diagnostic = scope["model_request"], scope["diagnostic"]
        deadline = action.fields["parameters"]["deadline"] if diagnostic else current["context"]["deadline"]
        if action.fields["attempt_id"] is not None:
            return self.ledger.claim(intent_id, attempt_id, plan, expected_revision=expected_revision)
        from .capacity_journal import admission_gate
        with self.ledger._transaction():
            now = self.ledger._clock()
            eligible = admission_gate(self.ledger, current, now, request=request)
            if now < eligible:
                return self._wait(action, "shared_capacity_wait", now, eligible)
        observer_input = strict_json(canonical_bytes(scope))
        source = self._source(scope)
        activity = self.observe_activity(strict_json(canonical_bytes(observer_input)))
        quota = self.observe_quota(strict_json(canonical_bytes(observer_input)))
        unavailable_quota = quota
        digest = fingerprint(scope)
        with self.ledger._transaction():
            if self._scope(peer, intent_id, attempt_id, plan, diagnoses)[1] != scope:
                raise Denied("root, intent or authority changed during admission observations")
            now = self.ledger._clock()
            eligible = admission_gate(self.ledger, current, now, request=request)
            if now < eligible:
                return self._wait(action, "shared_capacity_wait", now, eligible)
            root = self.ledger.root(action.fields["root_task_id"])
            control = scope["owner_control"]
            if root.fields["state"] not in ({"held"} if diagnostic else {"open", "active"}) or not control["known"] or control["desired_state"] != "running" or \
                    _deadline(deadline) <= now or not diagnostic and root.fields["usage"]["no_progress_handoffs"] >= self.ledger.threshold(root.id):
                return self._wait(action, "root_held_or_expired", now)
            if type(activity) is not ActivityReceipt or activity.scope_digest != digest or activity.pre_turn_fenced is not True or \
                    type(activity.active_sessions) is not tuple or len(activity.active_sessions) != len(set(activity.active_sessions)) or \
                    not now - self.policy.activity_max_age_ms <= integer(activity.observed_ms, 0) <= now:
                return self._wait(action, "all_source_activity_unverified", now)
            _digest(activity.source_digest)
            for session in activity.active_sessions:
                identifier(session)
            attempts = self._attempts()
            active = {row["session_id"] for row in attempts if row["leased"]} | set(activity.active_sessions)
            if scope["binding"]["session_id"] in active:
                return self._wait(action, "session_busy", now)
            if len(active) >= 3:
                return self._wait(action, "global_activity_cap", now)
            from .quota_estimates import EstimatedQuotaReceipt, resolve, committed as estimate_committed
            if type(quota) is not QuotaReceipt or not now - self.policy.quota_max_age_ms <= integer(quota.observed_ms, 0) <= now:
                quota, reason = resolve(self, scope, unavailable_quota, now)
                if reason:
                    return self._wait(action, reason, now)
            if type(quota) not in {QuotaReceipt, EstimatedQuotaReceipt} or quota.scope_digest != digest or quota.complete is not True or \
                    (quota.provider, quota.account_id, quota.model_id) != (request["provider"], request["account_id"], request["model_id"]) or \
                    not now - self.policy.quota_max_age_ms <= integer(quota.observed_ms, 0) <= now or \
                    type(quota.windows) is not tuple or not 1 <= len(quota.windows) <= 16:
                return self._wait(action, "quota_telemetry_unavailable", now)
            _digest(quota.source_digest)
            windows = {}
            for window in quota.windows:
                if type(window) is not QuotaWindow or window.pool not in {"account", request["model_id"]} or window.window_id in windows or \
                        type(window.accounted_attempts) is not tuple or len(set(window.accounted_attempts)) != len(window.accounted_attempts):
                    raise Denied("complete distinct applicable quota windows required")
                identifier(window.window_id)
                integer(window.allowance)
                integer(window.used, 0)
                integer(window.reset_ms)
                windows[window.window_id] = window
            if set(windows) != set(request["estimated_units"]):
                return self._wait(action, "window_estimates_incomplete", now)
            account = self._account(quota.provider, quota.account_id)
            if account:
                previous = account["quota"]
                if quota.observed_ms < previous["observed_ms"]:
                    raise Denied("quota observation regressed or persisted provenance changed")
            # Persist verified telemetry even when this work must wait. This
            # changes neither last-start time nor reserved/executed capacity.
            self._save_account(quota.provider, quota.account_id, account["last_auto_ms"] if account else None, account["next_auto_ms"] if account else 0, quota)
            allocations, gap = {}, self.policy.minimum_gap_ms
            if type(quota) is EstimatedQuotaReceipt:
                gap = max(gap, self.quota_estimates.policy.minimum_gap_ms)
            for key, window in windows.items():
                if window.reset_ms <= now:
                    return self._wait(action, "quota_refresh_required", now)
                pending = 0
                for row in attempts:
                    if (row["provider"], row["account_id"]) == (quota.provider, quota.account_id) and key in row["allocations"] and \
                            (row["allocations"][key]["reset_ms"], row["allocations"][key]["pool"]) == (window.reset_ms, window.pool):
                        if row["attempt_id"] not in window.accounted_attempts:
                            pending += row["allocations"][key]["units"]
                for attempt in window.accounted_attempts:
                    identifier(attempt)
                    if not any(row["attempt_id"] == attempt and (row["provider"], row["account_id"]) == (quota.provider, quota.account_id) and \
                               key in row["allocations"] and (row["allocations"][key]["reset_ms"], row["allocations"][key]["pool"]) == (window.reset_ms, window.pool) for row in attempts):
                        raise Denied("quota coverage differs from an admitted account/window attempt")
                reserve = 0 if source.owner_requested or source.owner_reserve_granted else (window.allowance + 9) // 10
                available, estimate = window.allowance - window.used - pending - reserve, request["estimated_units"][key]
                if estimate > available:
                    return self._wait(action, "owner_reserve_or_quota_wait", now, window.reset_ms)
                gap = max(gap, ((window.reset_ms - now) * estimate + available - 1) // available)
                allocations[key] = {"units": estimate, "reset_ms": window.reset_ms, "pool": window.pool}
            eligible = max(account["next_auto_ms"], account["last_auto_ms"] + gap if account["last_auto_ms"] is not None else 0) if account else 0
            if not source.owner_requested and now < eligible:
                return self._wait(action, "account_pacing_wait", now, eligible)
            usage, limits = dict(root.fields["usage"]), root.fields["limits"]
            budget_hit = (usage["turns"] >= limits["turns"] or usage["diagnoses"] >= limits["diagnoses"]) if diagnostic else \
                usage["turns"] + limits["diagnoses"] - usage["diagnoses"] >= limits["turns"]
            if budget_hit:
                return self._wait(action, "root_execution_budget", now)
            claimed = transition(action, "delivering", expected_revision=expected_revision, attempt_id=attempt_id,
                                 authorization_id=plan["authorization_id"])
            if action.fields["state"] != "stored" or current["hold_reason"] is not None:
                raise Denied("unsubmitted unheld model intent required")
            if self._scope(peer, intent_id, attempt_id, plan, diagnoses)[1] != scope:
                raise Denied("admission scope changed before attempt commit")
            if self._source(scope) != source:
                raise Denied("source/owner grant changed before attempt commit")
            from .model_dispatch import gate, committed
            reason = gate(self, peer, current, scope, source, activity, expected_revision, diagnoses, now)
            if reason:
                return self._wait(action, reason, self.ledger._clock())
            if type(quota) is EstimatedQuotaReceipt:
                refreshed, reason = resolve(self, scope, unavailable_quota, self.ledger._clock())
                if reason:
                    return self._wait(action, reason, self.ledger._clock())
                if refreshed != quota:
                    raise Denied("usage bound or verified baseline changed during admission")
            if self._source(scope) != source:
                raise Denied("source/owner grant changed during priority verification")
            if self._scope(peer, intent_id, attempt_id, plan, diagnoses)[1] != scope:
                raise Denied("admission scope changed during priority verification")
            final_now = self.ledger._clock()
            if _deadline(deadline) <= final_now or any(window.reset_ms <= final_now for window in windows.values()) or \
                    final_now - activity.observed_ms > self.policy.activity_max_age_ms or final_now - quota.observed_ms > self.policy.quota_max_age_ms or \
                    type(quota) is EstimatedQuotaReceipt and (final_now - quota.observed_ms > self.quota_estimates.policy.usage_bound_max_age_ms or \
                                                               final_now - quota.provider_observed_ms > self.quota_estimates.policy.anchor_max_age_ms):
                return self._wait(action, "admission_observation_expired", final_now)
            eligible = admission_gate(self.ledger, current, final_now, request=request)
            if final_now < eligible:
                return self._wait(action, "shared_capacity_wait", final_now, eligible)
            self._save_account(quota.provider, quota.account_id, now if not source.owner_requested else account["last_auto_ms"] if account else None,
                max(account["next_auto_ms"] if account else 0, now + gap) if not source.owner_requested else account["next_auto_ms"] if account else 0, quota)
            self.ledger._update(claimed, plan=plan)
            row = {"attempt_id": attempt_id, "intent_id": action.id, "session_id": scope["binding"]["session_id"], "leased": True,
                   "state": "active", "provider": quota.provider, "account_id": quota.account_id, "binding": scope["binding"],
                   "allocations": allocations, "admitted_ms": now, "source": asdict(source), "activity": receipt_body(activity), "quota": receipt_body(quota), "stop": None}
            self._save_attempt(row)
            root = self.ledger.root(action.fields["root_task_id"])
            usage = {**root.fields["usage"], "turns": root.fields["usage"]["turns"] + 1}
            if diagnostic:
                usage["diagnoses"] += 1
            updated = transition(root, "held" if diagnostic else "active", expected_revision=root.revision, usage=usage)
            self.ledger._save_root(updated, "diagnostic_attempt_admitted" if diagnostic else "model_attempt_admitted", {"attempt_id": attempt_id, "source": asdict(source)})
            if diagnostic:
                diagnoses._notice(updated, scope["binding"], action.fields["parameters"]["material_digest"], "diagnosis_attempted", action.id)
            estimate_committed(self, action.id, attempt_id, quota)
            committed(self.ledger, action.id, attempt_id)
            self.ledger.connection.execute("DELETE FROM model_waits WHERE intent_id=?", (action.id,))
            self.ledger.checkpoint("before_model_admission_commit")
        self.ledger.checkpoint("after_model_admission_commit")
        return {"may_execute": True, **self.ledger.load(action.id)}

    def release(self, peer, attempt_id):
        self._check()
        row = next((item for item in self._attempts() if item["attempt_id"] == identifier(attempt_id)), None)
        if row is None:
            raise Denied("unknown activity lease")
        action = self.ledger.load(row["intent_id"])["record"]
        self.ledger._controller(peer, self.ledger.root(action.fields["root_task_id"]).fields["owner_role_id"])
        if not row["leased"]:
            return row
        proof = self.verify_stop(strict_json(canonical_bytes(row)))
        if type(proof) is not StopReceipt or proof.scope_digest != fingerprint(row) or proof.all_tools_quiesced is not True or proof.pre_turn_fenced is not True:
            raise Denied("independent all-tool quiescence under a held pre-turn fence required")
        _digest(proof.source_digest)
        with self.ledger._transaction():
            if row not in self._attempts():
                raise Denied("activity lease changed during stop verification")
            self.ledger._controller(peer, self.ledger.root(action.fields["root_task_id"]).fields["owner_role_id"])
            released = {**row, "leased": False, "state": "released", "stop": {"receipt": asdict(proof), "prior_state": row["state"]}}
            self._save_attempt(released)
        return released  # Worktree custody and quota estimates remain retained.
