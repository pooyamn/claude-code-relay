"""Offline authorized render recovery, not live error characterization."""
import copy
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied
from relay_core.telegram_outbound import OutboundPolicy
from relay_core.telegram_producers import TelegramProducers, text_plan
from relay_core.telegram_repair import plain_pieces
from relay_core.telegram_scheduler import TelegramScheduler
from telegram_fixtures import FakeOutbound, asset_store, fixture_dispatch, open_telegram, policy_fields, protected_fixture, rejected
from test_core_telegram import TelegramFixture


def authorization(current, alternative, binding, response):
    """Invented protected compatibility verdict. JSON is NOT authentication."""
    return {"schema": "ccrelay.telegram_repair_authorization.v1", "authorization_id": "fixture-render-gate-1",
            "intent_id": current["record"].id, "outcome_evidence_id": current["record"].fields["outcome_evidence_id"],
            "recipe_digest": fingerprint(alternative), "kind": alternative["kind"], "policy_digest": current["context"]["policy_digest"]}


class RepairTests(TelegramFixture):
    def setUp(self):
        super().setUp()
        self.producer = TelegramProducers(self.ledger, authorize_source=lambda _: True)

    def binding(self, name="original", *, lane="reply"):
        return {"bundle_id": name, "root_task_id": "root-1", "session_id": "builder.fixture", "chat_id": -1003,
                "thread_id": 5, "lane": lane, "source_kind": "owner_reply" if lane == "reply" else lane,
                "native_session_id": "native-1", "turn_id": "turn-1", "submission_id": "submission-1"}

    def failed(self, *, text="**bold** [link](https://invented.invalid/path)", cursor=True):
        self.producer.text(content=text, **self.binding(), **({"cursor": {"stream_id": "stream-1", "expected": 0, "new": 800}} if cursor else {}))
        self.bot.responses = [rejected(400)]
        self.send()
        return self.ledger.items("original")[0]["current"]["record"].id

    def repair(self, intent):
        self.scheduler.authorize_repair = authorization
        return self.scheduler.repair_pending(intent)

    def test_plain_repair_retains_link_url_negative_receipt_and_original_cursor(self):
        text = "**bold** [link](https://invented.invalid/path)"
        intent = self.failed(text=text)
        proposal = self.repair(intent)
        self.assertTrue(proposal["prepared"])
        child = self.ledger.bundle(proposal["replacement_bundle_id"])["body"]
        self.assertEqual(child["operations"][0]["args"]["text"], text)
        self.assertNotIn("parse_mode", child["operations"][0]["args"])
        self.assertEqual(child["source"], self.ledger.bundle("original")["body"]["source"])
        self.assertIsNone(child["cursor"])
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.tick()
        self.assertEqual(self.ledger.status("original")["state"], "confirmed")
        self.assertEqual(self.ledger.status("original")["original_operation_states"], ["failed"])
        self.assertEqual(self.ledger.load(intent)["record"].fields["state"], "failed")
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 800)
        self.assertEqual(self.bot.count(), 1)

    def test_installed_authorizer_prepares_one_alternative_without_a_hidden_send(self):
        self.scheduler.authorize_repair = authorization
        self.producer.text(content="**text**", **self.binding())
        self.bot.responses = [rejected(400)]
        self.assertEqual(self.send()["state"], "pending")
        self.assertEqual(self.bot.count(), 0)
        self.assertEqual(len(self.bot.calls("sendMessage")), 1)
        self.assertEqual(self.tick()["state"], "confirmed")
        self.assertEqual(len(self.bot.calls("sendMessage")), 2)

    def test_plain_parts_preserve_every_unicode_character_and_fit_utf16(self):
        text = "first-" + "🚀" * 8000 + "-last"
        pieces = plain_pieces(text)
        self.assertEqual("".join(pieces), text)
        self.assertTrue(all(len(piece.encode("utf-16-le")) // 2 <= 4096 for piece in pieces))
        operations, recipes = text_plan(text, -1003, 5)
        self.assertTrue(all(len(op["args"]["text"].encode("utf-16-le")) // 2 <= 4096 for op in operations))
        self.assertEqual("".join(plan["content"] for plan in recipes), text)

    def test_photo_document_alternative_keeps_original_bytes_and_full_caption(self):
        reference = self.store.stage(b"original uploaded bytes", filename="odd-photo.png", mime_type="image/png")
        caption = "caption-first\n" + "line\n" * 3000 + "caption-last"
        self.producer.media(method="sendPhoto", reference=reference, caption=caption, cursor={"stream_id": "stream-1", "expected": 0, "new": 900}, **self.binding())
        self.bot.responses = [rejected(400)]
        self.send()
        intent = self.ledger.items("original")[0]["current"]["record"].id
        proposal = self.repair(intent)
        child = self.ledger.bundle(proposal["replacement_bundle_id"])["body"]
        self.assertEqual(child["operations"][0]["method"], "sendDocument")
        self.assertEqual(child["operations"][0]["assets"]["document"], reference)
        self.assertEqual(self.store.read(reference), b"original uploaded bytes")
        self.tick()
        self.assertEqual(self.bot.calls()[-1][0], "sendDocument")
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        for _ in range(20):
            if self.ledger.status("original")["state"] == "confirmed":
                break
            self.tick()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 900)
        self.assertIn("caption-last", self.bot.calls()[-1][1]["text"])

    def test_confirmed_prefix_is_never_replayed_when_a_later_chunk_is_repaired(self):
        self.producer.text(content="first-marker\n" + "line\n" * 3000 + "last-marker", cursor={"stream_id": "stream-1", "expected": 0, "new": 900}, **self.binding())
        self.send()
        first = self.ledger.items("original")[0]["current"]["record"]
        self.bot.responses = [rejected(400)]
        self.tick()
        self.repair(self.ledger.items("original")[1]["current"]["record"].id)
        for _ in range(20):
            if self.ledger.status("original")["state"] == "confirmed":
                break
            self.tick()
        self.assertEqual(self.ledger.items("original")[0]["current"]["record"], first)
        self.assertEqual(self.bot.count(), len(self.ledger.items("original")))
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 900)
        self.assertEqual(sum("first-marker" in params.get("text", "") for _, params in self.bot.calls()), 1)

    def test_rich_repair_keeps_all_plain_chunks_and_offset_across_restart(self):
        markdown = "| A | B |\n|---|---|\n" + "\n".join("| " + str(i) + " | " + "x" * 80 + " |" for i in range(100))
        intent = self.failed(text=markdown)
        proposal = self.repair(intent)
        child = proposal["replacement_bundle_id"]
        self.assertGreater(len(self.ledger.items(child)), 2)
        self.tick()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        self.restart()
        for _ in range(10):
            if self.ledger.status("original")["state"] == "confirmed":
                break
            self.tick()
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 800)
        self.assertEqual(self.bot.count(), len(self.ledger.items(child)))
        output = "".join(params["text"] for method, params in self.bot.calls() if method == "sendMessage")
        self.assertEqual(output, markdown)

    def test_identical_repair_proposal_is_idempotent_changed_authorization_denied(self):
        intent = self.failed()
        first = self.repair(intent)
        second = self.repair(intent)
        self.assertFalse(second["prepared"])
        self.assertEqual(first["replacement_bundle_id"], second["replacement_bundle_id"])
        current = self.ledger.load(intent)
        alt = self.ledger.bundle("original")["body"]["repair_plans"][0]
        value = authorization(current, alt, None, None)
        value["authorization_id"] = "another-gate"
        with self.assertRaises(Denied):
            self.ledger.prepare_repair(intent, value)
        self.assertEqual(self.ledger.connection.execute("SELECT COUNT(*) FROM telegram_repairs").fetchone()[0], 1)

    def test_foreign_failure_recipe_policy_or_destination_cannot_authorize(self):
        intent = self.failed()
        current = self.ledger.load(intent)
        alternative = self.ledger.bundle("original")["body"]["repair_plans"][0]
        for changes in ({"intent_id": "different"}, {"outcome_evidence_id": "different"}, {"recipe_digest": "sha256:" + "0" * 64},
                        {"policy_digest": "sha256:" + "0" * 64}, {"kind": "photo_to_document"}):
            with self.assertRaises(Denied):
                self.ledger.prepare_repair(intent, {**authorization(current, alternative, None, None), **changes})
        value = copy.deepcopy(self.ledger.bundle("original")["body"])
        value["id"] = "tampered"
        value["cursor"] = None
        value["repair_plans"][0]["operations"][0]["args"]["chat_id"] = -1004
        with self.assertRaises(Denied):
            self.ledger.enqueue(value)
        self.assertEqual(self.ledger.connection.execute("SELECT COUNT(*) FROM telegram_repairs").fetchone()[0], 0)

    def test_uncharacterized_failure_or_no_authorizer_stays_failed_with_content(self):
        intent = self.failed()
        self.assertFalse(self.scheduler.repair_pending(intent)["prepared"])
        self.scheduler.authorize_repair = lambda *_: None
        self.assertFalse(self.scheduler.repair_pending(intent)["prepared"])
        self.assertEqual(self.ledger.status("original")["state"], "failed")
        self.assertEqual(self.bot.count(), 0)

    def test_unknown_ack_can_never_be_repaired_as_a_new_render(self):
        self.producer.text(content="**bold**", **self.binding())
        self.bot.lost_ack = True
        self.send()
        intent = self.ledger.items("original")[0]["current"]["record"].id
        with self.assertRaises(Denied):
            self.repair(intent)
        self.assertEqual(self.bot.count(), 1)
        self.assertEqual(self.ledger.connection.execute("SELECT COUNT(*) FROM telegram_repairs").fetchone()[0], 0)

    def test_replacement_failure_cannot_spawn_another_format_loop(self):
        intent = self.failed()
        self.scheduler.authorize_repair = authorization
        proposal = self.repair(intent)
        self.bot.responses = [rejected(400)]
        self.tick()
        child_intent = self.ledger.items(proposal["replacement_bundle_id"])[0]["current"]["record"].id
        self.assertFalse(self.scheduler.repair_pending(child_intent)["prepared"])
        self.assertEqual(self.ledger.status("original")["state"], "failed")
        self.assertEqual(len(self.bot.calls("sendMessage")), 2)

    def test_rate_retry_budget_is_shared_across_original_and_all_replacement_chunks(self):
        self.producer.text(content="**bold**", **self.binding())
        self.bot.responses = [rejected(retry_after=1), rejected(400)]
        self.send()
        self.tick()
        original = self.ledger.items("original")[0]
        self.assertEqual(original["retry"], 1)
        proposal = self.repair(original["current"]["record"].id)
        self.bot.responses = [rejected(retry_after=1), rejected(retry_after=1)]
        self.tick()
        self.tick()
        self.assertEqual(self.ledger.items(proposal["replacement_bundle_id"])[0]["retry"], 1)
        self.assertEqual(self.ledger.status("original")["state"], "failed")
        self.assertEqual(len(self.bot.calls("sendMessage")), 4)

    def test_repair_rate_budget_survives_restart_and_is_shared_between_plain_chunks(self):
        markdown = "| A | B |\n|---|---|\n" + "\n".join("| " + str(i) + " | " + "x" * 80 + " |" for i in range(100))
        proposal = self.repair(self.failed(text=markdown))
        child = proposal["replacement_bundle_id"]
        self.assertGreater(len(self.ledger.items(child)), 2)
        self.bot.responses = [rejected(retry_after=1)]
        self.tick()
        self.tick()
        self.assertEqual(self.ledger.items(child)[0]["effective_state"], "confirmed")
        self.restart()
        self.bot.responses = [rejected(retry_after=1)]
        self.tick()
        self.tick()
        self.assertEqual([item["retry"] for item in self.ledger.items(child)][:2], [1, 1])
        self.restart()
        self.bot.responses = [rejected(retry_after=1)]
        self.tick()
        self.assertEqual(self.ledger.status(child)["operation_states"][:3], ["confirmed", "confirmed", "failed"])
        self.assertEqual(self.ledger.status("original")["state"], "failed")
        self.assertEqual(self.ledger.stream("stream-1")["committed_cursor"], 0)
        calls = len(self.bot.calls("sendMessage"))
        for _ in range(3):
            self.assertFalse(self.tick()["submitted"])
        self.assertEqual(len(self.bot.calls("sendMessage")), calls)

    def test_pinned_method_ceiling_denies_repair_even_with_a_synthetic_authorizer(self):
        ledger = open_telegram(self.folder / "nonrepairable", now=lambda: self.now,
                               fields=policy_fields(repairable_methods=[]))
        try:
            producer = TelegramProducers(ledger, authorize_source=lambda _: True)
            producer.text(content="**text**", **self.binding())
            scheduler = TelegramScheduler(ledger, self.bot, self.store, ownership_check=self.guard.check,
                                          authorize_dispatch=fixture_dispatch, authorize_repair=authorization)
            self.bot.responses = [rejected(400)]
            scheduler.verify()
            self.assertEqual(scheduler.step()["state"], "failed")
            intent = ledger.items("original")[0]["current"]["record"].id
            with self.assertRaises(Denied):
                scheduler.repair_pending(intent)
            self.assertEqual(ledger.connection.execute("SELECT COUNT(*) FROM telegram_repairs").fetchone()[0], 0)
            self.assertFalse(scheduler.step()["submitted"])
            self.assertEqual(len(self.bot.calls("sendMessage")), 1)
            self.assertEqual(self.bot.count(), 0)
        finally:
            ledger.close()

    def test_old_edit_repair_runs_before_new_status_and_unknown_child_fences_newer_edit(self):
        self.producer.status_edit(content="**old**", message_id=88, coalesce_key="progress", **self.binding("old", lane="status"))
        self.bot.responses = [rejected(400)]
        self.send()
        intent = self.ledger.items("old")[0]["current"]["record"].id
        self.producer.status_edit(content="**new**", message_id=88, coalesce_key="progress", **self.binding("new", lane="status"))
        child = self.repair(intent)["replacement_bundle_id"]
        self.bot.lost_ack = True
        self.assertEqual(self.tick()["state"], "unknown")
        self.assertEqual(self.bot.calls()[-1][1]["text"], "**old**")
        self.assertEqual(self.ledger.items(child)[0]["current"]["record"].fields["state"], "unknown")
        self.bot.lost_ack = False
        self.assertFalse(self.tick()["submitted"])
        self.assertEqual(self.ledger.status("new")["operation_states"], ["stored"])

    def test_late_old_edit_repair_cannot_overwrite_a_newer_confirmed_edit(self):
        self.producer.status_edit(content="**old**", message_id=88, coalesce_key="progress", **self.binding("old", lane="status"))
        self.bot.responses = [rejected(400)]
        self.send()
        intent = self.ledger.items("old")[0]["current"]["record"].id
        self.producer.status_edit(content="**new**", message_id=88, coalesce_key="progress", **self.binding("new", lane="status"))
        self.tick()
        with self.assertRaises(Denied):
            self.repair(intent)
        self.assertEqual(self.bot.calls()[-1][1]["text"], "<b>new</b>")

    def test_schema_v1_is_preserved_and_requires_explicit_migration(self):
        self.ledger.close()
        path = self.folder / "ledger/outbox.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("UPDATE telegram_metadata SET schema='ccrelay.telegram_queue.v1'")
        before = path.read_bytes()
        with self.assertRaises(Denied):
            open_telegram(self.folder / "ledger")
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(Denied):
            OutboundPolicy(policy_fields(schema="ccrelay.telegram_outbound_policy.v1"))


class RepairCrashTests(unittest.TestCase):
    def test_actual_process_deaths_preserve_one_repair_and_never_replay_uncertain_replacement(self):
        boundaries = (
            "before_repair_commit", "after_repair_commit", "before_claim_commit", "after_claim_commit",
            "after_submit_commit", "after_fake_telegram_effect", "after_telegram_effect", "before_response_publish",
            "after_response_body", "after_response_spool", "before_cursor_commit", "before_receipt_commit",
            "after_receipt_commit", "after_outbound_commit",
        )
        recoverable_spool = {"after_response_spool", "before_cursor_commit", "before_receipt_commit"}
        complete = {"after_receipt_commit", "after_outbound_commit"}
        not_submitted = {"before_repair_commit", "after_repair_commit", "before_claim_commit"}
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary, protected_fixture():
                folder = Path(temporary)
                ledger = open_telegram(folder / "ledger")
                try:
                    ledger.register_stream("stream-1", session_id="builder.fixture", native_session_id="native-1",
                                           initial_cursor=0, evidence_id="stream-evidence-1")
                    producer = TelegramProducers(ledger, authorize_source=lambda _: True)
                    producer.text(content="**repair-source** [url](https://invented.invalid/path)",
                                  bundle_id="original", root_task_id="root-1", session_id="builder.fixture",
                                  chat_id=-1003, thread_id=5, lane="reply", source_kind="owner_reply",
                                  native_session_id="native-1", turn_id="turn-1", submission_id="submission-1",
                                  cursor={"stream_id": "stream-1", "expected": 0, "new": 800})
                    store = asset_store(folder / "assets")
                    bot = FakeOutbound(folder / "provider.sqlite")
                    bot.responses = [rejected(400)]
                    scheduler = TelegramScheduler(ledger, bot, store, ownership_check=lambda: None, authorize_dispatch=fixture_dispatch)
                    scheduler.verify()
                    self.assertEqual(scheduler.step()["state"], "failed")
                    parent = ledger.items("original")[0]["current"]["record"].id
                    original_receipt = ledger.captured_evidence(parent)
                finally:
                    ledger.close()
                killed = subprocess.run([sys.executable, str(Path(__file__).with_name("telegram_repair_fault_fixture.py")),
                                         str(folder), boundary], capture_output=True, text=True, timeout=15)
                self.assertEqual(killed.returncode, 73, killed.stderr)
                now = [1790913606000]
                ledger = open_telegram(folder / "ledger", now=lambda: now[0])
                try:
                    ledger.recover_inflight()
                    bot = FakeOutbound(folder / "provider.sqlite")
                    scheduler = TelegramScheduler(ledger, bot, store, ownership_check=lambda: None,
                                                  authorize_dispatch=fixture_dispatch, authorize_repair=authorization)
                    scheduler.verify()
                    self.assertEqual(ledger.captured_evidence(parent), original_receipt)
                    self.assertEqual(ledger.load(parent)["record"].fields["state"], "failed")
                    self.assertEqual(ledger.stream("stream-1")["tail_cursor"], 800)
                    proposal = scheduler.repair_pending(parent)
                    self.assertEqual(proposal["prepared"], boundary == "before_repair_commit")
                    child = proposal["replacement_bundle_id"]
                    self.assertEqual(ledger.connection.execute("SELECT COUNT(*) FROM telegram_repairs").fetchone()[0], 1)
                    child_intent = ledger.items(child)[0]["current"]["record"].id
                    if boundary in recoverable_spool:
                        self.assertEqual(ledger.status(child)["state"], "unknown")
                        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 0)
                        scheduler.reconcile_spooled(child_intent)
                    elif boundary in not_submitted:
                        self.assertEqual(ledger.status(child)["operation_states"], ["stored"])
                        self.assertEqual(scheduler.step()["state"], "confirmed")
                    expected_complete = boundary in recoverable_spool | complete | not_submitted
                    self.assertEqual(ledger.status("original")["state"], "confirmed" if expected_complete else "unknown")
                    self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 800 if expected_complete else 0)
                    effects = bot.count()
                    for _ in range(3):
                        now[0] += 3000
                        self.assertFalse(scheduler.step()["submitted"])
                    self.assertEqual(bot.count(), effects)
                    self.assertEqual(effects, 0 if boundary in {"after_claim_commit", "after_submit_commit"} else 1)
                    self.assertEqual(len(bot.calls("sendMessage")), 1 + effects)
                    self.assertEqual(ledger.load(parent)["record"].fields["state"], "failed")
                finally:
                    ledger.close()


if __name__ == "__main__":
    unittest.main()
