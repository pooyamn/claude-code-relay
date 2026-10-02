"""Joined durable source grants + send guard. Mac kernel identities are fakes."""
import copy
from dataclasses import replace
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from relay_core.contracts import canonical_bytes
from relay_core.identity import Denied, Peer
from relay_core.telegram_authority import DispatchPermit, DispatchRequest, SourceGrants
from relay_core.telegram_outbound import SingleAttemptBot
from relay_core.telegram_producers import TelegramProducers
from relay_core.telegram_scheduler import TelegramScheduler
from source_grant_fixtures import CONTROLLER, sources
from telegram_fixtures import FakeOutbound, asset_store, open_telegram, protected_fixture, rejected, reply
from test_core_telegram import TelegramFixture
from test_core_telegram_repair import authorization


class SourceTests(TelegramFixture):
    def setUp(self):
        super().setUp()
        self.context_allowed = True
        self.checks = []
        def current_check(body, binding):
            self.checks.append((body["id"], binding["session_id"]))
            return self.context_allowed
        self.joined = sources(self.folder / "authority", self.ledger, current_check=current_check)
        self.grants, self.authority = self.joined.__enter__()
        self.addCleanup(lambda: self.joined.__exit__(None, None, None))
        self.scheduler = TelegramScheduler(self.ledger, self.bot, self.store, ownership_check=self.guard.check,
                                            authorize_dispatch=self.grants.authorize, authorize_repair=authorization)
        self.producer = TelegramProducers(self.ledger, authorize_source=self.grants.enrollment_allowed)

    def enroll(self, **kwargs):
        body = reply(**kwargs)
        self.grants.issue(CONTROLLER, body, expires_ms=self.now + 86400000)
        self.producer.enqueue(body)
        return body

    def current_item(self, body):
        return {**self.ledger.items(body["id"])[0], "bundle": body}

    def test_missing_current_checker_or_guarded_transport_rejected_before_network(self):
        with self.assertRaises(Denied):
            TelegramScheduler(self.ledger, self.bot, self.store, ownership_check=self.guard.check, authorize_dispatch=None)
        self.bot.dispatch_contract = "old-unfenced-adapter"
        with self.assertRaises(Denied):
            TelegramScheduler(self.ledger, self.bot, self.store, ownership_check=self.guard.check, authorize_dispatch=self.grants.authorize)
        with self.assertRaises(Denied):
            SourceGrants(self.folder / "authority" / "grants", ledger=self.ledger, authority=self.authority, current_check=None)
        self.assertEqual(self.bot.calls(), [])

    def test_registered_worker_and_caller_uid_header_cannot_issue_or_revoke_grants(self):
        body = reply()
        for peer in (Peer(12, 101, 121), Peer(13, 99, 121), {"uid": 0, "role": "controller"}):
            with self.assertRaises(Denied):
                self.grants.issue(peer, body, expires_ms=self.now + 10000)
        self.enroll()
        with self.assertRaises(Denied):
            self.grants.revoke(Peer(12, 101, 121), "reply-1")
        self.assertFalse(self.grants.grant("reply-1")["revoked"])

    def test_unregistered_source_root_mismatch_expired_and_context_denied_cannot_enroll(self):
        for changes in ({"session_id": "reviewer.other"}, {"root_task_id": "foreign-root"}):
            with self.assertRaises(Denied):
                self.grants.issue(CONTROLLER, {**reply(), **changes}, expires_ms=self.now + 10000)
        with self.assertRaises(Denied):
            self.grants.issue(CONTROLLER, reply(), expires_ms=self.now)
        self.context_allowed = False
        with self.assertRaises(Denied):
            self.grants.issue(CONTROLLER, reply(), expires_ms=self.now + 10000)
        with self.assertRaises(Denied):
            self.producer.enqueue(reply())
        self.assertIsNone(self.ledger.bundle("reply-1"))

    def test_grant_binds_full_manifest_route_native_ids_content_and_alternatives(self):
        body = self.enroll()
        for key, value in (("chat_id", -1004), ("thread_id", 7), ("session_id", "foreign"), ("root_task_id", "other-root")):
            changed = {**body, key: value}
            with self.assertRaises(Denied):
                self.grants.enrollment_allowed(changed)
        for key in ("native_session_id", "turn_id", "submission_id"):
            changed = copy.deepcopy(body)
            changed["source"][key] = "foreign"
            with self.assertRaises(Denied):
                self.grants.enrollment_allowed(changed)
        changed = copy.deepcopy(body)
        changed["operations"][0]["args"]["text"] = "changed"
        with self.assertRaises(Denied):
            self.grants.enrollment_allowed(changed)
        self.assertEqual(self.bot.count(), 0)

    def test_revoked_queued_source_is_held_without_attempt_and_other_work_continues(self):
        self.enroll(count=2, cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.enroll(bundle_id="unrelated", chat_id=-1004)
        self.grants.revoke(CONTROLLER, "reply-1")
        self.assertEqual(self.send()["state"], "held")
        denied = self.ledger.items("reply-1")[0]["current"]
        self.assertIsNone(denied["record"].fields["attempt_id"])
        self.assertEqual(denied["hold_reason"], "source_authorization_denied")
        status = self.ledger.status("reply-1")
        self.assertEqual(status["state"], "held")
        self.assertEqual(status["hold_reasons"], ["source_authorization_denied", None])
        self.assertEqual(self.scheduler.step()["bundle_id"], "unrelated")
        self.assertEqual(self.bot.count(), 1)
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)

    def test_revocation_between_confirmed_chunks_preserves_receipt_and_offset(self):
        self.enroll(count=2, cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.send()
        first = self.ledger.items("reply-1")[0]["current"]
        self.grants.revoke(CONTROLLER, "reply-1")
        self.assertEqual(self.tick()["state"], "held")
        self.assertEqual(self.ledger.items("reply-1")[0]["current"], first)
        self.assertEqual(self.bot.count(), 1)
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(self.ledger.stream("stream-1")["tail_cursor"], 50)

    def test_registry_revocation_and_context_grant_loss_each_fence_pending_output(self):
        self.enroll()
        self.authority.registry.revoke("builder.fixture")
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)

    def test_context_unavailability_holds_and_only_fresh_explicit_release_can_resume(self):
        self.enroll()
        self.context_allowed = False
        self.assertEqual(self.send()["state"], "held")
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        with self.assertRaises(Denied):
            self.scheduler.release_source_hold(intent)
        self.context_allowed = True
        self.assertFalse(self.scheduler.step()["submitted"])  # no automatic release
        self.scheduler.release_source_hold(intent)
        self.assertEqual(self.scheduler.step()["state"], "confirmed")
        self.assertEqual(self.bot.count(), 1)

    def test_revoke_after_claim_is_caught_at_final_pre_request_check(self):
        self.enroll()
        def checkpoint(name):
            if name == "after_claim_commit":
                self.grants.revoke(CONTROLLER, "reply-1")
        self.ledger.checkpoint = checkpoint
        self.assertEqual(self.send()["state"], "unknown")
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(self.bot.calls("sendMessage"), [])
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        with self.assertRaises(Denied):
            self.scheduler.release_source_hold(intent)
        self.assertFalse(self.tick()["submitted"])

    def test_changed_permission_revision_after_claim_cannot_send(self):
        self.enroll()
        original = self.grants.authorize
        calls = []
        def changed(request):
            permit = original(request)
            calls.append(request)
            return replace(permit, grant_revision=permit.grant_revision + (len(calls) > 1))
        self.scheduler.authorize_dispatch = changed
        self.assertEqual(self.send()["state"], "unknown")
        self.assertEqual(self.bot.count(), 0)

    def test_boolean_json_and_foreign_permission_claims_never_send(self):
        self.enroll()
        for value in (True, {"grant_id": "owner-approved"}, None):
            self.scheduler.authorize_dispatch = lambda _, value=value: value
            self.assertEqual(self.send()["state"], "held")
            intent = self.ledger.items("reply-1")[0]["current"]["record"].id
            self.scheduler.authorize_dispatch = self.grants.authorize
            self.scheduler.release_source_hold(intent)
        def foreign(request):
            return DispatchPermit(replace(request, bundle_id="foreign"), "grant-other", 1, self.now + 10000)
        self.scheduler.authorize_dispatch = foreign
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)

    def test_dispatch_plan_records_real_grant_and_operation_not_a_static_bundle_hash(self):
        body = self.enroll()
        request = DispatchRequest.for_item(self.ledger.policy, self.current_item(body))
        permit = self.grants.authorize(request)
        self.assertEqual(self.send()["state"], "confirmed")
        current = self.ledger.items(body["id"])[0]["current"]
        self.assertEqual(current["plan"]["authorization_id"], permit.authorization_id)
        self.assertEqual(current["record"].fields["authorization_id"], permit.authorization_id)
        self.assertGreaterEqual(len(self.checks), 4)  # issuance, enrollment, claim, wire

    def test_rate_replacement_rechecks_original_source_grant(self):
        body = reply()
        self.grants.issue(CONTROLLER, body, expires_ms=self.now + 100000)
        self.producer.enqueue(body)
        self.bot.responses = [rejected()]
        self.send()
        self.grants.revoke(CONTROLLER, body["id"])
        self.now += 30000
        self.assertEqual(self.scheduler.step()["state"], "held")
        self.assertEqual(len(self.bot.calls("sendMessage")), 1)

    def test_authorized_repair_inherits_original_grant_and_revocation_stops_child(self):
        # Enroll the formatter's exact body through a protected controller, not
        # by approving a new child ID after failure.
        from relay_core.telegram_producers import bundle, text_plan
        operations, recipes = text_plan("**fixture**", -1003, 5)
        body = bundle(bundle_id="original", root_task_id="root-1", session_id="builder.fixture", chat_id=-1003,
                      thread_id=5, lane="reply", source_kind="owner_reply", native_session_id="native-1", turn_id="turn-1",
                      submission_id="submission-1", content="**fixture**", operations=operations, repair_plans=recipes)
        self.grants.issue(CONTROLLER, body, expires_ms=self.now + 100000)
        self.producer.enqueue(body)
        self.bot.responses = [rejected(400)]
        self.send()
        child = self.ledger.items("original")[0]["repair"]["id"]
        self.assertIsNone(self.grants.grant(child))
        self.grants.revoke(CONTROLLER, "original")
        self.assertEqual(self.tick()["state"], "held")
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(self.ledger.load(self.ledger.items("original")[0]["current"]["record"].id)["record"].fields["state"], "failed")

    def test_revocation_survives_consistent_snapshot_and_reopening_without_unrevoke(self):
        body = self.enroll()
        self.grants.revoke(CONTROLLER, body["id"])
        snapshot = self.folder / "saved-source.sqlite"
        self.grants.snapshot(snapshot)
        db = sqlite3.connect(snapshot)
        saved = db.execute("SELECT body FROM grants").fetchone()[0]
        db.close()
        self.assertIn(b'"revoked":true', saved)
        second = SourceGrants(self.folder / "authority" / "grants", ledger=self.ledger, authority=self.authority, current_check=lambda *args: True)
        try:
            self.assertTrue(second.grant(body["id"])["revoked"])
            with self.assertRaises(Denied):
                second.issue(CONTROLLER, body, expires_ms=self.now + 86400000)
            with self.assertRaises(Denied):
                second.enrollment_allowed(body)
        finally:
            second.close()

    def test_unknown_schema_and_modified_grant_index_preserved_not_reset(self):
        body = self.enroll()
        self.grants.db.execute("UPDATE grants SET digest='changed'")
        with self.assertRaises(Denied):
            self.grants.grant(body["id"])
        self.grants.db.execute("UPDATE metadata SET schema='unknown.v100'")
        with self.assertRaises(Denied):
            SourceGrants(self.folder / "authority" / "grants", ledger=self.ledger, authority=self.authority, current_check=lambda *args: True)
        self.assertEqual(self.grants.db.execute("SELECT schema FROM metadata").fetchone()[0], "unknown.v100")

    def test_expiry_before_claim_preserves_content_without_send(self):
        self.enroll()
        self.now += 86400000
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)

    def test_expiry_after_claim_fences_wire_and_cannot_replay_the_attempt(self):
        self.enroll()
        def checkpoint(name):
            if name == "after_claim_commit":
                self.now += 86400000
        self.ledger.checkpoint = checkpoint
        self.assertEqual(self.send()["state"], "unknown")
        self.assertEqual(self.bot.calls("sendMessage"), [])
        self.assertFalse(self.scheduler.step()["submitted"])

    def test_exact_binding_change_cannot_reuse_old_source_permission(self):
        self.enroll()
        original = self.authority.registry.session
        def session(sid):
            binding = original(sid)
            return {**binding, "leader_start": binding["leader_start"].split(":")[0] + ":999"}
        with mock.patch.object(self.authority.registry, "session", side_effect=session):
            self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.count(), 0)

    def test_revocation_during_slow_context_check_is_detected_before_admission(self):
        self.enroll()
        def check(body, binding):
            self.grants.revoke(CONTROLLER, body["id"])
            return True
        self.grants.current_check = check
        self.assertEqual(self.send()["state"], "held")
        self.assertEqual(self.bot.calls("sendMessage"), [])

    def test_explicit_renewal_preserves_revocation_history_and_releases_only_unattempted_content(self):
        body = self.enroll()
        self.grants.revoke(CONTROLLER, body["id"])
        self.assertEqual(self.send()["state"], "held")
        intent = self.ledger.items(body["id"])[0]["current"]["record"].id
        self.grants.renew(CONTROLLER, body, expires_ms=self.now + 100000)
        value = self.grants.grant(body["id"])
        self.assertEqual(value["revision"], 3)
        self.assertFalse(value["revoked"])
        history = self.grants.db.execute("SELECT body FROM grant_events WHERE bundle_id=? ORDER BY revision", (body["id"],)).fetchall()
        self.assertEqual(len(history), 3)
        self.assertIn(b'"revoked":true', history[1][0])
        self.assertFalse(self.scheduler.step()["submitted"])
        self.scheduler.release_source_hold(intent)
        self.assertEqual(self.scheduler.step()["state"], "confirmed")
        self.assertEqual(self.bot.count(), 1)

    def test_renewal_cannot_change_content_or_gain_permission_after_revocation(self):
        body = self.enroll()
        changed = copy.deepcopy(body)
        changed["operations"][0]["args"]["text"] = "different"
        with self.assertRaises(Denied):
            self.grants.renew(CONTROLLER, changed, expires_ms=self.now + 100000)
        with self.assertRaises(Denied):
            self.grants.renew(Peer(12, 101, 121), body, expires_ms=self.now + 100000)
        self.context_allowed = False
        with self.assertRaises(Denied):
            self.grants.renew(CONTROLLER, body, expires_ms=self.now + 100000)
        self.assertEqual(self.grants.grant(body["id"])["revision"], 1)

    def test_guarded_config_requires_distinct_source_state_and_rejects_old_examples(self):
        from ccrelay_outbound import configuration
        cfg = {"schema": "ccrelay.telegram_outbound_config.v2", "enabled": False, "test_bot": "khadang",
               "policy_path": "/etc/fixture/policy.json", "state_dir": "/var/lib/fixture/send",
               "asset_dir": "/var/lib/fixture/assets", "source_grant_dir": "/var/lib/fixture/sources"}
        self.assertEqual(configuration(cfg), cfg)
        for changed in ({**cfg, "schema": "ccrelay.telegram_outbound_config.v1"},
                        {**cfg, "source_grant_dir": cfg["state_dir"]}, {**cfg, "enabled": True}):
            with self.assertRaises(Denied):
                configuration(changed)


