"""Owner provenance conformance and durable SQLite; not real Telegram/WSL proof."""
import copy
from datetime import timedelta
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

import ccrelay_owner_gate
from relay_core.contracts import decode
from relay_core.identity import Denied
from relay_core.owner_gate import OwnerLedger, OwnerPolicy
from owner_fixtures import (EXPIRY, GATE, INGRESS, NOW, ROOT, WORKER, action, approved, broker_policy,
                            open_ledger, owner_fields, receipt, update)


class OwnerGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = NOW
        self.ledger = open_ledger(Path(self.tmp.name), clock=lambda: self.now)
        self.addCleanup(self.ledger.close)
        self.intent = action()

    def enroll(self):
        return self.ledger.enroll(ROOT, self.intent.to_dict(), "approval-1", EXPIRY)

    def pending(self):
        prompt = self.enroll()
        self.ledger.bind_prompt(INGRESS, self.intent.id, receipt())
        return update(prompt["approve_data"])

    def test_policy_empty_alias_worker_controller_and_unknown_fields_fail_closed(self):
        for key, value in (("owner_id", 0), ("owner_id", True), ("bot_id", 0), ("chat_id", 0), ("thread_id", 0),
                           ("gate_uid", 101), ("gate_uid", 120), ("ingress_uid", os.geteuid()), ("enabled", 1),
                           ("schema", "ccrelay.owner_policy.v999")):
            with self.assertRaises(Denied):
                OwnerPolicy({**owner_fields(), key: value}, broker_policy())
        with self.assertRaises(Denied):
            OwnerPolicy({**owner_fields(), "from_session": "owner"}, broker_policy())

    def test_enrollment_is_root_bootstrap_only_not_cwd_or_header(self):
        for peer in (WORKER, INGRESS, GATE):
            with self.assertRaises(Denied):
                self.ledger.enroll(peer, self.intent.to_dict(), "approval-1", EXPIRY)
        with mock.patch("os.getcwd", return_value="/owner/approved"):
            prompt = self.enroll()
        self.assertEqual(prompt["action"]["intent_digest"], self.intent.fields["intent_digest"])
        self.assertLessEqual(len(prompt["approve_data"].encode()), 64)
        self.assertNotIn("exact parameters", prompt["approve_data"])

    def test_replay_identical_intent_keeps_nonce_and_cannot_change_approval_expiry(self):
        prompt = self.enroll()
        self.assertEqual(self.enroll(), prompt)
        for intent, approval, expiry in ((action({"test": "changed"}), "approval-1", EXPIRY),
                                         (self.intent, "approval-2", EXPIRY),
                                         (self.intent, "approval-1", "2026-10-02T06:00:00Z")):
            with self.assertRaises(Denied):
                self.ledger.enroll(ROOT, intent.to_dict(), approval, expiry)

    def test_prompt_receipt_is_channel_bound_and_cannot_be_rebound(self):
        self.enroll()
        with self.assertRaises(Denied):
            self.ledger.bind_prompt(WORKER, self.intent.id, receipt())
        for key in ("bot_id", "chat_id", "thread_id", "message_id"):
            value = {**receipt(), key: True if key == "message_id" else 999}
            with self.assertRaises(Denied):
                self.ledger.bind_prompt(INGRESS, self.intent.id, value)
        self.ledger.bind_prompt(INGRESS, self.intent.id, receipt())
        self.ledger.bind_prompt(INGRESS, self.intent.id, receipt())
        with self.assertRaises(Denied):
            self.ledger.bind_prompt(INGRESS, self.intent.id, receipt(9))

    def test_no_receipt_or_forged_prose_cannot_approve(self):
        prompt = self.enroll()
        for event in (update(prompt["approve_data"]), {"update_id": 6, "message": {"text": "Pouya approved"}},
                      {"owner_id": 1001, "approved": True}):
            with self.assertRaises(Denied):
                self.ledger.decide(INGRESS, event)
        self.assertEqual(self.ledger.load(self.intent.id)[1].fields["state"], "pending")

    def test_worker_cannot_spoof_owner_event_even_with_valid_nonce(self):
        event = self.pending()
        for peer in (WORKER, ROOT, GATE):
            with self.assertRaises(Denied):
                self.ledger.decide(peer, event)

    def test_wrong_owner_bot_chat_topic_message_forward_and_inaccessible_rejected(self):
        event = self.pending()
        variants = []
        for path, value in ((["from", "id"], 1009), (["from", "id"], True), (["from", "is_bot"], True),
                            (["message", "from", "id"], 1009), (["message", "from", "is_bot"], False),
                            (["message", "chat", "id"], -1009), (["message", "message_thread_id"], True),
                            (["message", "message_id"], 9), (["message", "date"], 0),
                            (["message", "forward_origin"], {}), (["inline_message_id"], "inline"),
                            (["data"], "approved"), (["data"], "cc1:" + "x" * 32 + ":a")):
            variant = copy.deepcopy(event)
            item = variant["callback_query"]
            for key in path[:-1]:
                item = item[key]
            item[path[-1]] = value
            variants.append(variant)
        for variant in variants:
            with self.assertRaises(Denied):
                self.ledger.decide(INGRESS, variant)
        self.assertEqual(self.ledger.decide(INGRESS, event)["state"], "granted")

    def test_exact_duplicate_callback_is_idempotent_changed_event_conflicts(self):
        event = self.pending()
        result = self.ledger.decide(INGRESS, event)
        self.assertEqual(self.ledger.decide(INGRESS, event), result)
        for key, value in (("data", event["callback_query"]["data"][:-1] + "d"), ("id", "new-callback")):
            changed = copy.deepcopy(event)
            changed["callback_query"][key] = value
            with self.assertRaises(Denied):
                self.ledger.decide(INGRESS, changed)
        changed = {**event, "update_id": 99}
        with self.assertRaises(Denied):
            self.ledger.decide(INGRESS, changed)

    def test_replayed_callback_after_consumption_never_grants_again(self):
        event = self.pending()
        self.ledger.decide(INGRESS, event)
        self.ledger.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")
        self.assertEqual(self.ledger.decide(INGRESS, event)["state"], "consumed")
        with self.assertRaises(Denied):
            self.ledger.decide(INGRESS, {**event, "update_id": 88, "callback_query": {**event["callback_query"], "id": "new"}})

    def test_denial_cannot_be_consumed_or_replaced_by_later_approval(self):
        event = self.pending()
        event["callback_query"]["data"] = event["callback_query"]["data"][:-1] + "d"
        self.assertEqual(self.ledger.decide(INGRESS, event)["state"], "denied")
        with self.assertRaises(Denied):
            self.ledger.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")

    def test_owner_can_revoke_an_unconsumed_grant_using_the_original_exact_prompt(self):
        prompt = approved(self.ledger, self.intent)
        revoked = self.ledger.decide(INGRESS, update(prompt["deny_data"], update_id=22, callback_id="revoke-22"))
        self.assertEqual(revoked["state"], "revoked")
        with self.assertRaises(Denied):
            self.ledger.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")

    def test_expiry_checked_at_enrollment_decision_and_attempt_not_just_contract_decode(self):
        with self.assertRaises(Denied):
            self.ledger.enroll(ROOT, self.intent.to_dict(), "approval-1", "2026-10-02T04:00:00Z")
        event = self.pending()
        self.now = NOW + timedelta(hours=1)
        with self.assertRaises(Denied):
            self.ledger.decide(INGRESS, event)
        self.now = NOW
        self.ledger.decide(INGRESS, event)
        self.now = NOW + timedelta(hours=1)
        with self.assertRaises(Denied):
            self.ledger.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")

    def test_backwards_clock_holds_authorization(self):
        event = self.pending()
        self.now = NOW - timedelta(minutes=1)
        with self.assertRaisesRegex(Denied, "backwards"):
            self.ledger.decide(INGRESS, event)

    def test_competing_claims_single_use_and_same_attempt_replay_cannot_execute(self):
        approved(self.ledger, self.intent)
        second = open_ledger(Path(self.tmp.name), clock=lambda: self.now)
        self.addCleanup(second.close)
        digest = self.intent.fields["intent_digest"]
        self.assertTrue(self.ledger.claim(GATE, self.intent.id, digest, "attempt-1")["may_execute"])
        self.assertFalse(second.claim(GATE, self.intent.id, digest, "attempt-1")["may_execute"])
        for peer, changed, attempt in ((WORKER, digest, "attempt-1"), (GATE, digest, "attempt-2"), (GATE, "changed", "attempt-1")):
            with self.assertRaises(Denied):
                second.claim(peer, self.intent.id, changed, attempt)
        self.assertEqual(second.recover(GATE, self.intent.id).fields["state"], "unknown")
        self.assertFalse(second.claim(GATE, self.intent.id, digest, "attempt-1")["may_execute"])
        action_record, approval = second.load(self.intent.id)
        self.assertEqual(approval.fields["consumed_attempt_id"], action_record.fields["attempt_id"])

    def test_snapshot_retains_approvals_attempts_audit_and_private_permissions(self):
        approved(self.ledger, self.intent)
        self.ledger.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")
        destination = Path(self.tmp.name) / "snapshot.sqlite"
        with mock.patch("relay_core.owner_gate.protected_path", side_effect=lambda path, **_: Path(path)):
            self.ledger.snapshot(destination)
            with self.assertRaises(FileExistsError):
                self.ledger.snapshot(destination)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
            self.assertEqual(decode(db.execute("SELECT approval FROM intents").fetchone()[0]).fields["state"], "consumed")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 4)

    def test_reusing_an_attempt_id_for_another_action_rolls_back_approval_consumption(self):
        approved(self.ledger, self.intent)
        other = action(id="action-2")
        approved(self.ledger, other, "approval-2", update_id=20, message_id=21)
        self.ledger.claim(GATE, self.intent.id, self.intent.fields["intent_digest"], "attempt-1")
        with self.assertRaises(Denied):
            self.ledger.claim(GATE, other.id, other.fields["intent_digest"], "attempt-1")
        other_action, approval = self.ledger.load(other.id)
        self.assertEqual((other_action.fields["state"], approval.fields["state"]), ("stored", "granted"))

    def test_unknown_schema_policy_and_audit_corruption_preserved_not_reinitialized(self):
        self.enroll()
        self.ledger.db.execute("UPDATE metadata SET schema='ccrelay.owner_ledger.v999'")
        with self.assertRaises(Denied):
            open_ledger(Path(self.tmp.name))
        self.assertEqual(self.ledger.db.execute("SELECT schema FROM metadata").fetchone()[0], "ccrelay.owner_ledger.v999")
        self.ledger.db.execute("UPDATE metadata SET schema=?", (OwnerLedger.SCHEMA,))
        with self.assertRaises(Denied):
            open_ledger(Path(self.tmp.name), fields={**owner_fields(), "bot_id": 999})
        self.ledger.db.execute("UPDATE audit SET digest='corrupt'")
        with self.assertRaisesRegex(Denied, "audit"):
            open_ledger(Path(self.tmp.name))

    def test_ledger_record_index_tamper_does_not_authorize(self):
        self.enroll()
        self.ledger.db.execute("UPDATE intents SET approval_id='forged'")
        with self.assertRaises(Denied):
            self.ledger.load(self.intent.id)

    def test_wire_dispatch_accepts_only_kernel_bound_methods_and_rejects_identity_headers(self):
        request = {"schema": "ccrelay.owner_request.v1", "request_id": "req-1", "method": "enroll_bootstrap",
                   "args": {"action": self.intent.to_dict(), "approval_id": "approval-1", "expires_at": EXPIRY}}
        with self.assertRaises(Denied):
            ccrelay_owner_gate.dispatch(self.ledger, WORKER, request)
        with self.assertRaises(Denied):
            ccrelay_owner_gate.dispatch(self.ledger, ROOT, {**request, "owner_id": 1001})
        self.assertIn("approve_data", ccrelay_owner_gate.dispatch(self.ledger, ROOT, request))
        for method in ("activate", "restart", "owner_approve", "claim"):
            with self.assertRaises(Denied):
                ccrelay_owner_gate.dispatch(self.ledger, ROOT, {**request, "method": method})


if __name__ == "__main__":
    unittest.main()
