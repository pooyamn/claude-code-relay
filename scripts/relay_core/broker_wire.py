"""One bounded request per Unix connection, with per-message Linux credentials.

SO_PEERCRED alone describes the process that connected, not necessarily the
process now writing an inherited/transferred descriptor. Require PASSCRED on
every received fragment and reject transferred descriptors, too.
"""
import array
import os
import socket
import struct
import time

from .contracts import canonical_bytes
from .identity import Denied, MAX_FRAME, Peer, integer, peer_credentials, strict_json


def receive_credentialed_chunk(connection, peer, max_bytes):
    """One chunk from the exact kernel sender; never accept transferred FDs."""
    integer(max_bytes)
    if type(peer) is not Peer or max_bytes > MAX_FRAME + 1:
        raise Denied("bounded kernel-authenticated receive required")
    body, ancillary, flags, _ = connection.recvmsg(
        max_bytes, socket.CMSG_SPACE(12) + socket.CMSG_SPACE(256))
    credentials, unexpected = [], False
    for level, kind, value in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(value) == 12:
            try:
                credentials.append(Peer(*struct.unpack("3i", value)))
            except Denied:
                # Still inspect/close any SCM_RIGHTS entries later in this
                # ancillary list before refusing malformed credentials.
                unexpected = True
        else:
            unexpected = True
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                descriptors = array.array("i")
                descriptors.frombytes(value[:len(value) - len(value) % descriptors.itemsize])
                for descriptor in descriptors:
                    os.close(descriptor)
    if flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) or unexpected or credentials != [peer]:
        raise Denied("missing, transferred or mismatched kernel message credentials")
    return body


def receive_request(connection, *, timeout=3):
    peer = peer_credentials(connection)
    chunks, size = [], 0
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Denied("broker frame deadline expired")
        connection.settimeout(remaining)
        body = receive_credentialed_chunk(connection, peer, min(8192, MAX_FRAME + 1 - size))
        if not body:
            raise Denied("incomplete broker frame")
        chunks.append(body)
        size += len(body)
        if size > MAX_FRAME:
            raise Denied("broker frame too large")
        if b"\n" in body:
            frame = b"".join(chunks)
            if frame.count(b"\n") != 1 or not frame.endswith(b"\n"):
                raise Denied("exactly one complete JSON frame required")
            return peer, strict_json(frame[:-1])


def send_response(connection, response):
    body = canonical_bytes(response) + b"\n"
    if len(body) > MAX_FRAME:
        raise Denied("broker response too large")
    connection.sendall(body)


def client_request(path, request, *, broker_uid, timeout=3):
    # Config comes from the reviewed launcher. A caller can redirect its own
    # client, but cannot make the real broker trust a header or sender argument.
    from pathlib import PurePosixPath
    if not isinstance(path, str) or not path.startswith("/") or ".." in PurePosixPath(path).parts or "\x00" in path:
        raise Denied("absolute broker socket path required")
    payload = canonical_bytes(request) + b"\n"
    if len(payload) > MAX_FRAME:
        raise Denied("broker request too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        deadline = time.monotonic() + timeout
        connection.settimeout(timeout)
        connection.connect(path)
        if peer_credentials(connection).uid != broker_uid:
            raise Denied("unexpected broker socket owner")
        connection.sendall(payload)
        response = bytearray()
        while b"\n" not in response:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Denied("broker response deadline expired; outcome may be unknown")
            connection.settimeout(remaining)
            part = connection.recv(min(8192, MAX_FRAME + 1 - len(response)))
            if not part:
                raise Denied("broker response interrupted; outcome may be unknown")
            response += part
            if len(response) > MAX_FRAME:
                raise Denied("broker response too large")
        if response.count(b"\n") != 1 or not response.endswith(b"\n"):
            raise Denied("invalid broker response framing")
        result = strict_json(bytes(response[:-1]))
        if type(result) is not dict or result.get("request_id") != request["request_id"] or type(result.get("ok")) is not bool:
            raise Denied("broker response does not match request")
        return result
