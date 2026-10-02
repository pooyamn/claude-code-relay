"""Real pipe framing/handshake, synthetic provider/gates; no live native fixture."""
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from native_rpc_fixtures import CLIENT, INITIALIZED, RPCFixture, TRANSPORT_DIGEST
from native_resume_fixtures import FakeResume, SETTINGS_DIGEST
from native_session_fixtures import CONTROLLER, enrollment, native_fixture, observation
from outbox_fixtures import CONTEXT, open_outbox
from relay_core.contracts import fingerprint
from relay_core.identity import Denied
from relay_core.native_rpc import CodexRPC, IOTimedOut, JSONLChannel
from relay_core.native_resume import CodexExactResume, resume_action


class RPCTests(unittest.TestCase):
    def fixture(self, **limits):
        wire = RPCFixture(**limits)
        self.addCleanup(wire.close)
        return wire

    def test_initialize_once_then_exact_rpc_with_no_config_or_transport_fallback(self):
        wire = self.fixture()
        with self.assertRaises(Denied):
            wire.rpc.rpc("thread/resume", {"threadId": "native-1"}, request_id=1)
        wire.peer.assert_quiet()
        self.assertEqual(wire.initialize()["result"], INITIALIZED)
        with self.assertRaises(Denied):
            wire.rpc.initialize(CLIENT, request_id="init-2")
        wire.peer.assert_quiet()
        def provider(peer):
            request = peer.receive()
            self.assertEqual(request, {"id": 7, "method": "thread/resume", "params": {"threadId": "native-1", "cwd": "/scratch/work"}})
            peer.write({"id": 7, "result": {"thread": {"id": "native-1"}}})
        wire.peer.start(provider)
        result = wire.rpc.rpc("thread/resume", {"threadId": "native-1", "cwd": "/scratch/work"}, request_id=7)
        wire.peer.finish()
        self.assertEqual(result["result"]["thread"]["id"], "native-1")
        self.assertEqual(len(wire.authorized), 1)
        self.assertEqual([event["kind"] for event in wire.events], ["response", "response"])
        self.assertTrue(wire.rpc.initialized)

    def test_initialization_error_wrong_pin_or_wrong_id_never_emits_initialized(self):
        variants = ({"id": "init-1", "error": {"code": -1}},
                    {"id": "init-1", "result": {**INITIALIZED, "userAgent": "changed/2"}},
                    {"id": "foreign", "result": INITIALIZED})
        for value in variants:
            wire = self.fixture()
            wire.peer.start(lambda peer: (peer.receive(), peer.write(value)))
            with self.assertRaises(Denied):
                wire.rpc.initialize(CLIENT, request_id="init-1")
            wire.peer.finish()
            wire.peer.assert_quiet()
            self.assertTrue(wire.peer.channel.closed)
            self.assertFalse(wire.rpc.initialized)

    def test_real_fragmented_reads_and_partial_writes_preserve_complete_frames(self):
        wire = self.fixture()
        wire.initialize()
        def provider(peer):
            request = peer.receive()
            self.assertEqual(request["params"], {"text": "🧩" * 30})
            body = json.dumps({"id": "read-1", "result": {"ok": True}}).encode() + b"\n"
            for offset in range(0, len(body), 3):
                peer.write(body[offset:offset + 3])
        wire.peer.start(provider)
        real_write = os.write
        def partial(fd, body):
            return real_write(fd, body[:7] if fd == wire.peer.channel.fds[1] else body)
        with mock.patch("relay_core.native_rpc.os.write", side_effect=partial):
            result = wire.rpc.rpc("thread/read", {"text": "🧩" * 30}, request_id="read-1")
        wire.peer.finish()
        self.assertTrue(result["result"]["ok"])

    def test_notifications_requests_and_response_are_captured_without_autoapproval(self):
        wire = self.fixture()
        wire.initialize()
        def provider(peer):
            request = peer.receive()
            peer.write({"method": "item/agentMessage/delta", "params": {"threadId": "foreign", "delta": "work"}})
            peer.write({"id": 20, "method": "item/commandExecution/requestApproval", "params": {"threadId": "native-1"}})
            peer.write({"id": request["id"], "result": {"ok": True}})
        wire.peer.start(provider)
        wire.rpc.rpc("thread/read", {"threadId": "native-1"}, request_id="read-1")
        wire.peer.finish()
        self.assertEqual([event["kind"] for event in wire.events][-3:], ["notification", "server_request", "response"])
        for event in wire.events:
            self.assertEqual(json.loads(event["raw"]), event["message"])
            self.assertEqual(event["connection_id"], wire.rpc.connection_id)
        self.assertEqual(wire.authorized_replies, [])
        wire.peer.assert_quiet()
        self.assertIn((int, 20), wire.rpc.server_requests)

    def test_idle_goal_tool_events_and_partial_frame_timeout_keep_connection(self):
        wire = self.fixture()
        wire.initialize()
        self.assertFalse(wire.rpc.poll(timeout_ms=10))
        wire.peer.write(b'{"method":"thread/goal/updated",')
        self.assertFalse(wire.rpc.poll(timeout_ms=10))
        self.assertTrue(wire.peer.channel.buffer)
        wire.peer.write(b'"params":{"threadId":"native-1","goal":null}}\n')
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        wire.peer.write({"method": "item/commandExecution/outputDelta", "params": {"delta": "done", "duration": 1.5}})
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        self.assertEqual(wire.events[-2]["message"]["method"], "thread/goal/updated")
        self.assertEqual(wire.events[-1]["message"]["params"]["duration"], 1.5)
        self.assertTrue(wire.rpc.initialized)
        wire.peer.assert_quiet()

    def test_typed_ids_and_unmatched_or_ambiguous_responses_poison_without_retry(self):
        variants = ({"id": "7", "result": {}}, {"id": True, "result": {}},
                    {"id": 8, "result": {}}, {"id": 7, "result": {}, "error": {}},
                    {"id": 7, "result": {}, "params": {}}, {"result": {}},
                    {"id": 7, "jsonrpc": "1.0", "result": {}})
        for value in variants:
            wire = self.fixture()
            wire.initialize()
            wire.peer.start(lambda peer: (peer.receive(), peer.write(value)))
            with self.assertRaises(Denied):
                wire.rpc.rpc("thread/read", {}, request_id=7)
            wire.peer.finish()
            self.assertEqual(len(wire.authorized), 1)
            wire.peer.assert_quiet()
            self.assertTrue(wire.peer.channel.closed)
            with self.assertRaises(Denied):
                wire.rpc.rpc("thread/read", {}, request_id=7)

    def test_native_error_is_returned_not_retried_or_reclassified_by_prose(self):
        wire = self.fixture()
        wire.initialize()
        value = {"id": 7, "error": {"code": -32000, "message": "fixture capacity", "data": {"kind": "fixture"}}}
        wire.peer.start(lambda peer: (peer.receive(), peer.write(value)))
        self.assertEqual(wire.rpc.rpc("thread/read", {}, request_id=7), value)
        wire.peer.finish()
        self.assertTrue(wire.rpc.initialized)
        wire.peer.assert_quiet()
        with self.assertRaises(Denied):
            wire.rpc.rpc("thread/read", {}, request_id=7)
        wire.peer.assert_quiet()

    def test_eof_after_request_is_unknown_and_no_new_call_is_possible(self):
        wire = self.fixture()
        wire.initialize()
        wire.peer.start(lambda peer: (peer.receive(), peer.end_output()))
        with self.assertRaisesRegex(Denied, "outcome is unconfirmed"):
            wire.rpc.rpc("thread/resume", {"threadId": "native-1"}, request_id="resume-1")
        wire.peer.finish()
        wire.peer.assert_quiet()
        with self.assertRaises(Denied):
            wire.rpc.rpc("thread/start", {}, request_id="replacement")

    def test_outstanding_rpc_timeout_closes_without_replaying_request(self):
        wire = self.fixture(timeout_ms=100)
        wire.initialize()
        wire.peer.start(lambda peer: peer.receive())
        with self.assertRaises(IOTimedOut):
            wire.rpc.rpc("thread/resume", {"threadId": "native-1"}, request_id="resume-1")
        wire.peer.finish()
        wire.peer.assert_quiet()
        self.assertTrue(wire.peer.channel.closed)

    def test_duplicate_keys_nonfinite_utf8_depth_and_invalid_events_are_not_dropped(self):
        variants = (b'{"method":"warning","method":"warning"}\n',
                    '{"method":"warning","params":{}}'.encode("utf-16") + b"\n",
                    b'{"method":"warning","params":{"value":NaN}}\n',
                    b'{"method":"warning","params":{"value":1e999}}\n',
                    b'{"method":"warning","params":{"value":"\xff"}}\n',
                    b'{"method":"warning","params":' + b'[' * 35 + b'0' + b']' * 35 + b'}\n',
                    b'{"method":"invalid event","params":{}}\n',
                    b'{"method":"warning","result":{}}\n', b'{"method":"warning","extra":true}\n')
        for value in variants:
            wire = self.fixture()
            wire.initialize()
            wire.peer.write(value)
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=100)
            self.assertTrue(wire.peer.channel.closed)
            self.assertEqual(len(wire.events), 1)

    def test_input_and_output_frame_bounds_refuse_without_truncation(self):
        wire = self.fixture(max_frame_bytes=512)
        wire.initialize()
        wire.peer.write(b'{"method":"warning","params":{"text":"' + b'x' * 550 + b'"}}\n')
        with self.assertRaisesRegex(Denied, "input frame exceeds"):
            wire.rpc.poll(timeout_ms=100)
        self.assertTrue(wire.peer.channel.closed)
        wire = self.fixture(max_frame_bytes=512)
        wire.initialize()
        with self.assertRaises(Denied):
            wire.rpc.rpc("thread/read", {"text": "x" * 550}, request_id=7)
        self.assertEqual(wire.authorized, [])
        wire.peer.assert_quiet()

    def test_transport_pin_or_authorization_failure_prevents_native_write(self):
        for fail_pin in (True, False):
            wire = self.fixture()
            wire.initialize()
            if fail_pin:
                wire.pin = fingerprint({"fixture_transport": "changed"})
            else:
                def denied(*args, **kwargs):
                    raise Denied("fixture admission rejected")
                wire.rpc.authorize = denied
            with self.assertRaises(Denied):
                wire.rpc.rpc("thread/resume", {"threadId": "native-1"}, request_id=7)
            wire.peer.assert_quiet()
            self.assertTrue(wire.peer.channel.closed)

    def test_pin_change_after_read_or_idle_timeout_closes_before_trusting_event(self):
        for idle in (False, True):
            wire = self.fixture()
            wire.initialize()
            observations = []
            def pin(channel):
                observations.append(True)
                return TRANSPORT_DIGEST if len(observations) == 1 else fingerprint({"changed": True})
            wire.rpc.verify_transport = pin
            if not idle:
                wire.peer.write({"method": "warning", "params": {"message": "fixture"}})
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=10)
            self.assertTrue(wire.peer.channel.closed)
            self.assertEqual(len(wire.events), 1)

    def test_capture_failure_and_capture_mutation_cannot_manufacture_rpc_ack(self):
        for failure in (True, False):
            wire = self.fixture()
            wire.initialize()
            def capture(message, **kwargs):
                if failure:
                    raise Denied("fixture capture not durable")
                message["id"] = "invented"
                message["result"] = {"thread": {"id": "invented"}}
            wire.rpc.capture = capture
            wire.peer.start(lambda peer: (peer.receive(), peer.write({"id": 7, "result": {"thread": {"id": "native-1"}}})))
            if failure:
                with self.assertRaises(Denied):
                    wire.rpc.rpc("thread/read", {}, request_id=7)
                self.assertTrue(wire.peer.channel.closed)
            else:
                result = wire.rpc.rpc("thread/read", {}, request_id=7)
                self.assertEqual(result, {"id": 7, "result": {"thread": {"id": "native-1"}}})
            wire.peer.finish()

    def test_authorization_mutation_cannot_change_the_wire_parameters(self):
        wire = self.fixture()
        wire.initialize()
        parameters = {"threadId": "native-1", "input": [{"text": "original"}]}
        def authorize(method, value, **kwargs):
            value["threadId"] = "injected"
            value["input"][0]["text"] = "injected"
            parameters["input"][0]["text"] = "caller-changed"
            return "fixture-admission"
        wire.rpc.authorize = authorize
        wire.peer.start(lambda peer: (peer.receive(), peer.write({"id": 7, "result": {}})))
        wire.rpc.rpc("turn/start", parameters, request_id=7)
        wire.peer.finish()
        self.assertEqual(wire.peer.requests[-1]["params"], {"threadId": "native-1", "input": [{"text": "original"}]})

    def test_server_reply_requires_exact_connection_typed_id_and_current_gate(self):
        wire = self.fixture()
        wire.initialize()
        request = {"id": 20, "method": "item/commandExecution/requestApproval", "params": {"threadId": "native-1"}}
        wire.peer.write(request)
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        for request_id, connection_id in (("20", wire.rpc.connection_id), (20, "foreign-connection")):
            with self.assertRaises(Denied):
                wire.rpc.reply(request_id, connection_id=connection_id, result=None)
        wire.peer.assert_quiet()
        def gate(original, response, **kwargs):
            self.assertEqual(original, request)
            original["params"]["threadId"] = "injected"
            response["result"] = "injected"
            return "fixture-reply-admission"
        wire.rpc.authorize_reply = gate
        wire.rpc.reply(20, connection_id=wire.rpc.connection_id, result=None)
        self.assertEqual(wire.peer.receive(), {"id": 20, "result": None})
        with self.assertRaises(Denied):
            wire.rpc.reply(20, connection_id=wire.rpc.connection_id, result=None)
        wire.peer.assert_quiet()
        wire.peer.write(request)
        with self.assertRaises(Denied):
            wire.rpc.poll(timeout_ms=100)
        self.assertTrue(wire.peer.channel.closed)

    def test_concurrent_server_replies_cannot_write_twice(self):
        wire = self.fixture()
        wire.initialize()
        wire.peer.write({"id": 20, "method": "item/commandExecution/requestApproval", "params": {}})
        self.assertTrue(wire.rpc.poll(timeout_ms=100))
        entered, release, errors = threading.Event(), threading.Event(), []
        def gate(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise AssertionError("fixture gate not released")
            return "fixture-reply-admission"
        wire.rpc.authorize_reply = gate
        def first():
            try:
                wire.rpc.reply(20, connection_id=wire.rpc.connection_id, result={"decision": "decline"})
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=first, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaisesRegex(Denied, "reply already in flight"):
                wire.rpc.reply(20, connection_id=wire.rpc.connection_id, result={"decision": "accept"})
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(wire.peer.receive(), {"id": 20, "result": {"decision": "decline"}})
        wire.peer.assert_quiet()

    def test_denied_reply_keeps_unknown_pending_request_and_does_not_write(self):
        wire = self.fixture()
        wire.initialize()
        wire.peer.write({"id": 20, "method": "item/commandExecution/requestApproval", "params": {}})
        wire.rpc.poll(timeout_ms=100)
        def denied(*args, **kwargs):
            raise Denied("fixture reply unauthorized")
        wire.rpc.authorize_reply = denied
        with self.assertRaises(Denied):
            wire.rpc.reply(20, connection_id=wire.rpc.connection_id, result={"decision": "accept"})
        self.assertIn((int, 20), wire.rpc.server_requests)
        self.assertTrue(wire.peer.channel.closed)
        wire.peer.assert_quiet()

    def test_reply_rechecks_transport_after_authorization_before_any_write(self):
        wire = self.fixture()
        wire.initialize()
        wire.peer.write({"id": 20, "method": "item/commandExecution/requestApproval", "params": {}})
        wire.rpc.poll(timeout_ms=100)
        def gate(*args, **kwargs):
            wire.pin = fingerprint({"changed": True})
            return "fixture-reply-admission"
        wire.rpc.authorize_reply = gate
        with self.assertRaises(Denied):
            wire.rpc.reply(20, connection_id=wire.rpc.connection_id, result={"decision": "decline"})
        wire.peer.assert_quiet()
        self.assertIn((int, 20), wire.rpc.server_requests)
        self.assertTrue(wire.peer.channel.closed)

    def test_explicit_server_reply_can_unblock_inflight_rpc_without_autoapproval(self):
        wire = self.fixture()
        wire.initialize()
        def capture(message, **metadata):
            wire.capture(message, **metadata)
            if metadata["kind"] == "server_request":
                wire.rpc.reply(message["id"], connection_id=metadata["connection_id"],
                               result={"decision": "decline"})
        wire.rpc.capture = capture
        def provider(peer):
            request = peer.receive()
            peer.write({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {}})
            self.assertEqual(peer.receive(), {"id": "approval-1", "result": {"decision": "decline"}})
            peer.write({"id": request["id"], "result": {"observed": True}})
        wire.peer.start(provider)
        self.assertEqual(wire.rpc.rpc("thread/read", {}, request_id=7)["result"], {"observed": True})
        wire.peer.finish()
        self.assertEqual(len(wire.authorized_replies), 1)
        self.assertEqual(wire.rpc.server_requests, {})
        wire.peer.assert_quiet()

    def test_no_implicit_rpc_queue_or_poll_during_existing_call(self):
        wire = self.fixture()
        wire.initialize()
        wire.rpc.call_lock.acquire()
        try:
            with self.assertRaises(Denied):
                wire.rpc.rpc("thread/read", {}, request_id=7)
            with self.assertRaises(Denied):
                wire.rpc.poll(timeout_ms=10)
        finally:
            wire.rpc.call_lock.release()
        wire.peer.assert_quiet()
        self.assertTrue(wire.rpc.initialized)

    def test_explicit_handles_limits_and_required_trusted_gates(self):
        wire = self.fixture()
        for changes in ({"verify_transport": None}, {"authorize": None}, {"capture": None},
                        {"authorize_reply": None}, {"transport_digest": "invented"}, {"initialize_digest": "invented"}):
            arguments = dict(verify_transport=lambda _: TRANSPORT_DIGEST, transport_digest=TRANSPORT_DIGEST,
                             initialize_digest=fingerprint(INITIALIZED), authorize=wire.authorize,
                             capture=wire.capture, authorize_reply=wire.authorize_reply)
            arguments.update(changes)
            with self.assertRaises(Denied):
                CodexRPC(wire.peer.channel, **arguments)
        for timeout, maximum in ((0, 100), (30001, 100), (100, 0), (100, 8 * 1024 * 1024 + 1)):
            with self.assertRaises(Denied):
                JSONLChannel(*wire.peer.channel.fds, timeout_ms=timeout, max_frame_bytes=maximum)
        os.set_blocking(wire.peer.channel.fds[0], True)
        with self.assertRaises(Denied):
            JSONLChannel(*wire.peer.channel.fds, timeout_ms=100, max_frame_bytes=100)
        with self.assertRaises(Denied):
            wire.peer.channel.current()
        with tempfile.TemporaryFile() as regular:
            os.set_blocking(regular.fileno(), False)
            with self.assertRaises(Denied):
                JSONLChannel(regular.fileno(), regular.fileno(), timeout_ms=100, max_frame_bytes=100)


class JoinedResumeTests(unittest.TestCase):
    wire_type = RPCFixture

    def test_durable_resume_uses_initialized_real_pipe_and_lost_ack_is_never_replayed(self):
        for lose_ack in (False, True):
            with self.subTest(lose_ack=lose_ack), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                observations = []
                def inspect(binding, record, probe_id):
                    observations.append(record)
                    return observation(binding, record, probe_id)
                with native_fixture(folder, observer=inspect) as (registry, authority), \
                        closing(open_outbox(folder / "outbox", policy_digest=authority.policy.digest)) as ledger:
                    registry.enroll(CONTROLLER, enrollment())
                    ledger.store(resume_action(registry._row("builder.task"), "resume-1", settings_digest=SETTINGS_DIGEST), CONTEXT)
                    wire = self.wire_type()
                    try:
                        wire.initialize()
                        def provider(peer):
                            request = peer.receive()
                            native = FakeResume(folder / "provider.sqlite")
                            try:
                                response = native.rpc(request["method"], request["params"], request_id=request["id"])
                            finally:
                                native.close()
                            if lose_ack:
                                peer.end_output()
                            else:
                                peer.write(response)
                        wire.peer.start(provider)
                        adapter = CodexExactResume(wire.rpc.rpc, authorize=lambda *_: "fixture-admission", resume_supported=True)
                        result = adapter.deliver(ledger, "resume-1", "resume-attempt", registry, CONTROLLER)
                        wire.peer.finish()
                        self.assertEqual(result["state"], "unknown" if lose_ack else "confirmed")
                        self.assertEqual(len(observations), 0 if lose_ack else 1)
                        self.assertEqual(len(wire.authorized), 1)
                        native = FakeResume(folder / "provider.sqlite")
                        try:
                            self.assertEqual(native.count(), 1)
                            self.assertEqual(adapter.deliver(ledger, "resume-1", "resume-attempt", registry, CONTROLLER)["state"], result["state"])
                            self.assertEqual(native.count(), 1)
                        finally:
                            native.close()
                        wire.peer.assert_quiet()
                    finally:
                        wire.close()
