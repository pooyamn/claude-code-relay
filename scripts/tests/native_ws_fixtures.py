"""Independent anonymous-socket WebSocket peer, not a native daemon fixture."""
import base64
import hashlib
import json
import os
import select
import socket
import struct
import time

from native_rpc_fixtures import CLIENT, INITIALIZED, PipePeer, RPCFixture
from relay_core.contracts import fingerprint
from relay_core.native_ws import UnixWSChannel


WS_DIGEST = fingerprint({"fixture_transport": "owned-unix-websocket"})


def frame(body, *, opcode=1, fin=True):
    if type(body) is dict:
        body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    size = len(body)
    header = bytes(((0x80 if fin else 0) | opcode, size)) if size < 126 else \
        bytes(((0x80 if fin else 0) | opcode, 126)) + struct.pack("!H", size) if size < 65536 else \
        bytes(((0x80 if fin else 0) | opcode, 127)) + struct.pack("!Q", size)
    return header + body


class WSPeer(PipePeer):
    def __init__(self, *, timeout_ms=1000, max_frame_bytes=8192):
        client, server = socket.socketpair()
        client.setblocking(False)
        server.setblocking(False)
        self.read_fd = self.write_fd = server.detach()
        client_fd = client.detach()
        self.channel = UnixWSChannel(client_fd, timeout_ms=timeout_ms, max_frame_bytes=max_frame_bytes)
        self.buffer, self.requests, self.errors, self.frames = bytearray(), [], [], []
        self.thread = None
        self.header_filter = lambda value: value
        self.header_chunk_bytes, self.extra_frame = 0, b""
        self.upgrade_request = None

    def read(self, size):
        deadline = time.monotonic() + 2
        while len(self.buffer) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.read_fd], [], [], remaining)[0]:
                raise AssertionError("fixture did not receive expected WebSocket bytes")
            chunk = os.read(self.read_fd, 65536)
            if not chunk:
                raise EOFError("client stream closed")
            self.buffer.extend(chunk)
        body = bytes(self.buffer[:size])
        del self.buffer[:size]
        return body

    def upgrade(self):
        body = bytearray()
        while not body.endswith(b"\r\n\r\n"):
            body.extend(self.read(1))
            assert len(body) < 16384
        request = body.decode("ascii")
        assert request.startswith("GET / HTTP/1.1\r\nHost: localhost\r\n")
        headers = dict(line.split(": ", 1) for line in request.split("\r\n")[1:] if line)
        assert headers["Upgrade"] == "websocket" and headers["Connection"] == "Upgrade"
        assert headers["Sec-WebSocket-Version"] == "13"
        assert len(base64.b64decode(headers["Sec-WebSocket-Key"], validate=True)) == 16
        self.upgrade_request = request
        accept = base64.b64encode(hashlib.sha1((headers["Sec-WebSocket-Key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(), usedforsecurity=False).digest())
        response = self.header_filter(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n") + self.extra_frame
        size = self.header_chunk_bytes or len(response)
        for offset in range(0, len(response), size):
            super().write(response[offset:offset + size])

    def receive_frame(self):
        first, second = self.read(2)
        assert first & 0x80 and not first & 0x70 and second & 0x80, "client frames must be final, unextended and masked"
        length_code = second & 0x7f
        size = struct.unpack("!H", self.read(2))[0] if length_code == 126 else \
            struct.unpack("!Q", self.read(8))[0] if length_code == 127 else length_code
        assert size <= 1024 * 1024
        mask = self.read(4)
        masked = self.read(size)
        body = bytes(value ^ mask[index % 4] for index, value in enumerate(masked))
        observed = {"opcode": first & 0x0f, "mask": mask, "body": body, "length_code": length_code}
        self.frames.append(observed)
        return observed

    def receive(self):
        observed = self.receive_frame()
        assert observed["opcode"] == 1
        message = json.loads(observed["body"].decode("utf-8"))
        self.requests.append(message)
        return message

    def write(self, value):
        super().write(frame(value) if type(value) is dict else value)

    def end_output(self):
        stream = socket.socket(fileno=self.write_fd)
        try:
            stream.shutdown(socket.SHUT_WR)
        finally:
            stream.detach()

    def close(self):
        self.channel.close()
        if self.read_fd is not None:
            os.close(self.read_fd)
        self.read_fd = self.write_fd = None
        if self.thread is not None:
            self.thread.join(3)
            if self.thread.is_alive():
                raise AssertionError("fixture worker survived cleanup")


class WSRPCFixture(RPCFixture):
    def __init__(self, **limits):
        super().__init__(peer_type=WSPeer, transport_digest=WS_DIGEST, **limits)

    def initialize(self):
        def handshake(peer):
            peer.upgrade()
            request = peer.receive()
            assert request == {"id": "init-1", "method": "initialize", "params": {"clientInfo": CLIENT}}
            peer.write({"id": request["id"], "result": INITIALIZED})
            assert peer.receive() == {"method": "initialized", "params": {}}
        self.peer.start(handshake)
        result = self.rpc.initialize(CLIENT, request_id="init-1")
        self.peer.finish()
        return result
