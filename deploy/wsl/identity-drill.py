#!/usr/bin/env python3
"""Credential-free, real-UID drill; never provision accounts or run models.

Run only inside a reviewed, restricted transient system service. Its numeric
UIDs exercise kernel boundaries, not provider login or launcher registration.
All files/processes/sockets belong to the disposable RuntimeDirectory.
"""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import struct
import sys


ROLES = {"builder": 23100, "reviewer": 23101, "cto": 23102}
DENIED = {errno.EPERM, errno.EACCES, errno.ENOENT, errno.EROFS, errno.ESRCH}


def forbidden(operation):
    try:
        operation()
    except OSError as error:
        if error.errno in DENIED:
            return True
        raise
    return False


def enter_role(uid):
    initial_status = [line for line in Path("/proc/self/status").read_text().splitlines()
                      if line.startswith(("Uid:", "Gid:", "Cap"))]
    libc = ctypes.CDLL(None, use_errno=True)
    # Only the trusted fixture manager receives SETPCAP/ambient SETUID.
    # Each child removes its entire bounding ceiling before dropping UID.
    for capability in range(64):
        if libc.prctl(24, capability, 0, 0, 0) != 0 and ctypes.get_errno() != errno.EINVAL:
            raise RuntimeError("fixture bounding-capability drop failed")
    os.setgroups([23200])
    os.setgid(uid)
    try:
        os.setuid(uid)
    except PermissionError:
        status = Path("/proc/self/status").read_text().splitlines()
        print(json.dumps({"uid_drop_failed": uid, "initial_controls": initial_status,
              "kernel_controls": [line for line in status
              if line.startswith(("Cap", "NoNewPrivs:", "Seccomp:"))]}), file=sys.stderr, flush=True)
        raise
    header = (ctypes.c_uint32 * 2)(0x20080522, 0)
    data = (ctypes.c_uint32 * 6)()  # Two v3 capability structs: all zero.
    if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
        raise RuntimeError("fixture inheritable-capability drop failed")
    if os.geteuid() != uid or os.getegid() != uid or os.getgroups() != [23200]:
        raise RuntimeError("fixture credentials did not change")


