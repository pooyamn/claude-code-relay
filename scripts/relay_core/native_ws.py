"""WebSocket framing on an explicit owned connected Unix stream, never discovery.

The protected launcher supplies the connection and verifies its peer/runtime.
HTTP Upgrade is not agent authentication. No socket path, login, TCP listener,
process launch, automatic reconnect or fallback is implemented here.
"""
import base64
import hashlib
import os
import re
import selectors
import socket
import struct
import time

from .identity import Denied
from .native_rpc import IOTimedOut, JSONLChannel, _decode, _encode


TRANSPORT = "codex-app-server-unix-websocket.v1"
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_HEADER_LIMIT = 16384


class UnixWSChannel(JSONLChannel):
    def __init__(self, fd, *, timeout_ms, max_frame_bytes):
        super().__init__(fd, fd, timeout_ms=timeout_ms, max_frame_bytes=max_frame_bytes)
        self._unix_stream()
        self.upgraded = False
        self.fragments, self.fragment_size = None, 0
        self.fragment_frames = 0

    def _unix_stream(self):
        stream = None
        try:
            stream = socket.socket(fileno=self.fds[0])
            if stream.family != socket.AF_UNIX or stream.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
                raise Denied("explicit connected Unix stream required; no TCP fallback")
            stream.getpeername()
        except OSError:
            raise Denied("explicit connected Unix stream required") from None
        finally:
            if stream is not None:
                stream.detach()  # The channel owns this FD, not this temporary view.

    def current(self):
        super().current()
        self._unix_stream()

    def _read_more(self, deadline, *, maximum):
        self._wait(self.fds[0], selectors.EVENT_READ, deadline)
        try:
            body = os.read(self.fds[0], min(65536, maximum - len(self.buffer)))
        except BlockingIOError:
            return
        if not body:
            raise Denied("native WebSocket ended; any pending outcome is unconfirmed")
        self.buffer.extend(body)

    def prepare(self, deadline, verify):
        verify()
        if self.upgraded:
            return
        try:
            key = base64.b64encode(os.urandom(16))
            request = (b"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                       b"Connection: Upgrade\r\nSec-WebSocket-Key: " + key +
                       b"\r\nSec-WebSocket-Version: 13\r\n\r\n")
            self._write_bytes(request, deadline)
            while b"\r\n\r\n" not in self.buffer:
                if len(self.buffer) >= _HEADER_LIMIT:
                    raise Denied("native upgrade header exceeds bound")
                self._read_more(deadline, maximum=_HEADER_LIMIT)
                verify()
            end = self.buffer.find(b"\r\n\r\n") + 4
            if end > _HEADER_LIMIT:
                raise Denied("native upgrade header exceeds bound")
            try:
                lines = bytes(self.buffer[:end - 4]).decode("ascii").split("\r\n")
            except UnicodeError:
                raise Denied("invalid native upgrade headers") from None
            if not re.fullmatch(r"HTTP/1\.1 101(?: [^\x00-\x1f\x7f]*)?", lines[0]) or len(lines) > 129:
                raise Denied("native upgrade rejected; no redirect/reconnect fallback")
            headers = {}
            for line in lines[1:]:
                name, colon, value = line.partition(":")
                name = name.lower()
                if not colon or not re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", name) or name in headers or \
                        any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in value):
                    raise Denied("invalid or duplicate native upgrade header")
                headers[name] = value.strip(" \t")
            expected = base64.b64encode(hashlib.sha1(key + _GUID, usedforsecurity=False).digest()).decode()
            if headers.get("upgrade", "").lower() != "websocket" or \
                    "upgrade" not in {part.strip().lower() for part in headers.get("connection", "").split(",")} or \
                    headers.get("sec-websocket-accept") != expected or \
                    set(headers) & {"sec-websocket-extensions", "sec-websocket-protocol", "transfer-encoding"} or \
                    headers.get("content-length", "0") != "0":
                raise Denied("native upgrade accept/extension contract differs")
            del self.buffer[:end]
            verify()
            self.upgraded = True
        except Exception:
            self.close()
            raise

    def _send_frame(self, opcode, body, deadline):
        try:
            if not self.upgraded:
                raise Denied("native WebSocket upgrade required before framed writes")
            if len(body) > self.max_frame or opcode >= 8 and len(body) > 125:
                raise Denied("native WebSocket output frame exceeds bound; no truncation")
            size = len(body)
            head = bytes((0x80 | opcode, 0x80 | size)) if size < 126 else \
                bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", size) if size < 65536 else \
                bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", size)
            mask = os.urandom(4)
            masked = bytes(value ^ mask[index % 4] for index, value in enumerate(body))
            self._write_bytes(head + mask + masked, deadline)
        except Exception:
            # A timed-out partial pong would otherwise be mistaken for an idle
            # read timeout and leave a corrupt connection eligible for new RPCs.
            self.close()
            raise

    def send(self, message, deadline):
        self._send_frame(1, _encode(message), deadline)

    def _frame(self, deadline):
        while True:
            self.current()
            if time.monotonic() >= deadline:
                raise IOTimedOut("native I/O deadline exceeded; outcome unconfirmed")
            if len(self.buffer) < 2:
                self._read_more(deadline, maximum=self.max_frame + 14)
                continue
            first, second = self.buffer[:2]
            fin, opcode, size = bool(first & 0x80), first & 0x0f, second & 0x7f
            if first & 0x70 or second & 0x80 or opcode not in {0, 1, 8, 9, 10} or opcode >= 8 and not fin:
                raise Denied("unsupported native WebSocket flags/opcode/masking")
            header = 2 + (2 if size == 126 else 8 if size == 127 else 0)
            if len(self.buffer) < header:
                self._read_more(deadline, maximum=self.max_frame + 14)
                continue
            if size == 126:
                size = struct.unpack("!H", self.buffer[2:header])[0]
                if size < 126:
                    raise Denied("nonminimal native WebSocket frame length")
            elif size == 127:
                size = struct.unpack("!Q", self.buffer[2:header])[0]
                if size < 65536 or size >= 2**63:
                    raise Denied("invalid native WebSocket frame length")
            if size > self.max_frame or opcode >= 8 and size > 125:
                raise Denied("native WebSocket input frame exceeds bound; no truncation")
            if len(self.buffer) < header + size:
                self._read_more(deadline, maximum=self.max_frame + 14)
                continue
            body = bytes(self.buffer[header:header + size])
            del self.buffer[:header + size]
            return fin, opcode, body

    def receive(self, deadline):
        if not self.upgraded:
            raise Denied("native WebSocket upgrade required before framed reads")
        for _ in range(4096):
            fin, opcode, body = self._frame(deadline)
            if opcode == 8:
                if len(body) == 1:
                    raise Denied("invalid native WebSocket close payload")
                if body:
                    code = struct.unpack("!H", body[:2])[0]
                    if code < 1000 or code >= 5000 or 1016 <= code < 3000 or code in {1004, 1005, 1006, 1015}:
                        raise Denied("invalid native WebSocket close code")
                    try:
                        body[2:].decode("utf-8")
                    except UnicodeError:
                        raise Denied("invalid native WebSocket close reason") from None
                self._send_frame(8, body, deadline)
                self.close()
                raise Denied("native WebSocket closed; any pending outcome is unconfirmed")
            if opcode == 9:
                self._send_frame(10, body, deadline)
                continue
            if opcode == 10:
                continue
            if opcode == 1:
                if self.fragments is not None:
                    raise Denied("new native text message before fragmented message finished")
                self.fragments, self.fragment_size = [], 0
                self.fragment_frames = 0
            elif self.fragments is None:
                raise Denied("native continuation without a text message")
            self.fragment_size += len(body)
            self.fragment_frames += 1
            if self.fragment_size > self.max_frame or self.fragment_frames > 4096:
                raise Denied("native fragmented message exceeds bound; no truncation")
            self.fragments.append(body)
            if fin:
                raw = b"".join(self.fragments)
                self.fragments, self.fragment_size = None, 0
                return _decode(raw), raw
        raise Denied("native WebSocket frame inspection bound reached")
