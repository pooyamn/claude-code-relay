"""Pinned JSONL app-server connection on owned handles, not daemon discovery.

The protected launcher supplies exclusive nonblocking stdio handles and real
runtime/UID/generation verification. No process launch, login, connect, automatic
reconnect/retry, server-request approval or live entry point exists here.
"""
import json
import math
import os
import re
import selectors
import stat
import threading
import time
import uuid

from .contracts import fingerprint
from .identity import Denied, exact, identifier, integer


TRANSPORT = "codex-app-server-jsonl.v1"
_MISSING = object()


class IOTimedOut(Denied):
    pass


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise Denied("explicit reviewed transport/initialization digest required")
    return value


def _request_id(value):
    if type(value) is int and -(2**63) <= value < 2**63 or type(value) is str and 1 <= len(value) <= 200 and \
            not any(ord(char) < 32 for char in value):
        return value
    raise Denied("bounded typed RPC request ID required")


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Denied("duplicate native JSON key")
            result[key] = value
        return result
    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise Denied("non-finite native JSON number")
        return number
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=floating,
                           parse_constant=lambda _: (_ for _ in ()).throw(Denied("non-finite native JSON number")))
    except (ValueError, UnicodeError, RecursionError):
        raise Denied("malformed native JSON frame") from None
    # Native metrics may contain finite floats; protected financial/task
    # contracts still use their separate strict decoder.
    def bounded(item, depth=0):
        if depth > 32:
            raise Denied("native JSON nesting exceeds inspection bound")
        if type(item) is dict:
            for child in item.values():
                bounded(child, depth + 1)
        elif type(item) is list:
            for child in item:
                bounded(child, depth + 1)
    bounded(value)
    if type(value) is not dict or value.get("jsonrpc", "2.0") != "2.0" or \
            set(value) - {"jsonrpc", "id", "method", "params", "result", "error"}:
        raise Denied("unsupported native RPC envelope")
    return value


def _encode(message):
    try:
        return json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Denied("native output must be finite bounded JSON") from None


class JSONLChannel:
    """Own explicit pipe/socketpair FDs; socketpair fixtures are not UnixWS."""
    def __init__(self, read_fd, write_fd, *, timeout_ms, max_frame_bytes):
        integer(timeout_ms, 1)
        integer(max_frame_bytes, 1)
        if timeout_ms > 30000 or max_frame_bytes > 8 * 1024 * 1024:
            raise Denied("bounded explicit native I/O limits required")
        self.fds = (read_fd, write_fd)
        self.identities = {}
        for fd in set(self.fds):
            if type(fd) is not int or fd < 0:
                raise Denied("explicit owned native I/O handles required")
            metadata = os.fstat(fd)
            if not (stat.S_ISFIFO(metadata.st_mode) or stat.S_ISSOCK(metadata.st_mode)) or os.get_blocking(fd):
                raise Denied("exclusive nonblocking native stream handles required")
            self.identities[fd] = (metadata.st_dev, metadata.st_ino)
        self.timeout = timeout_ms / 1000
        self.max_frame = max_frame_bytes
        self.buffer = bytearray()
        self.closed = False
        self.write_lock = threading.Lock()

    def current(self):
        if self.closed:
            raise Denied("native channel closed; reconcile before any replacement")
        for fd, identity in self.identities.items():
            metadata = os.fstat(fd)
            if (metadata.st_dev, metadata.st_ino) != identity or os.get_blocking(fd):
                raise Denied("native stream handle changed")

    def _wait(self, fd, event, deadline):
        self.current()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IOTimedOut("native I/O deadline exceeded; outcome unconfirmed")
        with selectors.DefaultSelector() as selector:
            selector.register(fd, event)
            if not selector.select(remaining):
                raise IOTimedOut("native I/O deadline exceeded; outcome unconfirmed")

    def send(self, message, deadline):
        body = _encode(message)
        if len(body) > self.max_frame:
            raise Denied("native output frame exceeds bound; no truncation")
        with self.write_lock:
            offset = 0
            body += b"\n"
            while offset < len(body):
                self._wait(self.fds[1], selectors.EVENT_WRITE, deadline)
                try:
                    written = os.write(self.fds[1], body[offset:])
                except BlockingIOError:
                    continue
                if written <= 0:
                    raise Denied("native write incomplete; outcome unconfirmed")
                offset += written

    def receive(self, deadline):
        while True:
            self.current()
            if time.monotonic() >= deadline:
                raise IOTimedOut("native I/O deadline exceeded; outcome unconfirmed")
            end = self.buffer.find(b"\n")
            if end >= 0:
                if end > self.max_frame:
                    raise Denied("native input frame exceeds bound; no truncation")
                body = bytes(self.buffer[:end])
                del self.buffer[:end + 1]
                return _decode(body), body
            if len(self.buffer) > self.max_frame:
                raise Denied("native input frame exceeds bound; no truncation")
            self._wait(self.fds[0], selectors.EVENT_READ, deadline)
            try:
                body = os.read(self.fds[0], min(65536, self.max_frame + 1 - len(self.buffer)))
            except BlockingIOError:
                continue
            if not body:
                raise Denied("native stream ended; any pending outcome is unconfirmed")
            self.buffer.extend(body)

    def close(self):
        if self.closed:
            return
        self.closed = True
        for fd, identity in self.identities.items():
            try:
                metadata = os.fstat(fd)
                if (metadata.st_dev, metadata.st_ino) == identity:
                    os.close(fd)
            except OSError:
                pass