def child_checks(root, name, holders, listener_path, group):
    uid = ROLES[name]
    enter_role(uid)
    checks = {}
    own = root / name / "synthetic-secret"
    checks["own_home_read"] = own.read_bytes() == b"SYNTHETIC"
    own.write_bytes(b"SYNTHETIC")
    checks["own_home_write"] = True
    checks["protected_policy_write_denied"] = forbidden(
        lambda: (root / "policy").write_bytes(b"NOT ALLOWED"))
    libc = ctypes.CDLL(None, use_errno=True)
    for other, pid in holders.items():
        if other == name:
            continue
        checks[other + "_read_denied"] = forbidden(
            lambda: (root / other / "synthetic-secret").read_bytes())
        checks[other + "_write_denied"] = forbidden(
            lambda: (root / other / "synthetic-secret").write_bytes(b"NOT ALLOWED"))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            checks[other + "_socket_denied"] = forbidden(
                lambda: connection.connect(str(root / other / "native.sock")))
        checks[other + "_signal_denied"] = forbidden(lambda: os.kill(pid, 0))
        ctypes.set_errno(0)
        result = libc.ptrace(16, pid, None, None)  # PTRACE_ATTACH, synthetic child only.
        checks[other + "_ptrace_denied"] = result == -1 and ctypes.get_errno() in DENIED
        if result == 0:
            libc.ptrace(17, pid, None, None)  # PTRACE_DETACH on failed boundary.
        checks[other + "_proc_memory_denied"] = forbidden(
            lambda: Path("/proc").joinpath(str(pid), "mem").read_bytes())
    for filename in ("cgroup.procs", "cgroup.threads"):
        path = Path("/sys/fs/cgroup") / group.lstrip("/") / filename
        # Opening, without writing a PID, proves migration permission safely.
        def open_migration():
            descriptor = os.open(path, os.O_WRONLY)
            os.close(descriptor)
        checks[filename + "_write_denied"] = forbidden(open_migration)
    for name_space, flag in (("user", 0x10000000), ("mount", 0x00020000)):
        ctypes.set_errno(0)
        result = libc.unshare(flag)
        checks[name_space + "_namespace_denied"] = result == -1 and ctypes.get_errno() in DENIED
    checks["windows_drive_denied"] = forbidden(
        lambda: Path("/mnt/c/Windows/win.ini").read_bytes())
    checks["wsl_init_not_executable"] = not os.access("/init", os.X_OK)
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines()
                  if ":" in line)
    checks["effective_capabilities_empty"] = int(status["CapEff"].strip(), 16) == 0
    checks["all_capability_sets_empty"] = all(int(status[key].strip(), 16) == 0
        for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
    checks["no_new_privileges"] = status["NoNewPrivs"].strip() == "1"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(listener_path)
        connection.sendall(json.dumps({"role": name, "checks": checks}).encode() + b"\n")


def run(root):
    if sys.platform != "linux" or os.geteuid() != 0 or not os.environ.get("INVOCATION_ID"):
        raise RuntimeError("restricted root transient service required; not a model process")
    if not re.fullmatch(r"/run/ccrelay-identity-proof-[a-f0-9]{12}", str(root)):
        raise RuntimeError("unexpected disposable runtime directory")
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise RuntimeError("runtime directory must already be protected")
    if list(root.iterdir()):
        raise RuntimeError("refusing existing fixture state")
    for uid in ROLES.values():
        try:
            pwd.getpwuid(uid)
        except KeyError:
            pass
        else:
            raise RuntimeError("fixture UID is already provisioned; choose a disposable target")
    for process in Path("/proc").iterdir():
        if process.name.isdigit():
            try:
                if process.stat().st_uid in ROLES.values():
                    raise RuntimeError("fixture UID already has a process")
            except FileNotFoundError:
                pass
    signal.alarm(25)
    group_rows = Path("/proc/self/cgroup").read_text().splitlines()
    if len(group_rows) != 1 or not group_rows[0].startswith("0::/system.slice/ccrelay-identity-proof-"):
        raise RuntimeError("root-controlled unified systemd fixture cgroup required")
    group = group_rows[0][3:]
    children, private_sockets = [], []
    try:
        holders = {}
        for name, uid in ROLES.items():
            folder = root / name
            folder.mkdir(mode=0o700)
            (folder / "synthetic-secret").write_bytes(b"SYNTHETIC")
            os.chown(folder / "synthetic-secret", uid, uid)
            os.chown(folder, uid, uid)
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            private_sockets.append(connection)
            connection.bind(str(folder / "native.sock"))
            os.chmod(folder / "native.sock", 0o600)
            os.chown(folder / "native.sock", uid, uid)
            connection.listen(1)
            ready_read, ready_write = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(ready_read)
                for item in private_sockets:
                    item.close()
                enter_role(uid)
                os.write(ready_write, b"1")
                os.close(ready_write)
                signal.alarm(20)
                signal.pause()
                os._exit(0)
            children.append(pid)
            holders[name] = pid
            os.close(ready_write)
            if os.read(ready_read, 1) != b"1":
                raise RuntimeError("synthetic role holder failed")
            os.close(ready_read)
        (root / "policy").write_bytes(b"SYNTHETIC POLICY")
        os.chmod(root / "policy", 0o644)
        reports = {}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            path = str(root / "broker.sock")
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            listener.bind(path)
            os.chown(path, 0, 23200)
            os.chmod(path, 0o660)
            listener.listen(3)
            listener.settimeout(5)
            for name, uid in ROLES.items():
                pid = os.fork()
                if pid == 0:
                    listener.close()
                    for item in private_sockets:
                        item.close()
                    try:
                        child_checks(root, name, holders, path, group)
                    except BaseException:
                        os._exit(2)
                    os._exit(0)
                children.append(pid)
                with listener.accept()[0] as connection:
                    connection.settimeout(3)
                    expected = (pid, uid, uid)
                    peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    body, ancillary, flags, _ = connection.recvmsg(16384, socket.CMSG_SPACE(12))
                    credentials = [struct.unpack("3i", value) for level, kind, value in ancillary
                                   if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS]
                    report = json.loads(body)
                    if report["role"] != name:
                        raise RuntimeError("fixture report identity mismatch")
                    report["checks"]["real_peer_credentials"] = peer == expected
                    report["checks"]["real_sender_credentials"] = not flags and credentials == [expected]
                    reports[name] = report["checks"]
                _, status = os.waitpid(pid, 0)
                children.remove(pid)
                if status:
                    raise RuntimeError("synthetic role probe failed")
        passed = all(value is True for checks in reports.values() for value in checks.values())
        print(json.dumps({"schema": "ccrelay.identity_drill.v1", "passed": passed,
                          "checks": sum(map(len, reports.values())), "roles": reports,
                          "uid_allocation": ROLES, "cgroup": group,
                          "accounts_provisioned": False, "models_started": False,
                          "live_role_acceptance": False}, sort_keys=True))
        return 0 if passed else 1
    finally:
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)  # Exact synthetic child PIDs only.
                os.waitpid(pid, 0)
            except ProcessLookupError:
                pass
        for item in private_sockets:
            item.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--fixture-root", type=Path)
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({"mode": "plan-only", "uids": ROLES, "changes_applied": False}))
    elif args.fixture_root is None:
        parser.error("--run requires --fixture-root")
    else:
        raise SystemExit(run(args.fixture_root))
