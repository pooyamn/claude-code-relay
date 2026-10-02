"""Offline scheduler conformance. Fakes do not prove WSL or real bot acceptance."""
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

from intake_fixtures import FakeGuard, process
from relay_core.contracts import fingerprint, canonical_bytes
from relay_core.identity import ContractError, Denied
from relay_core.polling import NoRedirect, PollError
from relay_core.telegram_outbound import OutboundPolicy, Response, SendOwnership, SingleAttemptBot, receipt, verify_bot
from relay_core.telegram_producers import TelegramProducers, bundle, text_operations
from relay_core.telegram_scheduler import TelegramScheduler
from telegram_fixtures import FakeOutbound, asset_store, open_telegram, policy_fields, protected_fixture, rejected, reply


class TelegramFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.protection = protected_fixture()
        self.protection.__enter__()
        self.addCleanup(lambda: self.protection.__exit__(None, None, None))
        self.now = 1790913600000
        self.ledger = open_telegram(self.folder / "ledger", now=lambda: self.now)
        self.addCleanup(lambda: self.ledger.close())
        self.store = asset_store(self.folder / "assets")
        self.bot = FakeOutbound(self.folder / "provider.sqlite")
        self.guard = FakeGuard()
        self.scheduler = self.new_scheduler()
        self.ledger.register_stream("stream-1", session_id="builder.fixture", native_session_id="native-1", initial_cursor=0, evidence_id="stream-evidence-1")

    def new_scheduler(self):
        return TelegramScheduler(self.ledger, self.bot, self.store, ownership_check=self.guard.check)

    def enqueue(self, **kwargs):
        return self.ledger.enqueue(reply(**kwargs))

    def restart(self):
        self.ledger.close()
        self.ledger = open_telegram(self.folder / "ledger", now=lambda: self.now)
        self.scheduler = self.new_scheduler()
        self.scheduler.verify()

    def send(self):
        self.scheduler.verify()
        return self.scheduler.step()

    def tick(self, ms=3000):
        self.now += ms
        return self.scheduler.step()


