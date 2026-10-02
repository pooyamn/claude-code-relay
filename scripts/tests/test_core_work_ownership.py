"""Atomic root/work custody with real SQLite, locks and deaths; synthetic OS facts."""
from dataclasses import replace
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from work_ownership_fixtures import NOW, root_record, work_fixture
from relay_core.contracts import transition
from relay_core.identity import Denied, Peer
from relay_core.work_ownership import WorkOwnership


BUILDER = Peer(11, 101, 121)
OTHER = Peer(12, 101, 121)
REVIEWER = Peer(21, 102, 121)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = work_fixture(self.folder)
        self.fixture = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.ledger = self.fixture.ledger
        self.initial = root_record(self.fixture.authority.policy.digest)
        self.ledger.enroll_root(CONTROLLER, self.initial)
        self.enroll()

    def enroll(self, work_id="work-1", *, resource="fixture-worktree", dependencies=None):
        return self.ledger.enroll_work(CONTROLLER, work_id=work_id, root_id="root-builder", criteria=["Passed fixture gate"],
                                      dependencies=dependencies or [], assignee_role_id="builder", resource_id=resource)

    def claim(self, peer=BUILDER, claim_id="claim-1", work_id="work-1", revision=0):
        return self.ledger.checkout(peer, work_id, claim_id, expected_revision=revision)

    def charge(self, operation, kind="turn", peer=BUILDER):
        return self.ledger.charge(peer, operation, kind, expected_revision=self.ledger.root("root-builder").revision)

    def assess(self, charge, evidence_id):
        return self.ledger.assess_handoff(CONTROLLER, "root-builder", charge["receipt"]["scope"]["id"], evidence_id,
                                          expected_revision=self.ledger.root("root-builder").revision)

    def test_one_owner_exact_run_replay_and_current_fence(self):
        first = self.claim()
        self.assertTrue(first["claimed_now"])
        self.assertFalse(self.claim()["claimed_now"])
        with self.assertRaises(Denied):
            self.claim(OTHER, "other-claim")
        self.ledger.validate_fence(BUILDER, "work-1", first["work"]["fencing_token"])
        with self.assertRaises(Denied):
            self.ledger.validate_fence(OTHER, "work-1", first["work"]["fencing_token"])

    def test_resource_exclusive_even_between_different_items_and_terminal_work(self):
        self.enroll("work-2")
        first = self.claim()["work"]
        finished = self.ledger.finish_work(CONTROLLER, "work-1", "gate-1", expected_revision=first["revision"])
        self.assertEqual(finished["state"], "completed")
        self.assertIsNotNone(finished["binding"])
        with self.assertRaises(Denied):
            self.claim(OTHER, "other-claim", "work-2")
        self.ledger.verify_quiescence = lambda _: None
        with self.assertRaises(Denied):
            self.ledger.release(CONTROLLER, "work-1", expected_revision=finished["revision"])
        self.assertIsNotNone(self.ledger.work("work-1")["binding"])

    def test_quiescence_releases_resource_and_old_fence_cannot_write(self):
        work = self.claim()["work"]
        self.enroll("work-2")
        released = self.ledger.release(CONTROLLER, "work-1", expected_revision=work["revision"])
        with self.assertRaises(Denied):
            self.ledger.validate_fence(BUILDER, "work-1", work["fencing_token"])
        with self.assertRaises(Denied):
            self.claim(revision=released["revision"])
        second = self.claim(OTHER, "new-claim", "work-2")["work"]
        self.assertGreater(second["fencing_token"], work["fencing_token"])

    def test_terminal_root_does_not_release_writer_custody(self):
        self.claim()
        root = self.ledger.root("root-builder")
        self.ledger.control_root(CONTROLLER, root.id, "cancelled", expected_revision=root.revision)
        self.assertIsNotNone(self.ledger.work("work-1")["binding"])
        self.enroll_root_denied_after_terminal()

    def enroll_root_denied_after_terminal(self):
        with self.assertRaises(Denied):
            self.enroll("other-work")

    def test_charge_ids_and_cross_session_budget_are_shared_and_diagnostics_cost_a_turn(self):
        first = self.charge("turn-1")
        self.assertTrue(first["charged_now"])
        self.assertFalse(self.charge("turn-1")["charged_now"])
        second = self.charge("diagnose-1", "diagnosis", OTHER)
        self.assertEqual(second["record"].fields["usage"]["turns"], 2)
        self.assertEqual(second["record"].fields["usage"]["diagnoses"], 1)
        with self.assertRaises(Denied):
            self.charge("turn-1", "diagnosis")
        for index in range(2):
            self.charge("extra-" + str(index), peer=OTHER)
        with self.assertRaises(Denied):
            self.charge("over-budget")
        self.assertEqual(self.ledger.root("root-builder").fields["usage"]["turns"], 4)

    def test_three_handoffs_hold_root_across_new_message_chains_and_evidence_is_not_text(self):
        for index in range(3):
            charged = self.charge("new-chain-" + str(index), "handoff", OTHER if index % 2 else BUILDER)
            self.assess(charged, "assessed-" + str(index))
        root = self.ledger.root("root-builder")
        self.assertEqual(root.fields["state"], "held")
        with self.assertRaises(Denied):
            self.charge("another-chain", "handoff")
        with self.assertRaises(Denied):
            self.ledger.control_root(CONTROLLER, root.id, "active", expected_revision=root.revision)
        self.ledger.verify_progress = lambda *_: {"acceptance_complete": True}
        with self.assertRaises(Denied):
            self.ledger.progress(CONTROLLER, root.id, "claimed-progress", expected_revision=root.revision)
        self.assertEqual(self.ledger.root(root.id), root)

    def test_verified_progress_only_resets_watchdog_not_limits_or_usage(self):
        self.charge("turn-1")
        self.assess(self.charge("handoff-1", "handoff"), "completed-handoff-1")
        before = self.ledger.root("root-builder")
        after = self.ledger.progress(CONTROLLER, before.id, "verified-gate", expected_revision=before.revision)
        self.assertEqual(after.fields["usage"]["no_progress_handoffs"], 0)
        self.assertEqual(after.fields["usage"]["turns"], before.fields["usage"]["turns"])
        self.assertEqual(after.fields["limits"], before.fields["limits"])
        with self.assertRaises(Denied):
            self.ledger.progress(CONTROLLER, after.id, "verified-gate", expected_revision=after.revision)

    def test_clock_regression_and_deadline_never_reset_budget(self):
        self.charge("turn-1")
        self.fixture.clock[0] = NOW - 1
        with self.assertRaises(Denied):
            self.charge("turn-2")
        self.fixture.clock[0] = NOW + 7 * 86400000
        with self.assertRaises(Denied):
            self.charge("late-turn")
        self.assertEqual(self.ledger.root("root-builder").fields["usage"]["turns"], 1)

    def test_workers_cannot_create_roots_or_rewrite_limits_and_wrong_root_cannot_claim(self):
        with self.assertRaises(Denied):
            self.ledger.enroll_root(BUILDER, root_record(self.fixture.authority.policy.digest, root_id="new-root"))
        self.charge("turn-1")
        self.assertEqual(self.ledger.enroll_root(CONTROLLER, self.initial).fields["usage"]["turns"], 1)
        with self.assertRaises(Denied):
            self.ledger.enroll_root(CONTROLLER, root_record(self.fixture.authority.policy.digest, turns=50))
        with self.assertRaises(Denied):
            self.claim(REVIEWER)

    def test_dependencies_require_verified_completion_and_root_completion_requires_acceptance(self):
        self.enroll("dependent", resource="other-resource", dependencies=["work-1"])
        with self.assertRaises(Denied):
            self.claim(OTHER, "dependent-claim", "dependent")
        work = self.claim()["work"]
        self.ledger.finish_work(CONTROLLER, "work-1", "passed-work-gate", expected_revision=work["revision"])
        self.assertTrue(self.claim(OTHER, "dependent-claim", "dependent")["claimed_now"])
        self.charge("turn-1")
        root = self.ledger.root("root-builder")
        verify = self.ledger.verify_progress
        self.ledger.verify_progress = lambda *args: replace(verify(*args), acceptance_complete=False)
        with self.assertRaises(Denied):
            self.ledger.control_root(CONTROLLER, root.id, "completed", expected_revision=root.revision, evidence_id="partial")
        self.ledger.verify_progress = verify
        completed = self.ledger.control_root(CONTROLLER, root.id, "completed", expected_revision=root.revision, evidence_id="complete-gate")
        self.assertEqual(completed.fields["state"], "completed")
        self.assertIsNotNone(self.ledger.work("work-1")["binding"])

    def test_progress_and_quiescence_receipts_must_bind_current_scope(self):
        root = self.ledger.root("root-builder")
        verify = self.ledger.verify_progress
        self.ledger.verify_progress = lambda *args: replace(verify(*args), scope_digest="sha256:" + "d" * 64)
        with self.assertRaises(Denied):
            self.ledger.progress(CONTROLLER, root.id, "old-scope", expected_revision=root.revision)
        work = self.claim()["work"]
        quiesce = self.ledger.verify_quiescence
        self.ledger.verify_quiescence = lambda *args: replace(quiesce(*args), scope_digest="sha256:" + "d" * 64)
        with self.assertRaises(Denied):
            self.ledger.release(CONTROLLER, work["id"], expected_revision=work["revision"])

    def test_restore_keeps_counters_and_writers_with_no_current_fence_permission(self):
        work = self.claim()["work"]
        self.charge("turn-1")
        self.ledger.recover_inflight()
        self.assertEqual(self.ledger.root("root-builder").fields["state"], "held")
        self.assertEqual(self.ledger.root("root-builder").fields["usage"]["turns"], 1)
        self.assertEqual(self.ledger.work("work-1")["binding"], work["binding"])
        self.assertFalse(self.claim()["claimed_now"])
        with self.assertRaises(Denied):
            self.ledger.validate_fence(BUILDER, "work-1", work["fencing_token"])

    def test_revoked_execution_cannot_charge_or_validate_existing_fence(self):
        work = self.claim()["work"]
        self.fixture.authority.registry.revoke("builder.task")
        with self.assertRaises(Denied):
            self.charge("turn-1")
        with self.assertRaises(Denied):
            self.ledger.validate_fence(BUILDER, "work-1", work["fencing_token"])
        self.assertIsNotNone(self.ledger.work("work-1")["binding"])

    def test_actual_claim_and_charge_process_deaths_preserve_ownership_and_do_not_double_charge(self):
        for point in ("before_work_state_commit", "after_work_claim_commit", "after_root_charge_commit"):
            folder = self.folder / point
            with work_fixture(folder) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                f.ledger.enroll_work(CONTROLLER, work_id="work-1", root_id="root-builder", criteria=["Gate"], dependencies=[],
                                    assignee_role_id="builder", resource_id="fixture-worktree")
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("work_ownership_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with work_fixture(folder) as f:
                if point == "before_work_state_commit":
                    self.assertIsNone(f.ledger.work("work-1")["binding"])
                    claimed = f.ledger.checkout(OTHER, "work-1", "other-claim", expected_revision=0)
                    self.assertTrue(claimed["claimed_now"])
                    self.assertEqual(claimed["work"]["fencing_token"], 1)
                elif "claim" in point:
                    work = f.ledger.work("work-1")
                    self.assertIsNotNone(work["binding"])
                    self.assertEqual(work["state"], "held")
                    with self.assertRaises(Denied):
                        f.ledger.checkout(OTHER, "work-1", "other-claim", expected_revision=work["revision"])
                else:
                    root = f.ledger.root("root-builder")
                    self.assertFalse(f.ledger.charge(BUILDER, "turn-1", "turn", expected_revision=root.revision)["charged_now"])
                    self.assertEqual(f.ledger.root(root.id).fields["usage"]["turns"], 1)

    def test_actual_second_process_cannot_open_or_recover_a_live_owner_component(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("work_ownership_fault_fixture.py")), str(self.folder), "probe-lock"],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 74, result.stderr.decode())
        self.assertEqual(self.ledger.root("root-builder"), self.initial)

    def test_allocator_regression_and_future_schema_are_refused_before_recovery_mutates_state(self):
        for mode in ("allocator", "future", "result-index"):
            with work_fixture(self.folder / mode) as f:
                f.ledger.enroll_root(CONTROLLER, root_record(f.authority.policy.digest))
                f.ledger.enroll_work(CONTROLLER, work_id="work-1", root_id="root-builder", criteria=["Gate"], dependencies=[],
                                    assignee_role_id="builder", resource_id="fixture-worktree")
                f.ledger.checkout(BUILDER, "work-1", "claim-1", expected_revision=0)
                if mode == "future":
                    f.ledger.connection.execute("UPDATE work_metadata SET schema='future'")
                elif mode == "allocator":
                    f.ledger.connection.execute("UPDATE work_metadata SET next_fence=1")
                else:
                    root = f.ledger.root("root-builder")
                    f.ledger.progress(CONTROLLER, root.id, "verified-gate", expected_revision=root.revision)
                    f.ledger.connection.execute("DELETE FROM root_results")
                folder, authority = f.ledger.folder, f.authority
                now, progress, quiescence, handoff = f.ledger.now_ms, f.ledger.verify_progress, f.ledger.verify_quiescence, f.ledger.verify_handoff
                f.ledger.close()
                with mock.patch("relay_core.outbox.protected_path", side_effect=lambda path, **_: Path(path)), self.assertRaises(Denied):
                    WorkOwnership(folder, owner_uid=os.geteuid(), authority=authority, now_ms=now,
                                  verify_progress=progress, verify_quiescence=quiescence, verify_handoff=handoff)

    def test_inflight_delegations_and_repeated_assessments_do_not_inflate_watchdog(self):
        charged = [self.charge("inflight-" + str(index), "handoff") for index in range(3)]
        root = self.ledger.root("root-builder")
        self.assertEqual(root.fields["state"], "active")
        self.assertEqual(root.fields["usage"]["no_progress_handoffs"], 0)
        verify = self.ledger.verify_handoff
        self.ledger.verify_handoff = lambda *args: replace(verify(*args), completed=False)
        with self.assertRaises(Denied):
            self.assess(charged[0], "waiting")
        self.ledger.verify_handoff = verify
        self.assertTrue(self.assess(charged[0], "completed")["assessed_now"])
        self.assertFalse(self.assess(charged[0], "completed")["assessed_now"])
        self.assertEqual(self.ledger.root(root.id).fields["usage"]["no_progress_handoffs"], 1)

    def test_changed_evidence_id_for_same_verified_result_cannot_reset_progress(self):
        root = self.ledger.root("root-builder")
        verify = self.ledger.verify_progress
        self.ledger.verify_progress = lambda *args: replace(verify(*args), result_digest="sha256:" + "d" * 64)
        current = self.ledger.progress(CONTROLLER, root.id, "first-result", expected_revision=root.revision)
        with self.assertRaises(Denied):
            self.ledger.progress(CONTROLLER, root.id, "renamed-result", expected_revision=current.revision)
        self.assertEqual(self.ledger.root(root.id), current)
        charge = self.charge("same-result-delegation", "handoff")
        verify_handoff = self.ledger.verify_handoff
        self.ledger.verify_handoff = lambda *args: replace(verify_handoff(*args), progress_evidence_id="renamed-result")
        assessed = self.assess(charge, "assessed-duplicate")["record"]
        self.assertEqual(assessed.fields["usage"]["no_progress_handoffs"], 1)
        self.assertNotIn("renamed-result", assessed.fields["verified_evidence_ids"])

    def test_handoff_progress_uses_independent_criteria_evidence_and_threshold_is_pinned(self):
        self.assess(self.charge("handoff-1", "handoff"), "no-progress-1")
        charged = self.charge("handoff-2", "handoff")
        verify = self.ledger.verify_handoff
        self.ledger.verify_handoff = lambda *args: replace(verify(*args), progress_evidence_id="verified-result")
        current = self.assess(charged, "assessed-result")["record"]
        self.assertEqual(current.fields["usage"]["no_progress_handoffs"], 0)
        self.assertEqual(current.fields["usage"]["delegations"], 2)
        self.assertIn("verified-result", current.fields["verified_evidence_ids"])
        self.assertEqual(self.ledger.threshold(current.id), 3)
        with self.assertRaises(Denied):
            self.ledger.enroll_root(CONTROLLER, self.initial, watchdog_handoffs=99)


if __name__ == "__main__":
    unittest.main()