class TransportGuardTests(unittest.TestCase):
    def test_missing_denied_or_raising_final_guard_never_calls_opener(self):
        opener = mock.Mock()
        bot = SingleAttemptBot("1002:INVENTED_TOKEN", opener=opener)
        for guard in (None, lambda: False, mock.Mock(side_effect=Denied("current grant revoked"))):
            with self.assertRaises(Denied):
                bot.request("sendMessage", {"chat_id": -1003, "text": "fixture"}, {}, None, before_send=guard)
        opener.open.assert_not_called()

    def test_guard_runs_after_asset_assembly_and_revocation_blocks_actual_request(self):
        from telegram_fixtures import asset_store, protected_fixture
        import tempfile
        with tempfile.TemporaryDirectory() as folder, protected_fixture():
            store = asset_store(Path(folder) / "assets")
            ref = store.stage(b"invented voice", filename="sample.ogg", mime_type="audio/ogg")
            allowed = [True]
            original = store.read
            def read(reference):
                data = original(reference)
                allowed[0] = False
                return data
            opener = mock.Mock()
            bot = SingleAttemptBot("1002:INVENTED_TOKEN", opener=opener)
            with mock.patch.object(store, "read", side_effect=read), self.assertRaises(Denied):
                bot.request("sendVoice", {"chat_id": -1003, "voice": "attach://voice"}, {"voice": ref}, store,
                            before_send=lambda: allowed[0])
            opener.open.assert_not_called()


