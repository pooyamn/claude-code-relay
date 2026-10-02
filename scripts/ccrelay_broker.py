#!/usr/bin/env python3
"""Protected Linux action broker with durable, held message enrollment.

No model, provider, Telegram, GitHub, approval or deployment adapters are
enabled here. Message storage/logging is not queued or delivered model input.
Do not launch this against live state as part of local conformance tests.
"""
import argparse
import fcntl
import os
from pathlib import Path
import selectors
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.bindings import BindingRegistry
from relay_core.identity import Authority, Denied, Policy, exact, identifier, protected_path
from relay_core.broker_wire import receive_request, send_response
from relay_core.messaging import BrokerMessages
from relay_core.outbox import DeliveryLedger


def dispatch(authority, peer, request, *, control=False, messages=None):
    if control:
        exact(request, {"schema", "request_id", "method", "args"})
        if request["schema"] != "ccrelay.broker_control.v1":
            raise Denied("unsupported launcher control schema")
        identifier(request["request_id"])
        if request["method"] == "register":
            return authority.register(peer, request["args"])
        if request["method"] == "revoke":
            exact(request["args"], {"session_id"})
            return authority.revoke(peer, request["args"]["session_id"])
        raise Denied("unsupported launcher control operation")
    actor = authority.authorize(peer, request)
    if request["method"] in {"send_message", "message_status", "message_log"} and messages is not None:
        return messages.dispatch(actor, request["method"], request["args"])
    if request["method"] == "whoami":
        exact(request["args"], set())
        return {"ok": True, "role": actor.role_id, "session": actor.session_id,
                "root_task": actor.root_task_id, "execution": actor.execution_id}
    if request["method"] == "list_sessions":
        exact(request["args"], set())
        rows = [row for row in authority.registry.rows() if not row["revoked"] and
                row["policy_digest"] == authority.policy.digest and row["session_id"] != actor.session_id and
                authority.policy.roles.get(row["role_id"]) is not None and
                authority.policy.roles[row["role_id"]].fields["enabled"]]
        return {"ok": True, "you": actor.session_id, "sessions": [
            {"name": row["session_id"], "role": row["role_id"], "reachable": False,
             "state": "registered; runtime readiness not established"} for row in rows]}
    raise Denied("operation is not enabled: durable runtime/publication/approval gates are pending")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--runtime-dir", required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or not all(hasattr(socket, field) for field in ("SO_PEERCRED", "SO_PASSCRED", "SCM_CREDENTIALS")):
        raise Denied("Linux credential primitives required; broker is not portable by fallback")
    policy = Policy.load(args.policy)
    if os.geteuid() != policy.broker_uid or os.getegid() != policy.client_gid:
        raise Denied("broker must use its configured protected UID and client socket group")
    os.umask(0o077)
    runtime = protected_path(args.runtime_dir, owners={0, policy.broker_uid}, directory=True)
    if runtime.lstat().st_uid != policy.broker_uid or runtime.lstat().st_gid != policy.client_gid or runtime.lstat().st_mode & 0o007:
        raise Denied("unexpected broker runtime ownership/permissions")
    registry = BindingRegistry(args.state_dir, owner_uid=policy.broker_uid)
    lock_path = runtime / "broker.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    protected_path(lock_path, owners={0, policy.broker_uid}, private=True)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    authority = Authority(policy, registry)
    ledger = DeliveryLedger(args.state_dir, owner_uid=policy.broker_uid, policy_digest=policy.digest)
    messages = BrokerMessages(authority, ledger)
    with selectors.DefaultSelector() as selector:
        listeners = []
        try:
            for name, control in (("actions.sock", False), ("launcher.sock", True)):
                path = runtime / name
                if path.exists() or path.is_symlink():
                    raise Denied("existing broker socket needs trusted reconciliation; refusing to unlink it")
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                listeners.append((listener, path))
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                listener.bind(str(path))
                os.chmod(path, 0o600 if control else 0o660)
                listener.listen(16)
                selector.register(listener, selectors.EVENT_READ, control)
            while True:
                for key, _ in selector.select():
                    connection, _ = key.fileobj.accept()
                    with connection:
                        connection.settimeout(3)
                        request_id = None
                        try:
                            peer, request = receive_request(connection)
                            if type(request) is dict:
                                request_id = identifier(request.get("request_id"))
                            result = dispatch(authority, peer, request, control=key.data, messages=messages)
                        except (Denied, ValueError, OSError):
                            # Never log private arguments or proc/config paths.
                            result = {"ok": False, "error": "request denied; required identity or operation gate unavailable"}
                        try:
                            send_response(connection, {**result, "request_id": request_id})
                        except (Denied, OSError):
                            pass  # Caller inspects/replays SAME stable intent; no adapter resubmission.
        finally:
            for listener, path in listeners:
                listener.close()
                # Only files created while holding our lifetime lock are removed.
                if path.exists() and path.is_socket():
                    path.unlink()
            registry.close()
            ledger.close()
            os.close(lock_fd)


if __name__ == "__main__":
    main()
