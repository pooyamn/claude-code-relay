"""Observe a pinned Linux executable through procfs, never argv/version claims.

The controller supplies reviewed root-owned binary bytes. This proves the file
observed at /proc/PID/exe, not loaded settings, mapped libraries, memory integrity
or continuous execution identity. Protected launch/isolation remains required.
"""
import hashlib
import os
from pathlib import PurePosixPath
import re
import stat
import sys

from .contracts import fingerprint
from .identity import Denied, integer, protected_path


SCHEMA = "ccrelay.native_executable.v1"
MAX_IMAGE_BYTES = 512 * 1024 * 1024


def _identity(metadata):
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or \
            metadata.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID) or not metadata.st_mode & stat.S_IXUSR or \
            metadata.st_nlink < 1 or not 4 <= metadata.st_size <= MAX_IMAGE_BYTES:
        raise Denied("bounded root-owned non-privileged executable required")
    return (metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_gid,
            metadata.st_mode, metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


class NativeExecutable:
    """Hash once; reject changed inode/metadata instead of accepting an upgrade.

    Every subsequent check reopens both the reviewed path and the kernel's
    executable link. No FD is retained, no process is started/stopped and no
    caller-selectable proc root or platform fallback exists. The native peer
    brackets checks with its current UID/cgroup/leader/process-generation gate.
    """
    def __init__(self, pid, executable, expected_digest):
        if sys.platform != "linux":
            raise Denied("Linux executable observation required; no path/version fallback")
        integer(pid)
        if type(executable) is not str or str(PurePosixPath(executable)) != executable or \
                not re.fullmatch(r"/opt/ccrelay/native/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", executable) or \
                any(part in {".", ".."} for part in PurePosixPath(executable).parts) or \
                type(expected_digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", expected_digest):
            raise Denied("explicit canonical native executable and reviewed byte digest required")
        self.pid, self.executable, self.expected_digest = pid, executable, expected_digest
        self.proc_path = "/proc/" + str(pid) + "/exe"
        self.identity = None
        self._inspect(hash_bytes=True)
        self.digest = fingerprint({"schema": SCHEMA, "pid": pid, "executable": executable,
                                   "byte_digest": expected_digest, "file_identity": list(self.identity)})

    def _inspect(self, *, hash_bytes=False):
        installed_fd = observed_fd = None
        try:
            protected_path(self.executable, owners={0})
            if os.readlink(self.proc_path) != self.executable:
                raise Denied("native executable path changed, deleted or unsupported")
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
            installed_fd = os.open(self.executable, flags | os.O_NOFOLLOW)
            # Deliberately follow THIS kernel magic link to the executed inode.
            observed_fd = os.open(self.proc_path, flags)
            identity = _identity(os.fstat(installed_fd))
            if _identity(os.fstat(observed_fd)) != identity or self.identity is not None and identity != self.identity:
                raise Denied("native executed inode or pinned metadata changed")
            if hash_bytes:
                remaining = identity[6]
                hasher = hashlib.sha256()
                prefix = b""
                while remaining:
                    chunk = os.read(observed_fd, min(128 * 1024, remaining))
                    if not chunk:
                        raise Denied("native executable truncated during byte verification")
                    if len(prefix) < 4:
                        prefix += chunk[:4 - len(prefix)]
                    hasher.update(chunk)
                    remaining -= len(chunk)
                if os.read(observed_fd, 1) or prefix != b"\x7fELF" or \
                        "sha256:" + hasher.hexdigest() != self.expected_digest:
                    raise Denied("reviewed native ELF bytes do not match")
            if _identity(os.fstat(installed_fd)) != identity or _identity(os.fstat(observed_fd)) != identity or \
                    _identity(os.stat(self.executable, follow_symlinks=False)) != identity or \
                    _identity(os.stat(self.proc_path)) != identity or os.readlink(self.proc_path) != self.executable:
                raise Denied("native executable changed during observation")
            protected_path(self.executable, owners={0})
            self.identity = identity
        except Denied:
            raise
        except (OSError, ValueError, UnicodeError) as error:
            raise Denied("native executable observation unavailable") from error
        finally:
            if observed_fd is not None:
                os.close(observed_fd)
            if installed_fd is not None:
                os.close(installed_fd)

    def current(self):
        self._inspect()
        return self.digest
