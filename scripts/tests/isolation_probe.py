"""Actual OS boundary probe; fail before running tests if isolation is absent."""
import errno
import os
from pathlib import Path
import socket
import subprocess
import sys


def main():
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1":
        raise RuntimeError("use run_isolated.py, not an unconfined test process")
    for key in ("HOME", "CODEX_HOME", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CCRELAY_BOT_TOKEN",
                "TMUX", "TMUX_PANE", "CLAUDE_RELAY_SESSION", "RELAY_CHAT_ID", "RELAY_THREAD_ID"):
        if key in os.environ:
            raise RuntimeError(f"unexpected inherited environment: {key}")
    outside = Path(os.environ["CCRELAY_DENIED_SENTINEL"])
    for operation in (lambda: outside.read_bytes(), lambda: outside.write_bytes(b"NOT ALLOWED")):
        try:
            operation()
        except (PermissionError, FileNotFoundError):
            pass
        else:
            raise RuntimeError("filesystem boundary not enforced")
    # Deadline/error cleanup must be able to stop its own children, without
    # permission to signal the host runner or unrelated user applications.
    child = subprocess.Popen([sys.executable, "-c",
        "import signal; print('ready', flush=True); signal.pause()"], stdout=subprocess.PIPE)
    try:
        if child.stdout.readline() != b"ready\n":
            raise RuntimeError("child signal probe did not start")
        child.kill()
        if child.wait(timeout=3) != -9:
            raise RuntimeError("same-sandbox child cleanup not enforced")
    finally:
        child.stdout.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
    if os.uname().sysname == "Darwin":
        try:
            os.kill(os.getppid(), 0)  # Permission probe only; sends no signal.
        except PermissionError:
            pass
        else:
            raise RuntimeError("sandbox can signal its unsandboxed host runner")
    for family in (socket.AF_INET, socket.AF_UNIX):
        try:
            with socket.socket(family) as connection:
                address = ("127.0.0.1", 0) if family == socket.AF_INET else "/tmp/ccrelay-forbidden.sock"
                connection.bind(address)
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EACCES, errno.ENOENT, errno.EROFS}:
                raise
        else:
            # Linux network namespaces may permit isolated loopback/Unix
            # sockets; neither reaches host network or daemon namespaces.
            if not os.uname().sysname == "Linux":
                raise RuntimeError("network/socket boundary not enforced")
    print("OS isolation verified: clean env; outside reads/writes denied; host network excluded")


if __name__ == "__main__":
    main()
