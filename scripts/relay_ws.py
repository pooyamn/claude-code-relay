"""Minimal WebSocket client over a unix socket (stdlib only).

The codex remote-control daemon serves the app-server protocol on
~/.codex/app-server-control/app-server-control.sock, framed as WEBSOCKET text
messages -- not newline-delimited JSON like `codex app-server` on stdio. Raw
JSON lines written to that socket are silently ignored, which is why it looked
for weeks as if the daemon refused local clients (measured 2026-09-29: an HTTP
Upgrade gets "101 Switching Protocols" and initialize answers immediately).

Exposes the two things Conn needs from a transport: write(text) and an iterator
of complete text messages.
"""
import base64
import os
import socket
import struct
import threading

DAEMON_SOCK = os.path.expanduser("~/.codex/app-server-control/app-server-control.sock")


class WSClosed(Exception):
    pass


class UnixWS:
    def __init__(self, path=DAEMON_SOCK, timeout=10):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSClosed("closed during handshake")
            head += chunk
        status, _, self._buf = head.partition(b"\r\n\r\n")
        if b" 101 " not in status.split(b"\r\n", 1)[0]:
            raise WSClosed("handshake refused: " + status[:120].decode(errors="replace"))
        self.sock.settimeout(None)
        self._wlock = threading.Lock()
        self.closed = False

    # --- framing ------------------------------------------------------------
    def _frame(self, opcode, payload):
        n = len(payload)
        if n < 126:
            hdr = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        mask = os.urandom(4)
        body = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        with self._wlock:
            self.sock.sendall(hdr + mask + body)

    def write(self, text):
        if self.closed:
            raise WSClosed("write on closed socket")
        self._frame(0x1, text.encode())

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSClosed("peer closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        """One complete text message (reassembling fragments), or raise WSClosed."""
        parts = []
        while True:
            b0, b1 = self._read(2)
            fin, op, n = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
            if op == 0x8:
                self.closed = True
                raise WSClosed("close frame")
            if op == 0x9:
                self._frame(0xA, data)          # ping -> pong
                continue
            if op == 0xA:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode(errors="replace")

    def __iter__(self):
        while True:
            try:
                yield self.recv()
            except (WSClosed, OSError):
                self.closed = True
                return

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self._frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