class TelegramTests(TelegramFixture):
    def test_verification_and_current_send_ownership_required_before_any_send(self):
        self.enqueue()
        with self.assertRaises(Denied):
            self.scheduler.step()
        self.bot.username = "WrongBot"
        with self.assertRaises(Denied):
            self.scheduler.verify()
        self.bot.username = "SyntheticKhadang"
        self.scheduler.verify()
        self.guard.valid = False
        with self.assertRaises(Denied):
            self.scheduler.step()
        self.assertEqual(self.bot.count(), 0)

    def test_single_reply_receipt_and_cursor_are_confirmed_in_one_transaction(self):
        self.enqueue(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.assertEqual(self.send()["state"], "confirmed")
        status = self.ledger.status("reply-1")
        self.assertEqual(status["message_ids"], [[101]])
        self.assertTrue(status["cursor_committed"])
        self.assertEqual(status["source"]["turn_id"], "turn-1")
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 50)

    def test_partial_chunks_never_advance_cursor_or_duplicate_confirmed_chunks(self):
        self.enqueue(count=3, cursor={"stream_id": "stream-1", "expected": 0, "new": 500})
        self.send()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertFalse(self.scheduler.step()["submitted"])
        self.restart()
        self.tick()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.tick()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 500)
        self.assertEqual(self.bot.count(), 3)
        self.assertEqual(self.ledger.status("reply-1")["message_ids"], [[101], [102], [103]])

    def test_duplicate_bundle_retains_complete_ticket_changed_content_or_turn_denied(self):
        value = reply()
        self.ledger.enqueue(value)
        self.send()
        self.assertEqual(self.ledger.enqueue(value)["state"], "confirmed")
        for change in ("content", "turn_id", "submission_id"):
            changed = copy.deepcopy(value)
            changed["source"][change] = "changed"
            changed["source"]["content_digest"] = fingerprint(changed["source"]["content"])
            with self.assertRaises(Denied):
                self.ledger.enqueue(changed)
        self.assertFalse(self.tick()["submitted"])
        self.assertEqual(self.bot.count(), 1)

    def test_stream_initial_identity_never_resets_and_replies_are_ordered(self):
        self.enqueue(cursor={"stream_id": "stream-1", "expected": 0, "new": 50}, count=2)
        self.enqueue(bundle_id="reply-2", cursor={"stream_id": "stream-1", "expected": 50, "new": 70})
        with self.assertRaises(Denied):
            self.enqueue(bundle_id="overlap", cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        with self.assertRaises(Denied):
            self.ledger.register_stream("stream-1", session_id="builder.fixture", native_session_id="new", initial_cursor=0, evidence_id="stream-evidence-1")
        self.send()
        self.assertEqual(self.ledger.status("reply-2")["operation_states"], ["stored"])
        self.tick()
        self.tick()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 70)

    def test_definite_429_creates_linked_replacement_and_persists_cooldown(self):
        self.enqueue()
        original = self.ledger.items("reply-1")[0]["current"]["record"].id
        self.bot.responses = [rejected()]
        self.assertEqual(self.send()["state"], "pending")
        current = self.ledger.items("reply-1")[0]
        self.assertEqual(current["retry"], 1)
        self.assertEqual(current["current"]["context"]["previous_intent_id"], original)
        self.assertEqual(self.ledger.load(original)["record"].fields["state"], "failed")
        self.assertEqual(current["current"]["context"]["negative_evidence_id"], self.ledger.load(original)["record"].fields["outcome_evidence_id"])
        self.restart()
        for _ in range(10):
            self.assertFalse(self.scheduler.step()["submitted"])
        self.assertEqual(len(self.bot.calls("sendMessage")), 1)
        self.tick(29999)
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(self.tick(1)["state"], "confirmed")
        self.assertEqual(self.bot.count(), 1)

    def test_provider_wait_is_not_shortened_and_rate_limit_retry_count_is_finite(self):
        self.enqueue()
        self.bot.responses = [rejected(retry_after=100000), rejected(), rejected()]
        self.send()
        self.assertFalse(self.tick(86400000)["submitted"])
        self.tick(13600000)
        self.tick(30000)
        self.assertEqual(self.ledger.status("reply-1")["state"], "failed")
        self.restart()
        self.assertFalse(self.tick(100000000)["submitted"])
        self.assertEqual(len(self.bot.calls("sendMessage")), 3)
        self.assertEqual(self.bot.count(), 0)

    def test_callback_priority_survives_edit_cooldown_without_whole_bot_sleep(self):
        edit = {"method": "editMessageText", "args": {"chat_id": -1003, "message_id": 88, "text": "status"}, "assets": {}}
        self.enqueue(bundle_id="status-1", lane="status", operations=[edit])
        self.bot.responses = [rejected()]
        self.send()
        self.enqueue(bundle_id="callback-1", lane="callback", operations=[{"method": "answerCallbackQuery", "args": {"callback_query_id": "query-1"}, "assets": {}}])
        self.assertEqual(self.tick(40)["state"], "confirmed")
        self.assertEqual(self.bot.calls()[-1][0], "answerCallbackQuery")
        self.assertEqual(self.ledger.status("status-1")["state"], "pending")

    def test_lane_priority_global_spacing_and_group_chat_spacing_are_durable(self):
        self.enqueue(bundle_id="bus-1", lane="bus", chat_id=-1004)
        self.enqueue(bundle_id="alert-1", lane="alert", chat_id=-1003)
        self.assertEqual(self.send()["bundle_id"], "alert-1")
        self.assertFalse(self.scheduler.step()["submitted"])
        self.assertEqual(self.tick(40)["bundle_id"], "bus-1")
        self.enqueue(bundle_id="reply-1", chat_id=-1003)
        self.restart()
        self.assertFalse(self.scheduler.step()["submitted"])
        self.assertEqual(self.tick(2960)["bundle_id"], "reply-1")

    def test_only_unattempted_disposable_status_edits_can_coalesce(self):
        def status(name):
            return reply(name, lane="status", coalesce_key="progress", operations=[{"method": "editMessageText",
                         "args": {"chat_id": -1003, "message_id": 99, "text": name}, "assets": {}}])
        self.ledger.enqueue(status("old-status"))
        self.ledger.enqueue(status("new-status"))
        self.assertEqual(self.ledger.status("old-status")["state"], "superseded")
        self.assertEqual(self.send()["bundle_id"], "new-status")
        self.ledger.enqueue(status("next-status"))
        self.assertEqual(self.ledger.status("new-status")["state"], "confirmed")
        with self.assertRaises(Denied):
            self.enqueue(bundle_id="reply-coalesce", coalesce_key="progress")
        with self.assertRaises(Denied):
            self.enqueue(bundle_id="status-send-coalesce", lane="status", coalesce_key="progress")

    def test_lost_ack_keeps_unknown_without_resending_or_advancing_cursor(self):
        self.enqueue(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.bot.lost_ack = True
        self.assertEqual(self.send()["state"], "unknown")
        self.restart()
        self.assertFalse(self.tick(99999)["submitted"])
        self.assertEqual(self.bot.count(), 1)
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        with self.assertRaises((Denied, FileNotFoundError)):
            self.scheduler.reconcile_spooled(intent)

    def test_unknown_edit_blocks_later_edit_of_same_message_not_other_work(self):
        def edit(name, mid):
            return reply(name, lane="status", operations=[{"method": "editMessageText", "args": {"chat_id": -1003, "message_id": mid, "text": name}, "assets": {}}])
        self.ledger.enqueue(edit("old", 77))
        self.bot.lost_ack = True
        self.send()
        self.bot.lost_ack = False
        self.ledger.enqueue(edit("new", 77))
        self.ledger.enqueue(edit("other", 78))
        self.assertEqual(self.tick()["bundle_id"], "other")
        self.assertEqual(self.ledger.status("new")["operation_states"], ["stored"])

    def test_mismatched_chat_bot_topic_and_5xx_are_unknown_not_retryable(self):
        for name, response in (("chat", Response(200, canonical_bytes({"ok": True, "result": {"message_id": 1, "chat": {"id": -999}, "from": {"id": 1002, "is_bot": True}}}))),
                               ("5xx", Response(503, canonical_bytes({"ok": False, "error_code": 503})))):
            self.enqueue(bundle_id=name)
            self.bot.responses = [response]
            self.scheduler.verify()
            result = self.scheduler.step() if name == "chat" else self.tick()
            self.assertEqual(result["state"], "unknown")
            self.assertEqual(self.ledger.items(name)[0]["retry"], 0)

    def test_unverified_429_or_migration_never_creates_replacement(self):
        for name, body in (("no-hint", {"ok": False, "error_code": 429}),
                           ("migration", {"ok": False, "error_code": 400, "parameters": {"migrate_to_chat_id": -999}})):
            self.enqueue(bundle_id=name)
            self.bot.responses = [Response(429 if name == "no-hint" else 400, canonical_bytes(body))]
            self.scheduler.verify()
            self.scheduler.step() if name == "no-hint" else self.tick()
            self.assertEqual(self.ledger.status(name)["state"], "unknown")
            self.assertEqual(self.ledger.items(name)[0]["retry"], 0)

    def test_definite_non_rate_limit_rejections_stay_failed_no_automatic_retry(self):
        self.enqueue()
        self.bot.responses = [rejected(400)]
        self.assertEqual(self.send()["state"], "failed")
        self.assertFalse(self.tick()["submitted"])
        self.assertEqual(len(self.bot.calls("sendMessage")), 1)

    def test_receipt_hook_failure_rolls_back_receipt_and_cursor_then_spool_reconciles(self):
        self.enqueue(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        with mock.patch.object(self.ledger, "_advance_cursor", side_effect=OSError("invented disk failure")):
            self.assertEqual(self.send()["state"], "unknown")
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.scheduler.reconcile_spooled(intent)
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 50)
        self.assertEqual(self.bot.count(), 1)

    def test_decoded_forged_evidence_cannot_override_captured_response(self):
        self.enqueue()
        with mock.patch.object(self.ledger, "finish", side_effect=OSError("invented receipt storage failure")):
            self.assertEqual(self.send()["state"], "unknown")
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        evidence = self.ledger.captured_evidence(intent)
        altered = copy.deepcopy(evidence)
        altered["payload"]["receipt"]["message_ids"] = [9999]
        with self.assertRaises(Denied):
            self.ledger.reconcile(altered, commit_hook=self.ledger.finish)
        self.assertEqual(self.ledger.load(intent)["record"].fields["state"], "unknown")
        self.assertEqual(self.ledger.connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 0)
        self.scheduler.reconcile_spooled(intent)

    def test_claim_hook_failure_rolls_back_pacing_and_permission_before_effect(self):
        self.enqueue()
        self.scheduler.verify()
        with mock.patch.object(self.ledger, "reserve", side_effect=Denied("invented admission failure")):
            with self.assertRaises(Denied):
                self.scheduler.step()
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(self.ledger.items("reply-1")[0]["current"]["record"].fields["state"], "stored")
        self.assertEqual(self.ledger.connection.execute("SELECT global_after_ms FROM telegram_metadata").fetchone()[0], 0)

    def test_saved_response_cannot_be_rebound_to_another_attempt_or_forged_evidence(self):
        self.enqueue()
        self.send()
        first = self.ledger.items("reply-1")[0]["current"]["record"].id
        self.enqueue(bundle_id="second")
        self.bot.lost_ack = True
        self.tick()
        second = self.ledger.items("second")[0]["current"]["record"].id
        path = self.ledger.responses / (second + ".receipt")
        path.write_bytes((self.ledger.responses / (first + ".receipt")).read_bytes())
        path.chmod(0o400)
        with self.assertRaises(Denied):
            self.scheduler.reconcile_spooled(second)
        self.assertEqual(self.ledger.status("second")["state"], "unknown")

    def test_original_response_tampering_is_detected_and_preserved(self):
        self.enqueue()
        self.send()
        intent = self.ledger.items("reply-1")[0]["current"]["record"].id
        binding, _ = self.ledger.read_response(intent)
        path = self.ledger.responses / (binding["body_digest"] + ".body")
        path.chmod(0o600)
        path.write_bytes(b"changed")
        path.chmod(0o400)
        with self.assertRaises(Denied):
            self.ledger.read_response(intent)
        self.assertEqual(path.read_bytes(), b"changed")

    def test_schema_policy_index_and_clock_drift_fail_closed_without_reset(self):
        self.enqueue()
        self.now -= 1
        with self.assertRaises(Denied):
            self.scheduler.verify()
            self.scheduler.step()
        self.now += 1
        self.ledger.connection.execute("UPDATE telegram_bundles SET priority=99")
        with self.assertRaises(Denied):
            self.ledger.status("reply-1")
        self.ledger.connection.execute("UPDATE telegram_bundles SET priority=10")
        self.ledger.close()
        with self.assertRaises(Denied):
            open_telegram(self.folder / "ledger", fields=policy_fields(global_spacing_ms=100))
        with sqlite3.connect(self.folder / "ledger/outbox.sqlite") as db:
            db.execute("UPDATE telegram_metadata SET schema='future' ")
        with self.assertRaises(Denied):
            open_telegram(self.folder / "ledger")
        with sqlite3.connect(self.folder / "ledger/outbox.sqlite") as db:
            self.assertEqual(db.execute("SELECT schema FROM telegram_metadata").fetchone()[0], "future")


class ProducerTests(TelegramFixture):
    def binding(self, bundle_id="produced-1", lane="reply"):
        return {"bundle_id": bundle_id, "root_task_id": "root-1", "session_id": "builder.fixture", "chat_id": -1003,
                "thread_id": 5, "lane": lane, "source_kind": "owner_reply" if lane == "reply" else lane,
                "native_session_id": "native-1", "turn_id": "turn-1", "submission_id": "submission-1"}

    def test_common_source_authorization_gate_denies_without_enrolling(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: False)
        with self.assertRaises(Denied):
            producer.text(content="invented", **self.binding())
        self.assertIsNone(self.ledger.bundle("produced-1"))
        self.assertEqual(self.bot.count(), 0)

    def test_reply_ticket_retains_full_source_and_never_supplies_placeholder_receipt(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        original = "first\n" + "line\n" * 2000 + "last"
        ticket = producer.text(content=original, cursor={"stream_id": "stream-1", "expected": 0, "new": 800}, **self.binding())
        self.assertEqual(ticket["source"]["content"], original)
        self.assertEqual(ticket["state"], "pending")
        self.assertTrue(all(mid is None for mid in ticket["message_ids"]))
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(self.bot.count(), 0)

    def test_document_photo_voice_audio_and_complete_caption_use_sealed_assets(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        for method, mime, filename in (("sendDocument", "application/pdf", "test.pdf"), ("sendPhoto", "image/png", "test.png"),
                                       ("sendVoice", "audio/ogg", "test.ogg"), ("sendAudio", "audio/mpeg", "test.mp3")):
            ref = self.store.stage(b"invented immutable media", filename=filename, mime_type=mime)
            text = "caption-first\n" + "caption line\n" * 500 + "caption-last"
            ticket = producer.media(method=method, reference=ref, caption=text, **self.binding(method))
            self.assertEqual(ticket["source"]["content"]["caption"], text)
            items = self.ledger.items(method)
            self.assertEqual(items[0]["operation"]["method"], method)
            self.assertGreater(len(items), 2)
            self.assertIn("caption-last", items[-1]["operation"]["args"]["text"])
        self.send()
        self.assertEqual(self.bot.count(), 1)

    def test_status_tail_is_disposable_but_original_is_retained_and_final_is_not_trimmed(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        original = "status-header\n```\n" + "old line\n" * 1000 + "latest-line\n```"
        ticket = producer.status_edit(content=original, message_id=80, coalesce_key="progress", **self.binding("status-1", "status"))
        self.assertEqual(ticket["source"]["content"], original)
        operation = self.ledger.items("status-1")[0]["operation"]
        self.assertIn("latest-line", operation["args"]["text"])
        self.assertLessEqual(len(operation["args"]["text"]), 4096)
        with self.assertRaises(Denied):
            producer.status_edit(content=original, message_id=80, coalesce_key="progress", **self.binding("final", "reply"))

    def test_approval_alert_bus_callback_and_native_app_all_use_bundle_tickets(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        for lane in ("approval", "alert", "bus"):
            self.assertEqual(producer.text(content="invented " + lane, **self.binding(lane, lane))["state"], "pending")
        native = self.binding("native")
        native["source_kind"] = "native_app"
        self.assertEqual(producer.text(content="mirrored native reply", **native)["source"]["source_kind"], "native_app")
        callback = bundle(content="ack", operations=[{"method": "answerCallbackQuery", "args": {"callback_query_id": "query-1"}, "assets": {}}], **self.binding("callback", "callback"))
        self.assertEqual(producer.enqueue(callback)["state"], "pending")
        self.assertEqual(self.bot.count(), 0)

    def test_media_group_receipt_count_preserves_each_attachment_and_id(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        refs = [self.store.stage(b"file" + bytes([i]), filename="sample" + str(i) + ".png", mime_type="image/png") for i in range(2)]
        operation = {"method": "sendMediaGroup", "args": {"chat_id": -1003, "message_thread_id": 5,
                     "media": [{"type": "photo", "media": "attach://file0"}, {"type": "photo", "media": "attach://file1"}]},
                     "assets": {"file0": refs[0], "file1": refs[1]}}
        producer.enqueue(bundle(content=refs, operations=[operation], **self.binding("album")))
        self.assertEqual(self.send()["state"], "confirmed")
        self.assertEqual(self.ledger.status("album")["message_ids"], [[101, 102]])

    def test_changed_asset_cannot_be_claimed_or_sent(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        reference = self.store.stage(b"small", filename="sample.png", mime_type="image/png")
        producer.media(method="sendPhoto", reference=reference, **self.binding())
        path = self.store.folder / (reference["digest"][7:] + ".blob")
        path.chmod(0o600)
        with self.assertRaises(Denied):
            self.send()
        self.assertEqual(self.ledger.items("produced-1")[0]["current"]["record"].fields["state"], "stored")
        self.assertEqual(self.bot.count(), 0)

    def test_owner_loss_during_upload_validation_prevents_provider_effect(self):
        producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)
        reference = self.store.stage(b"small", filename="sample.png", mime_type="image/png")
        producer.media(method="sendPhoto", reference=reference, **self.binding())
        self.scheduler.verify()
        original_read = self.store.read
        def read(ref):
            value = original_read(ref)
            self.guard.valid = False
            return value
        with mock.patch.object(self.store, "read", side_effect=read):
            self.assertEqual(self.scheduler.step()["state"], "unknown")
        self.assertEqual(self.bot.count(), 0)

    def test_large_bundle_uses_strict_parser_and_retains_original_source(self):
        value = reply(count=25)
        value["source"]["content"] = "x" * 80000
        value["source"]["content_digest"] = fingerprint(value["source"]["content"])
        self.ledger.enqueue(value)
        self.assertEqual(self.ledger.bundle("reply-1")["body"]["source"]["content"], "x" * 80000)
        encoded = canonical_bytes(value)
        self.ledger.connection.execute("UPDATE telegram_bundles SET body=?", (encoded[:-1] + b',"schema":"ccrelay.telegram_bundle.v1"}',))
        with self.assertRaises(Denied):
            self.ledger.bundle("reply-1")

    def test_uncharacterized_method_does_not_auto_retry_even_with_429(self):
        reference = self.store.stage(b"small", filename="sample.png", mime_type="image/png")
        TelegramProducers(self.ledger, authorize_source=lambda _: True).media(method="sendPhoto", reference=reference, **self.binding())
        self.bot.responses = [rejected()]
        self.assertEqual(self.send()["state"], "failed")
        self.assertEqual(self.ledger.items("produced-1")[0]["retry"], 0)


class FormattingTests(unittest.TestCase):
    def test_a_fenced_single_long_line_terminates_and_every_chunk_fits(self):
        probe = "import json,relay_tg; p=relay_tg._split_for_html('```py\\n'+'x'*12000+'\\n```'); print(json.dumps({'count':len(p),'max':max(len(relay_tg.md_to_html(s)) for s in p),'characters':sum(s.count('x') for s in p)}))"
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        output = json.loads(result.stdout)
        self.assertGreater(output["count"], 2)
        self.assertLessEqual(output["max"], 4096)
        self.assertEqual(output["characters"], 12000)

    def test_rich_tables_and_classic_code_are_ordered_without_live_calls(self):
        operations = text_operations("Before\n\n| A | B |\n|---|---|\n| left | right |\n\n```py\nprint('hello')\n```\nAfter", -1003, 5)
        self.assertEqual([op["method"] for op in operations], ["sendRichMessage", "sendMessage", "sendMessage"])
        self.assertIn("<table", operations[0]["args"]["rich_message"]["html"])
        self.assertIn("print", operations[1]["args"]["text"])
        self.assertIn("After", operations[2]["args"]["text"])
        self.assertTrue(all(op["args"]["message_thread_id"] == 5 for op in operations))

    def test_long_required_text_and_general_topic_have_all_chunks_not_a_tail(self):
        text = "first-marker\n" + "Invented line\n" * 1000 + "last-marker"
        operations = text_operations(text, -1003, 1)
        self.assertGreater(len(operations), 2)
        self.assertIn("first-marker", operations[0]["args"]["text"])
        self.assertIn("last-marker", operations[-1]["args"]["text"])
        self.assertTrue(all("message_thread_id" not in op["args"] for op in operations))


class OutboundProtectionTests(unittest.TestCase):
    def test_policy_denies_empty_chats_paid_sends_paths_unknown_fields_and_asset_mismatch(self):
        for changes in ({"allowed_chats": []}, {"test_bot": "hamal"}, {"max_rate_limit_retries": 51}, {"bot_id": True}):
            with self.assertRaises(Denied):
                OutboundPolicy(policy_fields(**changes))
        policy = OutboundPolicy(policy_fields())
        mutable_copy = policy.raw
        mutable_copy["allowed_chats"].append(-999)
        self.assertNotIn(-999, policy.raw["allowed_chats"])
        for args in ({"chat_id": -1003, "text": "hello", "allow_paid_broadcast": True},
                     {"chat_id": -1003, "text": "hello", "business_connection_id": "id"},
                     {"chat_id": -1003, "text": "hello", "invented_new_field": 1}):
            with self.assertRaises(Denied):
                policy.operation({"method": "sendMessage", "args": args, "assets": {}}, -1003)
        for field in ("https://invalid.example/image", "/invented/private/file", "attach://missing"):
            with self.assertRaises(Denied):
                policy.operation({"method": "sendPhoto", "args": {"chat_id": -1003, "photo": field}, "assets": {}}, -1003)

    def test_asset_is_sealed_content_addressed_and_rejects_link_corruption_or_bad_headers(self):
        with tempfile.TemporaryDirectory() as directory, protected_fixture():
            store = asset_store(directory)
            ref = store.stage(b"invented", filename="sample.png", mime_type="image/png")
            self.assertEqual(store.read(ref), b"invented")
            path = Path(directory) / (ref["digest"][7:] + ".blob")
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            path.chmod(0o600)
            with self.assertRaises(Denied):
                store.read(ref)
            path.write_bytes(b"corrupt!")
            path.chmod(0o400)
            with self.assertRaises(Denied):
                store.read(ref)
            for filename in ("../private", "header\r\ninjection", 'quote".png'):
                with self.assertRaises(Denied):
                    store.stage(b"small", filename=filename, mime_type="image/png")

    def test_getme_shapes_and_receipt_topic_bot_message_ids_are_strict(self):
        policy = OutboundPolicy(policy_fields())
        for body in ([], {"ok": True, "result": {"id": True}}, {"ok": True, "result": {"id": 1002, "is_bot": True, "username": "Wrong"}}):
            with self.assertRaises(Denied):
                verify_bot(Response(200, canonical_bytes(body)), policy)
        operation = reply()["operations"][0]
        message = {"message_id": 10, "chat": {"id": -1003}, "from": {"id": 1002, "is_bot": True}, "message_thread_id": 5}
        self.assertEqual(receipt(Response(200, canonical_bytes({"ok": True, "result": message})), operation, policy, -1003)["message_ids"], [10])
        for changed in ({**message, "message_thread_id": 8}, {**message, "from": {"id": 1009, "is_bot": True}}, {**message, "message_id": True}):
            with self.assertRaises(Denied):
                receipt(Response(200, canonical_bytes({"ok": True, "result": changed})), operation, policy, -1003)

    def test_transport_one_call_no_retry_or_redirect_and_secret_is_not_error_text(self):
        token = "1002:INVENTED_NEVER_A_REAL_TOKEN"
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.URLError("https://api.telegram.org/bot" + token)
        bot = SingleAttemptBot(token, opener=opener)
        with self.assertRaises(Denied) as caught:
            bot.request("sendMessage", {"chat_id": -1003, "text": "hello"}, {}, None)
        self.assertNotIn(token, str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)
        with self.assertRaises(PollError):
            NoRedirect().redirect_request(None, None, None, None, None, "https://invalid.example")
        opener.open.side_effect = urllib.error.HTTPError("https://secret.invalid", 429, "invented", {}, io.BytesIO(rejected().body))
        self.assertEqual(bot.request("sendMessage", {"chat_id": -1003, "text": "hello"}, {}, None).status, 429)
        self.assertEqual(opener.open.call_count, 2)
        with self.assertRaises(Denied):
            bot.request("setWebhook", {}, {}, None)
        with self.assertRaises(Denied):
            bot.request("sendMessage", {"allow_paid_broadcast": True}, {}, None)

    def test_multipart_transport_preserves_immutable_voice_and_requests_once(self):
        with tempfile.TemporaryDirectory() as directory, protected_fixture():
            store = asset_store(directory)
            ref = store.stage(b"invented voice bytes", filename="sample.ogg", mime_type="audio/ogg")
            opener = mock.MagicMock()
            response = opener.open.return_value.__enter__.return_value
            response.status, response.read.return_value = 200, b'{"ok":true,"result":true}'
            bot = SingleAttemptBot("1002:INVENTED_TOKEN", opener=opener)
            self.assertEqual(bot.request("sendVoice", {"chat_id": -1003, "voice": "attach://voice"}, {"voice": ref}, store).status, 200)
            request = opener.open.call_args[0][0]
            self.assertIn(b'invented voice bytes', request.data)
            self.assertIn(b'filename="sample.ogg"', request.data)
            self.assertIn(b'Content-Type: audio/ogg', request.data)
            self.assertIn("multipart/form-data", request.get_header("Content-type"))
            self.assertEqual(opener.open.call_count, 1)

    def test_prepare_cli_is_read_only_and_has_no_run_or_token_interface(self):
        source = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-I", str(source / "ccrelay_outbound.py"), "--plan"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan["enabled"])
        self.assertFalse(plan["network_calls"])
        self.assertFalse(plan["state_changes"])
        self.assertEqual(plan["send_owner_registry"], "/var/lib/ccrelay-sendowners")
        for args in (["--run"], ["--token", "1002:INVENTED"]):
            result = subprocess.run([sys.executable, "-I", str(source / "ccrelay_outbound.py"), *args],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)

    def test_actual_send_lock_is_hostwide_per_bot_not_per_outbox_directory(self):
        with tempfile.TemporaryDirectory() as directory, protected_fixture(), \
                mock.patch("relay_core.polling.protected_path", side_effect=lambda path, **_: Path(path)):
            with SendOwnership(directory, bot_id=1002, owner_uid=os.geteuid(), observer=process) as owner:
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("telegram_fault_fixture.py")), directory, "lock_probe"],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 42, result.stderr)
                owner.check()
            self.assertTrue((Path(directory) / "1002.lock").exists())


class TelegramCrashTests(unittest.TestCase):
    def test_actual_process_deaths_preserve_bundle_offset_attempt_and_captured_receipts(self):
        boundaries = {"before_bundle_commit": (0, "absent"), "after_bundle_commit": (0, "stored"),
                      "before_claim_commit": (0, "stored"), "after_claim_commit": (0, "unknown"),
                      "after_submit_commit": (0, "unknown"), "after_fake_telegram_effect": (1, "unknown"),
                      "after_telegram_effect": (1, "unknown"), "before_response_publish": (1, "unknown"),
                      "after_response_body": (1, "unknown"), "after_response_spool": (1, "unknown"),
                      "before_cursor_commit": (1, "unknown"), "before_receipt_commit": (1, "unknown"),
                      "after_receipt_commit": (1, "confirmed"), "after_outbound_commit": (1, "confirmed")}
        for boundary, (effects, state) in boundaries.items():
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory, protected_fixture():
                folder = Path(directory)
                ledger = open_telegram(folder / "ledger")
                ledger.register_stream("stream-1", session_id="builder.fixture", native_session_id="native-1", initial_cursor=0, evidence_id="stream-evidence-1")
                if boundary not in {"before_bundle_commit", "after_bundle_commit"}:
                    ledger.enqueue(reply(cursor={"stream_id": "stream-1", "expected": 0, "new": 50}))
                ledger.close()
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("telegram_fault_fixture.py")), directory, boundary],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 73, result.stderr)
                ledger = open_telegram(folder / "ledger")
                bot = FakeOutbound(folder / "provider.sqlite")
                try:
                    self.assertEqual(bot.count(), effects)
                    current = ledger.bundle("reply-1")
                    if state == "absent":
                        self.assertIsNone(current)
                        self.assertEqual(ledger.stream("stream-1")["tail_cursor"], 0)
                        continue
                    intent = ledger.items("reply-1")[0]["current"]["record"].id
                    self.assertEqual(ledger.load(intent)["record"].fields["state"], state)
                    self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 50 if state == "confirmed" else 0)
                    scheduler = TelegramScheduler(ledger, bot, asset_store(folder / "assets"), ownership_check=lambda: None)
                    scheduler.verify()
                    if state == "unknown":
                        self.assertFalse(scheduler.step()["submitted"])
                        if boundary in {"after_response_spool", "before_cursor_commit", "before_receipt_commit"}:
                            scheduler.reconcile_spooled(intent)
                            self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 50)
                            self.assertEqual(bot.count(), effects)
                    elif state == "confirmed":
                        self.assertFalse(scheduler.step()["submitted"])
                        self.assertEqual(bot.count(), effects)
                finally:
                    ledger.close()


if __name__ == "__main__":
    unittest.main()
