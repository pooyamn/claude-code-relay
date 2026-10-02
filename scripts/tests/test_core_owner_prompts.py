"""Offline receipt-bound approval UI and cross-ledger crash recovery."""
import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import ccrelay_owner_gate
from relay_core.contracts import canonical_bytes, fingerprint
from relay_core.identity import Denied
from relay_core.owner_prompts import OwnerPromptBridge, prompt_bundle
from owner_fixtures import EXPIRY, GATE, INGRESS, NOW, ROOT, WORKER, action, owner_fields, receipt, update
from owner_prompt_fixtures import joined
from telegram_fixtures import rejected


class OwnerPromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = joined(Path(self.tmp.name))
        self.gate, self.ledger, self.bridge, self.bot, self.scheduler, self.now = self.fixture.__enter__()
        self.addCleanup(lambda: self.fixture.__exit__(None, None, None))
        self.intent = action({"candidate": "sha256:" + "a" * 64, "screening": {"verdict": "flagged"},
                              "screening_exception": "owner-only choice", "unicode": "🚀\u202ereversed",
                              "text": "**not Markdown**\n```\n<not HTML>"})
        self.prompt = self.gate.enroll(ROOT, self.intent.to_dict(), "approval-1", EXPIRY)

    def deliver(self):
        ticket = self.bridge.enqueue(self.intent.id)
        self.scheduler.verify()
        for _ in range(100):
            if self.ledger.status(ticket["id"])["state"] == "confirmed":
                return ticket["id"]
            self.now[0] += 3000
            self.scheduler.step()
        raise AssertionError("fixture did not deliver all prompt chunks")

    def test_gate_read_requires_kernel_ingress_and_no_identity_headers(self):
        for peer in (ROOT, WORKER, GATE):
            with self.assertRaises(Denied):
                self.gate.read_prompt(peer, self.intent.id)
        request = {"schema": "ccrelay.owner_request.v1", "request_id": "read-1", "method": "read_prompt",
                   "args": {"action_id": self.intent.id}}
        self.assertEqual(ccrelay_owner_gate.dispatch(self.gate, INGRESS, request)["receipt"], None)
        for variant in ({**request, "uid": INGRESS.uid}, {**request, "args": {**request["args"], "peer_uid": INGRESS.uid}}):
            with self.assertRaises(Denied):
                ccrelay_owner_gate.dispatch(self.gate, INGRESS, variant)

    def test_prompt_shows_every_exact_parameter_digest_expiry_and_opaque_buttons(self):
        view = self.gate.read_prompt(INGRESS, self.intent.id)
        value = prompt_bundle(view, self.gate.policy)
        source = value["source"]["content"]
        output = "".join(op["args"]["text"] for op in value["operations"])
        self.assertEqual(output, source["text"])
        encoded = output.split("Parameters (exact JSON, including any screening verdict/exception):\n", 1)[1].split("\n\nButtons apply", 1)[0]
        self.assertEqual(json.loads(encoded), self.intent.to_dict()["parameters"])
        self.assertIn(self.intent.fields["intent_digest"], output)
        self.assertIn(EXPIRY, output)
        self.assertIn("\\u202e", output)
        self.assertNotIn("\u202e", output)
        self.assertEqual(value["lane"], "approval")
        self.assertEqual(value["thread_id"], self.gate.policy.thread_id)
        self.assertTrue(all("parse_mode" not in op["args"] for op in value["operations"]))
        buttons = value["operations"][-1]["args"]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([button["callback_data"] for button in buttons], [self.prompt["approve_data"], self.prompt["deny_data"]])
        self.assertTrue(all(len(button["callback_data"].encode()) <= 64 for button in buttons))

    def test_ticket_or_unbound_owner_prose_cannot_approve(self):
        ticket = self.bridge.enqueue(self.intent.id)
        self.assertEqual(ticket["state"], "pending")
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        with self.assertRaises(Denied):
            self.gate.decide(INGRESS, update(self.prompt["approve_data"], message_id=101))
        self.assertEqual(self.gate.load(self.intent.id)[1].fields["state"], "pending")
        self.assertEqual(self.bot.count(), 0)

    def test_complete_delivery_binds_actual_final_receipt_not_ticket_then_single_use_decision(self):
        bid = self.deliver()
        result = self.bridge.bind(self.intent.id)
        self.assertEqual(result["bundle_id"], bid)
        self.assertEqual(result["receipt"], receipt(101))
        self.assertEqual(self.gate.load(self.intent.id)[1].fields["state"], "pending")
        event = update(self.prompt["approve_data"], message_id=101)
        self.assertEqual(self.gate.decide(INGRESS, event)["state"], "granted")
        claimed = self.gate.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")
        self.assertTrue(claimed["may_execute"])
        self.assertFalse(self.gate.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")["may_execute"])
        self.assertEqual(self.gate.decide(INGRESS, event)["state"], "consumed")
        self.assertEqual(self.bridge.enqueue(self.intent.id)["state"], "confirmed")
        self.assertEqual(self.bridge.bind(self.intent.id), result)
        self.assertEqual(self.bot.count(), 1)

    def test_partial_long_prompt_cannot_bind_and_buttons_belong_only_to_final_chunk(self):
        self.intent = action({"long": "line🚀\n" * 1600}, id="large-action")
        prompt = self.gate.enroll(ROOT, self.intent.to_dict(), "large-approval", EXPIRY)
        ticket = self.bridge.enqueue(self.intent.id)
        self.assertGreater(len(self.ledger.items(ticket["id"])), 2)
        self.scheduler.verify()
        self.now[0] += 3000
        self.scheduler.step()
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        self.assertNotIn("reply_markup", self.bot.calls("sendMessage")[0][1])
        self.deliver()
        confirmed = self.bridge.bind(self.intent.id)["receipt"]["message_id"]
        self.assertGreater(confirmed, 101)
        with self.assertRaises(Denied):
            self.gate.decide(INGRESS, update(prompt["approve_data"], message_id=101))
        self.assertEqual(self.gate.decide(INGRESS, update(prompt["approve_data"], message_id=confirmed))["state"], "granted")
        self.assertTrue(all(len(args["text"].encode("utf-16-le")) // 2 <= 4096 for _, args in self.bot.calls("sendMessage")))

    def test_unknown_send_never_binds_or_resends(self):
        ticket = self.bridge.enqueue(self.intent.id)
        self.scheduler.verify()
        self.bot.lost_ack = True
        self.scheduler.step()
        self.assertEqual(self.ledger.status(ticket["id"])["state"], "unknown")
        for _ in range(3):
            self.now[0] += 3000
            self.assertFalse(self.scheduler.step()["submitted"])
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        with self.assertRaises(Denied):
            self.gate.decide(INGRESS, update(self.prompt["approve_data"], message_id=101))
        self.assertEqual(self.bot.count(), 1)

    def test_failed_prompt_keeps_exact_source_without_owner_authorization(self):
        ticket = self.bridge.enqueue(self.intent.id)
        self.bot.responses = [rejected(400)]
        self.scheduler.verify()
        self.scheduler.step()
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        self.assertEqual(self.ledger.status(ticket["id"])["state"], "failed")
        self.assertEqual(self.gate.read_prompt(INGRESS, self.intent.id)["receipt"], None)
        self.assertEqual(self.bot.count(), 0)

    def test_flood_replacement_binds_its_actual_receipt_and_employee_cannot_approve(self):
        self.bridge.enqueue(self.intent.id)
        self.bot.responses = [rejected(retry_after=1)]
        bid = self.deliver()
        self.assertEqual(self.ledger.items(bid)[0]["retry"], 1)
        result = self.bridge.bind(self.intent.id)
        self.assertEqual(result["receipt"], receipt(101))
        employee = update(self.prompt["approve_data"], message_id=101)
        employee["callback_query"]["from"]["id"] = 1009
        with self.assertRaises(Denied):
            self.gate.decide(INGRESS, employee)
        self.assertEqual(self.gate.load(self.intent.id)[1].fields["state"], "pending")
        self.assertEqual(self.bot.count(), 1)

    def test_general_topic_uses_omitted_field_and_preserves_owner_callback_binding(self):
        with tempfile.TemporaryDirectory() as temporary, joined(temporary, owner_policy={**owner_fields(), "thread_id": None}) as \
                (gate, ledger, bridge, bot, scheduler, now):
            prompt = gate.enroll(ROOT, action().to_dict(), "approval-1", EXPIRY)
            ticket = bridge.enqueue("action-1")
            scheduler.verify()
            scheduler.step()
            result = bridge.bind("action-1")
            self.assertEqual(result["receipt"]["thread_id"], None)
            self.assertNotIn("message_thread_id", bot.calls("sendMessage")[0][1])
            event = update(prompt["approve_data"], message_id=result["receipt"]["message_id"])
            event["callback_query"]["message"].pop("message_thread_id")
            self.assertEqual(gate.decide(INGRESS, event)["state"], "granted")
            self.assertEqual(ledger.status(ticket["id"])["state"], "confirmed")

    def test_changed_candidate_or_forged_view_never_rebinds_existing_action(self):
        bid = self.deliver()
        self.bridge.bind(self.intent.id)
        with self.assertRaises(Denied):
            self.gate.enroll(ROOT, action({"candidate": "changed"}).to_dict(), "approval-1", EXPIRY)
        view = self.gate.read_prompt(INGRESS, self.intent.id)
        for change in ("policy", "nonce", "owner", "other_action"):
            changed = copy.deepcopy(view)
            if change == "policy":
                changed["policy_digest"] = "sha256:" + "0" * 64
            elif change == "nonce":
                changed["prompt"]["deny_data"] = "cc1:" + "x" * 32 + ":d"
            elif change == "owner":
                changed["prompt"]["approval"]["owner_id"] = "telegram:999"
            else:
                other = action(id="other-action")
                changed["prompt"]["action"] = other.to_dict()
                changed["prompt"]["approval"].update(action_id=other.id, action_digest=other.fields["intent_digest"])
            with mock.patch.object(self.bridge.channel, "read", return_value=changed), self.assertRaises(Denied):
                self.bridge.enqueue(self.intent.id)
        self.assertEqual(self.ledger.status(bid)["state"], "confirmed")
        self.assertEqual(self.bot.count(), 1)

    def test_forged_confirmed_receipt_or_tampered_response_cannot_bind(self):
        bid = self.deliver()
        record = self.ledger.items(bid)[0]["current"]["record"]
        evidence = self.ledger._evidence(record.fields["outcome_evidence_id"])
        forged = copy.deepcopy(evidence)
        forged["payload"]["receipt"]["message_ids"] = [999]
        self.ledger.connection.execute("UPDATE evidence SET body=?,digest=? WHERE id=?",
                                       (canonical_bytes(forged), fingerprint(forged), evidence["id"]))
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        self.ledger.connection.execute("UPDATE evidence SET body=?,digest=? WHERE id=?",
                                       (canonical_bytes(evidence), fingerprint(evidence), evidence["id"]))
        binding, _ = self.ledger.read_response(record.id)
        path = self.ledger.responses / (binding["body_digest"] + ".body")
        os.chmod(path, 0o600)
        path.write_bytes(b"forged original response")
        os.chmod(path, 0o400)
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        self.assertIsNone(self.gate.read_prompt(INGRESS, self.intent.id)["receipt"])

    def test_bound_prompt_with_missing_component_history_is_held_not_recreated(self):
        self.deliver()
        self.bridge.bind(self.intent.id)
        with mock.patch.object(self.ledger, "bundle", return_value=None), self.assertRaisesRegex(Denied, "reconcile restore"):
            self.bridge.enqueue(self.intent.id)
        self.assertEqual(self.bot.count(), 1)

    def test_expired_prompt_cannot_enroll_or_bind_and_ownership_is_rechecked(self):
        self.now[0] += 3600000
        with self.assertRaises(Denied):
            self.bridge.enqueue(self.intent.id)
        self.now[0] -= 3600000
        self.deliver()
        self.gate.clock = lambda: NOW + timedelta(hours=1)
        with self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        self.gate.clock = lambda: NOW
        with mock.patch.object(self.bridge, "ownership_check", side_effect=Denied("lost send ownership")), self.assertRaises(Denied):
            self.bridge.bind(self.intent.id)
        self.assertIsNone(self.gate.read_prompt(INGRESS, self.intent.id)["receipt"])

    def test_unmatched_bot_general_topic_and_untrusted_or_unmatched_channel_denied(self):
        self.bridge.channel.policy.bot_id = 999
        with self.assertRaises(Denied):
            OwnerPromptBridge(self.bridge.producer, self.bridge.channel, ownership_check=lambda: None)
        self.bridge.channel.policy.bot_id = 1002
        self.bridge.channel.policy.thread_id = 1
        with self.assertRaises(Denied):
            OwnerPromptBridge(self.bridge.producer, self.bridge.channel, ownership_check=lambda: None)
        with self.assertRaises(Denied):
            OwnerPromptBridge(self.bridge.producer, object(), ownership_check=lambda: None)
        with mock.patch("relay_core.owner_prompts.client_request", return_value={"ok": True, "request_id": "foreign", "result": {}}), self.assertRaises(Denied):
            self.bridge.channel.read(self.intent.id)


class OwnerPromptCrashTests(unittest.TestCase):
    def test_real_deaths_bind_original_message_without_replaying_send_or_owner_decision(self):
        boundaries = ("before_bundle_commit", "after_bundle_commit", "after_fake_telegram_effect",
                      "after_response_spool", "before_prompt_bind", "after_owner_bind_before_ack", "after_prompt_bind")
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                with joined(folder) as (gate, _, _, _, _, _):
                    prompt = gate.enroll(ROOT, action().to_dict(), "approval-1", EXPIRY)
                killed = subprocess.run([sys.executable, str(Path(__file__).with_name("owner_prompt_fault_fixture.py")),
                                         str(folder), boundary], capture_output=True, text=True, timeout=15)
                self.assertEqual(killed.returncode, 73, killed.stderr)
                with joined(folder) as (gate, ledger, bridge, bot, scheduler, now):
                    now[0] += 6000
                    ledger.recover_inflight()
                    ticket = bridge.enqueue("action-1")
                    scheduler.verify()
                    if boundary == "after_response_spool":
                        intent = ledger.items(ticket["id"])[0]["current"]["record"].id
                        scheduler.reconcile_spooled(intent)
                    elif boundary in {"before_bundle_commit", "after_bundle_commit"}:
                        self.assertEqual(scheduler.step()["state"], "confirmed")
                    if boundary == "after_fake_telegram_effect":
                        self.assertEqual(ledger.status(ticket["id"])["state"], "unknown")
                        with self.assertRaises(Denied):
                            bridge.bind("action-1")
                        with self.assertRaises(Denied):
                            gate.decide(INGRESS, update(prompt["approve_data"], message_id=101))
                        self.assertIsNone(gate.read_prompt(INGRESS, "action-1")["receipt"])
                    else:
                        result = bridge.bind("action-1")
                        self.assertEqual(result["receipt"], receipt(101))
                        self.assertEqual(bridge.bind("action-1"), result)
                        self.assertEqual(gate.load("action-1")[1].fields["state"], "pending")
                        event = update(prompt["approve_data"], message_id=101)
                        self.assertEqual(gate.decide(INGRESS, event)["state"], "granted")
                        self.assertEqual(gate.decide(INGRESS, event)["state"], "granted")
                        gate.verify_audit()
                    for _ in range(3):
                        now[0] += 3000
                        self.assertFalse(scheduler.step()["submitted"])
                    self.assertEqual(bot.count(), 1)
                    self.assertEqual(len(bot.calls("sendMessage")), 1)


if __name__ == "__main__":
    unittest.main()
