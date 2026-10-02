#!/usr/bin/env python3
"""Linux protected approval ingress. No bot polling, deploy/restart or model calls."""
import argparse
import fcntl
import os
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.broker_wire import receive_request, send_response
from relay_core.identity import Denied, Policy, exact, identifier, protected_path
from relay_core.owner_gate import OwnerLedger, OwnerPolicy


def dispatch(ledger, peer, request):
    exact(request, {"schema", "request_id", "method", "args"})
    if request["schema"] != "ccrelay.owner_request.v1":
        raise Denied("unsupported owner ingress protocol")
    identifier(request["request_id"])
    args = request["args"]
    if request["method"] == "enroll_bootstrap":
        exact(args, {"action", "approval_id", "expires_at"})
        return ledger.enroll(peer, **args)
    if request["method"] == "bind_prompt":
        exact(args, {"action_id", "receipt"})
        ledger.bind_prompt(peer, **args)
        return {"bound": True}
    if request["method"] == "read_prompt":
        exact(args, {"action_id"})
        return ledger.read_prompt(peer, **args)
    if request["method"] == "owner_callback":
        exact(args, {"update"})
        return ledger.decide(peer, args["update"])
    raise Denied("unsupported operation; effectful deployment is not exposed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-policy", required=True)
    parser.add_argument("--broker-policy", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--runtime-dir", required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or not all(hasattr(socket, name) for name in ("SO_PEERCRED", "SO_PASSCRED", "SCM_CREDENTIALS")):
        raise Denied("Linux kernel credentials required; no portable identity fallback")
    policy = OwnerPolicy.load(args.owner_policy, Policy.load(args.broker_policy))
    if not policy.enabled or os.geteuid() != policy.gate_uid:
        raise Denied("owner gate disabled or started as wrong identity")
    os.umask(0o077)
    runtime = protected_path(args.runtime_dir, owners={0, policy.gate_uid}, directory=True)
    if runtime.lstat().st_uid != policy.gate_uid or runtime.lstat().st_mode & 0o007:
        raise Denied("unexpected private owner runtime ownership/permissions")
    ledger = OwnerLedger(args.state_dir, policy)
    lock_path = runtime / "owner.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    path = runtime / "owner.sock"
    created = False
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        protected_path(lock_path, owners={0, policy.gate_uid}, private=True)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists() or path.is_symlink():
            raise Denied("stale owner socket requires trusted reconciliation")
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        listener.bind(str(path))
        created = True
        os.chmod(path, 0o660)
        listener.listen(16)
        while True:
            connection, _ = listener.accept()
            with connection:
                request_id = None
                try:
                    peer, request = receive_request(connection)
                    if type(request) is dict:
                        request_id = identifier(request.get("request_id"))
                    result = {"ok": True, "result": dispatch(ledger, peer, request)}
                except (Denied, ValueError, OSError):
                    result = {"ok": False, "error": "owner request denied; identity, intent or required gate invalid"}
                try:
                    send_response(connection, {**result, "request_id": request_id})
                except (Denied, OSError):
                    pass  # Caller reconciles; no replay-driven external effect.
    finally:
        listener.close()
        if created and path.exists() and path.is_socket():
            path.unlink()
        ledger.close()
        os.close(lock_fd)


if __name__ == "__main__":
    main()
