"""Linux broker identity boundary; no directory, environment or header identity.

Pure authorization accepts kernel observations supplied by the protected broker.
Production observations come only from SO_PEERCRED/SCM_CREDENTIALS and procfs.
Conformance fakes cannot establish that target-WSL isolation works.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys
from types import MappingProxyType

from .contracts import ContractError, canonical_bytes, decode, fingerprint


class Denied(ContractError):
    pass


MAX_FRAME = 65536
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
METHODS = {
    "whoami": "message", "list_sessions": "message", "message_log": "message",
    "send_message": "message", "report_issue": "report_issue", "list_issues": "report_issue",
    "comment_issue": "report_issue", "publish": "publish", "review_publication": "review",
    "request_merge": "request_merge", "request_action": "request_action",
    "request_deploy": "request_deploy", "propose_memory": "propose_memory",
}


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise Denied("unexpected or missing fields")


def identifier(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise Denied("invalid identifier")
    return value


def integer(value, minimum=1):
    if type(value) is not int or value < minimum:
        raise Denied("invalid integer")
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Denied("duplicate JSON key")
            result[key] = value
        return result

    if not isinstance(raw, (bytes, str)) or len(raw) > MAX_FRAME:
        raise Denied("oversized or invalid JSON frame")
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        canonical_bytes(value)  # rejects nonfinite values, floats and unsafe Unicode
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Denied("invalid JSON frame") from error


@dataclass(frozen=True)
class Peer:
    pid: int
    uid: int
    gid: int

    def __post_init__(self):
        integer(self.pid)
        integer(self.uid, 0)
        integer(self.gid, 0)


@dataclass(frozen=True)
class Process:
    pid: int
    uid: int
    start_identity: str
    cgroup: str


def expected_cgroup(execution_id):
    return "/system.slice/ccrelay-session-" + identifier(execution_id) + ".service"


def peer_credentials(connection):
    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        raise Denied("Linux kernel peer credentials required; no UID fallback")
    if connection.family != socket.AF_UNIX or connection.type != socket.SOCK_STREAM:
        raise Denied("connected Unix stream socket required")
    return Peer(*struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)))


def proc_stat(raw, expected_pid):
    # comm may contain spaces and parentheses: splitting the whole line is wrong.
    begin, end = raw.find("("), raw.rfind(")")
    if begin < 0 or end <= begin or raw[:begin].strip() != str(expected_pid):
        raise Denied("invalid process stat")
    fields = raw[end + 1:].split()
    if len(fields) < 20 or fields[0] in {"Z", "X", "x"} or not fields[19].isdigit():
        raise Denied("process is dead or has invalid start identity")
    return fields[19]  # field 22, starttime; fields[0] is field 3


def proc_cgroup(raw):
    rows = raw.splitlines()
    if len(rows) != 1 or not rows[0].startswith("0::"):
        raise Denied("unified cgroup v2 required")
    path = rows[0][3:]
    if not path.startswith("/") or any(part in {".", ".."} for part in path.split("/")):
        raise Denied("invalid cgroup observation")
    return path


def observe_process(pid):
    """Read a fresh process generation, UID and cgroup, bracketing PID reuse.

    No caller-selected proc root. The broker must see the host's protected proc
    and cgroup namespaces; workers must not have cgroup migration permission.
    """
    integer(pid)
    if sys.platform != "linux":
        raise Denied("Linux process observation required")
    try:
        folder = Path("/proc") / str(pid)
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not re.fullmatch(r"[a-f0-9-]{36}", boot):
            raise Denied("invalid boot identity")
        first = proc_stat((folder / "stat").read_text(), pid)
        uid_rows = [row for row in (folder / "status").read_text().splitlines() if row.startswith("Uid:")]
        if len(uid_rows) != 1:
            raise Denied("missing process UID")
        uids = uid_rows[0].split()[1:]
        if len(uids) != 4 or not all(item.isdigit() for item in uids) or len(set(uids)) != 1:
            raise Denied("mixed process credentials")
        group = proc_cgroup((folder / "cgroup").read_text())
        protected_cgroup(group)
        second = proc_stat((folder / "stat").read_text(), pid)
        if first != second:
            raise Denied("process generation changed")
        return Process(pid, int(uids[0]), boot + ":" + first, group)
    except (OSError, UnicodeError, ValueError) as error:
        raise Denied("process observation unavailable") from error


def protected_cgroup(group):
    path = Path("/sys/fs/cgroup") / group.lstrip("/")
    protected_path(path, owners={0}, directory=True)
    protected_path(path / "cgroup.procs", owners={0})
    protected_path(path / "cgroup.threads", owners={0})


def protected_path(path, *, owners, directory=False, private=False):
    """Reject symlinks and writable ancestors, not silently repair permissions."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise Denied("absolute protected path required")
    for item in reversed([path, *path.parents]):
        metadata = item.lstat()
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid not in owners or metadata.st_mode & 0o022:
            raise Denied("untrusted ownership, symlink or writable protected path")
        if item != path or directory:
            if not stat.S_ISDIR(metadata.st_mode):
                raise Denied("protected directory required")
        elif not stat.S_ISREG(metadata.st_mode):
            raise Denied("protected regular file required")
    if private and path.lstat().st_mode & 0o077:
        raise Denied("private storage permissions required")
    return path


