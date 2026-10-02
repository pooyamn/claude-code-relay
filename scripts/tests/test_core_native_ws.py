"""Real anonymous Unix streams and synthetic upgrade/RPC/gates, no live sockets."""
import json
import os
import socket
import struct
import unittest
from unittest import mock

from native_rpc_fixtures import CLIENT
from native_ws_fixtures import frame, WSRPCFixture
from relay_core.contracts import fingerprint
from relay_core.identity import Denied
from relay_core.native_rpc import IOTimedOut
from relay_core.native_ws import UnixWSChannel
import test_core_native_rpc as rpc_tests


class WSTests(unittest.TestCase):
    def fixture(self, **limits):
        wire = WSRPCFixture(**limits)
        self.addCleanup(wire.close)
        return wire

    def test_verified_upgrade_precedes_native_handshake_and_idle_goal_update(self):
        wire = self.fixture()
        wire.initialize()
        self.assertTrue(wire.peer.channel.upgraded)
        self.assertNotIn("Authorization:", wire.peer.upgrade_request)
        wire.peer.write({"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": None}})
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        self.assertEqual(wire.events[-1]["kind"], "notification")
        self.assertEqual(wire.events[-1]["message"]["method"], "thread/goal/updated")
        self.assertEqual([value["opcode"] for value in wire.peer.frames], [1, 1])
        wire.peer.assert_quiet()

    def test_bad_accept_redirect_duplicates_extensions_and_malformed_headers_never_send_json(self):
        transforms = (lambda body: body.replace(b"101 Switching Protocols", b"302 Found"),
                      lambda body: body.replace(b"Sec-WebSocket-Accept: ", b"Sec-WebSocket-Accept: wrong"),
                      lambda body: body.replace(b"Connection: Upgrade\r\n", b"Connection: Upgrade\r\nConnection: Upgrade\r\n"),
                      lambda body: body.replace(b"\r\n\r\n", b"\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n"),
                      lambda body: body.replace(b"\r\n\r\n", b"\r\nSec-WebSocket-Protocol: unexpected\r\n\r\n"),
                      lambda body: body.replace(b"Upgrade: websocket", b"Upgrade: not-websocket"),
                      lambda body: body.replace(b"\r\n\r\n", b"\r\nX-Test: bad\x00value\r\n\r\n"),
                      lambda body: body.replace(b"\r\n\r\n", b"\r\n malformed\r\n\r\n"),
                      lambda body: body.replace(b"\r\n\r\n", b"\r\nContent-Length: 1\r\n\r\n"))
        for transform in transforms:
            wire = self.fixture()
            wire.peer.header_filter = transform
            wire.peer.start(lambda peer: peer.upgrade())
            with self.assertRaises(Denied):
                wire.rpc.initialize(CLIENT, request_id="init-1")
            wire.peer.finish()
            self.assertEqual(wire.peer.requests, [])
            self.assertFalse(wire.rpc.initialized)
            self.assertTrue(wire.peer.channel.closed)
            wire.peer.assert_quiet()

    def test_header_limit_and_incomplete_upgrade_timeout_close_without_fallback(self):
        wire = self.fixture()
        # Supply exactly the header ceiling without a delimiter. The client
        # refuses it before a peer can finish an oversized response.
        wire.peer.header_filter = lambda body: (body[:-2] + b"X-Test: " + b"x" * 16384)[:16384]
        wire.peer.start(lambda peer: peer.upgrade())
        with self.assertRaisesRegex(Denied, "header exceeds"):
            wire.rpc.initialize(CLIENT, request_id="init-1")
        wire.peer.finish()
        self.assertTrue(wire.peer.channel.closed)
        wire.peer.assert_quiet()
        wire = self.fixture(timeout_ms=100)
        wire.peer.header_filter = lambda _: b"HTTP/1.1 101"
        wire.peer.start(lambda peer: peer.upgrade())
        with self.assertRaises(IOTimedOut):
            wire.rpc.initialize(CLIENT, request_id="init-1")
        wire.peer.finish()
        self.assertFalse(wire.rpc.initialized)
        self.assertTrue(wire.peer.channel.closed)
        wire.peer.assert_quiet()

    def test_fragmented_upgrade_preserves_coalesced_first_notification(self):
        wire = self.fixture()
        wire.peer.header_chunk_bytes = 7
        event = {"method": "warning", "params": {"message": "fixture"}}
        wire.peer.extra_frame = frame(event)
        wire.initialize()
        self.assertEqual([value["kind"] for value in wire.events], ["notification", "response"])
        self.assertEqual(wire.events[0]["message"], event)
        self.assertEqual(json.loads(wire.events[0]["raw"]), event)

    def test_pin_failure_before_and_after_upgrade_blocks_native_initialization(self):
        wire = self.fixture()
        wire.pin = fingerprint({"changed": True})
        with self.assertRaises(Denied):
            wire.rpc.initialize(CLIENT, request_id="init-1")
        wire.peer.assert_quiet()
        self.assertIsNone(wire.peer.upgrade_request)
        wire = self.fixture()
        def response(body):
            wire.pin = fingerprint({"changed": True})
            return body
        wire.peer.header_filter = response
        wire.peer.start(lambda peer: peer.upgrade())
        with self.assertRaises(Denied):
            wire.rpc.initialize(CLIENT, request_id="init-1")
        wire.peer.finish()
        wire.peer.assert_quiet()
        self.assertEqual(wire.peer.requests, [])

    def test_client_masks_all_payload_lengths_and_partial_writes_remain_one_frame(self):
        for length, code in ((1, None), (130, 126), (70000, 127)):
            wire = self.fixture(max_frame_bytes=100000)
            wire.initialize()
            wire.peer.start(lambda peer: (peer.receive(), peer.write({"id": 7, "result": {}})))
            real_write = os.write
            def partial(fd, body):
                return real_write(fd, body[:97] if fd == wire.peer.channel.fds[1] else body)
            with mock.patch("relay_core.native_rpc.os.write", side_effect=partial):
                result = wire.rpc.rpc("thread/read", {"text": "x" * length}, request_id=7)
            wire.peer.finish()
            self.assertEqual(result, {"id": 7, "result": {}})
            self.assertEqual(wire.peer.requests[-1]["params"], {"text": "x" * length})
            self.assertEqual(len(wire.peer.frames[-1]["mask"]), 4)
            if code is not None:
                self.assertEqual(wire.peer.frames[-1]["length_code"], code)
            wire.peer.assert_quiet()

    def test_fragmented_utf8_json_survives_idle_timeout_and_interleaved_ping(self):
        wire = self.fixture()
        wire.initialize()
        event = {"method": "item/agentMessage/delta", "params": {"delta": "🧩 done"}}
        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        split = body.index("🧩".encode()) + 1
        wire.peer.write(frame(body[:split], fin=False) + frame(b"alive", opcode=9))
        self.assertFalse(wire.rpc.poll(timeout_ms=10))
        pong = wire.peer.receive_frame()
        self.assertEqual((pong["opcode"], pong["body"]), (10, b"alive"))
        self.assertIsNotNone(wire.peer.channel.fragments)
        wire.peer.write(frame(body[split:], opcode=0))
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        self.assertEqual(wire.events[-1]["message"], event)
        self.assertEqual(wire.events[-1]["raw"], body)
        self.assertTrue(wire.rpc.initialized)

    def test_partial_frame_header_and_body_are_retained_across_idle_reads(self):
        wire = self.fixture()
        wire.initialize()
        event = {"method": "warning", "params": {"message": "x" * 200}}
        body = frame(event)
        wire.peer.write(body[:3])
        self.assertFalse(wire.rpc.poll(timeout_ms=10))
        wire.peer.write(body[3:-3])
        self.assertFalse(wire.rpc.poll(timeout_ms=10))
        wire.peer.write(body[-3:])
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        self.assertEqual(wire.events[-1]["message"], event)

    def test_server_mask_binary_reserved_bits_continuation_and_control_flags_reject(self):
        variants = (b"\xc1\x02{}", b"\x81\x82abcd{}", frame(b"{}", opcode=2),
                    frame(b"{}", opcode=0), frame(b"ping", opcode=9, fin=False),
                    frame(b"first", fin=False) + frame(b"new"), frame(b"x" * 126, opcode=9))
        for body in variants:
            wire = self.fixture()
            wire.initialize()
            wire.peer.write(body)
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=100)
            self.assertTrue(wire.peer.channel.closed)
            self.assertEqual(len(wire.events), 1)

    def test_nonminimal_signed_and_overlarge_lengths_reject_before_payload_allocation(self):
        variants = (b"\x81\x7e\x00\x02{}", b"\x81\x7f" + struct.pack("!Q", 2) + b"{}",
                    b"\x81\x7f" + struct.pack("!Q", 2**63), b"\x81\x7e" + struct.pack("!H", 600))
        for body in variants:
            wire = self.fixture(max_frame_bytes=512)
            wire.initialize()
            wire.peer.write(body)
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=100)
            self.assertTrue(wire.peer.channel.closed)
            self.assertLessEqual(len(wire.peer.channel.buffer), 32)

    def test_fragmented_message_budget_cannot_be_bypassed_by_individual_small_frames(self):
        wire = self.fixture(max_frame_bytes=512)
        wire.initialize()
        wire.peer.write(frame(b"x" * 300, fin=False))
        self.assertFalse(wire.rpc.poll(timeout_ms=10))
        wire.peer.write(frame(b"x" * 300, opcode=0))
        with self.assertRaisesRegex(Denied, "fragmented message exceeds"):
            wire.rpc.poll(timeout_ms=100)
        self.assertTrue(wire.peer.channel.closed)

    def test_json_encoding_duplicate_keys_and_unmatched_rpc_id_poison_connection(self):
        bodies = ('{"method":"warning","params":{}}'.encode("utf-16"),
                  b'{"method":"warning","params":{"text":"\xff"}}',
                  b'{"method":"warning","method":"warning"}',
                  b'{"method":"warning","params":{"value":NaN}}')
        for body in bodies:
            wire = self.fixture()
            wire.initialize()
            wire.peer.write(frame(body))
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=100)
            self.assertTrue(wire.peer.channel.closed)
        wire = self.fixture()
        wire.initialize()
        wire.peer.start(lambda peer: (peer.receive(), peer.write({"id": "7", "result": {}})))
        with self.assertRaises(Denied):
            wire.rpc.rpc("thread/read", {}, request_id=7)
        wire.peer.finish()
        wire.peer.assert_quiet()

    def test_interrupted_partial_pong_write_is_not_treated_as_an_idle_wait(self):
        wire = self.fixture()
        wire.initialize()
        wire.peer.write(frame(b"alive", opcode=9))
        def interrupted(body, deadline):
            os.write(wire.peer.channel.fds[1], body[:1])
            raise IOTimedOut("fixture partial transport-control write")
        with mock.patch.object(wire.peer.channel, "_write_bytes", side_effect=interrupted):
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=100)
        self.assertTrue(wire.peer.channel.closed)
        self.assertFalse(wire.rpc.initialized)
        self.assertEqual(wire.peer.read(1), b"\x8a")
        wire.peer.assert_quiet()

    def test_peer_close_is_echoed_but_is_not_a_native_stop_or_resume_receipt(self):
        wire = self.fixture()
        wire.initialize()
        body = struct.pack("!H", 1000) + b"fixture"
        wire.peer.write(frame(body, opcode=8))
        with self.assertRaisesRegex(Denied, "pending outcome is unconfirmed"):
            wire.rpc.poll(timeout_ms=100)
        reply = wire.peer.receive_frame()
        self.assertEqual((reply["opcode"], reply["body"]), (8, body))
        self.assertFalse(wire.rpc.initialized)
        self.assertTrue(wire.peer.channel.closed)
        wire.peer.assert_quiet()

    def test_invalid_close_payload_code_and_utf8_reason_cannot_confirm_stop(self):
        for body in (b"x", struct.pack("!H", 1005), struct.pack("!H", 2500), struct.pack("!H", 1000) + b"\xff"):
            wire = self.fixture()
            wire.initialize()
            wire.peer.write(frame(body, opcode=8))
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=100)
            self.assertTrue(wire.peer.channel.closed)
            wire.peer.assert_quiet()

    def test_explicit_approval_reply_uses_same_rpc_gates_and_never_autoapproves(self):
        wire = self.fixture()
        wire.initialize()
        def capture(message, **metadata):
            wire.capture(message, **metadata)
            if metadata["kind"] == "server_request":
                self.assertEqual(wire.authorized_replies, [])
                wire.rpc.reply(message["id"], connection_id=metadata["connection_id"], result={"decision": "decline"})
        wire.rpc.capture = capture
        def provider(peer):
            request = peer.receive()
            peer.write({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {}})
            self.assertEqual(peer.receive(), {"id": "approval-1", "result": {"decision": "decline"}})
            peer.write({"id": request["id"], "result": {}})
        wire.peer.start(provider)
        self.assertEqual(wire.rpc.rpc("thread/read", {}, request_id=7), {"id": 7, "result": {}})
        wire.peer.finish()
        self.assertEqual(len(wire.authorized_replies), 1)
        self.assertEqual(wire.rpc.server_requests, {})
        wire.peer.assert_quiet()

    def test_pipes_datagrams_tcp_and_unconnected_streams_cannot_become_unix_channel(self):
        read_fd, write_fd = os.pipe()
        try:
            os.set_blocking(read_fd, False)
            with self.assertRaises(Denied):
                UnixWSChannel(read_fd, timeout_ms=100, max_frame_bytes=512)
        finally:
            os.close(read_fd)
            os.close(write_fd)
        for family, kind in ((socket.AF_INET, socket.SOCK_STREAM), (socket.AF_UNIX, socket.SOCK_DGRAM),
                             (socket.AF_UNIX, socket.SOCK_STREAM)):
            with socket.socket(family, kind) as stream:
                stream.setblocking(False)
                with self.assertRaises(Denied):
                    UnixWSChannel(stream.fileno(), timeout_ms=100, max_frame_bytes=512)
                self.assertGreaterEqual(stream.fileno(), 0)  # Failed adoption preserves caller ownership.


class WSJoinedResumeTests(rpc_tests.JoinedResumeTests):
    wire_type = WSRPCFixture