class CodexRPC:
    def __init__(self, channel, *, verify_transport, transport_digest, initialize_digest, authorize, capture, authorize_reply):
        if type(channel) is not JSONLChannel or not all(callable(value) for value in (verify_transport, authorize, capture, authorize_reply)):
            raise Denied("owned channel, protected identity/admission/capture/reply gates required")
        self.channel, self.verify_transport = channel, verify_transport
        self.transport_digest, self.initialize_digest = _hash(transport_digest), _hash(initialize_digest)
        self.authorize, self.capture, self.authorize_reply = authorize, capture, authorize_reply
        self.connection_id = "native-connection-" + uuid.uuid4().hex
        self.initialized = False
        self.request_ids, self.server_requests, self.server_ids = set(), {}, set()
        self.call_lock = threading.Lock()
        self.reply_lock = threading.Lock()

    def _current(self):
        self.channel.current()
        if self.verify_transport(self.channel) != self.transport_digest:
            raise Denied("native runtime/UID/generation/transport pin no longer current")

    def _exchange(self, method, parameters, request_id, deadline):
        key = (type(_request_id(request_id)), request_id)
        if key in self.request_ids or len(self.request_ids) >= 4096:
            raise Denied("RPC ID reused or connection inspection bound reached")
        self._current()
        self.request_ids.add(key)
        self.channel.send({"id": request_id, "method": method, "params": parameters}, deadline)
        for _ in range(4096):
            self._current()
            message, raw = self.channel.receive(deadline)
            self._current()
            if "method" in message:
                self._event(message, raw)
                continue
            if ("result" in message) == ("error" in message) or "id" not in message or \
                    type(message["id"]) is not type(request_id) or message["id"] != request_id or "params" in message:
                raise Denied("unmatched or ambiguous native response")
            self.capture(_decode(raw), raw=raw, kind="response", connection_id=self.connection_id)
            return message
        raise Denied("native event inspection bound reached")

    def _event(self, message, raw):
        if type(message.get("method")) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_/]{0,127}", message["method"]) or \
                set(message) & {"result", "error"}:
            raise Denied("unsupported native notification/request")
        kind = "notification"
        if "id" in message:
            server_id = (type(_request_id(message["id"])), message["id"])
            if server_id in self.server_ids or len(self.server_ids) >= 4096:
                raise Denied("server request ID reused or inspection bound reached")
            self.server_ids.add(server_id)
            self.server_requests[server_id] = raw
            kind = "server_request"
        self.capture(_decode(raw), raw=raw, kind=kind, connection_id=self.connection_id)

    def poll(self, *, timeout_ms):
        """Drain one idle-stream event; no background thread or implicit poller."""
        integer(timeout_ms, 1)
        if not self.initialized or timeout_ms > 30000 or not self.call_lock.acquire(blocking=False):
            raise Denied("initialized idle native stream and bounded wait required")
        try:
            self._current()
            message, raw = self.channel.receive(time.monotonic() + timeout_ms / 1000)
            self._current()
            self._event(message, raw)
            return True
        except IOTimedOut:
            try:
                self._current()
            except Exception:
                self.close()
                raise
            return False  # Expected idle wait, not an outstanding RPC timeout.
        except Exception:
            self.close()
            raise
        finally:
            self.call_lock.release()

    def initialize(self, client_info, *, request_id):
        exact(client_info, {"name", "title", "version"})
        if any(type(value) is not str or not 1 <= len(value) <= 128 or any(ord(char) < 32 for char in value) for value in client_info.values()):
            raise Denied("explicit bounded native client metadata required")
        if self.initialized or not self.call_lock.acquire(blocking=False):
            raise Denied("native connection already initialized or busy")
        try:
            deadline = time.monotonic() + self.channel.timeout
            response = self._exchange("initialize", {"clientInfo": dict(client_info)}, request_id, deadline)
            if "error" in response or type(response.get("result")) is not dict or fingerprint(response["result"]) != self.initialize_digest:
                raise Denied("native initialization/version contract differs")
            self._current()
            self.channel.send({"method": "initialized", "params": {}}, deadline)
            self.initialized = True
            return response
        except Exception:
            self.close()
            raise
        finally:
            self.call_lock.release()

    def rpc(self, method, parameters, *, request_id):
        if not self.initialized or type(method) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_/]{0,127}", method) or \
                method in {"initialize", "initialized"} or type(parameters) is not dict:
            raise Denied("initialized exact native method/parameters required")
        if not self.call_lock.acquire(blocking=False):
            raise Denied("native RPC already in flight; no implicit queue")
        try:
            self._current()
            _request_id(request_id)
            raw = _encode({"params": parameters})
            if len(raw) > self.channel.max_frame:
                raise Denied("native parameters exceed frame bound")
            parameters = _decode(raw)["params"]
            identifier(self.authorize(method, _decode(raw)["params"], request_id=request_id))
            return self._exchange(method, parameters, request_id, time.monotonic() + self.channel.timeout)
        except Exception:
            self.close()
            raise
        finally:
            self.call_lock.release()

    def reply(self, request_id, *, connection_id, result=_MISSING, error=_MISSING):
        key = (type(_request_id(request_id)), request_id)
        if not self.reply_lock.acquire(blocking=False):
            raise Denied("native reply already in flight; no implicit queue")
        try:
            raw = self.server_requests.get(key)
            if not self.initialized or connection_id != self.connection_id or raw is None or (result is _MISSING) == (error is _MISSING):
                raise Denied("exact pending server request and one authorized response required")
            try:
                self._current()
                response = {"id": request_id, "result": result} if error is _MISSING else {"id": request_id, "error": error}
                wire = _encode(response)
                response = _decode(wire)
                identifier(self.authorize_reply(_decode(raw), _decode(wire), connection_id=connection_id))
                self._current()
                self.channel.send(response, time.monotonic() + self.channel.timeout)
                del self.server_requests[key]
            except Exception:
                self.close()
                raise
        finally:
            self.reply_lock.release()

    def close(self):
        self.initialized = False
        self.channel.close()
