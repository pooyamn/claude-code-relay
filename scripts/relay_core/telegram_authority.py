"""Protected exact-source delivery grants, separate from owner action approval.

No worker RPC or caller-selected authority. A trusted controller must first
verify native/source and human/company/root/route provenance. That current check
is mandatory again at dispatch. Mac fixtures cannot prove WSL UID/IPC isolation.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, Peer, exact, identifier, integer, protected_path, strict_json, validate_binding
from .outbox import fsync_directory


@dataclass(frozen=True)
class DispatchRequest:
    policy_digest: str
    bundle_id: str
    bundle_digest: str
    intent_id: str
    intent_digest: str
    position: int
    operation_digest: str

    @classmethod
    def for_item(cls, policy, item):
        record, body = item["current"]["record"], item["bundle"]
        return cls(policy.digest, body["id"], fingerprint(body), record.id,
                   record.fields["intent_digest"], item["position"], fingerprint(item["operation"]))


@dataclass(frozen=True)
class DispatchPermit:
    request: DispatchRequest
    grant_id: str
    grant_revision: int
    expires_ms: int

    @property
    def authorization_id(self):
        return "tg-permit-" + fingerprint({"grant": self.grant_id, "revision": self.grant_revision,
                                           "expires_ms": self.expires_ms, "request": self.request.__dict__})[7:]

    def validate(self, request, now):
        if type(self.request) is not DispatchRequest or self.request != request:
            raise Denied("source permission does not bind this exact operation")
        identifier(self.grant_id)
        integer(self.grant_revision)
        integer(self.expires_ms)
        if self.expires_ms <= integer(now, 0):
            raise Denied("source permission expired")
        return self


class SourceGrants:
    """Private controller-issued manifest approvals with durable revocation.

    `current_check(body, binding)` must consult protected current native/root/
    route and human/company grants; JSON attribution or an old cached boolean
    cannot supply it. BindingReadClient supplies fresh broker registration without
    sharing its DB; actual split-UID IPC and native/context remain activation gates.
    Already attested output can outlive its producer process; revocation and
    changed execution bindings still fence it. This never authorizes an action.
    """
    def __init__(self, directory, *, ledger, authority, current_check):
        if not callable(current_check):
            raise Denied("protected current source/context checker required")
        self.ledger, self.authority, self.current_check = ledger, authority, current_check
        self.uid = ledger.owner_uid
        if os.geteuid() != self.uid:
            raise Denied("source grants require the protected outbound UID")
        self.folder = protected_path(directory, owners={0, self.uid}, directory=True, private=True)
        if self.folder.lstat().st_uid != self.uid or self.folder == ledger.folder:
            raise Denied("distinct private source grant directory with exact owner required")
        self.path = self.folder / "source-grants.sqlite"
        new = not self.path.exists() and not self.path.is_symlink()
        if new:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        protected_path(self.path, owners={0, self.uid}, private=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        try:
            if new:
                self.db.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE metadata (schema TEXT, outbound_policy TEXT, broker_policy TEXT);
                    CREATE TABLE grants (bundle_id TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, body BLOB NOT NULL, digest TEXT NOT NULL);
                    CREATE TABLE grant_events (bundle_id TEXT NOT NULL, revision INTEGER NOT NULL, body BLOB NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(bundle_id,revision));
                """)
                self.db.execute("INSERT INTO metadata VALUES (?,?,?)", (
                    "ccrelay.telegram_source_grants.v1", ledger.policy.digest, authority.policy.digest))
                self.db.execute("COMMIT")
            if self.db.execute("SELECT * FROM metadata").fetchall() != [(
                    "ccrelay.telegram_source_grants.v1", ledger.policy.digest, authority.policy.digest)]:
                raise Denied("unknown source grant schema/policy; preserve for migration")
            self.db.execute("SELECT bundle_id,revision,body,digest FROM grant_events LIMIT 0")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=WAL")
            if new:
                fsync_directory(self.folder)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def grant(self, bundle_id):
        row = self.db.execute("SELECT id,body,digest FROM grants WHERE bundle_id=?", (identifier(bundle_id),)).fetchone()
        if row is None:
            return None
        value = strict_json(row[1])
        exact(value, {"schema", "id", "bundle_id", "bundle_digest", "binding", "binding_digest",
                      "outbound_policy", "broker_policy", "issuer_uid", "expires_ms", "revision", "revoked"})
        validate_binding(value["binding"])
        if (value["id"], fingerprint(value)) != (row[0], row[2]) or value["bundle_id"] != bundle_id \
                or value["schema"] != "ccrelay.telegram_source_grant.v1" \
                or value["binding_digest"] != fingerprint(value["binding"]) \
                or (value["outbound_policy"], value["broker_policy"]) != (self.ledger.policy.digest, self.authority.policy.digest) \
                or type(value["revoked"]) is not bool:
            raise Denied("source grant binding/index changed")
        identifier(value["id"])
        integer(value["issuer_uid"], 0)
        integer(value["expires_ms"])
        integer(value["revision"])
        event = self.db.execute("SELECT body,digest FROM grant_events WHERE bundle_id=? AND revision=?", (bundle_id, value["revision"])).fetchone()
        count, maximum = self.db.execute("SELECT COUNT(*),MAX(revision) FROM grant_events WHERE bundle_id=?", (bundle_id,)).fetchone()
        if event != (row[1], row[2]) or (count, maximum) != (value["revision"], value["revision"]):
            raise Denied("source grant revision/history changed")
        return value

    def _controller(self, peer, role_id):
        if type(peer) is not Peer or role_id not in self.authority.policy.controllers.get(peer.uid, frozenset()):
            raise Denied("kernel-authenticated protected controller required")

    def _binding(self, body):
        binding = self.authority.registry.session(body["session_id"])
        role = None if binding is None else self.authority.policy.roles.get(binding["role_id"])
        if binding is None or binding["revoked"] or binding["root_task_id"] != body["root_task_id"] \
                or binding["policy_digest"] != self.authority.policy.digest or role is None or not role.fields["enabled"]:
            raise Denied("source session/root is not a current registered role binding")
        return validate_binding(binding)

    def issue(self, peer, body, *, expires_ms):
        """Protected driver only after provenance checks; no worker issuance RPC."""
        self.ledger.validate_bundle(body)
        binding = self._binding(body)
        self._controller(peer, binding["role_id"])
        if integer(expires_ms) <= self.ledger.now() or self.current_check(body, binding) is not True:
            raise Denied("source/context grant is stale or not permitted")
        value = {"schema": "ccrelay.telegram_source_grant.v1", "id": "tg-source-" + fingerprint({
                    "bundle": body["id"], "digest": fingerprint(body), "binding": fingerprint(binding),
                    "outbound": self.ledger.policy.digest, "broker": self.authority.policy.digest})[7:],
                 "bundle_id": body["id"], "bundle_digest": fingerprint(body), "binding": binding,
                 "binding_digest": fingerprint(binding), "outbound_policy": self.ledger.policy.digest,
                 "broker_policy": self.authority.policy.digest, "issuer_uid": peer.uid,
                 "expires_ms": expires_ms, "revision": 1, "revoked": False}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.grant(body["id"])
            if old is not None:
                if old != value:
                    raise Denied("source grant cannot be replaced, unrevoked or extended implicitly")
            else:
                self.db.execute("INSERT INTO grants VALUES (?,?,?,?)", (body["id"], value["id"], canonical_bytes(value), fingerprint(value)))
                self._event(value)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return value["id"]

    def revoke(self, peer, bundle_id):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            value = self.grant(bundle_id)
            if value is None:
                raise Denied("unknown source grant")
            self._controller(peer, value["binding"]["role_id"])
            if not value["revoked"]:
                value.update(revoked=True, revision=value["revision"] + 1)
                self.db.execute("UPDATE grants SET body=?,digest=? WHERE bundle_id=?", (canonical_bytes(value), fingerprint(value), bundle_id))
                self._event(value)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _event(self, value):
        self.db.execute("INSERT INTO grant_events VALUES (?,?,?,?)", (
            value["bundle_id"], value["revision"], canonical_bytes(value), fingerprint(value)))

    def renew(self, peer, body, *, expires_ms):
        """Explicit controller reauthorization; retains history and old attempts."""
        self.ledger.validate_bundle(body)
        binding = self._binding(body)
        self._controller(peer, binding["role_id"])
        if integer(expires_ms) <= self.ledger.now() or self.current_check(body, binding) is not True:
            raise Denied("current source/context permission required for renewal")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            value = self.grant(body["id"])
            if value is None or value["bundle_digest"] != fingerprint(body) or value["binding_digest"] != fingerprint(binding) \
                    or fingerprint(self._binding(body)) != fingerprint(binding):
                raise Denied("renewal cannot change source manifest, route or execution")
            value.update(revoked=False, expires_ms=expires_ms, issuer_uid=peer.uid, revision=value["revision"] + 1)
            self.db.execute("UPDATE grants SET body=?,digest=? WHERE bundle_id=?", (canonical_bytes(value), fingerprint(value), body["id"]))
            self._event(value)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _current(self, body):
        value = self.grant(body["id"])
        binding = self._binding(body)
        if value is None or value["revoked"] or value["expires_ms"] <= self.ledger.now() \
                or value["bundle_digest"] != fingerprint(body) or value["binding_digest"] != fingerprint(binding) \
                or self.current_check(body, binding) is not True \
                or self.grant(body["id"]) != value or fingerprint(self._binding(body)) != fingerprint(binding) \
                or value["expires_ms"] <= self.ledger.now():
            raise Denied("current exact-source/context permission required")
        return value

    def enrollment_allowed(self, body):
        self.ledger.validate_bundle(body)
        self._current(body)
        return True

    def authorize(self, request):
        if type(request) is not DispatchRequest or request.policy_digest != self.ledger.policy.digest:
            raise Denied("protected exact dispatch request required")
        body = self.ledger.bundle(request.bundle_id)["body"]
        items = self.ledger.items(request.bundle_id)
        if not 0 <= request.position < len(items):
            raise Denied("dispatch position outside immutable manifest")
        item = {**items[request.position], "bundle": body}
        if DispatchRequest.for_item(self.ledger.policy, item) != request:
            raise Denied("dispatch differs from private intent/manifest")
        parent = self.ledger.repair_parent(body["id"])
        # A recipe-bound child inherits only the exact original manifest grant,
        # never a grant based on its new ID or model-supplied parent attribution.
        original = body if parent is None else self.ledger.bundle(parent["original_bundle_id"])["body"]
        value = self._current(original)
        return DispatchPermit(request, value["id"], value["revision"], value["expires_ms"])

    def snapshot(self, destination):
        destination = Path(destination)
        protected_path(destination.parent, owners={0, self.uid}, directory=True, private=True)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        target = sqlite3.connect(destination)
        try:
            self.db.backup(target)
        finally:
            target.close()
        fd = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_directory(destination.parent)
