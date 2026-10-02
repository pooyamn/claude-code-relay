"""Durable capacity waits/proposals joined to model admission, not a retry loop.

Protected pinned adapters must verify failure/negative/native-retry provenance.
No native call, error-text classifier, sleep, checkpoint invention or repair.
Fresh-input replacement is prepared; steering/continuation adapters remain gates.
"""
from dataclasses import asdict, dataclass

from .capacity_retry import RetryPolicy, cancel, new_state, request_due, schedule, validate_state
from .contracts import canonical_bytes, create, fingerprint, intent_payload
from .identity import Denied, exact, identifier, integer, strict_json
from .model_admission import ModelAdmission, SCHEMA as MODEL_SCHEMA
from .work_ownership import _deadline, _digest


SCHEMA = "ccrelay.capacity_journal.v1"


@dataclass(frozen=True)
class FailureReceipt:
    failure_id: str
    scope_digest: str
    source_digest: str
    evidence_id: str
    observed_ms: int
    classification: str
    outcome: str
    retry_after_ms: int
    native_retry_pending: bool
    cooldown_pool: str


def policy_value(raw):
    exact(raw, {"schema", "base_delay_ms", "max_delay_ms", "jitter_per_mille", "max_retries", "max_elapsed_ms"})
    if raw["schema"] != "ccrelay.capacity_retry_policy.v1":
        raise Denied("unknown retry policy; preserve state")
    return RetryPolicy(**{key: value for key, value in raw.items() if key != "schema"})


def load_job(ledger, job_id):
    metadata = ledger.connection.execute("SELECT schema,policy_digest FROM capacity_metadata").fetchall()
    row = ledger.connection.execute("SELECT original_intent_id,body,digest FROM capacity_jobs WHERE id=?", (identifier(job_id),)).fetchone()
    if row is None:
        raise Denied("unknown capacity job")
    job = strict_json(row[1])
    exact(job, {"schema", "id", "original_intent_id", "binding", "policy", "state"})
    policy = policy_value(job["policy"])
    validate_state(job["state"], policy)
    if metadata != [(SCHEMA, fingerprint(policy.body()))] or fingerprint(job) != row[2] or \
            (job["id"], job["original_intent_id"], job["schema"]) != (job_id, row[0], SCHEMA):
        raise Denied("capacity job/policy/index changed; preserve history")
    original = ledger.load(job["original_intent_id"])
    if original is None or original["context"].get("binding") != job["binding"] or \
            original["record"].fields["root_task_id"] != job["state"]["scope"]["root_task_id"]:
        raise Denied("capacity job no longer matches its original outbox/root binding")
    return job


def failure_row(ledger, failure_id):
    row = ledger.connection.execute("SELECT job_id,body,digest FROM capacity_failures WHERE id=?", (identifier(failure_id),)).fetchone()
    if row is None:
        raise Denied("capacity failure proof missing")
    body = strict_json(row[1])
    exact(body, {"job_id", "source_intent_id", "receipt"})
    if fingerprint(body) != row[2] or body["job_id"] != row[0] or body["receipt"]["failure_id"] != failure_id:
        raise Denied("capacity failure provenance/index changed")
    return body