class Policy:
    def __init__(self, raw):
        exact(raw, {"schema", "broker_uid", "client_gid", "roles", "controllers"})
        if raw["schema"] != "ccrelay.broker_policy.v1":
            raise Denied("unsupported broker policy schema")
        self.broker_uid = integer(raw["broker_uid"])
        self.client_gid = integer(raw["client_gid"])
        if type(raw["roles"]) is not list or not raw["roles"]:
            raise Denied("empty role allowlist")
        roles, uids = {}, set()
        for item in raw["roles"]:
            role = decode(item)
            if role.kind != "role" or role.id in roles or role.fields["uid"] in uids:
                raise Denied("duplicate role or UID")
            if role.fields["uid"] == self.broker_uid:
                raise Denied("broker UID cannot be a worker")
            caps = role.fields["capabilities"]
            if "owner_approve" in caps or ("review" in caps and role.id != "reviewer") or \
                    ("request_merge" in caps and role.id != "cto") or \
                    ("request_deploy" in caps and role.id != "support"):
                raise Denied("role violates protected authority ceiling")
            roles[role.id] = role
            uids.add(role.fields["uid"])
        self.roles = MappingProxyType(roles)
        if type(raw["controllers"]) is not list or not raw["controllers"]:
            raise Denied("empty launcher allowlist")
        controllers = {}
        for item in raw["controllers"]:
            exact(item, {"uid", "roles"})
            uid = integer(item["uid"], 0)
            grants = item["roles"]
            if uid in uids or uid == self.broker_uid or uid in controllers or \
                    type(grants) is not list or not grants or any(type(grant) is not str for grant in grants) or \
                    len(set(grants)) != len(grants) or \
                    not set(grants).issubset(roles):
                raise Denied("invalid launcher grants")
            controllers[uid] = frozenset(grants)
        self.controllers = MappingProxyType(controllers)
        self.digest = fingerprint(raw)

    @classmethod
    def load(cls, path):
        protected_path(path, owners={0})
        return cls(strict_json(Path(path).read_bytes()))


BINDING_FIELDS = {"schema", "session_id", "role_id", "root_task_id", "execution_id",
                  "uid", "launcher_uid", "leader_pid", "leader_start", "cgroup", "policy_digest", "revoked"}


def validate_binding(raw):
    exact(raw, BINDING_FIELDS)
    if raw["schema"] != "ccrelay.session_binding.v1":
        raise Denied("unsupported binding schema; preserve for migration")
    for key in ("session_id", "role_id", "root_task_id", "execution_id"):
        identifier(raw[key])
    integer(raw["uid"])
    integer(raw["launcher_uid"], 0)
    integer(raw["leader_pid"])
    if type(raw["leader_start"]) is not str or not re.fullmatch(r"[a-f0-9-]{36}:[0-9]+", raw["leader_start"]):
        raise Denied("invalid leader generation")
    if raw["cgroup"] != expected_cgroup(raw["execution_id"]) or \
            type(raw["policy_digest"]) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", raw["policy_digest"]) or \
            type(raw["revoked"]) is not bool:
        raise Denied("invalid binding")
    return raw


