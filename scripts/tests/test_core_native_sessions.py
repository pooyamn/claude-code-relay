"""Controller mappings and stale-observation fencing, not live native readiness."""
from dataclasses import asdict, replace
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from relay_core.contracts import ContractError, canonical_bytes
from relay_core.identity import Denied, Peer, Policy
from native_session_fixtures import CONTROLLER, enrollment, native_fixture, observation, open_registry
from test_core_identity import policy_fields


class NativeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.calls = []
        def inspect(binding, record, probe_id):
            self.calls.append((binding, record, probe_id))
            return observation(binding, record, probe_id)
        self.fixture = native_fixture(self.folder, observer=inspect)
        self.registry, self.authority = self.fixture.__enter__()
        self.addCleanup(lambda: self.fixture.__exit__(None, None, None))

    def enroll(self, **kwargs):
        return self.registry.enroll(CONTROLLER, enrollment(**kwargs))

    def refresh(self, session_id="builder.task"):
        return self.registry.refresh(CONTROLLER, session_id, expected_revision=self.registry.cached(session_id).revision)

    def test_registration_is_unknown_and_requires_fresh_pinned_native_observation(self):
        stored = self.enroll()
        self.assertFalse(stored.fields["ready"])
        self.assertEqual(stored.fields["observed_state"], "unknown")
        self.assertEqual(self.calls, [])
        ready = self.refresh()
        self.assertTrue(ready.fields["ready"])
        self.assertEqual(ready.fields["provider_session_id"], "native-thread-1")
        self.assertEqual(ready.fields["active_turn_id"], "native-turn-1")
        self.assertEqual((ready.fields["root_task_id"], ready.fields["role_id"]), ("root-builder", "builder"))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.calls[0][1].fields["ready"])  # Cache invalidated BEFORE callback.
        self.assertEqual(self.registry.connection.execute("SELECT count(*) FROM intents").fetchone()[0], 0)

    def test_same_role_has_distinct_sessions_but_duplicate_native_conversation_denied(self):
        first = self.enroll()
        second = self.enroll(session_id="builder.other", native_id="native-thread-2")
        self.assertEqual(first.fields["role_id"], second.fields["role_id"])
        self.assertNotEqual(first.id, second.id)
        with self.assertRaises(Denied):
            self.registry.enroll(CONTROLLER, enrollment("reviewer.task"))
        self.assertIsNone(self.registry.cached("reviewer.task"))
        claude = self.registry.enroll(CONTROLLER, enrollment("reviewer.task", provider="claude"))
        self.assertEqual(claude.fields["provider"], "claude")  # Namespaces remain provider-specific.

    def test_replayed_enrollment_never_resets_later_pause_and_changed_contract_needs_transfer(self):
        self.enroll()
        observed = self.refresh()
        paused = self.registry.desired(CONTROLLER, observed.id, "paused", expected_revision=observed.revision)
        self.assertEqual(self.enroll(), paused)
        for change in ({"provider_session_id": "replacement"}, {"provider": "claude"},
                       {"worktree": "/other/worktree"}, {"desired_state": "stopped"},
                       {"expected": {**enrollment()["expected"], "permission_digest": "sha256:" + "d" * 64}}):
            with self.subTest(change=change), self.assertRaises(Denied):
                self.registry.enroll(CONTROLLER, {**enrollment(), **change})
        self.assertEqual(self.registry.cached("builder.task"), paused)

    def test_worker_cwd_uid_headers_and_other_role_controller_cannot_change_state(self):
        self.enroll()
        before = self.registry.cached("builder.task")
        for peer in (Peer(12, 101, 121), Peer(22, 102, 121), Peer(9, 99, 121), {"uid": 0, "role": "controller"}):
            with self.subTest(peer=peer), mock.patch("os.getcwd", return_value="/root/controller"):
                for action in (lambda: self.registry.enroll(peer, enrollment()),
                               lambda: self.registry.desired(peer, before.id, "paused", expected_revision=before.revision),
                               lambda: self.registry.refresh(peer, before.id, expected_revision=before.revision)):
                    with self.assertRaises(Denied):
                        action()
        self.assertEqual(self.registry.cached(before.id), before)
        self.assertEqual(self.calls, [])

    def test_stale_revision_cannot_pause_or_overwrite_and_invalid_state_retains_record(self):
        first = self.enroll()
        ready = self.refresh()
        for action in (lambda: self.registry.desired(CONTROLLER, first.id, "paused", expected_revision=first.revision),
                       lambda: self.registry.refresh(CONTROLLER, first.id, expected_revision=first.revision),
                       lambda: self.registry.desired(CONTROLLER, first.id, "invalid", expected_revision=ready.revision)):
            with self.assertRaises((Denied, ContractError)):
                action()
        self.assertEqual(self.registry.cached(first.id), ready)

    def test_pause_is_a_request_and_idle_running_observation_does_not_confirm_pause(self):
        self.enroll()
        ready = self.refresh()
        wanted = self.registry.desired(CONTROLLER, ready.id, "paused", expected_revision=ready.revision)
        self.assertEqual(wanted.fields["observed_state"], "unknown")
        self.assertFalse(wanted.fields["ready"])
        observed = self.refresh()
        self.assertEqual((observed.fields["desired_state"], observed.fields["observed_state"], observed.fields["ready"]),
                         ("paused", "running", False))

    def test_late_observation_cannot_override_owner_pause(self):
        self.enroll()
        def paused(binding, record, probe_id):
            self.registry.desired(CONTROLLER, record.id, "paused", expected_revision=record.revision)
            return observation(binding, record, probe_id)
        self.registry.observe_runtime = paused
        with self.assertRaises(Denied):
            self.refresh()
        current = self.registry.cached("builder.task")
        self.assertEqual(current.fields["desired_state"], "paused")
        self.assertFalse(current.fields["ready"])

    def test_newer_observation_wins_by_revision_not_by_old_callback_finishing_later(self):
        self.enroll()
        def concurrent(binding, record, probe_id):
            self.registry.observe_runtime = lambda b, r, p: replace(observation(b, r, p), active_turn_id="new-turn")
            self.registry.refresh(CONTROLLER, record.id, expected_revision=record.revision)
            return observation(binding, record, probe_id)
        self.registry.observe_runtime = concurrent
        with self.assertRaises(Denied):
            self.refresh()
        current = self.registry.cached("builder.task")
        self.assertTrue(current.fields["ready"])
        self.assertEqual(current.fields["active_turn_id"], "new-turn")

    def test_revocation_during_observation_never_makes_ready(self):
        self.enroll()
        def revoked(binding, record, probe_id):
            self.authority.registry.revoke(record.id)
            return observation(binding, record, probe_id)
        self.registry.observe_runtime = revoked
        with self.assertRaises(Denied):
            self.refresh()
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_broker_policy_change_before_or_during_observation_cannot_reuse_old_bindings(self):
        self.enroll()
        original = self.authority.policy
        changed = policy_fields()
        changed["controllers"].append({"uid": 98, "roles": ["builder"]})
        replacement = Policy(changed)
        self.authority.policy = replacement
        with self.assertRaises(Denied):
            self.refresh()
        self.authority.policy = original
        def change_during_read(binding, record, probe_id):
            self.authority.policy = replacement
            return observation(binding, record, probe_id)
        self.registry.observe_runtime = change_during_read
        with self.assertRaises(Denied):
            self.refresh()
        self.assertFalse(self.registry.cached("builder.task").fields["ready"])

    def test_wrong_id_worktree_binding_fingerprints_capabilities_and_decoded_claims_refused(self):
        self.enroll()
        changes = ({"provider_session_id": "foreign-thread"}, {"provider": "claude"}, {"worktree": "/different/worktree"},
                   {"binding_digest": "sha256:" + "e" * 64}, {"runtime_digest": "sha256:" + "e" * 64},
                   {"tool_contract_digest": "sha256:" + "e" * 64}, {"permission_digest": "sha256:" + "e" * 64},
                   {"probe_id": "stale-probe"}, {"capabilities": ("read",)}, {"observed_state": "unknown-v9"})
        for change in changes:
            with self.subTest(change=change):
                self.registry.observe_runtime = lambda b, r, p: replace(observation(b, r, p), **change)
                with self.assertRaises((Denied, ContractError)):
                    self.refresh()
                self.assertFalse(self.registry.cached("builder.task").fields["ready"])
        self.registry.observe_runtime = lambda b, r, p: asdict(observation(b, r, p))
        with self.assertRaises(Denied):
            self.refresh()

    def test_failed_observer_retains_exact_identity_and_last_turn_but_invalidates_readiness(self):
        self.enroll()
        self.refresh()
        self.registry.observe_runtime = mock.Mock(side_effect=TimeoutError("invented transport ambiguity"))
        with self.assertRaises(Denied):
            self.refresh()
        current = self.registry.cached("builder.task")
        self.assertEqual(current.fields["provider_session_id"], "native-thread-1")
        self.assertEqual(current.fields["active_turn_id"], "native-turn-1")
        self.assertEqual(current.fields["observed_state"], "unknown")
        self.assertFalse(current.fields["ready"])

    def test_unknown_observation_cannot_erase_last_known_turn_for_reconciliation(self):
        self.enroll()
        self.refresh()
        self.registry.observe_runtime = lambda b, r, p: replace(observation(b, r, p), observed_state="unknown", active_turn_id=None)
        current = self.refresh()
        self.assertEqual(current.fields["observed_state"], "unknown")
        self.assertEqual(current.fields["active_turn_id"], "native-turn-1")
        self.assertFalse(current.fields["ready"])

    def test_claude_supported_with_exact_mapping_but_cannot_claim_codex_goal(self):
        self.enroll(provider="claude")
        self.assertTrue(self.refresh().fields["ready"])
        self.registry.observe_runtime = lambda b, r, p: replace(observation(b, r, p), capabilities=("read", "exact_resume", "goal"))
        with self.assertRaises(Denied):
            self.refresh()
        with self.assertRaises(Denied):
            self.registry.enroll(CONTROLLER, {**enrollment("builder.other", provider="claude", native_id="native-2"),
                "capabilities": ["read", "goal"]})

    def test_snapshot_restore_invalidates_observation_preserves_desired_identity_history(self):
        self.enroll()
        ready = self.refresh()
        target = self.folder / "restore"
        target.mkdir(mode=0o700)
        with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)):
            self.registry.snapshot(target / "outbox.sqlite")
        restored = open_registry(target, self.authority)
        try:
            record = restored.cached("builder.task")
            self.assertEqual(record.fields["provider_session_id"], ready.fields["provider_session_id"])
            self.assertEqual(record.fields["active_turn_id"], ready.fields["active_turn_id"])
            self.assertEqual(record.fields["desired_state"], "running")
            self.assertEqual(record.fields["observed_state"], "unknown")
            self.assertFalse(record.fields["ready"])
            self.assertGreater(record.revision, ready.revision)
            self.assertTrue(restored.refresh(CONTROLLER, record.id, expected_revision=record.revision).fields["ready"])
        finally:
            restored.close()

    def test_unknown_component_version_or_future_record_preserves_original_bytes(self):
        self.enroll()
        self.registry.connection.execute("UPDATE native_metadata SET schema='future'")
        self.registry.close()
        path = self.folder / "native/outbox.sqlite"
        before = path.read_bytes()
        with self.assertRaises(Denied):
            open_registry(path.parent, self.authority)
        self.assertEqual(path.read_bytes(), before)

    def test_tampered_indices_or_history_never_become_current_mapping(self):
        self.enroll()
        for column, value in (("native_id", "different"), ("enrollment_digest", "sha256:" + "d" * 64),
                              ("binding_digest", "sha256:" + "d" * 64), ("body_digest", "sha256:" + "d" * 64)):
            with self.subTest(column=column):
                self.registry.connection.execute("BEGIN IMMEDIATE")
                try:
                    self.registry.connection.execute("UPDATE native_sessions SET " + column + "=?", (value,))
                    with self.assertRaises(Denied):
                        self.registry.cached("builder.task")
                finally:
                    self.registry.connection.execute("ROLLBACK")
        self.registry.connection.execute("DELETE FROM native_history")
        with self.assertRaises(Denied):
            self.registry.cached("builder.task")

    def test_future_session_record_is_not_recovered_or_replaced(self):
        self.enroll()
        future = self.registry.cached("builder.task").to_dict()
        future["schema"] = "ccrelay.session.v999"
        self.registry.connection.execute("UPDATE native_sessions SET body=?", (canonical_bytes(future),))
        self.registry.close()
        path = self.folder / "native/outbox.sqlite"
        before = path.read_bytes()
        with self.assertRaises(ContractError):
            open_registry(path.parent, self.authority)
        self.assertEqual(path.read_bytes(), before)

    def test_real_lifetime_lock_refuses_another_registry_writer(self):
        self.enroll()
        with self.assertRaises(BlockingIOError):
            open_registry(self.folder / "native", self.authority)

    def test_real_process_deaths_never_restore_cached_readiness_or_change_exact_ids(self):
        boundaries = ("before_native_enroll_commit", "after_native_enroll_commit", "before_native_probe_commit",
                      "after_native_probe_commit", "after_native_observation", "before_native_observation_commit",
                      "after_native_observation_commit", "before_native_desired_commit", "after_native_desired_commit")
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                folder = self.folder / boundary
                folder.mkdir(mode=0o700)
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_session_fault_fixture.py")),
                    str(folder), boundary], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 73, result.stderr)
                with native_fixture(folder) as (registry, authority):
                    row = registry.cached("builder.task")
                    if boundary == "before_native_enroll_commit":
                        self.assertIsNone(row)
                        continue
                    self.assertEqual(row.fields["provider_session_id"], "native-thread-1")
                    self.assertFalse(row.fields["ready"])
                    self.assertEqual(row.fields["observed_state"], "unknown")
                    self.assertEqual(row.fields["desired_state"], "paused" if boundary == "after_native_desired_commit" else "running")
                    self.assertIsNone(registry.connection.execute("SELECT probe_id FROM native_sessions").fetchone()[0])
                    self.assertEqual(registry.connection.execute("SELECT count(*) FROM intents").fetchone()[0], 0)
