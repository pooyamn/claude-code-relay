"""Protected publication/review/merge intents joined to original work and outbox.

No GitHub request, token minting, build, native call or rebase is performed here.
Independent readers and queue enforcement are mandatory; fixtures do not prove
real CI, installation provenance, company grants or target UID isolation.
"""
from dataclasses import asdict, dataclass
import re

from .contracts import canonical_bytes, create, fingerprint, intent_payload
from .identity import Denied, exact, identifier, integer, strict_json
from .model_admission import ModelAdmission
from .native_sessions import NativeSessionRegistry
from .work_ownership import _deadline, _digest


SCHEMA = "ccrelay.publications.v1"
PERMISSIONS = {"branch": {"contents": "write"}, "pull_request": {"pull_requests": "write"},
               "review": {"statuses": "write"}, "merge": {"contents": "write"}}


def oid(value):
    if type(value) is not str or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value):
        raise Denied("exact Git object ID required")
    return value


class PublicationPolicy:
    def __init__(self, raw):
        exact(raw, {"schema", "scope", "publisher_roles", "reviewer_role", "merge_role", "max_pending_per_repo", "test_max_age_ms", "repositories"})
        if raw["schema"] != "ccrelay.publication_policy.v1" or raw["scope"] != "platform-owner-only" or \
                type(raw["publisher_roles"]) is not list or not raw["publisher_roles"] or type(raw["repositories"]) is not list or not raw["repositories"]:
            raise Denied("explicit single-owner publication policy required; company grants not enabled")
        self.body = strict_json(canonical_bytes(raw))
        self.publishers = tuple(identifier(role) for role in raw["publisher_roles"])
        self.reviewer, self.merger = identifier(raw["reviewer_role"]), identifier(raw["merge_role"])
        if len(set(self.publishers)) != len(self.publishers) or self.reviewer == self.merger or {self.reviewer, self.merger} & set(self.publishers):
            raise Denied("publisher, reviewer and merge authority must be separate")
        self.max_pending, self.test_max_age = integer(raw["max_pending_per_repo"]), integer(raw["test_max_age_ms"])
        if self.max_pending > 128:
            raise Denied("publication merge queue exceeds bound")
        self.repositories = {}
        identities = set()
        for repo in raw["repositories"]:
            exact(repo, {"id", "owner", "name", "repository_id", "app_id", "installation_id", "base_branch", "required_checks"})
            for key in ("id", "owner", "name", "base_branch"):
                identifier(repo[key])
            for key in ("repository_id", "app_id", "installation_id"):
                integer(repo[key])
            if repo["id"] in self.repositories or repo["repository_id"] in identities or type(repo["required_checks"]) is not list or \
                    not repo["required_checks"] or len(set(repo["required_checks"])) != len(repo["required_checks"]) or \
                    any(type(check) is not str or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", check) for check in repo["required_checks"]):
                raise Denied("unique pinned repository and required CI checks required")
            identities.add(repo["repository_id"])
            self.repositories[repo["id"]] = self.body["repositories"][len(self.repositories)]
        self.digest = fingerprint(self.body)


@dataclass(frozen=True)
class PublicationCheckpoint:
    scope_digest: str
    source_digest: str
    head_sha: str
    tree_sha: str
    artifact_digest: str
    coherent: bool
    leases_valid: bool


@dataclass(frozen=True)
class PublicationAuthority:
    scope_digest: str
    source_digest: str
    allowed: bool


@dataclass(frozen=True)
class AppScope:
    scope_digest: str
    source_digest: str
    app_id: int
    installation_id: int
    repository_ids: tuple
    permissions: dict
    expires_ms: int


@dataclass(frozen=True)
class PublicationRemote:
    scope_digest: str
    source_digest: str
    branch: str
    head_sha: str
    base_sha: str
    pull_number: int
    state: str
    merged_sha: object


@dataclass(frozen=True)
class BuildTest:
    scope_digest: str
    source_digest: str
    head_sha: str
    base_sha: str
    tested_tree_sha: str
    observed_ms: int
    passed: bool
    independent_isolated_runner: bool


@dataclass(frozen=True)
class QueueRules:
    scope_digest: str
    source_digest: str
    required_checks: tuple
    require_merge_queue: bool
    squash: bool
    no_bypass: bool
    authorized_pair_check: bool
    merge_group_ci: bool


@dataclass(frozen=True)
class MergeResult:
    scope_digest: str
    source_digest: str
    request_id: str
    head_sha: str
    base_sha: str
    state: str
    merged_sha: object


def metadata(ledger):
    rows = ledger.connection.execute("SELECT schema,policy,body FROM publication_metadata").fetchall()
    if len(rows) != 1 or rows[0][0] != SCHEMA or PublicationPolicy(strict_json(rows[0][2])).digest != rows[0][1]:
        raise Denied("unsupported publication schema/policy; preserve for reviewed migration")
    return rows[0][1]


class Publications:
    def __init__(self, admission, registry, policy, *, verify_checkpoint, verify_authority, verify_app, observe_remote, verify_tests, verify_queue, verify_result):
        if type(admission) is not ModelAdmission or type(registry) is not NativeSessionRegistry or type(policy) is not PublicationPolicy or \
                registry.authority is not admission.ledger.authority or registry.policy_digest != admission.ledger.policy_digest or \
                not all(callable(reader) for reader in (verify_checkpoint, verify_authority, verify_app, observe_remote, verify_tests, verify_queue, verify_result)):
            raise Denied("joined authority/admission/native mappings and protected publication readers required")
        self.admission, self.ledger, self.registry, self.policy = admission, admission.ledger, registry, policy
        self.verify_checkpoint, self.verify_authority, self.verify_app = verify_checkpoint, verify_authority, verify_app
        self.observe_remote, self.verify_tests, self.verify_queue = observe_remote, verify_tests, verify_queue
        self.verify_result = verify_result

    def initialize(self, peer):
        self.ledger._controller(peer, self.policy.publishers[0])
        self.admission._check()
        with self.ledger._transaction():
            if not self.ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE name='publication_metadata'").fetchone():
                self.ledger.connection.execute("CREATE TABLE publication_metadata(schema TEXT,policy TEXT,body BLOB)")
                self.ledger.connection.execute("INSERT INTO publication_metadata VALUES (?,?,?)", (SCHEMA, self.policy.digest, canonical_bytes(self.policy.body)))
                self.ledger.connection.execute("CREATE TABLE publications(id TEXT PRIMARY KEY,session_id TEXT,active INTEGER,body BLOB,digest TEXT)")
                self.ledger.connection.execute("CREATE UNIQUE INDEX one_session_publication ON publications(session_id) WHERE active=1")
                self.ledger.connection.execute("CREATE TABLE publication_history(id TEXT,revision INTEGER,body BLOB,digest TEXT,PRIMARY KEY(id,revision))")
                self.ledger.connection.execute("CREATE TABLE publication_sequence(session_id TEXT PRIMARY KEY,next_number INTEGER)")
                self.ledger.connection.execute("CREATE TABLE merge_requests(id TEXT PRIMARY KEY,repo_id TEXT,sequence INTEGER UNIQUE,body BLOB,digest TEXT)")
                self.ledger.connection.execute("CREATE TABLE merge_slots(repo_id TEXT PRIMARY KEY,request_id TEXT UNIQUE)")
                self.ledger.connection.execute("CREATE TABLE merge_results(request_id TEXT PRIMARY KEY,body BLOB,digest TEXT)")
                self.ledger.connection.execute("CREATE TABLE publication_grants(intent_id TEXT PRIMARY KEY,attempt_id TEXT UNIQUE,body BLOB,digest TEXT)")
            self._check()
            for (key,) in self.ledger.connection.execute("SELECT id FROM publications").fetchall():
                self.load(key)
            for (key,) in self.ledger.connection.execute("SELECT id FROM intents WHERE kind='external_action'").fetchall():
                current = self.ledger.load(key)
                if current["context"].get("schema") == SCHEMA:
                    self._grant_for(current)
            for (key,) in self.ledger.connection.execute("SELECT intent_id FROM publication_grants").fetchall():
                self.grant(key)

    def _check(self):
        self.admission._check()
        if metadata(self.ledger) != self.policy.digest or fingerprint(self.policy.body) != self.policy.digest:
            raise Denied("publication policy changed; preserve original authorization")

    def _actor(self, peer, method, roles):
        self._check()
        actor = self.ledger.authority.authorize(peer, {"schema": "ccrelay.broker_request.v1", "request_id": "publication-control", "method": method, "args": {}})
        if actor.role_id not in roles:
            raise Denied("authenticated publication role required")
        binding = self.ledger.authority.registry.session(actor.session_id)
        native = self.registry._row(actor.session_id)
        if native is None or native["binding"] != binding:
            raise Denied("exact existing native mapping required")
        self.ledger._runnable(self.ledger.root(actor.root_task_id))
        return binding, native["enrollment"]

    def load(self, key):
        self._check()
        row = self.ledger.connection.execute("SELECT session_id,active,body,digest FROM publications WHERE id=?", (identifier(key),)).fetchone()
        if row is None:
            return None
        body = strict_json(row[2])
        exact(body, {"schema", "id", "repo_id", "source", "native", "work_id", "fencing_token", "head_sha", "checkpoint", "branch", "created_ms", "phase", "revision", "actions", "review"})
        if body["schema"] != SCHEMA or body["id"] != key or body["source"]["session_id"] != row[0] or body["phase"] not in {"prepared", "open", "closed", "merged"} or \
                row[1] != int(body["phase"] not in {"closed", "merged"}) or fingerprint(body) != row[3]:
            raise Denied("publication index/material changed")
        integer(body["revision"], 0)
        oid(body["head_sha"])
        history = self.ledger.connection.execute("SELECT body,digest FROM publication_history WHERE id=? AND revision=?", (key, body["revision"])).fetchone()
        count, maximum = self.ledger.connection.execute("SELECT COUNT(*),MAX(revision) FROM publication_history WHERE id=?", (key,)).fetchone()
        if history != (row[2], row[3]) or count != body["revision"] + 1 or maximum != body["revision"]:
            raise Denied("publication history incomplete")
        return body

    def _save(self, body):
        raw, digest = canonical_bytes(body), fingerprint(body)
        if len(raw) > 65536:
            raise Denied("publication material exceeds bound; use sealed references")
        self.ledger.connection.execute("INSERT OR REPLACE INTO publications VALUES (?,?,?,?,?)", (body["id"], body["source"]["session_id"], int(body["phase"] not in {"closed", "merged"}), raw, digest))
        self.ledger.connection.execute("INSERT INTO publication_history VALUES (?,?,?,?)", (body["id"], body["revision"], raw, digest))

    def _scope(self, body):
        self._check()
        if body is None:
            raise Denied("unknown publication")
        binding = self.ledger.authority.registry.session(body["source"]["session_id"])
        role = self.ledger.authority.policy.roles.get(body["source"]["role_id"])
        if binding != body["source"] or role is None or not role.fields["enabled"]:
            raise Denied("publication source revoked or changed")
        root = self.ledger.root(body["source"]["root_task_id"])
        self.ledger._runnable(root)
        control = self.ledger.owner_control(root.id)
        if not control["known"] or control["desired_state"] != "running":
            raise Denied("owner control holds publication")
        return {"publication": body, "root": root.to_dict(), "owner_control": control, "repository": self.policy.repositories[body["repo_id"]],
                "work": self.ledger.work(body["work_id"]), "policy_digest": self.policy.digest}

    def _proof(self, reader, kind, scope):
        proof = reader(strict_json(canonical_bytes(scope)))
        if type(proof) is not kind or proof.scope_digest != fingerprint(scope):
            raise Denied("independent current publication evidence required")
        _digest(proof.source_digest)
        return proof

    def _authority(self, scope):
        proof = self._proof(self.verify_authority, PublicationAuthority, scope)
        if proof.allowed is not True:
            raise Denied("current protected screening/owner authorization required")
        return proof

    def _intent(self, body, step, key, *, extra=None, binding=None):
        repo = self.policy.repositories[body["repo_id"]]
        parameters = {"publication_id": body["id"], "step": step, "repository": repo, "branch": body["branch"], "head_sha": body["head_sha"],
                      "app_scope": {"app_id": repo["app_id"], "installation_id": repo["installation_id"], "repository_ids": [repo["repository_id"]],
                                    "permissions": {"metadata": "read", **PERMISSIONS[step]}}, **(extra or {})}
        fields = {"id": identifier(key), "root_task_id": body["source"]["root_task_id"], "requested_by_session_id": (binding or body["source"])["session_id"],
                  "action_kind": "publish", "parameters": parameters}
        action = create("external_action", **fields, state="stored", intent_digest=fingerprint(intent_payload("external_action", fields)),
                        attempt_id=None, receipt_id=None, outcome_evidence_id=None, authorization_id=None)
        self.ledger._enroll(action, {"schema": SCHEMA, "publication_id": body["id"], "binding": binding or body["source"]})
        return action.id

    def publish(self, peer, key, work_id, repo_id, head_sha, *, fencing_token):
        key, head_sha = identifier(key), oid(head_sha)
        source, native = self._actor(peer, "publish", self.policy.publishers)
        work = self.ledger.validate_fence(peer, identifier(work_id), fencing_token)
        if repo_id not in self.policy.repositories:
            raise Denied("repository is not installed in protected policy")
        prior = self.load(key)
        if prior:
            if (prior["source"], prior["work_id"], prior["repo_id"], prior["head_sha"], prior["fencing_token"]) != (source, work_id, repo_id, head_sha, fencing_token):
                raise Denied("publication intent cannot be retargeted")
            return {"stored_now": False, "publication": prior}
        scope = {"id": key, "binding": source, "native": native, "work": work, "repository": self.policy.repositories[repo_id], "head_sha": head_sha}
        proof = self._proof(self.verify_checkpoint, PublicationCheckpoint, scope)
        if proof.head_sha != head_sha or proof.coherent is not True or proof.leases_valid is not True:
            raise Denied("sealed coherent exact-commit checkpoint and current artifact leases required")
        oid(proof.tree_sha)
        _digest(proof.artifact_digest)
        with self.ledger._transaction():
            if self._actor(peer, "publish", self.policy.publishers) != (source, native) or self.ledger.validate_fence(peer, work_id, fencing_token) != work:
                raise Denied("publication source/custody changed during checkpoint verification")
            if self.ledger.connection.execute("SELECT 1 FROM publications WHERE session_id=? AND active=1", (source["session_id"],)).fetchone():
                raise Denied("one open publication per session; retain original until verified terminal")
            row = self.ledger.connection.execute("SELECT next_number FROM publication_sequence WHERE session_id=?", (source["session_id"],)).fetchone()
            number = row[0] if row else 1
            self.ledger.connection.execute("INSERT OR REPLACE INTO publication_sequence VALUES (?,?)", (source["session_id"], number + 1))
            body = {"schema": SCHEMA, "id": key, "repo_id": repo_id, "source": source, "native": native, "work_id": work_id, "fencing_token": fencing_token,
                    "head_sha": head_sha, "checkpoint": asdict(proof), "branch": f"pub/{source['session_id']}/{number}", "created_ms": self.ledger._clock(),
                    "phase": "prepared", "revision": 0, "actions": {}, "review": None}
            for step in ("branch", "pull_request"):
                body["actions"][step] = self._intent(body, step, "pub-" + fingerprint({"id": key, "step": step})[7:])
            self._save(body)
            self.ledger.checkpoint("before_publication_store_commit")
        self.ledger.checkpoint("after_publication_store_commit")
        return {"stored_now": True, "publication": body, "meaning": "stored_not_pushed_or_opened"}

    def _remote(self, scope):
        proof = self._proof(self.observe_remote, PublicationRemote, scope)
        body = scope["publication"]
        if (proof.branch, proof.head_sha) != (body["branch"], body["head_sha"]) or proof.state not in {"open", "closed", "merged"}:
            raise Denied("remote branch/head/publication changed")
        oid(proof.base_sha)
        integer(proof.pull_number)
        return proof

    @staticmethod
    def _evidence_body(authorization):
        # Typed receipts use immutable tuples; persistence contracts use JSON
        # lists. Convert only these declared receipt fields, not arbitrary input.
        return {name: {field: list(value) if field in {"repository_ids", "required_checks"} else value
                       for field, value in receipt.items()} for name, receipt in authorization.items()}

    def _plan(self, action, authorization):
        authorization = self._evidence_body(authorization)
        return {"schema": "ccrelay.delivery_plan.v1", "intent_id": action.id, "intent_digest": action.fields["intent_digest"], "adapter_id": "github-app-publication.v1",
                "authorization_id": "pub-gate-" + fingerprint(authorization)[7:], "parameters": action.to_dict()["parameters"],
                "target": action.to_dict()["parameters"]["app_scope"]}

    def _store_grant(self, record, plan, authorization):
        evidence = self._evidence_body(authorization)
        if plan["authorization_id"] != "pub-gate-" + fingerprint(evidence)[7:]:
            raise Denied("publication gate evidence disagrees with claimed plan")
        body = {"schema": "ccrelay.publication_grant.v1", "intent_id": record.id, "intent_digest": record.fields["intent_digest"],
                "attempt_id": record.fields["attempt_id"], "plan_digest": fingerprint(plan), "authorization_id": plan["authorization_id"], "evidence": evidence}
        raw = canonical_bytes(body)
        if len(raw) > 65536:
            raise Denied("publication gate evidence exceeds bound")
        # Called inside the outbox claim transaction: a grant cannot survive
        # without its exact attempt, nor can an attempt lose its gate witness.
        self.ledger.connection.execute("INSERT INTO publication_grants VALUES (?,?,?,?)", (record.id, record.fields["attempt_id"], raw, fingerprint(body)))

    def _grant_for(self, current):
        if current is None or current["context"].get("schema") != SCHEMA:
            raise Denied("known publication intent required")
        record = current["record"]
        row = self.ledger.connection.execute("SELECT attempt_id,body,digest FROM publication_grants WHERE intent_id=?", (record.id,)).fetchone()
        if record.fields["attempt_id"] is None:
            if row is not None:
                raise Denied("publication grant has no matching attempt")
            return None
        if row is None:
            raise Denied("publication attempt has no retained gate evidence")
        body = strict_json(row[1])
        exact(body, {"schema", "intent_id", "intent_digest", "attempt_id", "plan_digest", "authorization_id", "evidence"})
        if body["schema"] != "ccrelay.publication_grant.v1" or fingerprint(body) != row[2] or \
                (body["intent_id"], body["intent_digest"], body["attempt_id"], body["plan_digest"], body["authorization_id"]) != \
                (record.id, record.fields["intent_digest"], record.fields["attempt_id"], current["plan_digest"], record.fields["authorization_id"]) or \
                row[0] != body["attempt_id"] or current["plan"]["adapter_id"] != "github-app-publication.v1" or \
                body["authorization_id"] != "pub-gate-" + fingerprint(body["evidence"])[7:]:
            raise Denied("publication gate evidence/index/attempt changed")
        return body

    def grant(self, intent_id):
        """Historical evidence only; reading a witness never grants execution."""
        self._check()
        return self._grant_for(self.ledger.load(identifier(intent_id)))

    def _app(self, scope, action):
        checked = {**scope, "action": action.to_dict()}
        proof = self._proof(self.verify_app, AppScope, checked)
        expected = action.to_dict()["parameters"]["app_scope"]
        if (proof.app_id, proof.installation_id, list(proof.repository_ids), proof.permissions) != \
                (expected["app_id"], expected["installation_id"], expected["repository_ids"], expected["permissions"]):
            raise Denied("exact installation, single repository and minimal permissions required")
        integer(proof.expires_ms)
        return proof

    def claim_publish(self, peer, key, step, attempt_id):
        body = self.load(key)
        if body is None or step not in {"branch", "pull_request", "review"} or step not in body["actions"]:
            raise Denied("known publication action required")
        self.ledger._controller(peer, body["source"]["role_id"])
        current = self.ledger.load(body["actions"][step])
        action = current["record"]
        if action.fields["attempt_id"] is not None:
            self._grant_for(current)
            return self.ledger.claim(action.id, attempt_id, current["plan"], expected_revision=0)
        scope = self._scope(body)
        if step in {"branch", "pull_request"} and (scope["work"]["binding"] != body["source"] or scope["work"]["fencing_token"] != body["fencing_token"] or scope["work"]["state"] != "owned"):
            raise Denied("original publication writer/resource custody is no longer current")
        if step == "review" and self.ledger.authority.registry.session(body["review"]["binding"]["session_id"]) != body["review"]["binding"]:
            raise Denied("reviewer authority revoked before status dispatch")
        checkpoint = self._proof(self.verify_checkpoint, PublicationCheckpoint, scope)
        if any(getattr(checkpoint, field) != value for field, value in body["checkpoint"].items() if field != "scope_digest"):
            raise Denied("sealed publication checkpoint/leases changed before dispatch")
        if step == "pull_request" and self.ledger.load(body["actions"]["branch"])["record"].fields["state"] != "confirmed":
            raise Denied("confirmed exact branch publication required before opening PR")
        authority = self._authority(scope)
        app = self._app(scope, action)
        authorization = {"scope": scope, "checkpoint": asdict(checkpoint), "authority": asdict(authority), "app": asdict(app)}
        def commit_hook(record, plan):
            if self.load(key) != body or self._proof(self.verify_checkpoint, PublicationCheckpoint, scope) != checkpoint or \
                    self._authority(scope) != authority or self._app(scope, action) != app or self._authority(scope) != authority or self._scope(body) != scope or \
                    step == "review" and self.ledger.authority.registry.session(body["review"]["binding"]["session_id"]) != body["review"]["binding"] or app.expires_ms <= self.ledger._clock():
                raise Denied("publication material/authority changed before dispatch")
            self._store_grant(record, plan, authorization)
            self.ledger.checkpoint("before_publication_" + step + "_commit")
        result = self.ledger.claim(action.id, identifier(attempt_id), self._plan(action, authorization), expected_revision=0, commit_hook=commit_hook)
        self.ledger.checkpoint("after_publication_" + step + "_commit")
        return result

    def sync_open(self, peer, key):
        body = self.load(key)
        if body is None:
            raise Denied("unknown publication")
        self.ledger._controller(peer, body["source"]["role_id"])
        scope = self._scope(body)
        remote = self._remote(scope)
        if any(self.ledger.load(body["actions"][step])["record"].fields["state"] != "confirmed" for step in ("branch", "pull_request")):
            raise Denied("independently confirmed branch and PR outcomes required")
        if remote.state not in {"open", "closed"}:
            raise Denied("merge completion needs separate accepted attempt evidence")
        if body["phase"] in {"closed", "merged"} and body["phase"] != remote.state:
            raise Denied("terminal publication cannot reopen; use a fresh reviewed publication")
        with self.ledger._transaction():
            if self._scope(body) != scope or self.load(key) != body:
                raise Denied("publication changed during remote observation")
            if body["phase"] != remote.state:
                self._save({**body, "phase": remote.state, "revision": body["revision"] + 1})
        return self.load(key)

    def review(self, peer, key, verdict_id, *, head_sha, verdict):
        reviewer, native = self._actor(peer, "review_publication", (self.policy.reviewer,))
        body = self.load(key)
        scope = self._scope(body)
        remote = self._remote(scope)
        if body["phase"] != "open" or remote.state != "open" or oid(head_sha) != body["head_sha"] or verdict not in {"approve", "reject"} or \
                native["provider"] == body["native"]["provider"] or reviewer["session_id"] == body["source"]["session_id"]:
            raise Denied("different-tool authenticated reviewer for exact open publication required")
        review = {"id": identifier(verdict_id), "head_sha": head_sha, "verdict": verdict, "binding": reviewer, "native": native}
        if body["review"] and body["review"]["id"] == verdict_id:
            if body["review"] != review:
                raise Denied("review verdict identity cannot change its meaning")
            return body["review"]
        with self.ledger._transaction():
            if self.load(key) != body or self._scope(body) != scope or self._actor(peer, "review_publication", (self.policy.reviewer,)) != (reviewer, native):
                raise Denied("review authority/material changed")
            actions = dict(body["actions"])
            actions["review"] = self._intent(body, "review", "review-" + fingerprint({"publication": key, "review": review})[7:],
                                             extra={"verdict": verdict, "review_context": "ccrelay/review"}, binding=reviewer)
            self._save({**body, "review": review, "actions": actions, "revision": body["revision"] + 1})
        return review

    def request_merge(self, peer, key, publication_id, *, head_sha, base_sha):
        merger, native = self._actor(peer, "request_merge", (self.policy.merger,))
        body = self.load(publication_id)
        scope = self._scope(body)
        remote = self._remote(scope)
        if body["phase"] != "open" or remote.state != "open" or (oid(head_sha), oid(base_sha)) != (body["head_sha"], remote.base_sha):
            raise Denied("exact open head and current merge target required")
        request = {"id": identifier(key), "publication_id": publication_id, "repo_id": body["repo_id"], "binding": merger,
                   "head_sha": head_sha, "base_sha": base_sha, "pull_number": remote.pull_number, "review": body["review"]}
        with self.ledger._transaction():
            prior = self.merge_request(key)
            if prior:
                if {field: prior[field] for field in request} != request:
                    raise Denied("merge request cannot change its actor/head/base/review")
                return prior
            if self._scope(body) != scope or self._actor(peer, "request_merge", (self.policy.merger,)) != (merger, native):
                raise Denied("merge request authority changed")
            pending = len(self._pending(body["repo_id"]))
            if pending >= self.policy.max_pending:
                raise Denied("bounded merge queue full; original publication retained")
            sequence = self.ledger.connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM merge_requests").fetchone()[0]
            action_id = self._intent(body, "merge", "merge-" + fingerprint(request)[7:], binding=merger,
                                     extra={"pull_number": remote.pull_number, "expected_base_sha": base_sha, "merge_action": "merge_queue", "bypass_rules": False})
            request.update(sequence=sequence, action_id=action_id)
            self.ledger.connection.execute("INSERT INTO merge_requests VALUES (?,?,?,?,?)", (key, body["repo_id"], sequence, canonical_bytes(request), fingerprint(request)))
            self.ledger.checkpoint("before_merge_request_commit")
        self.ledger.checkpoint("after_merge_request_commit")
        return request

    def merge_request(self, key):
        self._check()
        row = self.ledger.connection.execute("SELECT repo_id,sequence,body,digest FROM merge_requests WHERE id=?", (identifier(key),)).fetchone()
        if row is None:
            return None
        body = strict_json(row[2])
        if (body["id"], body["repo_id"], body["sequence"], fingerprint(body)) != (key, row[0], row[1], row[3]):
            raise Denied("merge request index/material changed")
        return body

    def _pending(self, repo_id):
        pending = []
        for (key,) in self.ledger.connection.execute("SELECT id FROM merge_requests WHERE repo_id=? ORDER BY sequence", (repo_id,)).fetchall():
            request = self.merge_request(key)
            current = self.ledger.load(request["action_id"])
            if current["record"].fields["state"] != "failed" and current["hold_reason"] is None and not \
                    self.ledger.connection.execute("SELECT 1 FROM merge_results WHERE request_id=?", (key,)).fetchone():
                pending.append(request)
        return pending

    def _principals(self, body, request):
        for binding, role in ((body["review"]["binding"], self.policy.reviewer), (request["binding"], self.policy.merger)):
            current = self.ledger.authority.registry.session(binding["session_id"])
            role_record = self.ledger.authority.policy.roles.get(role)
            if current != binding or binding["role_id"] != role or role_record is None or not role_record.fields["enabled"]:
                raise Denied("reviewer or CTO authority revoked/changed")

    def claim_merge(self, peer, key, attempt_id):
        request = self.merge_request(key)
        if request is None:
            raise Denied("unknown merge request")
        body = self.load(request["publication_id"])
        self.ledger._controller(peer, body["source"]["role_id"])
        current = self.ledger.load(request["action_id"])
        action = current["record"]
        if action.fields["attempt_id"] is not None:
            self._grant_for(current)
            return self.ledger.claim(action.id, attempt_id, current["plan"], expected_revision=0)
        scope = {**self._scope(body), "merge_request": request}
        remote = self._remote(scope)
        review = body["review"]
        if body["phase"] != "open" or remote.state != "open" or (remote.head_sha, remote.base_sha, remote.pull_number) != \
                (request["head_sha"], request["base_sha"], request["pull_number"]) or review != request["review"] or not review or review["verdict"] != "approve" or \
                self.ledger.authority.registry.session(review["binding"]["session_id"]) != review["binding"] or \
                self.ledger.authority.registry.session(request["binding"]["session_id"]) != request["binding"] or \
                self.ledger.load(body["actions"]["review"])["record"].fields["state"] != "confirmed":
            raise Denied("current authenticated reviewer/CTO, review status and unchanged head/base required")
        authority = self._authority(scope)
        app = self._app(scope, action)
        tests = self._proof(self.verify_tests, BuildTest, scope)
        rules = self._proof(self.verify_queue, QueueRules, scope)
        if (tests.head_sha, tests.base_sha) != (request["head_sha"], request["base_sha"]) or tests.passed is not True or tests.independent_isolated_runner is not True or \
                rules.required_checks != tuple(scope["repository"]["required_checks"]) or any(value is not True for value in
                    (rules.require_merge_queue, rules.squash, rules.no_bypass, rules.authorized_pair_check, rules.merge_group_ci)):
            raise Denied("independent current-target build/test and enforced protected merge-group checks required")
        oid(tests.tested_tree_sha)
        integer(tests.observed_ms, 0)
        authorization = {"scope": scope, "remote": asdict(remote), "authority": asdict(authority), "app": asdict(app), "tests": asdict(tests), "rules": asdict(rules)}
        def commit_hook(record, plan):
            if self.ledger.connection.execute("SELECT 1 FROM merge_slots WHERE repo_id=?", (body["repo_id"],)).fetchone():
                raise Denied("repository merge already active or unknown; retain lease until independent terminal evidence")
            pending = self._pending(body["repo_id"])
            if not pending or pending[0]["id"] != key:
                raise Denied("earlier repository merge request must settle or be explicitly cancelled")
            if self.load(body["id"]) != body or self.merge_request(key) != request or self._authority(scope) != authority or \
                    {**self._scope(body), "merge_request": request} != scope or self._remote(scope) != remote or \
                    self._proof(self.verify_tests, BuildTest, scope) != tests or self._proof(self.verify_queue, QueueRules, scope) != rules or self._app(scope, action) != app or \
                    self._remote(scope) != remote or self._authority(scope) != authority or \
                    {**self._scope(body), "merge_request": request} != scope:
                raise Denied("merge authority, target, tests or enforcement changed before dispatch")
            self._principals(body, request)
            now = self.ledger._clock()
            if not 0 <= now - tests.observed_ms <= self.policy.test_max_age or app.expires_ms <= now:
                raise Denied("merge test or scoped installation evidence expired")
            self.ledger.connection.execute("INSERT INTO merge_slots VALUES (?,?)", (body["repo_id"], key))
            self._store_grant(record, plan, authorization)
            self.ledger.checkpoint("before_publication_merge_commit")
        result = self.ledger.claim(action.id, identifier(attempt_id), self._plan(action, authorization), expected_revision=0, commit_hook=commit_hook)
        self.ledger.checkpoint("after_publication_merge_commit")
        return result

    def settle_merge(self, peer, key):
        request = self.merge_request(key)
        if request is None:
            raise Denied("unknown merge request")
        body = self.load(request["publication_id"])
        self.ledger._controller(peer, body["source"]["role_id"])
        row = self.ledger.connection.execute("SELECT body,digest FROM merge_results WHERE request_id=?", (key,)).fetchone()
        if row:
            result = strict_json(row[0])
            if fingerprint(result) != row[1]:
                raise Denied("merge result changed")
            return {"settled_now": False, "result": result}
        current = self.ledger.load(request["action_id"])
        if current["record"].fields["state"] not in {"confirmed", "failed"}:
            raise Denied("unknown/unconfirmed merge attempt retains repository lease")
        self._grant_for(current)
        scope = {"publication": body, "merge_request": request, "action": {**current, "record": current["record"].to_dict()}, "repository": self.policy.repositories[body["repo_id"]]}
        proof = self._proof(self.verify_result, MergeResult, scope)
        if (proof.request_id, proof.head_sha, proof.base_sha) != (key, request["head_sha"], request["base_sha"]) or proof.state not in {"enqueued", "merged", "rejected"}:
            raise Denied("independent exact merge attempt/group/head/base result required")
        if proof.state == "enqueued":
            return {"settled_now": False, "meaning": "queue_acceptance_is_not_merge_completion"}
        if proof.state == "merged":
            oid(proof.merged_sha)
            if current["record"].fields["state"] != "confirmed":
                raise Denied("rejected enqueue cannot establish a completed merge")
        elif proof.merged_sha is not None:
            raise Denied("rejected merge has no merge commit")
        with self.ledger._transaction():
            if self.load(body["id"]) != body or self.ledger.load(request["action_id"]) != current or \
                    self._proof(self.verify_result, MergeResult, scope) != proof or \
                    self.ledger.connection.execute("SELECT request_id FROM merge_slots WHERE repo_id=?", (body["repo_id"],)).fetchall() != [(key,)]:
                raise Denied("merge result/material/lease changed during reconciliation")
            encoded = asdict(proof)
            self.ledger.connection.execute("INSERT INTO merge_results VALUES (?,?,?)", (key, canonical_bytes(encoded), fingerprint(encoded)))
            self.ledger.connection.execute("DELETE FROM merge_slots WHERE repo_id=? AND request_id=?", (body["repo_id"], key))
            if proof.state == "merged":
                self._save({**body, "phase": "merged", "revision": body["revision"] + 1})
            self.ledger.checkpoint("before_publication_settle_commit")
        self.ledger.checkpoint("after_publication_settle_commit")
        return {"settled_now": True, "result": encoded, "meaning": "no_rebase_or_followup_execution_grant"}

    def cancel_merge(self, peer, key):
        binding, native = self._actor(peer, "request_merge", (self.policy.merger,))
        request = self.merge_request(key)
        if request is None or request["binding"] != binding:
            raise Denied("original authenticated CTO request required")
        current = self.ledger.load(request["action_id"])
        if current["record"].fields["attempt_id"] is not None:
            raise Denied("attempted/unknown merge cannot be cancelled into a new execution")
        self.ledger.hold(request["action_id"], "merge_request_cancelled")
        return {"cancelled": True, "meaning": "unattempted_intent_held_no_slot_or_history_reset"}