def admission_gate(ledger, current, now, *, request=None):
    """Necessary current retry/cooldown check; never an execution authorization."""
    present = ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capacity_metadata'").fetchone()
    linked = current["context"].get("capacity_retry")
    if not present:
        if linked is not None:
            raise Denied("retry journal unavailable; replacement cannot execute")
        return 0
    metadata = ledger.connection.execute("SELECT schema,policy_digest FROM capacity_metadata").fetchall()
    if len(metadata) != 1 or metadata[0][0] != SCHEMA:
        raise Denied("unsupported shared capacity journal")
    _digest(metadata[0][1])
    if linked is not None:
        exact(linked, {"job_id", "source_intent_id", "failure_id", "retry_number"})
        job = load_job(ledger, linked["job_id"])
        state = job["state"]
        if state["status"] != "requested" or state["proposal"]["intent_id"] != current["record"].id or \
                state["retry_count"] != linked["retry_number"] or state["proposal"]["source_failure_id"] != linked["failure_id"] or \
                now >= min(state["root_deadline_ms"], state["first_failure_ms"] + policy_value(job["policy"]).max_elapsed_ms):
            raise Denied("retry cancelled, expired or no longer the exact requested proposal")
        proof = failure_row(ledger, linked["failure_id"])
        source = ledger.load(linked["source_intent_id"])
        if proof["job_id"] != job["id"] or proof["source_intent_id"] != linked["source_intent_id"] or \
                proof["receipt"]["outcome"] != "not_accepted" or proof["receipt"]["native_retry_pending"] is not False or \
                source is None or source["record"].fields["state"] != "failed" or \
                source["record"].fields["outcome_evidence_id"] != proof["receipt"]["evidence_id"] or job["binding"] != current["context"]["binding"]:
            raise Denied("replacement lacks current exact negative/no-native-retry evidence")
    params = current["record"].fields["parameters"] if request is None else request
    until = 0
    for pool, model, eligible, body, digest in ledger.connection.execute(
            "SELECT pool,model_id,eligible_ms,body,digest FROM capacity_cooldowns WHERE provider=? AND account_id=?", (params["provider"], params["account_id"])):
        data = strict_json(body)
        exact(data, {"provider", "account_id", "pool", "model_id", "eligible_ms", "failure_id"})
        if fingerprint(data) != digest or (data["provider"], data["account_id"], data["pool"], data["model_id"], data["eligible_ms"]) != \
                (params["provider"], params["account_id"], pool, model, eligible) or pool not in {"account", "model"}:
            raise Denied("shared capacity cooldown index changed")
        proof = failure_row(ledger, data["failure_id"])
        job = load_job(ledger, proof["job_id"])
        scope = job["state"]["scope"]
        if (scope["provider"], scope["account_id"]) != (data["provider"], data["account_id"]) or \
                proof["receipt"]["classification"] != "temporary_capacity" or proof["receipt"]["cooldown_pool"] != pool or \
                model != (scope["model_id"] if pool == "model" else ""):
            raise Denied("cooldown differs from verified account/model failure provenance")
        if pool == "account" or model == params["model_id"]:
            until = max(until, integer(eligible, 0))
    return until


