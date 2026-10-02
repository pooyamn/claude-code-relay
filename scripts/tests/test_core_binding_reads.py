"""Protected read-channel conformance, not actual split-UID WSL acceptance.

The joined tests use real private scratch SQLite and outbox transactions. Only
Linux socket/process/ancestor observations are substituted; no native/bot calls.
"""
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest import mock

import ccrelay_broker
from relay_core import binding_reads, broker_wire, identity
from relay_core.binding_reads import BindingReadClient, BindingReadPolicy, BrokerBindingReads, REQUEST_SCHEMA
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Authority, Denied, Peer, Policy
from relay_core.telegram_producers import TelegramProducers
from relay_core.telegram_scheduler import TelegramScheduler
from source_grant_fixtures import CONTROLLER, sources
from telegram_fixtures import reply
from test_core_identity import policy_fields, request as worker_request
from test_core_telegram import TelegramFixture


def read_fields(policy, *, uid=None, roles=None, enabled=True):
    return {"schema": "ccrelay.binding_read_policy.v1", "enabled": enabled, "broker_policy_digest": policy.digest,
            "readers": [{"uid": os.geteuid() if uid is None else uid, "roles": list(policy.roles) if roles is None else roles}]}


def read_request(policy, session="builder.fixture", **extra):
    return {"schema": REQUEST_SCHEMA, "request_id": "binding-read-fixture", "method": "read_session",
            "args": {"session_id": session, "broker_policy_digest": policy.broker_policy.digest,
                     "reader_policy_digest": policy.digest}, **extra}


class ReadPolicyTests(unittest.TestCase):
    def setUp(self):
        self.broker = Policy(policy_fields())

    def test_no_worker_or_broker_can_be_enrolled_as_a_component_reader(self):
        for uid in (101, 102, 103, 104, self.broker.broker_uid, True):
            with self.assertRaises(Denied):
                BindingReadPolicy(read_fields(self.broker, uid=uid), self.broker)

    def test_unknown_empty_duplicate_escalating_or_drifted_policy_is_denied(self):
        raw = read_fields(self.broker)
        for changed in ({"schema": "ccrelay.binding_read_policy.v999"}, {"readers": []}, {"enabled": 1},
                        {"broker_policy_digest": "sha256:" + "f" * 64}, {"readers": raw["readers"] * 2},
                        {"unexpected": True}):
            with self.assertRaises(Denied):
                BindingReadPolicy({**raw, **changed}, self.broker)
        for roles in ([], ["builder", "builder"], ["owner"], [True]):
            with self.assertRaises(Denied):
                BindingReadPolicy(read_fields(self.broker, roles=roles), self.broker)

    def test_disabled_or_unregistered_local_reader_never_contacts_a_socket(self):
        for fields in (read_fields(self.broker, enabled=False), read_fields(self.broker, uid=98)):
            client = BindingReadClient("/run/synthetic/actions.sock", BindingReadPolicy(fields, self.broker))
            with mock.patch.object(binding_reads, "client_request") as transport, self.assertRaises(Denied):
                client.session("builder.fixture")
            transport.assert_not_called()
        for path in ("relative.sock", "/run/../fake.sock", "/run/fake\x00.sock"):
            with self.assertRaises(Denied):
                BindingReadClient(path, BindingReadPolicy(read_fields(self.broker), self.broker))

    def test_loading_a_reader_policy_requires_root_owned_protected_artifact(self):
        with mock.patch.object(binding_reads, "protected_path", side_effect=Denied("fixture unprotected policy")) as check:
            with self.assertRaises(Denied):
                BindingReadPolicy.load("/untrusted/policy.json", self.broker)
            check.assert_called_once_with("/untrusted/policy.json", owners={0})


