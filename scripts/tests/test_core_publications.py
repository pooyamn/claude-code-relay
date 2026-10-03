"""Real publication/custody/outbox conformance, with synthetic GitHub/CI facts."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from native_session_fixtures import CONTROLLER
from owner_fixtures import writable_fixture_tree
from publication_fixtures import BASE, BUILDER, CTO, HEAD, OTHER, REVIEWER, execute, open_publication, publication_fixture, publish, reviewed
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied
from relay_core.publications import PublicationPolicy


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.addCleanup(writable_fixture_tree, self.folder)
        self.manager = publication_fixture(self.folder)
        self.s = self.manager.__enter__()
        self.addCleanup(lambda: self.manager.__exit__(None, None, None))
        self.engine, self.ledger = self.s.engine, self.s.ledger
        self.root = self.ledger.root("root-builder")

    def request(self, key="merge-1", pub="pub-1", head=HEAD):
        return self.engine.request_merge(CTO, key, pub, head_sha=head, base_sha=self.s.state["base"])

    def prepared_merge(self):
        reviewed(self.s)
        return self.request()

    def claim_merge(self, key="merge-1", attempt="merge-attempt-1"):
        return self.engine.claim_merge(CONTROLLER, key, attempt)

    def test_publication_stores_fresh_branch_and_separate_effects_without_pushing(self):
        first = publish(self.s)
        self.assertTrue(first["stored_now"])
        self.assertEqual(first["publication"]["branch"], "pub/builder.task/1")
        self.assertEqual(set(first["publication"]["actions"]), {"branch", "pull_request"})
        self.assertEqual(self.s.provider.count(), 0)
        self.assertEqual(self.ledger.root("root-builder"), self.root)
        self.assertFalse(self.s.admission._attempts())
        self.assertFalse(publish(self.s)["stored_now"])

    def test_one_open_publication_and_stable_id_cannot_change_commit(self):
        publish(self.s)
        with self.assertRaises(Denied):
            publish(self.s, head="f" * 40)
        with self.assertRaises(Denied):
            publish(self.s, key="another-publication")
        self.assertEqual(self.s.provider.count(), 0)

    def test_unconfirmed_branch_cannot_open_pr_or_receive_review(self):
        publish(self.s)
        with self.assertRaises(Denied):
            self.engine.claim_publish(CONTROLLER, "pub-1", "pull_request", "pr-attempt")
        with self.assertRaises(Denied):
            self.engine.sync_open(CONTROLLER, "pub-1")
        with self.assertRaises(Denied):
            self.engine.review(REVIEWER, "pub-1", "review-1", head_sha=HEAD, verdict="approve")

    def test_publication_request_requires_current_custody_and_coherent_checkpoint(self):
        verify = self.engine.verify_checkpoint
        for change in ({"coherent": False}, {"leases_valid": False}, {"head_sha": "f" * 40}):
            self.engine.verify_checkpoint = lambda scope, change=change: replace(verify(scope), **change)
            with self.assertRaises(Denied):
                publish(self.s)
        self.engine.verify_checkpoint = verify
        with self.assertRaises(Denied):
            self.engine.publish(BUILDER, "pub-1", "work-1", "fixture", HEAD, fencing_token=999)

    def test_builder_cannot_approve_request_merge_or_dispatch_effects(self):
        open_publication(self.s)
        for action in (lambda: self.engine.review(BUILDER, "pub-1", "self-approval", head_sha=HEAD, verdict="approve"),
                       lambda: self.engine.request_merge(BUILDER, "self-merge", "pub-1", head_sha=HEAD, base_sha=BASE),
                       lambda: self.engine.claim_publish(BUILDER, "pub-1", "branch", "worker-attempt")):
            with self.assertRaises(Denied):
                action()

    def test_review_binds_exact_head_and_reject_verdict_cannot_merge(self):
        open_publication(self.s)
        with self.assertRaises(Denied):
            self.engine.review(REVIEWER, "pub-1", "stale-review", head_sha="f" * 40, verdict="approve")
        first = self.engine.review(REVIEWER, "pub-1", "review-1", head_sha=HEAD, verdict="reject")
        self.assertEqual(self.engine.review(REVIEWER, "pub-1", "review-1", head_sha=HEAD, verdict="reject"), first)
        with self.assertRaises(Denied):
            self.engine.review(REVIEWER, "pub-1", "review-1", head_sha=HEAD, verdict="approve")
        execute(self.s, self.engine.claim_publish(CONTROLLER, "pub-1", "review", "review-attempt"))
        self.request()
        with self.assertRaises(Denied):
            self.claim_merge()

    def test_same_tool_reviewer_is_not_an_independent_review(self):
        open_publication(self.s)
        original = self.engine._actor
        self.engine._actor = lambda *args: (original(*args)[0], {**original(*args)[1], "provider": "codex"})
        with self.assertRaises(Denied):
            self.engine.review(REVIEWER, "pub-1", "review-1", head_sha=HEAD, verdict="approve")

    def test_minimal_single_repository_installation_scope_is_required(self):
        publish(self.s)
        verify = self.engine.verify_app
        for change in ({"repository_ids": (123, 999)}, {"permissions": {"contents": "write", "administration": "write"}},
                       {"installation_id": 999}, {"app_id": 999}, {"expires_ms": 1}):
            self.engine.verify_app = lambda scope, change=change: replace(verify(scope), **change)
            with self.assertRaises(Denied):
                self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")
        self.assertEqual(self.s.provider.count(), 0)

    def test_owner_screening_denial_or_pause_prevents_publication_dispatch(self):
        publish(self.s)
        verify = self.engine.verify_authority
        self.engine.verify_authority = lambda scope: replace(verify(scope), allowed=False)
        with self.assertRaises(Denied):
            self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")
        self.engine.verify_authority = verify
        root = self.ledger.root("root-builder")
        self.ledger.set_owner_control(CONTROLLER, root.id, "paused", expected_revision=root.revision)
        with self.assertRaises(Denied):
            self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")

    def test_remote_head_change_invalidates_review_and_merge(self):
        self.prepared_merge()
        read = self.engine.observe_remote
        self.engine.observe_remote = lambda scope: replace(read(scope), head_sha="f" * 40)
        with self.assertRaises(Denied):
            self.claim_merge()
        with self.assertRaises(Denied):
            self.engine.review(REVIEWER, "pub-1", "review-2", head_sha=HEAD, verdict="approve")

    def test_base_change_invalidates_old_request_and_build_gate(self):
        self.prepared_merge()
        self.s.state["base"] = "f" * 40
        with self.assertRaises(Denied):
            self.claim_merge()
        with self.assertRaises(Denied):
            self.engine.request_merge(CTO, "merge-1", "pub-1", head_sha=HEAD, base_sha=self.s.state["base"])
        self.assertIsNone(self.ledger.load(self.engine.merge_request("merge-1")["action_id"])["record"].fields["attempt_id"])

    def test_model_review_never_substitutes_for_independent_current_target_tests(self):
        self.prepared_merge()
        verify = self.engine.verify_tests
        for change in ({"passed": False}, {"independent_isolated_runner": False}, {"base_sha": "f" * 40}, {"head_sha": "f" * 40}, {"observed_ms": 0}):
            self.engine.verify_tests = lambda scope, change=change: replace(verify(scope), **change)
            with self.assertRaises(Denied):
                self.claim_merge()

    def test_direct_merge_or_missing_per_group_pair_check_is_never_a_fallback(self):
        self.prepared_merge()
        verify = self.engine.verify_queue
        for field in ("require_merge_queue", "squash", "no_bypass", "authorized_pair_check", "merge_group_ci"):
            self.engine.verify_queue = lambda scope, field=field: replace(verify(scope), **{field: False})
            with self.assertRaises(Denied):
                self.claim_merge()

    def test_reviewer_or_cto_revocation_during_test_read_prevents_dispatch(self):
        self.prepared_merge()
        verify = self.engine.verify_tests
        def revoke(scope):
            self.s.f.authority.registry.revoke("cto.task")
            return verify(scope)
        self.engine.verify_tests = revoke
        with self.assertRaises(Denied):
            self.claim_merge()
        self.assertFalse(self.ledger.connection.execute("SELECT * FROM merge_slots").fetchall())

    def test_base_race_during_independent_tests_cannot_use_previous_snapshot(self):
        self.prepared_merge()
        verify = self.engine.verify_tests
        def move(scope):
            result = verify(scope)
            self.s.state["base"] = "f" * 40
            return result
        self.engine.verify_tests = move
        with self.assertRaises(Denied):
            self.claim_merge()

    def test_base_change_during_final_installation_read_denies_merge_atomically(self):
        self.prepared_merge()
        verify = self.engine.verify_app
        calls = []
        def move(scope):
            proof = verify(scope)
            calls.append(True)
            if len(calls) == 2:
                self.s.state["base"] = "f" * 40
            return proof
        self.engine.verify_app = move
        with self.assertRaises(Denied):
            self.claim_merge()
        self.assertFalse(self.ledger.connection.execute("SELECT * FROM merge_slots").fetchall())
        action = self.engine.merge_request("merge-1")["action_id"]
        self.assertIsNone(self.engine.grant(action))
        self.assertIsNone(self.ledger.load(action)["record"].fields["attempt_id"])

    def test_authority_change_during_final_installation_read_denies_merge(self):
        self.prepared_merge()
        verify, authority = self.engine.verify_app, self.engine.verify_authority
        calls = []
        def revoke(scope):
            proof = verify(scope)
            calls.append(True)
            if len(calls) == 2:
                self.engine.verify_authority = lambda checked: replace(authority(checked), allowed=False)
            return proof
        self.engine.verify_app = revoke
        with self.assertRaises(Denied):
            self.claim_merge()
        self.assertFalse(self.ledger.connection.execute("SELECT * FROM merge_slots").fetchall())

    def test_publication_claim_retains_exact_checkpoint_authority_and_app_evidence(self):
        body = publish(self.s)["publication"]
        action_id = body["actions"]["branch"]
        self.assertIsNone(self.engine.grant(action_id))
        result = self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")
        grant = self.engine.grant(action_id)
        self.assertEqual(grant["attempt_id"], "branch-attempt")
        self.assertEqual(grant["plan_digest"], result["plan_digest"])
        self.assertEqual(grant["evidence"]["scope"]["publication"], body)
        self.assertEqual(grant["evidence"]["checkpoint"]["head_sha"], HEAD)
        self.assertEqual(grant["evidence"]["app"]["repository_ids"], [123])
        self.assertEqual(set(grant["evidence"]["app"]), {"scope_digest", "source_digest", "app_id", "installation_id", "repository_ids", "permissions", "expires_ms"})
        self.assertTrue(grant["evidence"]["authority"]["allowed"])
        self.assertFalse(self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")["may_execute"])
        self.assertEqual(self.engine.grant(action_id), grant)
        self.assertEqual(self.s.provider.count(), 0)

    def test_merge_claim_retains_current_target_tests_and_queue_evidence(self):
        request = self.prepared_merge()
        result = self.claim_merge()
        grant = self.engine.grant(request["action_id"])
        self.assertEqual(grant["plan_digest"], result["plan_digest"])
        self.assertEqual(grant["evidence"]["scope"]["merge_request"], request)
        self.assertEqual(grant["evidence"]["remote"]["base_sha"], BASE)
        self.assertEqual(grant["evidence"]["tests"]["base_sha"], BASE)
        self.assertTrue(grant["evidence"]["tests"]["independent_isolated_runner"])
        self.assertEqual(grant["evidence"]["rules"]["required_checks"], self.engine.policy.repositories["fixture"]["required_checks"])
        self.assertFalse(self.claim_merge()["may_execute"])
        self.assertEqual(self.engine.grant(request["action_id"]), grant)

    def test_missing_publication_grant_denies_replay_and_reinitialization(self):
        publish(self.s)
        result = self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")
        self.ledger.connection.execute("DELETE FROM publication_grants WHERE intent_id=?", (result["record"].id,))
        with self.assertRaises(Denied):
            self.engine.claim_publish(CONTROLLER, "pub-1", "branch", "branch-attempt")
        with self.assertRaises(Denied):
            self.engine.initialize(CONTROLLER)
        self.assertEqual(self.s.provider.count(), 0)

    def test_changed_grant_even_with_new_storage_hash_is_not_plan_authority(self):
        request = self.prepared_merge()
        self.claim_merge()
        grant = self.engine.grant(request["action_id"])
        grant["evidence"]["tests"]["base_sha"] = "f" * 40
        self.ledger.connection.execute("UPDATE publication_grants SET body=?,digest=? WHERE intent_id=?",
                                       (canonical_bytes(grant), fingerprint(grant), request["action_id"]))
        with self.assertRaises(Denied):
            self.claim_merge()
        with self.assertRaises(Denied):
            self.engine.initialize(CONTROLLER)
        self.assertEqual(self.ledger.connection.execute("SELECT request_id FROM merge_slots").fetchall(), [("merge-1",)])

    def test_two_merges_serialize_and_enqueued_or_unknown_does_not_release_slot(self):
        self.prepared_merge()
        reviewed(self.s, "pub-2", OTHER, "work-2", "f" * 40)
        self.request("merge-2", "pub-2", "f" * 40)
        with self.assertRaises(Denied):
            self.claim_merge("merge-2", "merge-attempt-2")
        first = self.claim_merge()
        evidence = self.s.provider.call(first)
        self.ledger.unknown(first["record"].id, first["record"].fields["attempt_id"])
        self.assertFalse(self.claim_merge()["may_execute"])
        with self.assertRaises(Denied):
            self.claim_merge("merge-2", "merge-attempt-2")
        with self.assertRaises(Denied):
            self.engine.settle_merge(CONTROLLER, "merge-1")
        self.ledger.reconcile(evidence)
        self.assertFalse(self.engine.settle_merge(CONTROLLER, "merge-1")["settled_now"])
        with self.assertRaises(Denied):
            self.claim_merge("merge-2", "merge-attempt-2")
        self.s.state["result"] = "merged"
        self.assertTrue(self.engine.settle_merge(CONTROLLER, "merge-1")["settled_now"])
        self.assertFalse(self.engine.settle_merge(CONTROLLER, "merge-1")["settled_now"])
        self.assertTrue(self.claim_merge("merge-2", "merge-attempt-2")["may_execute"])
        self.assertEqual(self.engine.load("pub-1")["phase"], "merged")
        self.assertEqual(self.ledger.root("root-builder").fields["usage"], self.root.fields["usage"])
        self.assertFalse(self.s.admission._attempts())

    def test_cancel_unattempted_request_keeps_history_but_attempted_cannot_replay(self):
        self.prepared_merge()
        self.engine.cancel_merge(CTO, "merge-1")
        with self.assertRaises(Denied):
            self.claim_merge()
        self.assertIsNotNone(self.engine.merge_request("merge-1"))
        self.request("merge-2")
        execute(self.s, self.claim_merge("merge-2", "merge-attempt-2"))
        with self.assertRaises(Denied):
            self.engine.cancel_merge(CTO, "merge-2")
        self.assertFalse(self.claim_merge("merge-2", "merge-attempt-2")["may_execute"])

    def test_closed_publication_frees_session_but_next_branch_is_new_and_terminal_cannot_reopen(self):
        open_publication(self.s)
        self.s.state["remote"] = "closed"
        self.assertEqual(self.engine.sync_open(CONTROLLER, "pub-1")["phase"], "closed")
        second = publish(self.s, "pub-2", head="f" * 40)
        self.assertEqual(second["publication"]["branch"], "pub/builder.task/2")
        self.s.state["remote"] = "open"
        with self.assertRaises(Denied):
            self.engine.sync_open(CONTROLLER, "pub-1")

    def test_unchanged_review_is_not_accepted_without_confirmed_status_delivery(self):
        open_publication(self.s)
        self.engine.review(REVIEWER, "pub-1", "review-1", head_sha=HEAD, verdict="approve")
        self.request()
        with self.assertRaises(Denied):
            self.claim_merge()

    def test_unknown_publication_and_schema_or_changed_policy_are_not_authority(self):
        with self.assertRaises(Denied):
            self.engine.sync_open(CONTROLLER, "missing-publication")
        raw = self.engine.policy.body
        changed = {**raw, "test_max_age_ms": 2000}
        self.engine.policy = PublicationPolicy(changed)
        with self.assertRaises(Denied):
            self.engine.initialize(CONTROLLER)

    def test_actual_branch_and_merge_deaths_retain_attempts_and_do_not_repeat_effects(self):
        points = ("before_publication_store_commit", "after_publication_store_commit", "before_publication_branch_commit",
                  "after_publication_branch_commit", "after_fake_branch_effect", "before_merge_request_commit", "after_merge_request_commit",
                  "before_publication_merge_commit", "after_publication_merge_commit", "after_fake_merge_effect",
                  "before_publication_settle_commit", "after_publication_settle_commit")
        for point in points:
            folder = self.folder / point
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("publication_fault_fixture.py")), str(folder), point],
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            with publication_fixture(folder) as s:
                self.assertEqual(s.ledger.root("root-builder").fields["state"], "held")
                self.assertFalse(s.admission._attempts())
                body = s.engine.load("pub-1")
                if point == "before_publication_store_commit":
                    self.assertIsNone(body)
                    self.assertEqual(s.provider.count(), 0)
                elif point == "after_publication_settle_commit":
                    self.assertEqual(body["phase"], "merged")
                    self.assertFalse(s.engine.settle_merge(CONTROLLER, "merge-1")["settled_now"])
                    self.assertFalse(s.ledger.connection.execute("SELECT * FROM merge_slots").fetchall())
                elif point in {"after_publication_branch_commit", "after_fake_branch_effect"}:
                    before = s.provider.count()
                    self.assertFalse(s.engine.claim_publish(CONTROLLER, "pub-1", "branch", "attempt-pub-1-branch")["may_execute"])
                    self.assertEqual(s.provider.count(), before)
                    self.assertEqual(s.engine.grant(body["actions"]["branch"])["attempt_id"], "attempt-pub-1-branch")
                elif point in {"after_publication_merge_commit", "after_fake_merge_effect", "before_publication_settle_commit"}:
                    before = s.provider.count()
                    self.assertFalse(s.engine.claim_merge(CONTROLLER, "merge-1", "merge-attempt-1")["may_execute"])
                    self.assertEqual(s.provider.count(), before)
                    self.assertEqual(s.ledger.connection.execute("SELECT request_id FROM merge_slots").fetchall(), [("merge-1",)])
                    self.assertEqual(s.engine.grant(s.engine.merge_request("merge-1")["action_id"])["attempt_id"], "merge-attempt-1")
                elif point == "before_publication_branch_commit":
                    self.assertIsNone(s.engine.grant(body["actions"]["branch"]))
                elif point == "before_publication_merge_commit":
                    self.assertIsNone(s.engine.grant(s.engine.merge_request("merge-1")["action_id"]))
                    self.assertFalse(s.ledger.connection.execute("SELECT * FROM merge_slots").fetchall())