class SourceCrashTests(unittest.TestCase):
    def test_four_real_deaths_preserve_revocation_and_never_replay_unknown_effects(self):
        for boundary, effects, captured in (("after_claim_commit", 0, False), ("after_final_source_check", 0, False),
                                             ("after_fake_telegram_effect", 1, False), ("after_response_spool", 1, True)):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary, protected_fixture():
                folder = Path(temporary)
                ledger = open_telegram(folder / "send", now=lambda: 1790913600000)
                ledger.register_stream("stream-1", session_id="builder.fixture", native_session_id="native-1",
                                       initial_cursor=0, evidence_id="stream-evidence-1")
                body = reply(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
                with sources(folder / "authority", ledger) as (grants, authority):
                    grants.issue(CONTROLLER, body, expires_ms=1790913690000)
                    TelegramProducers(ledger, authorize_source=grants.enrollment_allowed).enqueue(body)
                ledger.close()
                killed = subprocess.run([sys.executable, str(Path(__file__).with_name("source_grant_fault_fixture.py")),
                                         str(folder), boundary], capture_output=True, text=True, timeout=10)
                self.assertEqual(killed.returncode, 74, killed.stderr)
                ledger = open_telegram(folder / "send", now=lambda: 1790913603000)
                try:
                    with sources(folder / "authority", ledger) as (grants, authority):
                        self.assertTrue(grants.grant(body["id"])["revoked"])
                        bot = FakeOutbound(folder / "provider.sqlite")
                        scheduler = TelegramScheduler(ledger, bot, asset_store(folder / "assets"),
                                                      ownership_check=lambda: None, authorize_dispatch=grants.authorize)
                        scheduler.verify()
                        intent = ledger.items(body["id"])[0]["current"]["record"].id
                        self.assertEqual(ledger.load(intent)["record"].fields["state"], "unknown")
                        self.assertFalse(scheduler.step()["submitted"])
                        self.assertEqual(bot.count(), effects)
                        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 0)
                        if captured:
                            scheduler.reconcile_spooled(intent)
                            self.assertEqual(ledger.load(intent)["record"].fields["state"], "confirmed")
                            self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 50)
                            self.assertEqual(bot.count(), effects)
                finally:
                    ledger.close()
