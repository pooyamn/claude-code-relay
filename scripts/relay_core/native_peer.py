"""Linux native Unix sender identity, optionally joined to executable evidence.

The protected controller supplies the current binding and expected process epoch.
Reuse the broker's kernel sender and Authority checks; no header/folder identity,
caller-selected proc root, socket discovery or non-Linux UID fallback exists.
"""
from contextlib import contextmanager
from dataclasses import asdict
import os
import re
import socket
import stat
import sys

from .broker_wire import receive_credentialed_chunk
from .contracts import fingerprint
from .identity import Authority, Denied, identifier, integer, peer_credentials


SCHEMA = "ccrelay.native_unix_peer.v1"


class KernelUnixPeer:
    """Borrow one explicit owned FD; credentials accompany every received chunk."""
    def __init__(self, fd, *, authority, session_id, binding_digest, process_start,
                 executable=None, executable_digest=None):
        if sys.platform != "linux" or not all(hasattr(socket, name) for name in ("SO_PEERCRED", "SO_PASSCRED", "SCM_CREDENTIALS")):
            raise Denied("Linux native sender credentials required; no UID fallback")
        integer(fd, 0)
        if type(authority) is not Authority or type(binding_digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", binding_digest) or \
                type(process_start) is not str or not re.fullmatch(r"[a-f0-9-]{36}:[0-9]+", process_start):
            raise Denied("protected authority, current binding pin and process epoch required")
        metadata = os.fstat(fd)
        if not stat.S_ISSOCK(metadata.st_mode) or os.get_blocking(fd):
            raise Denied("explicit owned nonblocking Unix native socket required")
        self.fd, self.fd_identity = fd, (metadata.st_dev, metadata.st_ino)
        self.authority, self.session_id = authority, identifier(session_id)
        self.policy_digest, self.binding_digest = authority.policy.digest, binding_digest
        self.process_start = process_start
        self.image = None
        if (executable is None) != (executable_digest is None):
            raise Denied("native executable path and byte digest must be supplied together")
        with self._borrow() as stream:
            self.peer = peer_credentials(stream)
        self._actor()
        if executable is not None:
            from .native_image import NativeExecutable
            self.image = NativeExecutable(self.peer.pid, executable, executable_digest)
        with self._borrow() as stream:
            stream.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        self.current()
        evidence = {"schema": SCHEMA, "policy_digest": self.policy_digest,
                    "session_id": self.session_id, "binding_digest": self.binding_digest,
                    "peer": asdict(self.peer), "process_start": self.process_start}
        if self.image is not None:
            evidence["executable_digest"] = self.image.digest
        self.digest = fingerprint(evidence)

    @contextmanager
    def _borrow(self):
        metadata = os.fstat(self.fd)
        if (metadata.st_dev, metadata.st_ino) != self.fd_identity or os.get_blocking(self.fd):
            raise Denied("native peer descriptor changed")
        stream = socket.socket(fileno=self.fd)
        try:
            if stream.family != socket.AF_UNIX or stream.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
                raise Denied("connected Unix stream required")
            stream.getpeername()
            yield stream
        finally:
            stream.detach()  # Ownership stays with the channel/launcher.

    def _actor(self):
        if self.authority.policy.digest != self.policy_digest:
            raise Denied("native peer policy changed")
        actor = self.authority.actor(self.peer)
        binding = self.authority.registry.session(self.session_id)
        if actor.session_id != self.session_id or fingerprint(binding) != self.binding_digest or \
                actor.peer_start != self.process_start:
            raise Denied("native peer execution/binding/process generation changed")
        return actor

    def current(self):
        with self._borrow() as stream:
            if peer_credentials(stream) != self.peer or stream.getsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED) != 1:
                raise Denied("native peer or kernel message credential mode changed")
        actor = self._actor()
        if self.image is not None:
            self.image.current()
            actor = self._actor()  # Bind image observation to the same current process epoch.
        return actor

    def receive(self, max_bytes):
        self.current()
        with self._borrow() as stream:
            body = receive_credentialed_chunk(stream, self.peer, max_bytes)
        self.current()  # Revocation/PID reuse while reading cannot supply evidence.
        return body

    def verify(self, channel):
        from .native_ws import UnixWSChannel
        if type(channel) is not UnixWSChannel or channel.kernel_peer is not self or channel.fds != (self.fd, self.fd):
            raise Denied("exact credentialed native channel required; no plain-read fallback")
        self.current()
        return self.digest
