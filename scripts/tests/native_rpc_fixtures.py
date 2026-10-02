"""Independent JSONL peer on real anonymous pipes; no native process or login."""
import json
import os
import select
import threading
import time

from relay_core.contracts import fingerprint
from relay_core.native_rpc import CodexRPC, JSONLChannel


CLIENT = {"name": "ccrelay-fixture", "title": "Offline fixture", "version": "1"}
INITIALIZED = {"userAgent": "fixture/1", "platformFamily": "unix", "platformOs": "fixture"}
TRANSPORT_DIGEST = fingerprint({"fixture_transport": "owned-stdio"})


class PipePeer:
    def __init__(self, *, timeout_ms=1000, max_frame_bytes=8192):
        client_read, self.write_fd = os.pipe()
        self.read_fd, client_write = os.pipe()
        for fd in (client_read, self.write_fd, self.read_fd, client_write):
            os.set_blocking(fd, False)
        self.channel = JSONLChannel(client_read, client_write, timeout_ms=timeout_ms, max_frame_bytes=max_frame_bytes)
        self.buffer, self.requests, self.errors = bytearray(), [], []
        self.thread = None

    def receive(self):
        deadline = time.monotonic() + 2
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.read_fd], [], [], remaining)[0]:
                raise AssertionError("fixture did not receive expected native frame")
            chunk = os.read(self.read_fd, 65536)
            if not chunk:
                raise EOFError("client stream closed")
            self.buffer.extend(chunk)
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer[:] = rest
        message = json.loads(line)
        self.requests.append(message)
        return message

    def write(self, value):
        body = value if type(value) is bytes else json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        deadline = time.monotonic() + 2
        while body:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.write_fd], [], remaining)[1]:
                raise AssertionError("fixture native write did not complete")
            body = body[os.write(self.write_fd, body):]

    def start(self, run):
        if self.thread is not None:
            self.finish()
        def worker():
            try:
                run(self)
            except Exception as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def finish(self):
        if self.thread is not None:
            self.thread.join(3)
            if self.thread.is_alive():
                raise AssertionError("fixture worker still running")
            self.thread = None
        if self.errors:
            raise self.errors.pop(0)

    def assert_quiet(self):
        if self.buffer or select.select([self.read_fd], [], [], 0)[0]:
            # EOF is quiet: closing an uncertain connection isn't a new RPC.
            if self.buffer or os.read(self.read_fd, 65536):
                raise AssertionError("unexpected native bytes")

    def end_output(self):
        os.close(self.write_fd)
        self.write_fd = None

    def close(self):
        self.channel.close()
        for fd in (self.read_fd, self.write_fd):
            if fd is not None:
                os.close(fd)
        self.read_fd = self.write_fd = None
        if self.thread is not None:
            self.thread.join(3)
            if self.thread.is_alive():
                raise AssertionError("fixture worker survived cleanup")


class RPCFixture:
    def __init__(self, *, peer_type=PipePeer, transport_digest=TRANSPORT_DIGEST, **limits):
        self.peer = peer_type(**limits)
        self.authorized, self.events, self.authorized_replies = [], [], []
        self.pin = transport_digest
        self.rpc = CodexRPC(self.peer.channel, verify_transport=lambda _: self.pin,
                            transport_digest=transport_digest, initialize_digest=fingerprint(INITIALIZED),
                            authorize=self.authorize, capture=self.capture, authorize_reply=self.authorize_reply)

    def authorize(self, method, parameters, *, request_id):
        self.authorized.append((method, parameters, request_id))
        return "fixture-admission"

    def capture(self, message, *, raw, kind, connection_id):
        self.events.append({"message": message, "raw": raw, "kind": kind, "connection_id": connection_id})

    def authorize_reply(self, request, response, *, connection_id):
        self.authorized_replies.append((request, response, connection_id))
        return "fixture-reply-admission"

    def initialize(self):
        def handshake(peer):
            request = peer.receive()
            assert request == {"id": "init-1", "method": "initialize", "params": {"clientInfo": CLIENT}}
            peer.write({"id": request["id"], "result": INITIALIZED})
            assert peer.receive() == {"method": "initialized", "params": {}}
        self.peer.start(handshake)
        result = self.rpc.initialize(CLIENT, request_id="init-1")
        self.peer.finish()
        return result

    def close(self):
        self.rpc.close()
        self.peer.close()
