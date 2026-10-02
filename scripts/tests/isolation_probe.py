"""Actual OS boundary probe; fail before running tests if isolation is absent."""
import errno
import os
from pathlib import Path
import socket


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
