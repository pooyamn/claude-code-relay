"""Synthetic kernel/permission conformance, NOT distinct-UID OS acceptance."""
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import ccrelay_broker
import ccrelay_broker_mcp
from relay_core.bindings import BindingRegistry
from relay_core.contracts import create, fingerprint
from relay_core import broker_wire, identity
from relay_core.identity import Authority, Denied, Peer, Policy, Process


BOOT = "00000000-0000-0000-0000-000000000001"


def policy_fields():
    roles = []
    for name, uid, extra in (("builder", 101, "publish"), ("reviewer", 102, "review"),
                             ("cto", 103, "request_merge"), ("support", 104, "request_deploy")):
        roles.append(create("role", id=name, revision=0, uid=uid, enabled=True,
                            capabilities=["message", "report_issue", extra], policy_digest=fingerprint({"rules": name})).to_dict())
    return {"schema": "ccrelay.broker_policy.v1", "broker_uid": 120, "client_gid": 121,
            "roles": roles, "controllers": [{"uid": 0, "roles": [item["id"] for item in roles]},
                                            {"uid": 99, "roles": ["reviewer"]}]}


def request(method="whoami", args=None, **extra):
    return {"schema": "ccrelay.broker_request.v1", "request_id": "request-1", "method": method,
            "args": {} if args is None else args, **extra}


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # macOS scratch has a shared /tmp ancestor; production correctly rejects
        # that. Mock ONLY this path check for private SQLite fixtures inside the
        # already-enforced OS sandbox. Permission semantics are tested separately.
        patcher = mock.patch("relay_core.bindings.protected_path", side_effect=lambda path, **_: Path(path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = BindingRegistry(Path(self.tmp.name), owner_uid=os.geteuid())
        self.addCleanup(self.registry.close)
        self.policy = Policy(policy_fields())
        self.processes = {}
        for index, role in enumerate(self.policy.roles.values(), 1):
            pid = index * 10 + 1
            group = identity.expected_cgroup("exec-" + role.id)
            self.processes[pid] = Process(pid, role.fields["uid"], BOOT + ":100", group)
            self.processes[pid + 1] = Process(pid + 1, role.fields["uid"], BOOT + ":101", group)

        def observer(pid):
            if pid not in self.processes:
                raise Denied("synthetic dead process")
            return self.processes[pid]
        self.authority = Authority(self.policy, self.registry, observer)
        for role in self.policy.roles:
            self.register(role)

    def fields(self, role):
        index = list(self.policy.roles).index(role) + 1
        return {"session_id": role + ".task", "role_id": role, "root_task_id": "root-" + role,
                "execution_id": "exec-" + role, "leader_pid": index * 10 + 1}

    def register(self, role):
        return self.authority.register(Peer(1, 0, 0), self.fields(role))

    def peer(self, role):
        fields = self.fields(role)
        return Peer(fields["leader_pid"] + 1, self.policy.roles[role].fields["uid"], 121)

    def test_actor_binds_exact_role_session_root_execution_not_cwd(self):
        with mock.patch("os.getcwd", return_value="/var/lib/ccrelay/roles/reviewer"):
            actor = self.authority.authorize(self.peer("builder"), request())
        self.assertEqual((actor.role_id, actor.session_id, actor.root_task_id, actor.execution_id),
                         ("builder", "builder.task", "root-builder", "exec-builder"))

    def test_payload_cannot_supply_identity_even_for_legitimate_role(self):
        for name in ("from", "sender", "role", "role_id", "session_id", "root_task_id", "uid"):
            for payload in (request(args={name: "reviewer"}), request(**{name: "reviewer"})):
                with self.assertRaises(Denied):
                    self.authority.authorize(self.peer("builder"), payload)

    def test_builder_cannot_review_merge_deploy_or_owner_approve(self):
        for method in ("review_publication", "request_merge", "request_deploy", "owner_approve"):
            with self.assertRaises(Denied):
                self.authority.authorize(self.peer("builder"), request(method))
        for role, method in (("reviewer", "review_publication"), ("cto", "request_merge"), ("support", "request_deploy")):
            self.assertEqual(self.authority.authorize(self.peer(role), request(method)).role_id, role)
            for other in ("review_publication", "request_merge", "request_deploy"):
                if other != method:
                    with self.assertRaises(Denied):
                        self.authority.authorize(self.peer(role), request(other))
            # Role authorization is NOT an implemented effectful gate/handler.
            with self.assertRaises(Denied):
                ccrelay_broker.dispatch(self.authority, self.peer(role), request(method))

    def test_unregistered_unit_and_socket_uid_mismatch_fail_closed(self):
        self.processes[12] = Process(12, 101, BOOT + ":101", "/user.slice/worker-shell.scope")
        with self.assertRaises(Denied):
            self.authority.actor(self.peer("builder"))
        with self.assertRaises(Denied):
            self.authority.actor(Peer(22, 101, 121))

    def test_unknown_request_schema_methods_and_malformed_fields_fail_closed(self):
        for changes in ({"schema": "ccrelay.broker_request.v0"}, {"schema": "ccrelay.broker_request.v999"},
                        {"request_id": True}, {"method": []}, {"method": None}, {"args": []}):
            with self.assertRaises(Denied):
                self.authority.authorize(self.peer("builder"), {**request(), **changes})

    def test_revocation_policy_drift_and_dead_or_reused_leader_deny(self):
        original = self.processes[11]
        for changed in (Process(11, 101, BOOT + ":999", original.cgroup),
                        Process(11, 101, original.start_identity, "/other.service"),
                        Process(11, 102, original.start_identity, original.cgroup)):
            self.processes[11] = changed
            with self.assertRaises(Denied):
                self.authority.actor(self.peer("builder"))
        del self.processes[11]
        with self.assertRaises(Denied):
            self.authority.actor(self.peer("builder"))
        self.processes[11] = original
        fields = policy_fields()
        fields["roles"][0]["enabled"] = False
        with self.assertRaises(Denied):
            Authority(Policy(fields), self.registry, self.authority.observer).actor(self.peer("builder"))
        self.authority.revoke(Peer(1, 0, 0), "builder.task")
        with self.assertRaises(Denied):
            self.authority.actor(self.peer("builder"))

    def test_bootstrap_grants_uid_and_protected_unit_are_checked(self):
        fields = self.fields("reviewer")
        for peer in (self.peer("builder"), self.peer("reviewer")):
            with self.assertRaises(Denied):
                self.authority.register(peer, fields)
        fields = {**fields, "session_id": "reviewer.second", "execution_id": "exec-reviewer-second", "leader_pid": 25}
        self.processes[25] = Process(25, 102, BOOT + ":105", identity.expected_cgroup(fields["execution_id"]))
        self.authority.register(Peer(5, 99, 99), fields)
        self.assertEqual(self.registry.session("reviewer.second")["launcher_uid"], 99)
        with self.assertRaises(Denied):
            self.authority.register(Peer(5, 99, 99), self.fields("builder"))
        fields["leader_pid"] = 11
        with self.assertRaises(Denied):
            self.authority.register(Peer(1, 0, 0), fields)
        fields = self.fields("builder")
        self.processes[11] = Process(11, 101, BOOT + ":100", "/unprotected.service")
        with self.assertRaises(Denied):
            self.authority.register(Peer(1, 0, 0), fields)

    def test_registration_replay_cannot_replace_bindings_or_reactivate_revoked(self):
        self.register("builder")
        fields = self.fields("builder")
        fields["root_task_id"] = "reset-root"
        with self.assertRaises(Denied):
            self.authority.register(Peer(1, 0, 0), fields)
        fields = self.fields("builder")
        fields["session_id"] = "second-session-same-unit"
        with self.assertRaises(Denied):
            self.authority.register(Peer(1, 0, 0), fields)
        self.authority.revoke(Peer(1, 0, 0), "builder.task")
        with self.assertRaises(Denied):
            self.register("builder")

    def test_sqlite_reopen_snapshot_and_corrupt_index_do_not_change_identity(self):
        reopened = BindingRegistry(Path(self.tmp.name), owner_uid=os.geteuid())
        try:
            self.assertEqual(reopened.session("builder.task"), self.registry.session("builder.task"))
        finally:
            reopened.close()
        snapshot = Path(self.tmp.name) / "snapshot.sqlite"
        self.registry.snapshot(snapshot)
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
        with sqlite3.connect(snapshot) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM bindings").fetchone()[0], 4)
        self.registry.connection.execute("UPDATE bindings SET cgroup='/wrong.service' WHERE session_id='builder.task'")
        with self.assertRaises(Denied):
            self.registry.session("builder.task")

    def test_unknown_registry_schema_preserves_original_database(self):
        self.registry.connection.execute("UPDATE metadata SET schema='ccrelay.binding_registry.v999'")
        with self.assertRaises(Denied):
            BindingRegistry(Path(self.tmp.name), owner_uid=os.geteuid())
        self.assertEqual(self.registry.connection.execute("SELECT schema FROM metadata").fetchone()[0], "ccrelay.binding_registry.v999")

    def test_introspection_does_not_claim_registered_peers_ready(self):
        out = ccrelay_broker.dispatch(self.authority, self.peer("builder"), request("list_sessions"))
        self.assertEqual(out["you"], "builder.task")
        self.assertEqual(len(out["sessions"]), 3)
        self.assertTrue(all(row["reachable"] is False for row in out["sessions"]))


class PolicyAndObservationTests(unittest.TestCase):
    def test_empty_duplicate_root_worker_and_escalating_policies_are_denied(self):
        variants = []
        for key in ("roles", "controllers"):
            value = policy_fields()
            value[key] = []
            variants.append(value)
        for change in ({"uid": 102}, {"uid": 120}, {"uid": 0}, {"capabilities": ["owner_approve"]},
                       {"capabilities": ["review"]}, {"capabilities": ["request_merge"]}):
            value = policy_fields()
            value["roles"][0].update(change)
            variants.append(value)
        value = policy_fields()
        value["controllers"][0]["uid"] = 101
        variants.append(value)
        for value in variants:
            with self.assertRaises(ValueError):
                Policy(value)

    def test_strict_json_rejects_duplicate_fields_nonfinite_and_unknown_request_versions(self):
        for raw in (b'{"uid":1,"uid":2}', b'{"uid":NaN}', b'{"uid":1.5}', b'"\ud800"'):
            with self.assertRaises(Denied):
                identity.strict_json(raw)

    def test_proc_stat_handles_parentheses_and_rejects_dead_processes(self):
        raw = "11 (name with ) parentheses) " + " ".join(["S"] + ["0"] * 18 + ["777"])
        self.assertEqual(identity.proc_stat(raw, 11), "777")
        with self.assertRaises(Denied):
            identity.proc_stat(raw.replace(") S ", ") Z "), 11)
        for group in ("1:memory:/old-v1", "0::/../spoof", "0::/unit\n1:cpu:/legacy"):
            with self.assertRaises(Denied):
                identity.proc_cgroup(group)

    def test_proc_observation_checks_generation_uid_cgroup_permissions(self):
        raw = "11 (fixture) " + " ".join(["S"] + ["0"] * 18 + ["777"])
        group = identity.expected_cgroup("exec-builder")
        with mock.patch.object(identity.sys, "platform", "linux"), \
                mock.patch.object(Path, "read_text", side_effect=[BOOT, raw, "Uid:\t101\t101\t101\t101", "0::" + group, raw]), \
                mock.patch.object(identity, "protected_cgroup") as permissions:
            process = identity.observe_process(11)
        self.assertEqual(process.start_identity, BOOT + ":777")
        permissions.assert_called_once_with(group)
        with mock.patch.object(identity.sys, "platform", "linux"), \
                mock.patch.object(Path, "read_text", side_effect=[BOOT, raw, "Uid:\t101\t101\t101\t101", "0::" + group, raw.replace("777", "778")]), \
                mock.patch.object(identity, "protected_cgroup"):
            with self.assertRaises(Denied):
                identity.observe_process(11)

    def test_protected_files_reject_writable_ancestors_symlinks_and_wrong_owner(self):
        def metadata(path):
            return SimpleNamespace(st_uid=0, st_mode=(stat.S_IFREG | 0o640) if str(path).endswith("policy") else (stat.S_IFDIR | 0o755))
        with mock.patch.object(Path, "lstat", autospec=True, side_effect=metadata):
            identity.protected_path("/etc/ccrelay/policy", owners={0})
        for failure in (SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o777),
                        SimpleNamespace(st_uid=101, st_mode=stat.S_IFDIR | 0o755),
                        SimpleNamespace(st_uid=0, st_mode=stat.S_IFLNK | 0o755)):
            def changed(path):
                return failure if str(path) == "/etc/ccrelay" else metadata(path)
            with mock.patch.object(Path, "lstat", autospec=True, side_effect=changed):
                with self.assertRaises(Denied):
                    identity.protected_path("/etc/ccrelay/policy", owners={0})

    def test_peer_credentials_have_no_nonlinux_or_tcp_fallback(self):
        connection = mock.Mock(family=identity.socket.AF_UNIX, type=identity.socket.SOCK_STREAM)
        connection.getsockopt.return_value = struct.pack("3i", 12, 101, 121)
        with mock.patch.object(identity.sys, "platform", "linux"), mock.patch.object(identity.socket, "SO_PEERCRED", 17, create=True):
            self.assertEqual(identity.peer_credentials(connection), Peer(12, 101, 121))
            connection.family = identity.socket.AF_INET
            with self.assertRaises(Denied):
                identity.peer_credentials(connection)
        with mock.patch.object(identity.sys, "platform", "darwin"):
            with self.assertRaises(Denied):
                identity.peer_credentials(connection)


class WireAndClientTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(broker_wire.socket, "SCM_CREDENTIALS", 2, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(broker_wire, "peer_credentials", return_value=Peer(12, 101, 121))
        patcher.start()
        self.addCleanup(patcher.stop)

    def connection(self, bodies, *, pid=12, flags=0):
        connection = mock.Mock()
        connection.recvmsg.side_effect = [(body, [(broker_wire.socket.SOL_SOCKET, 2, struct.pack("3i", pid, 101, 121))], flags, None) for body in bodies]
        return connection

    def test_every_fragment_needs_current_kernel_sender_and_complete_bounded_frame(self):
        data = json.dumps(request()).encode() + b"\n"
        _, out = broker_wire.receive_request(self.connection([data[:8], data[8:]]))
        self.assertEqual(out, request())
        for connection in (self.connection([data], pid=99), self.connection([data], flags=broker_wire.socket.MSG_CTRUNC),
                           self.connection([data + data]), self.connection([b"x" * 65537]), self.connection([b""])):
            with self.assertRaises(Denied):
                broker_wire.receive_request(connection)

    def test_missing_credentials_and_descriptor_transfer_are_denied_without_fd_leak(self):
        connection = mock.Mock()
        connection.recvmsg.return_value = (b"{}\n", [], 0, None)
        with self.assertRaises(Denied):
            broker_wire.receive_request(connection)
        descriptor = os.open("/dev/null", os.O_RDONLY)
        connection.recvmsg.return_value = (b"{}\n", [(broker_wire.socket.SOL_SOCKET, broker_wire.socket.SCM_RIGHTS,
                                                       struct.pack("i", descriptor))], 0, None)
        with self.assertRaises(Denied):
            broker_wire.receive_request(connection)
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_slow_fragments_cannot_reset_the_total_request_deadline(self):
        data = json.dumps(request()).encode() + b"\n"
        connection = self.connection([data[:8], data[8:]])
        with mock.patch.object(broker_wire.time, "monotonic", side_effect=[10, 11, 14]):
            with self.assertRaises(Denied):
                broker_wire.receive_request(connection, timeout=3)
        self.assertEqual(connection.recvmsg.call_count, 1)

    def test_mcp_client_forwards_arguments_without_reading_shared_state(self):
        transport = mock.Mock(return_value={"ok": True, "session": "builder.task"})
        input_stream = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                               "params": {"name": "whoami", "arguments": {}}}) + "\n")
        output = io.StringIO()
        with mock.patch("os.getcwd", side_effect=AssertionError("cwd is not authentication")):
            ccrelay_broker_mcp.run("/run/fixture/actions.sock", 120, input_stream, output, transport)
        body = transport.call_args.args[1]
        self.assertEqual(set(body), {"schema", "request_id", "method", "args"})
        self.assertNotIn("role", body["args"])
        self.assertFalse(json.loads(output.getvalue())["result"]["isError"])

    def test_mcp_unknown_effectful_operation_never_calls_transport(self):
        transport = mock.Mock()
        request_line = json.dumps({"id": 7, "method": "tools/call", "params": {"name": "request_merge"}}) + "\n"
        output = io.StringIO()
        ccrelay_broker_mcp.run("/run/fixture/actions.sock", 120, io.StringIO(request_line), output, transport)
        transport.assert_not_called()
        self.assertIn("error", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
