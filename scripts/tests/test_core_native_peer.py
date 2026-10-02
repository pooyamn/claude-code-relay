"""Real sockets/SQLite with substituted Linux credentials/proc facts on Mac."""
from contextlib import ExitStack
from dataclasses import replace
import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest import mock

from native_session_fixtures import native_fixture
from native_image_fixtures import executable_fixture
from native_ws_fixtures import WSRPCFixture
from relay_core import native_peer
from relay_core.contracts import fingerprint
from relay_core.identity import Denied, Peer, Policy
from relay_core.native_peer import KernelUnixPeer
from relay_core.native_ws import UnixWSChannel
from test_core_identity import policy_fields


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        fixture = native_fixture(Path(self.tmp.name))
        self.registry, self.authority = fixture.__enter__()
        self.addCleanup(lambda: fixture.__exit__(None, None, None))
        self.wire = WSRPCFixture()
        self.addCleanup(self.wire.close)
        self.fd = self.wire.peer.channel.fds[0]
        self.binding_digest = fingerprint(self.authority.registry.session("builder.task"))
        self.process_start = self.authority.observer(11).start_identity
        self.peer = Peer(13, 101, 121)
        self.sender = self.peer
        self.options, self.after_receive, self.raw_calls = {}, lambda: None, []
        self.transform_ancillary = lambda values: (values, 0)
        self.processes = {pid: self.authority.observer(pid) for pid in (11, 12, 21, 22)}
        self.processes[13] = replace(self.processes[11], pid=13)  # Native child inside builder.task's unit.
        self.authority.observer = lambda pid: self.processes[pid]
        original_socket = socket.socket
        owner = self

        class KernelView:
            """Only kernel options/ancillary metadata are substituted."""
            def __init__(self, *, fileno):
                self.stream = original_socket(fileno=fileno)
                self.fd = fileno
                self.family, self.type = self.stream.family, self.stream.type

            def getpeername(self):
                return self.stream.getpeername()

            def getsockopt(self, level, option, *args):
                if option == 60001:
                    return struct.pack("3i", owner.peer.pid, owner.peer.uid, owner.peer.gid)
                if option == 60002:
                    return owner.options.get(self.fd, 0)
                return self.stream.getsockopt(level, option, *args)

            def setsockopt(self, level, option, value):
                assert option == 60002
                owner.options[self.fd] = value

            def recvmsg(self, maximum, control_size):
                body = self.stream.recv(maximum)
                owner.raw_calls.append(maximum)
                sender = owner.sender
                ancillary, flags = owner.transform_ancillary([
                    (socket.SOL_SOCKET, 60003, struct.pack("3i", sender.pid, sender.uid, sender.gid))])
                owner.after_receive()
                return body, ancillary, flags, None

            def shutdown(self, how):
                self.stream.shutdown(how)

            def detach(self):
                return self.stream.detach()

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(native_peer.sys, "platform", "linux"))
        stack.enter_context(mock.patch.object(socket, "SO_PEERCRED", 60001, create=True))
        stack.enter_context(mock.patch.object(socket, "SO_PASSCRED", 60002, create=True))
        stack.enter_context(mock.patch.object(socket, "SCM_CREDENTIALS", 60003, create=True))
        stack.enter_context(mock.patch.object(socket, "socket", KernelView))

    def guard(self, **changes):
        arguments = dict(authority=self.authority, session_id="builder.task",
                         binding_digest=self.binding_digest, process_start=self.process_start)
        arguments.update(changes)
        return KernelUnixPeer(self.fd, **arguments)

    def attach(self):
        guard = self.guard()
        old = self.wire.peer.channel
        channel = UnixWSChannel(self.fd, timeout_ms=1000, max_frame_bytes=8192, kernel_peer=guard)
        old.closed = True  # Explicit fixture ownership transfer; never close the adopted FD twice.
        self.wire.peer.channel = self.wire.rpc.channel = channel
        self.wire.rpc.verify_transport = guard.verify
        self.wire.rpc.transport_digest = guard.digest
        return guard

    def test_current_binding_and_kernel_epoch_pin_without_consuming_native_data(self):
        guard = self.guard()
        self.assertEqual(guard.current().session_id, "builder.task")
        self.assertEqual(self.options[self.fd], 1)
        self.assertTrue(guard.digest.startswith("sha256:"))
        self.assertEqual(self.raw_calls, [])
        self.wire.peer.assert_quiet()
        os.fstat(self.fd)  # A borrowed socket view does not close the owned handle.

    def test_native_image_pin_joins_kernel_verification_and_denies_replacement_before_rpc(self):
        with executable_fixture(self.tmp.name) as image:
            guard = self.guard(executable=image.executable, executable_digest=image.byte_digest)
            channel = self.wire.peer.channel
            channel.kernel_peer = guard
            self.wire.rpc.verify_transport = guard.verify
            self.wire.rpc.transport_digest = guard.digest
            self.wire.initialize()
            os.replace(image.other, image.path)
            with self.assertRaises(Denied):
                self.wire.rpc.rpc("thread/read", {"threadId": "native-1"}, request_id=9)
            self.wire.peer.assert_quiet()
            self.assertTrue(channel.closed)

    def test_image_replacement_during_receive_cannot_supply_a_native_event(self):
        with executable_fixture(self.tmp.name) as image:
            guard = self.guard(executable=image.executable, executable_digest=image.byte_digest)
            channel = self.wire.peer.channel
            channel.kernel_peer = guard
            self.wire.rpc.verify_transport = guard.verify
            self.wire.rpc.transport_digest = guard.digest
            self.wire.initialize()
            self.after_receive = lambda: os.replace(image.other, image.path)
            self.wire.peer.write({"method": "warning", "params": {"message": "unverified image"}})
            with self.assertRaises(Denied):
                self.wire.rpc.poll(timeout_ms=100)
            self.assertEqual(len(self.wire.events), 1)
            self.assertTrue(channel.closed)

    def test_partial_image_pin_and_revoked_binding_during_hashing_deny_without_native_send(self):
        for changes in ({"executable": "/opt/ccrelay/native/v1/codex"}, {"executable_digest": "sha256:" + "a" * 64}):
            with self.assertRaises(Denied):
                self.guard(**changes)
        with executable_fixture(self.tmp.name) as image:
            image.after_read = lambda: self.authority.registry.revoke("builder.task")
            with self.assertRaises(Denied):
                self.guard(executable=image.executable, executable_digest=image.byte_digest)
        self.wire.peer.assert_quiet()

    def test_no_nonlinux_or_missing_credential_primitive_uid_fallback(self):
        with mock.patch.object(native_peer.sys, "platform", "darwin"):
            with self.assertRaisesRegex(Denied, "no UID fallback"):
                self.guard()
        with mock.patch.object(native_peer, "socket") as unavailable:
            unavailable.SO_PEERCRED = socket.SO_PEERCRED
            del unavailable.SO_PASSCRED
            with self.assertRaises(Denied):
                self.guard()
        os.fstat(self.fd)
        self.wire.peer.assert_quiet()

    def test_wrong_binding_session_start_or_kernel_role_cannot_make_a_pin(self):
        for changes in ({"binding_digest": fingerprint({"wrong": True})}, {"session_id": "reviewer.task"},
                        {"process_start": self.process_start[:-3] + "999"}, {"binding_digest": "invented"}):
            with self.assertRaises(Denied):
                self.guard(**changes)
        self.peer = Peer(22, 102, 121)
        with self.assertRaises(Denied):
            self.guard()
        self.peer = Peer(12, 101, 121)  # Same UID, but builder.other's execution.
        with self.assertRaises(Denied):
            self.guard()
        self.wire.peer.assert_quiet()

    def test_revoked_binding_changed_policy_and_changed_process_or_leader_deny(self):
        guard = self.guard()
        original = self.processes[13]
        for changed in (replace(original, uid=102), replace(original, start_identity=self.process_start[:-3] + "999"),
                        replace(original, cgroup="/wrong.service")):
            self.processes[13] = changed
            with self.assertRaises(Denied):
                guard.current()
        self.processes[13] = original
        leader = self.processes[11]
        self.processes[11] = replace(leader, start_identity=self.process_start[:-3] + "999")
        with self.assertRaises(Denied):
            guard.current()
        self.processes[11] = leader
        fields = policy_fields()
        fields["client_gid"] += 1
        self.authority.policy = Policy(fields)
        with self.assertRaises(Denied):
            guard.current()
        self.authority.policy = Policy(policy_fields())
        self.authority.registry.revoke("builder.task")
        with self.assertRaises(Denied):
            guard.current()

    def test_changed_passcred_connection_peer_or_blocking_flag_prevents_receive(self):
        guard = self.guard()
        self.options[self.fd] = 0
        with self.assertRaises(Denied):
            guard.current()
        self.options[self.fd] = 1
        self.peer = Peer(14, 101, 121)
        with self.assertRaises(Denied):
            guard.current()
        self.peer = Peer(13, 101, 121)
        os.set_blocking(self.fd, True)
        with self.assertRaises(Denied):
            guard.current()
        self.assertEqual(self.raw_calls, [])

    def test_verifier_requires_the_exact_credentialed_channel_no_plain_read_fallback(self):
        guard = self.guard()
        with self.assertRaises(Denied):
            guard.verify(self.wire.peer.channel)
        channel = self.wire.peer.channel
        channel.kernel_peer = guard
        self.assertEqual(guard.verify(channel), guard.digest)
        channel.kernel_peer = None
        with self.assertRaises(Denied):
            guard.verify(channel)
        with self.assertRaises(Denied):
            UnixWSChannel(self.fd, timeout_ms=100, max_frame_bytes=512, kernel_peer=lambda: True)

    def test_every_http_and_websocket_chunk_uses_credentialed_receive(self):
        guard = self.attach()
        self.wire.initialize()
        before = len(self.raw_calls)
        event = {"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": None}}
        self.wire.peer.write(event)
        self.assertTrue(self.wire.rpc.poll(timeout_ms=100))
        self.assertGreater(len(self.raw_calls), before)
        self.assertEqual(self.wire.events[-1]["message"], event)
        self.assertEqual(guard.verify(self.wire.peer.channel), guard.digest)
        self.wire.peer.assert_quiet()

    def test_forwarded_sender_after_valid_handshake_cannot_supply_event_or_ack(self):
        self.attach()
        self.wire.initialize()
        self.sender = Peer(14, 101, 121)  # Same UID, different sending process.
        self.wire.peer.write({"method": "warning", "params": {"message": "forwarded"}})
        with self.assertRaisesRegex(Denied, "mismatched kernel"):
            self.wire.rpc.poll(timeout_ms=100)
        self.assertEqual(len(self.wire.events), 1)
        self.assertTrue(self.wire.peer.channel.closed)
        self.assertFalse(self.wire.rpc.initialized)

    def test_missing_duplicate_truncated_and_unexpected_ancillary_are_denied(self):
        guard = self.guard()
        transforms = (lambda values: ([], 0), lambda values: (values + values, 0),
                      lambda values: (values, socket.MSG_CTRUNC), lambda values: (values, socket.MSG_TRUNC),
                      lambda values: (values + [(socket.SOL_SOCKET, 99999, b"unexpected")], 0))
        for transform in transforms:
            self.transform_ancillary = transform
            self.wire.peer.write(b"x")
            with self.assertRaises(Denied):
                guard.receive(1)

    def test_transferred_descriptors_are_closed_even_with_malformed_credentials(self):
        guard = self.guard()
        descriptor = os.open("/dev/null", os.O_RDONLY)
        def ancillary(values):
            invalid = (socket.SOL_SOCKET, 60003, struct.pack("3i", -1, 101, 121))
            rights = (socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack("i", descriptor))
            return [invalid, rights], 0
        self.transform_ancillary = ancillary
        self.wire.peer.write(b"x")
        with self.assertRaises(Denied):
            guard.receive(1)
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_revocation_while_reading_cannot_return_bytes_as_native_evidence(self):
        guard = self.guard()
        self.after_receive = lambda: self.authority.registry.revoke("builder.task")
        self.wire.peer.write(b"x")
        with self.assertRaises(Denied):
            guard.receive(1)
        self.assertEqual(self.raw_calls, [1])

    def test_request_bounds_do_not_receive_or_create_unowned_descriptors(self):
        guard = self.guard()
        for size in (0, True, 65538):
            with self.assertRaises(Denied):
                guard.receive(size)
        self.assertEqual(self.raw_calls, [])
        self.assertFalse(os.get_blocking(self.fd))