class JoinedReadTests(TelegramFixture):
    def setUp(self):
        super().setUp()
        self.context_allowed = True
        self.fixture = sources(self.folder / "source", self.ledger,
                               current_check=lambda body, binding: self.context_allowed)
        self.grants, self.server_authority = self.fixture.__enter__()
        self.addCleanup(lambda: self.fixture.__exit__(None, None, None))
        self.policy = BindingReadPolicy(read_fields(self.server_authority.policy), self.server_authority.policy)
        self.reads = BrokerBindingReads(self.server_authority, self.policy)
        self.client = BindingReadClient("/run/synthetic/actions.sock", self.policy)
        self.grants.authority = Authority(self.server_authority.policy, self.client)
        self.calls = []
        patcher = mock.patch.object(binding_reads, "client_request", side_effect=self.rpc)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.transport = patcher
        self.producer = TelegramProducers(self.ledger, authorize_source=self.grants.enrollment_allowed)
        self.scheduler = TelegramScheduler(self.ledger, self.bot, self.store, ownership_check=self.guard.check,
                                            authorize_dispatch=self.grants.authorize)

    def rpc(self, path, request, *, broker_uid, timeout):
        self.assertEqual((path, broker_uid, timeout), (self.client.path, self.server_authority.policy.broker_uid, 3))
        # Canonical framing and the actual broker dispatcher/registry remain
        # real; kernel sender observations are explicitly supplied by the fixture.
        request = identity.strict_json(canonical_bytes(request))
        self.calls.append(copy.deepcopy(request))
        out = ccrelay_broker.dispatch(self.server_authority, Peer(61, os.geteuid(), 121), request, binding_reads=self.reads)
        return {**out, "request_id": request["request_id"]}

    def enroll(self, **kwargs):
        body = reply(**kwargs)
        self.grants.issue(CONTROLLER, body, expires_ms=self.now + 100000)
        self.producer.enqueue(body)
        return body

    def test_fresh_client_reads_exact_binding_without_opening_broker_database(self):
        before = self.client.session("builder.fixture")
        self.assertEqual(before, self.server_authority.registry.session("builder.fixture"))
        self.assertFalse(hasattr(self.client, "connection"))
        self.assertFalse(hasattr(self.client, "register"))
        self.assertFalse(hasattr(self.client, "revoke"))
        self.server_authority.registry.revoke("builder.fixture")
        self.assertTrue(self.client.session("builder.fixture")["revoked"])
        self.assertNotEqual(self.calls[-1]["request_id"], self.calls[-2]["request_id"])
        self.assertIsNone(self.client.session("missing.fixture"))

    def test_worker_uid_or_identity_header_cannot_read_private_bindings(self):
        lookup = mock.Mock(wraps=self.server_authority.registry.session)
        with mock.patch.object(self.server_authority.registry, "session", lookup):
            for peer in (Peer(12, 101, 121), Peer(21, 102, 121), {"uid": os.geteuid()}):
                with self.assertRaises(Denied):
                    ccrelay_broker.dispatch(self.server_authority, peer, read_request(self.policy), binding_reads=self.reads)
            lookup.assert_not_called()
        for key in ("uid", "role", "from", "execution_id"):
            request = read_request(self.policy)
            request["args"][key] = os.geteuid()
            with self.assertRaises(Denied):
                self.rpc(self.client.path, request, broker_uid=self.server_authority.policy.broker_uid, timeout=3)

    def test_read_channel_cannot_register_revoke_or_authorize_worker_actions(self):
        original = self.server_authority.registry.session("builder.fixture")
        for method in ("register", "revoke", "send_message", "publish", "request_merge"):
            with self.assertRaises(Denied):
                self.rpc(self.client.path, read_request(self.policy, method=method),
                         broker_uid=self.server_authority.policy.broker_uid, timeout=3)
        with self.assertRaises(Denied):
            ccrelay_broker.dispatch(self.server_authority, Peer(61, os.geteuid(), 121), worker_request())
        with self.assertRaises(Denied):
            ccrelay_broker.dispatch(self.server_authority, CONTROLLER, read_request(self.policy), control=True, binding_reads=self.reads)
        with self.assertRaises(Denied):
            ccrelay_broker.dispatch(self.server_authority, Peer(61, os.geteuid(), 121), read_request(self.policy))
        self.assertEqual(self.server_authority.registry.session("builder.fixture"), original)

    def test_reader_role_ceiling_is_checked_on_server_and_consumer(self):
        limited = BindingReadPolicy(read_fields(self.server_authority.policy, roles=["reviewer"]), self.server_authority.policy)
        reads = BrokerBindingReads(self.server_authority, limited)
        with self.assertRaises(Denied):
            reads.dispatch(Peer(61, os.geteuid(), 121), read_request(limited))
        with self.assertRaises(Denied):
            limited.binding(self.server_authority.registry.session("builder.fixture"), "builder.fixture", limited.roles_for(os.geteuid()))

    def test_unknown_schema_and_changed_read_policy_do_not_modify_registry(self):
        original = self.server_authority.registry.session("builder.fixture")
        for changes in ({"schema": "ccrelay.binding_read_request.v999"}, {"method": "list_all"}, {"request_id": False}):
            with self.assertRaises(Denied):
                self.rpc(self.client.path, {**read_request(self.policy), **changes},
                         broker_uid=self.server_authority.policy.broker_uid, timeout=3)
        request = read_request(self.policy)
        request["args"]["reader_policy_digest"] = fingerprint({"other": True})
        with self.assertRaises(Denied):
            self.rpc(self.client.path, request, broker_uid=self.server_authority.policy.broker_uid, timeout=3)
        self.assertEqual(self.server_authority.registry.session("builder.fixture"), original)

    def test_stale_foreign_forged_or_partial_response_cannot_supply_a_binding(self):
        for changes in ({"request_id": "old-read"}, {"session_id": "foreign"}, {"reader_uid": 101}, {"reader_uid": True},
                        {"broker_policy_digest": fingerprint({"old": 1})}, {"reader_policy_digest": fingerprint({"old": 2})},
                        {"schema": "ccrelay.binding_read_result.v999"}, {"ok": 1}, {"binding_digest": "sha256:" + "f" * 64}):
            def altered(path, request, changes=changes, **kwargs):
                return {**self.rpc(path, request, **kwargs), **changes}
            with mock.patch.object(binding_reads, "client_request", side_effect=altered), self.assertRaises(Denied):
                self.client.session("builder.fixture")
        for result in (True, None, {"ok": True}, {"ok": False, "error": "denied"}):
            with mock.patch.object(binding_reads, "client_request", return_value=result), self.assertRaises(Denied):
                self.client.session("builder.fixture")

    def test_changed_binding_fields_fail_even_with_consistent_payload_hash(self):
        for key, value in (("uid", 102), ("session_id", "foreign"), ("launcher_uid", 98), ("policy_digest", fingerprint({"old": True}))):
            def altered(path, request, key=key, value=value, **kwargs):
                result = self.rpc(path, request, **kwargs)
                result["binding"][key] = value
                result["binding_digest"] = fingerprint(result["binding"])
                return result
            with mock.patch.object(binding_reads, "client_request", side_effect=altered), self.assertRaises(Denied):
                self.client.session("builder.fixture")

    def test_dispatch_reads_current_remote_revocation_and_preserves_pending_content(self):
        self.enroll(count=2, cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.server_authority.registry.revoke("builder.fixture")
        self.assertEqual(self.send()["state"], "held")
        item = self.ledger.items("reply-1")[0]["current"]
        self.assertIsNone(item["record"].fields["attempt_id"])
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(self.ledger.stream("stream-1")["tail_cursor"], 50)
        self.assertEqual(self.bot.count(), 0)

    def test_postclaim_remote_revocation_stops_wire_and_remains_unknown(self):
        self.enroll()
        def checkpoint(name):
            if name == "after_claim_commit":
                self.server_authority.registry.revoke("builder.fixture")
        self.ledger.checkpoint = checkpoint
        self.assertEqual(self.send()["state"], "unknown")
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(self.bot.calls("sendMessage"), [])
        self.assertFalse(self.tick()["submitted"])

    def test_channel_outage_cannot_reuse_cached_registration_or_auto_release_a_hold(self):
        self.enroll()
        with mock.patch.object(binding_reads, "client_request", side_effect=OSError("fixture unavailable")):
            self.assertEqual(self.send()["state"], "held")
        self.assertFalse(self.tick()["submitted"])
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        self.scheduler.release_source_hold(intent)
        self.assertEqual(self.scheduler.step()["state"], "confirmed")
        self.assertEqual(self.bot.count(), 1)

    def test_reader_policy_revocation_fences_existing_source_grant(self):
        self.enroll()
        disabled = BindingReadPolicy(read_fields(self.server_authority.policy, enabled=False), self.server_authority.policy)
        self.reads = BrokerBindingReads(self.server_authority, disabled)
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)

    def test_binding_read_is_not_native_context_root_or_company_permission(self):
        self.enroll()
        self.context_allowed = False
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)

    def test_actual_reader_policy_file_is_reloaded_and_brackets_slow_registry_reads(self):
        path = self.folder / "read-policy.json"
        path.write_text(json.dumps(read_fields(self.server_authority.policy)))
        self.reads = BrokerBindingReads(self.server_authority, self.policy, policy_path=str(path))
        with mock.patch.object(binding_reads, "protected_path", side_effect=lambda value, **_: Path(value)):
            self.assertFalse(self.client.session("builder.fixture")["revoked"])
            original = self.server_authority.registry.session
            def revoke_during_read(session_id):
                value = original(session_id)
                path.write_text(json.dumps(read_fields(self.server_authority.policy, enabled=False)))
                return value
            with mock.patch.object(self.server_authority.registry, "session", side_effect=revoke_during_read), self.assertRaises(Denied):
                self.client.session("builder.fixture")
            with self.assertRaises(Denied):
                self.client.session("builder.fixture")
            path.write_text('{"schema":"ccrelay.binding_read_policy.v999"}')
            with self.assertRaises(Denied):
                self.client.session("builder.fixture")
            self.assertEqual(json.loads(path.read_text())["schema"], "ccrelay.binding_read_policy.v999")

    def test_committed_revocation_survives_actual_process_death_without_reader_restart(self):
        self.enroll(count=2, cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.assertFalse(self.client.session("builder.fixture")["revoked"])
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("binding_read_fault_fixture.py")),
                                 str(self.folder / "source" / "bindings")], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertTrue(self.client.session("builder.fixture")["revoked"])
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(self.ledger.stream("stream-1")["tail_cursor"], 50)
        self.assertIsNone(self.ledger.items("reply-1")[0]["current"]["record"].fields["attempt_id"])


    def test_bounded_client_pins_serving_broker_uid_before_sending(self):
        connection = mock.MagicMock(family=identity.socket.AF_UNIX, type=identity.socket.SOCK_STREAM)
        connection.__enter__.return_value = connection
        connection.getsockopt.return_value = struct.pack("3i", 81, 999, 121)
        with mock.patch.object(binding_reads, "client_request", broker_wire.client_request), \
                mock.patch.object(broker_wire.socket, "socket", return_value=connection), \
                mock.patch.object(identity.sys, "platform", "linux"), \
                mock.patch.object(identity.socket, "SO_PEERCRED", 17, create=True):
            with self.assertRaises(Denied):
                self.client.session("builder.fixture")
        connection.sendall.assert_not_called()

    def test_bounded_framed_client_observes_same_registry_revocation(self):
        connection = mock.MagicMock(family=identity.socket.AF_UNIX, type=identity.socket.SOCK_STREAM)
        connection.__enter__.return_value = connection
        connection.getsockopt.return_value = struct.pack("3i", 81, self.server_authority.policy.broker_uid, 121)
        received = []
        def send(payload):
            request = identity.strict_json(payload[:-1])
            received.append(request)
            response = self.rpc(self.client.path, request, broker_uid=self.server_authority.policy.broker_uid, timeout=3)
            connection.recv.return_value = canonical_bytes(response) + b"\n"
        connection.sendall.side_effect = send
        with mock.patch.object(binding_reads, "client_request", broker_wire.client_request), \
                mock.patch.object(broker_wire.socket, "socket", return_value=connection), \
                mock.patch.object(identity.sys, "platform", "linux"), \
                mock.patch.object(identity.socket, "SO_PEERCRED", 17, create=True):
            self.assertFalse(self.client.session("builder.fixture")["revoked"])
            self.server_authority.registry.revoke("builder.fixture")
            self.assertTrue(self.client.session("builder.fixture")["revoked"])
        self.assertEqual(len(received), 2)
        self.assertNotEqual(received[0]["request_id"], received[1]["request_id"])
        connection.connect.assert_called_with(self.client.path)

    def test_component_descriptor_cannot_be_inherited_by_a_worker_writer(self):
        request = canonical_bytes(read_request(self.policy)) + b"\n"
        connection = mock.Mock()
        component = Peer(61, os.geteuid(), 121)
        credentials = lambda uid: [(broker_wire.socket.SOL_SOCKET, 2, struct.pack("3i", 61, uid, 121))]
        connection.recvmsg.side_effect = [(request[:20], credentials(component.uid), 0, None),
                                          (request[20:], credentials(101), 0, None)]
        with mock.patch.object(broker_wire, "peer_credentials", return_value=component), \
                mock.patch.object(broker_wire.socket, "SCM_CREDENTIALS", 2, create=True), \
                self.assertRaises(Denied):
            broker_wire.receive_request(connection)