class CapacityJournal:
    def __init__(self, admission, policy, *, verify_failure):
        if type(admission) is not ModelAdmission or type(policy) is not RetryPolicy or not callable(verify_failure):
            raise Denied("shared admission, explicit retry policy and protected pinned failure verifier required")
        self.admission, self.ledger, self.policy, self.verify_failure = admission, admission.ledger, policy, verify_failure

    def initialize(self, peer):
        roles = self.ledger.authority.policy.controllers.get(peer.uid, frozenset())
        if not roles:
            raise Denied("protected controller required for capacity journal")
        self.ledger._controller(peer, sorted(roles)[0])
        self.admission._check()
        with self.ledger._transaction():
            exists = self.ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capacity_metadata'").fetchone()
            if not exists:
                self.ledger.connection.execute("CREATE TABLE capacity_metadata (schema TEXT,policy_digest TEXT)")
                self.ledger.connection.execute("INSERT INTO capacity_metadata VALUES (?,?)", (SCHEMA, fingerprint(self.policy.body())))
                self.ledger.connection.execute("CREATE TABLE capacity_jobs (id TEXT PRIMARY KEY,original_intent_id TEXT UNIQUE NOT NULL,body BLOB,digest TEXT)")
                self.ledger.connection.execute("CREATE TABLE capacity_failures (id TEXT PRIMARY KEY,job_id TEXT NOT NULL,body BLOB,digest TEXT)")
                self.ledger.connection.execute("CREATE TABLE capacity_cooldowns (provider TEXT,account_id TEXT,pool TEXT,model_id TEXT,eligible_ms INTEGER,body BLOB,digest TEXT,PRIMARY KEY(provider,account_id,pool,model_id))")
            if self.ledger.connection.execute("SELECT schema,policy_digest FROM capacity_metadata").fetchall() != [(SCHEMA, fingerprint(self.policy.body()))]:
                raise Denied("changed capacity policy/component; reviewed migration required")
            for (job_id,) in self.ledger.connection.execute("SELECT id FROM capacity_jobs").fetchall():
                load_job(self.ledger, job_id)

    def _save(self, job):
        self.ledger.connection.execute("INSERT OR REPLACE INTO capacity_jobs VALUES (?,?,?,?)", (
            job["id"], job["original_intent_id"], canonical_bytes(job), fingerprint(job)))

    def _check(self):
        self.admission._check()
        if self.ledger.connection.execute("SELECT schema,policy_digest FROM capacity_metadata").fetchall() != [(SCHEMA, fingerprint(self.policy.body()))]:
            raise Denied("current pinned capacity policy required; preserve state for migration")

    def enroll(self, peer, intent_id):
        self._check()
        current = self.ledger.load(identifier(intent_id))
        if current is None or current["context"].get("schema") != MODEL_SCHEMA or current["record"].fields.get("action_kind") != "model_turn":
            raise Denied("an admitted model intent is required; steering/continuation cannot become fresh input")
        root = self.ledger.root(current["record"].fields["root_task_id"])
        self.ledger._controller(peer, root.fields["owner_role_id"])
        if current["context"].get("capacity_retry"):
            return load_job(self.ledger, current["context"]["capacity_retry"]["job_id"])
        original = current["record"]
        job_id = "capacity-job-" + fingerprint({"intent_id": original.id, "intent_digest": original.fields["intent_digest"]})[7:]
        with self.ledger._transaction():
            prior = self.ledger.connection.execute("SELECT id FROM capacity_jobs WHERE id=?", (job_id,)).fetchone()
            if prior:
                return load_job(self.ledger, job_id)
            attempt = next((row for row in self.admission._attempts() if row["intent_id"] == original.id), None)
            if attempt is None:
                raise Denied("capacity job requires a once-admitted original attempt")
            params = original.to_dict()["parameters"]
            scope = {"work_id": job_id, "root_task_id": root.id, "session_id": params["session_id"],
                     **{key: params[key] for key in ("provider", "account_id", "model_id", "native_session_id", "runtime_digest", "adapter_digest")},
                     "mode": "start", "expected_turn_id": None}
            state = new_state(scope, self.policy, now_ms=attempt["admitted_ms"], root_deadline_ms=_deadline(current["context"]["deadline"]))
            job = {"schema": SCHEMA, "id": job_id, "original_intent_id": original.id, "binding": current["context"]["binding"], "policy": self.policy.body(), "state": state}
            self._save(job)
        return job

    def _notice(self, job, phase):
        state = job["state"]
        notice_id = "capacity-report-" + fingerprint({"job": job["id"], "phase": phase, "retry_number": state["retry_count"]})[7:]
        if self.ledger.load(notice_id):
            return notice_id
        root = self.ledger.root(state["scope"]["root_task_id"])
        params = {"job_id": job["id"], "phase": phase, "reason": state["reason"], "retry_number": state["retry_count"],
                  "next_eligible_ms": state["next_eligible_ms"], "deadline_ms": state["root_deadline_ms"], "spent": dict(root.fields["usage"]), "destination": "protected_owner_issues",
                  "original_intent_id": job["original_intent_id"], "source_evidence_id": state["failures"][-1]["evidence_id"] if state["failures"] else None}
        fields = {"id": notice_id, "root_task_id": root.id, "requested_by_session_id": job["binding"]["session_id"], "action_kind": "passive_capacity_report", "parameters": params}
        action = create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                        attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
        self.ledger._enroll(action, {"schema": SCHEMA, "meaning": "pending_protected_report_not_sent"})
        return notice_id

    def record_failure(self, peer, job_id, source_intent_id, *, jitter_ms):
        self._check()
        job = load_job(self.ledger, job_id)
        root = self.ledger.root(job["state"]["scope"]["root_task_id"])
        self.ledger._controller(peer, root.fields["owner_role_id"])
        current = self.ledger.load(identifier(source_intent_id))
        allowed = job["state"]["proposal"]["intent_id"] if job["state"]["proposal"] else job["original_intent_id"]
        historical = any(failure_row(self.ledger, failure_id)["source_intent_id"] == source_intent_id for (failure_id,) in
                         self.ledger.connection.execute("SELECT id FROM capacity_failures WHERE job_id=?", (job_id,)))
        if current is None or source_intent_id != allowed and not historical or current["context"].get("binding") != job["binding"]:
            raise Denied("failure must belong to the exact current original/replacement intent")
        snapshot = {"job_id": job_id, "retry_scope": job["state"]["scope"], "binding": job["binding"], "source": current["record"].to_dict(),
                    "plan_digest": current["plan_digest"], "evidence": None if current["record"].fields["outcome_evidence_id"] is None else self.ledger._evidence(current["record"].fields["outcome_evidence_id"])}
        receipt = self.verify_failure(strict_json(canonical_bytes(snapshot)))
        if type(receipt) is not FailureReceipt or receipt.scope_digest != fingerprint(snapshot) or \
                receipt.classification not in {"temporary_capacity", "quota_exhausted", "authentication", "configuration", "unclassified"} or \
                receipt.outcome not in {"not_accepted", "unknown", "terminal_reconciled"} or type(receipt.native_retry_pending) is not bool or receipt.cooldown_pool not in {"account", "model"}:
            raise Denied("independent normalized failure/native-retry provenance required")
        identifier(receipt.failure_id)
        identifier(receipt.evidence_id)
        _digest(receipt.source_digest)
        integer(receipt.retry_after_ms, 0)
        if receipt.outcome == "not_accepted" and (current["record"].fields["state"] != "failed" or current["record"].fields["outcome_evidence_id"] != receipt.evidence_id):
            raise Denied("unknown/accepted delivery cannot be retried as rejected input")
        proof = {"job_id": job_id, "source_intent_id": source_intent_id, "receipt": asdict(receipt)}
        with self.ledger._transaction():
            if load_job(self.ledger, job_id) != job or self.ledger.load(source_intent_id) != current:
                raise Denied("retry job/source changed during failure verification")
            self.ledger._controller(peer, root.fields["owner_role_id"])
            now = self.ledger._clock()
            prior = self.ledger.connection.execute("SELECT body,digest FROM capacity_failures WHERE id=?", (receipt.failure_id,)).fetchone()
            if prior:
                if strict_json(prior[0]) != proof or fingerprint(proof) != prior[1]:
                    raise Denied("failure ID changed provenance/time")
                return job
            if not job["state"]["last_checked_ms"] <= integer(receipt.observed_ms, 0) <= now:
                raise Denied("failure time regressed or lies in the future")
            failure = {"schema": "ccrelay.capacity_failure.v1", "id": receipt.failure_id, "scope_digest": job["state"]["scope_digest"],
                       "classification": receipt.classification, "outcome": receipt.outcome, "evidence_id": receipt.evidence_id,
                       "retry_after_ms": receipt.retry_after_ms, "native_retry_pending": receipt.native_retry_pending,
                       "retry_intent_id": None if source_intent_id == job["original_intent_id"] else source_intent_id}
            updated = {**job, "state": schedule(job["state"], failure, self.policy, now_ms=receipt.observed_ms, jitter_ms=jitter_ms)}
            self.ledger.connection.execute("INSERT INTO capacity_failures VALUES (?,?,?,?)", (receipt.failure_id, job_id, canonical_bytes(proof), fingerprint(proof)))
            self._save(updated)
            if receipt.classification == "temporary_capacity":
                scope = job["state"]["scope"]
                model = scope["model_id"] if receipt.cooldown_pool == "model" else ""
                eligible = max(receipt.observed_ms + receipt.retry_after_ms, updated["state"]["next_eligible_ms"] or 0)
                old = self.ledger.connection.execute("SELECT eligible_ms,body,digest FROM capacity_cooldowns WHERE provider=? AND account_id=? AND pool=? AND model_id=?", (scope["provider"], scope["account_id"], receipt.cooldown_pool, model)).fetchone()
                if old:
                    retained = strict_json(old[1])
                    if fingerprint(retained) != old[2] or retained["eligible_ms"] != old[0]:
                        raise Denied("retained cooldown changed; do not overwrite corrupt pacing state")
                if old is None or eligible > old[0]:
                    cooldown = {"provider": scope["provider"], "account_id": scope["account_id"], "pool": receipt.cooldown_pool, "model_id": model, "eligible_ms": eligible, "failure_id": receipt.failure_id}
                    self.ledger.connection.execute("INSERT OR REPLACE INTO capacity_cooldowns VALUES (?,?,?,?,?,?,?)", (scope["provider"], scope["account_id"], receipt.cooldown_pool, model, eligible, canonical_bytes(cooldown), fingerprint(cooldown)))
            self._notice(updated, updated["state"]["status"])
            self.ledger.checkpoint("before_capacity_failure_commit")
        self.ledger.checkpoint("after_capacity_failure_commit")
        return updated

    def advance(self, peer, job_id):
        self._check()
        with self.ledger._transaction():
            job = load_job(self.ledger, job_id)
            scope = job["state"]["scope"]
            root = self.ledger.root(scope["root_task_id"])
            self.ledger._controller(peer, root.fields["owner_role_id"])
            now = self.ledger._clock()
            control = self.ledger.owner_control(root.id)
            if not control["known"] or control["desired_state"] != "running" or root.fields["state"] in {"held", "completed", "cancelled"}:
                return {"job": job, "proposal": None, "reason": "owner_or_root_held"}
            if self.admission._binding(peer, scope["session_id"]) != job["binding"]:
                raise Denied("retry native execution binding changed")
            if job["state"]["status"] == "requested" and now >= min(job["state"]["root_deadline_ms"], job["state"]["first_failure_ms"] + self.policy.max_elapsed_ms):
                state = {**job["state"], "status": "exhausted", "reason": "retry_budget_or_deadline", "last_checked_ms": now, "proposal": None}
                validate_state(state, self.policy)
                updated = {**job, "state": state}
                self._save(updated)
                current = self.ledger.load(job["state"]["proposal"]["intent_id"])
                if current and current["record"].fields["state"] == "stored":
                    self.ledger._update(current["record"], hold="capacity_retry_deadline")
                self._notice(updated, "exhausted")
                return {"job": updated, "proposal": None, "reason": "retry_budget_or_deadline"}
            if job["state"]["status"] != "waiting":
                return {"job": job, "proposal": None}
            state, proposal = request_due(job["state"], self.policy, now_ms=now)
            updated = {**job, "state": state}
            self._save(updated)
            if proposal:
                proof = failure_row(self.ledger, proposal["source_failure_id"])
                source = self.ledger.load(proof["source_intent_id"])
                params = source["record"].to_dict()["parameters"]
                params["id"] = proposal["intent_id"]
                fields = {"id": proposal["intent_id"], "root_task_id": root.id, "requested_by_session_id": scope["session_id"], "action_kind": "model_turn", "parameters": params}
                action = create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                                attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
                context = {**source["context"], "capacity_retry": {"job_id": job_id, "source_intent_id": proof["source_intent_id"], "failure_id": proposal["source_failure_id"], "retry_number": state["retry_count"]}}
                self.ledger._enroll(action, context)
            self._notice(updated, state["status"])
            self.ledger.checkpoint("before_capacity_proposal_commit")
        self.ledger.checkpoint("after_capacity_proposal_commit")
        return {"job": updated, "proposal": proposal, "meaning": "stored_proposal_not_execution"}

    def cancel(self, peer, job_id):
        self._check()
        with self.ledger._transaction():
            job = load_job(self.ledger, job_id)
            self.ledger._controller(peer, self.ledger.root(job["state"]["scope"]["root_task_id"]).fields["owner_role_id"])
            updated = {**job, "state": cancel(job["state"], self.policy, now_ms=self.ledger._clock())}
            self._save(updated)
            if job["state"]["proposal"]:
                current = self.ledger.load(job["state"]["proposal"]["intent_id"])
                if current and current["record"].fields["state"] == "stored":
                    self.ledger._update(current["record"], hold="capacity_retry_cancelled")
            self._notice(updated, "cancelled")
        return updated  # No interrupt, lease release or counter/deadline reset.

    def observe_acceptance(self, peer, job_id):
        """Report confirmed replacement input acceptance, not task completion."""
        self._check()
        with self.ledger._transaction():
            job = load_job(self.ledger, job_id)
            root = self.ledger.root(job["state"]["scope"]["root_task_id"])
            self.ledger._controller(peer, root.fields["owner_role_id"])
            proposal = job["state"]["proposal"]
            current = self.ledger.load(proposal["intent_id"]) if proposal else None
            if current is None or current["record"].fields["state"] != "confirmed" or current["record"].fields["receipt_id"] is None:
                raise Denied("exact confirmed replacement acceptance required")
            notice_id = self._notice(job, "recovered_input_accepted")
        return {"notice_id": notice_id, "meaning": "input_accepted_not_task_completed"}
