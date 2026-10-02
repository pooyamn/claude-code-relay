"""Fresh, component-only broker binding reads across protected UIDs.

This reads registered identity, not native readiness, company membership,
task admission or source/action approval. Never share the broker's private DB
with the outbound UID to supply SourceGrants.authority.registry.session.
"""
from pathlib import Path
from types import MappingProxyType
import os
import uuid

from .broker_wire import client_request
from .contracts import fingerprint
from .identity import Denied, Peer, exact, identifier, integer, protected_path, strict_json, validate_binding


REQUEST_SCHEMA = "ccrelay.binding_read_request.v1"
RESULT_SCHEMA = "ccrelay.binding_read_result.v1"


class BindingReadPolicy:
    def __init__(self, raw, broker_policy):
        exact(raw, {"schema", "enabled", "broker_policy_digest", "readers"})
        if raw["schema"] != "ccrelay.binding_read_policy.v1" or type(raw["enabled"]) is not bool or \
                raw["broker_policy_digest"] != broker_policy.digest or type(raw["readers"]) is not list or not raw["readers"]:
            raise Denied("unsupported, empty or mismatched binding-read policy")
        workers = {role.fields["uid"] for role in broker_policy.roles.values()}
        readers = {}
        for item in raw["readers"]:
            exact(item, {"uid", "roles"})
            uid, roles = integer(item["uid"], 0), item["roles"]
            if uid in workers or uid == broker_policy.broker_uid or uid in readers or \
                    type(roles) is not list or not roles or any(type(role) is not str for role in roles) or \
                    len(set(roles)) != len(roles) or not set(roles).issubset(broker_policy.roles):
                raise Denied("binding readers must be explicit non-worker components with role ceilings")
            readers[uid] = frozenset(roles)
        self.broker_policy, self.enabled = broker_policy, raw["enabled"]
        self.readers, self.digest = MappingProxyType(readers), fingerprint(raw)

    @classmethod
    def load(cls, path, broker_policy):
        protected_path(path, owners={0})
        return cls(strict_json(Path(path).read_bytes()), broker_policy)

    def roles_for(self, uid):
        if not self.enabled or type(uid) is not int or uid not in self.readers:
            raise Denied("current protected binding-reader permission required")
        return self.readers[uid]

    def binding(self, value, session_id, roles):
        if value is None:
            return None
        validate_binding(value)
        role = self.broker_policy.roles.get(value["role_id"])
        if value["session_id"] != session_id or value["role_id"] not in roles or role is None or \
                value["uid"] != role.fields["uid"] or value["policy_digest"] != self.broker_policy.digest or \
                value["role_id"] not in self.broker_policy.controllers.get(value["launcher_uid"], frozenset()):
            raise Denied("binding does not match the current broker policy or reader ceiling")
        return value


class BrokerBindingReads:
    """Read-only handler; peer comes only from the broker's kernel wire layer."""
    def __init__(self, authority, policy, *, policy_path=None):
        if authority.policy.digest != policy.broker_policy.digest:
            raise Denied("binding reader and broker authority policy differ")
        self.authority, self.policy, self.policy_path = authority, policy, policy_path

    def current_policy(self):
        # The actual broker supplies the root-owned artifact path. Pure fixtures
        # may use an explicit installed policy object; there is no worker field
        # selecting this source or permission fallback after a failed load.
        return self.policy if self.policy_path is None else BindingReadPolicy.load(self.policy_path, self.authority.policy)

    def dispatch(self, peer, request):
        if type(peer) is not Peer:
            raise Denied("kernel-authenticated component peer required")
        policy = self.current_policy()
        roles = policy.roles_for(peer.uid)  # Before any private registry lookup.
        exact(request, {"schema", "request_id", "method", "args"})
        if request["schema"] != REQUEST_SCHEMA or request["method"] != "read_session":
            raise Denied("only exact binding reads are enabled on this channel")
        identifier(request["request_id"])
        args = request["args"]
        exact(args, {"session_id", "broker_policy_digest", "reader_policy_digest"})
        session_id = identifier(args["session_id"])
        if args["broker_policy_digest"] != self.authority.policy.digest or args["reader_policy_digest"] != policy.digest:
            raise Denied("binding read policy changed")
        # Registered output can outlive its producer. Do not invent readiness or
        # ignore a revoked row; the source/context gates decide whether it sends.
        value = policy.binding(self.authority.registry.session(session_id), session_id, roles)
        if self.current_policy().digest != policy.digest:
            raise Denied("binding-reader permission changed during registry observation")
        return {"schema": RESULT_SCHEMA, "ok": True, "reader_uid": peer.uid, "session_id": session_id,
                "broker_policy_digest": self.authority.policy.digest, "reader_policy_digest": policy.digest,
                "binding": value, "binding_digest": None if value is None else fingerprint(value)}


class BindingReadClient:
    """Registry.session-compatible client, never a shared SQLite handle/cache.

    Every call has a fresh nonce and the bounded Linux Unix client pins the
    serving broker UID. Decoded fields alone are not authority. The installed
    protected client/policy/transport are part of this boundary and need actual
    WSL acceptance; Mac fixtures explicitly substitute kernel observations.
    """
    def __init__(self, path, policy):
        if not isinstance(path, str) or not path.startswith("/") or ".." in Path(path).parts or "\x00" in path:
            raise Denied("explicit protected broker socket required")
        self.path, self.policy = path, policy

    def session(self, session_id):
        session_id = identifier(session_id)
        uid = os.geteuid()  # Never from an argument, cwd, environment or header.
        roles = self.policy.roles_for(uid)
        request = {"schema": REQUEST_SCHEMA, "request_id": "binding-read-" + uuid.uuid4().hex,
                   "method": "read_session", "args": {"session_id": session_id,
                   "broker_policy_digest": self.policy.broker_policy.digest, "reader_policy_digest": self.policy.digest}}
        try:
            result = client_request(self.path, request, broker_uid=self.policy.broker_policy.broker_uid, timeout=3)
        except (Denied, OSError):
            raise Denied("fresh authenticated binding read unavailable") from None
        if type(result) is not dict or result.get("ok") is not True:
            raise Denied("fresh authenticated binding read denied")
        exact(result, {"schema", "ok", "request_id", "reader_uid", "session_id", "broker_policy_digest",
                       "reader_policy_digest", "binding", "binding_digest"})
        if result["schema"] != RESULT_SCHEMA or result["request_id"] != request["request_id"] or \
                type(result["reader_uid"]) is not int or result["reader_uid"] != uid or result["session_id"] != session_id or \
                result["broker_policy_digest"] != self.policy.broker_policy.digest or result["reader_policy_digest"] != self.policy.digest:
            raise Denied("binding read response differs from the exact request/policy/component")
        value = self.policy.binding(result["binding"], session_id, roles)
        if result["binding_digest"] != (None if value is None else fingerprint(value)):
            raise Denied("binding read response content changed")
        return value