@dataclass(frozen=True)
class Actor:
    role_id: str
    session_id: str
    root_task_id: str
    execution_id: str
    policy_digest: str
    peer: Peer
    peer_start: str


class Authority:
    def __init__(self, policy, registry, observer=observe_process):
        self.policy, self.registry, self.observer = policy, registry, observer

    def register(self, peer, fields):
        exact(fields, {"session_id", "role_id", "root_task_id", "execution_id", "leader_pid"})
        identifier(fields["role_id"])
        grants = self.policy.controllers.get(peer.uid, frozenset())
        if fields["role_id"] not in grants:
            raise Denied("launcher is not permitted to register this role")
        role = self.policy.roles[fields["role_id"]]
        if not role.fields["enabled"]:
            raise Denied("role disabled")
        for key in ("session_id", "role_id", "root_task_id", "execution_id"):
            identifier(fields[key])
        leader = self.observer(integer(fields["leader_pid"]))
        if leader.uid != role.fields["uid"] or leader.cgroup != expected_cgroup(fields["execution_id"]):
            raise Denied("launcher process does not match protected role/unit")
        row = validate_binding({"schema": "ccrelay.session_binding.v1", **fields,
                                "uid": leader.uid, "launcher_uid": peer.uid, "leader_start": leader.start_identity,
                                "cgroup": leader.cgroup, "policy_digest": self.policy.digest, "revoked": False})
        self.registry.register(row)
        return {"ok": True, "session_id": row["session_id"], "execution_id": row["execution_id"]}

    def revoke(self, peer, session_id):
        row = self.registry.session(identifier(session_id))
        if row is None or row["role_id"] not in self.policy.controllers.get(peer.uid, frozenset()):
            raise Denied("launcher cannot revoke this session")
        self.registry.revoke(session_id)
        return {"ok": True, "revoked": session_id}

    def actor(self, peer):
        process = self.observer(peer.pid)
        if process.uid != peer.uid:
            raise Denied("socket/process credentials differ")
        row = self.registry.cgroup(process.cgroup)
        if row is None:
            raise Denied("unregistered process unit")
        validate_binding(row)
        role = self.policy.roles.get(row["role_id"])
        if row["cgroup"] != process.cgroup or row["revoked"] or row["policy_digest"] != self.policy.digest or role is None or \
                not role.fields["enabled"] or row["uid"] != peer.uid or role.fields["uid"] != peer.uid or \
                row["role_id"] not in self.policy.controllers.get(row["launcher_uid"], frozenset()):
            raise Denied("revoked, disabled, stale or wrong-role binding")
        leader = self.observer(row["leader_pid"])
        if leader.uid != peer.uid or leader.start_identity != row["leader_start"] or leader.cgroup != row["cgroup"]:
            raise Denied("session leader changed or left its unit")
        return Actor(row["role_id"], row["session_id"], row["root_task_id"], row["execution_id"],
                     self.policy.digest, peer, process.start_identity)

    def authorize(self, peer, request):
        exact(request, {"schema", "request_id", "method", "args"})
        if request["schema"] != "ccrelay.broker_request.v1":
            raise Denied("unsupported broker request schema")
        identifier(request["request_id"])
        if type(request["method"]) is not str or request["method"] not in METHODS or type(request["args"]) is not dict:
            raise Denied("unsupported operation")
        actor = self.actor(peer)
        cap = METHODS[request["method"]]
        if cap not in self.policy.roles[actor.role_id].fields["capabilities"]:
            raise Denied("role capability denied")
        if any(key in request["args"] for key in ("from", "sender", "role", "role_id", "session_id", "root_task_id", "uid")):
            raise Denied("caller-supplied identity is forbidden")
        return actor
