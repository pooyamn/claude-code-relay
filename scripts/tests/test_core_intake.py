"""Real SQLite/spool/crash tests with synthetic Telegram and UID observations."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import ccrelay_intake
import ccrelayd
from relay_core.identity import Denied
from relay_core.intake import IntakeLedger, IntakePolicy, provider_json
from intake_fixtures import (FakeTelegram, callback, message, open_ledger, policy, policy_fields, response)


class RoutingTests(unittest.TestCase):
    def test_empty_invalid_owner_allowlists_and_unknown_roles_fail_closed(self):
        for key, value in (("allow_users", []), ("allow_users", [True]), ("allow_users", [{}]), ("allow_users", [999]),
                           ("allow_chats", [0]), ("allow_chats", [True]), ("allow_users", [1001, 1001])):
            with self.assertRaises(Denied):
                policy({**policy_fields(), key: value})
        bad = policy_fields()
        bad["bindings"][0]["role_id"] = "reviewer"
        with self.assertRaises(Denied):
            policy(bad)

    def test_legacy_empty_allowlist_denies_instead_of_allowing_everyone(self):
        daemon = ccrelayd.Daemon.__new__(ccrelayd.Daemon)
        daemon.allow, daemon.allow_chats = set(), {"-1003"}
        self.assertFalse(daemon.allowed(1001, -1003))
        daemon.allow = {1001}
        self.assertTrue(daemon.allowed(1001, -1003))
        self.assertFalse(daemon.allowed(1009, -1009))

    def test_owner_message_is_priority_steering_intent_not_a_queued_model_turn(self):
        route = policy().route(message(text="سلام exact owner input"))
        self.assertEqual((route["lane"], route["mode"], route["priority"]), ("owner_steer", "prefer_steer", 20))
        self.assertEqual(route["target"], {"role_id": "builder", "session_id": "builder.fixture"})
        self.assertNotIn("expected_turn_id", route)  # PR 5 independently resolves the runtime.

    def test_owner_pause_stop_cancel_resume_bypass_normal_model_work(self):
        for command, operation in (("/stop", "stop"), ("/pause", "pause"), ("/cancel", "interrupt"), ("esc", "interrupt"), ("/resume", "resume")):
            route = policy().route(message(text=command))
            self.assertEqual((route["decision"], route["lane"], route["operation"], route["priority"]), ("accept", "owner_control", operation, 10))
        for text, target in (("/stop all", {"scope": "all"}), ("/pause builder.fixture", {"role_id": "builder", "session_id": "builder.fixture"})):
            self.assertEqual(policy().route(message(text=text, thread=4))["target"], target)
        self.assertEqual(policy().route(message(text="/stop all", thread=5))["decision"], "rejected")
        self.assertEqual(policy().route(message(text="/pause@SyntheticKhadang"))["operation"], "pause")
        self.assertEqual(policy().route(message(text="/pause@OtherBot"))["decision"], "held")

    def test_allow_chat_member_cannot_issue_owner_controls_or_owner_approval(self):
        shared = policy({**policy_fields(), "allow_chats": [-1003]})
        self.assertEqual(shared.route(message(sender=999))["decision"], "accept")
        self.assertEqual(shared.route(message(sender=999, text="/stop"))["decision"], "rejected")
        self.assertEqual(shared.route(callback(sender=999))["decision"], "rejected")
        self.assertEqual(shared.route(message(text="/stop", forward_origin={"type": "user"}))["decision"], "rejected")

    def test_callback_nonce_is_only_an_owner_gate_route_not_an_authorization(self):
        route = policy().route(callback())
        self.assertEqual((route["lane"], route["priority"], route["operation"]), ("owner_approval", 0, "owner_callback"))
        self.assertIsNone(route["target"])
        self.assertNotIn("approved", route)
        route = policy().route(callback(data="ccsel:3"))
        self.assertEqual((route["operation"], route["mode"]), ("selection", "prefer_steer"))

    def test_media_reply_voice_album_references_preserve_content_without_download(self):
        event = message(text="caption", media_group_id="album-1", reply_to_message={"text": "quoted"},
                        photo=[{"file_id": "small-photo", "file_unique_id": "unique-1"}, {"file_id": "large-photo"}],
                        voice={"file_id": "voice-1", "mime_type": "audio/ogg"},
                        document={"file_id": "document-1", "file_name": "../../untrusted-name.md"})
        route = policy().route(event)
        self.assertEqual([entry["file_id"] for entry in route["media"]], ["small-photo", "large-photo", "document-1", "voice-1"])
        self.assertEqual(route["media"][2]["file_name"], "../../untrusted-name.md")  # Metadata, never a destination path.
        self.assertEqual(event["message"]["reply_to_message"]["text"], "quoted")

    def test_unknown_unbound_missing_sender_bot_and_malformed_input_are_explicit(self):
        samples = [(message(thread=999), "held", "unbound"), ({"update_id": 9, "poll": {}}, "held", "unsupported_update"),
                   ({"update_id": 10, "message": {}}, "held", "malformed_update"),
                   (message(sender=999), "rejected", "sender_not_allowed")]
        bot = message()
        bot["message"]["from"]["is_bot"] = True
        samples.append((bot, "rejected", "sender_not_allowed"))
        for event, decision, reason in samples:
            route = policy().route(event)
            self.assertEqual((route["decision"], route["reason"]), (decision, reason))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.patcher = mock.patch("relay_core.intake.protected_path", side_effect=lambda path, **_: Path(path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.ledger = open_ledger(self.folder)
        self.addCleanup(self.ledger.close)

    def test_original_wire_bytes_and_routes_are_durable_before_next_ack(self):
        raw = b'{ "ok": true, "result": ' + json.dumps([message()]).encode() + b" }"
        self.assertEqual(self.ledger.capture(raw, 0), 2)
        event = self.ledger.event(1)
        header, stored = self.ledger._read_batch(event["batch_id"])
        self.assertEqual(stored, raw)
        self.assertEqual(header["request_offset"], 0)
        self.assertEqual(event["state"], "stored")
        self.assertEqual(event["route"]["lane"], "owner_steer")
        self.assertEqual(stat.S_IMODE(self.ledger.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.ledger.batches / (event["batch_id"] + ".batch")).stat().st_mode), 0o600)

    def test_duplicate_batches_events_and_materialization_create_one_logical_dispatch(self):
        raw = response(message())
        self.ledger.capture(raw, 0)
        self.ledger.capture(raw, 0)
        self.assertEqual(self.ledger.materialize(), ["tg-1002-1"])
        self.assertEqual(self.ledger.materialize(), [])
        self.ledger.capture(raw, 2)
        self.assertEqual(self.ledger.materialize(), [])
        self.assertEqual(len(self.ledger.pending_dispatches()), 1)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_conflicting_replay_keeps_original_and_raw_conflict_without_advancing_cursor(self):
        self.ledger.capture(response(message()), 0)
        before = self.ledger.state()
        with self.assertRaises(Denied):
            self.ledger.capture(response(message(text="conflicting"), message(2)), 2)
        self.assertEqual(self.ledger.state(), before)
        self.assertEqual(self.ledger.event(1)["update"]["message"]["text"], "Synthetic text")
        with self.assertRaises(Denied):
            self.ledger.event(2)
        self.assertEqual(len(list(self.ledger.batches.glob("*.batch"))), 2)

    def test_rejected_and_unsupported_updates_are_stored_with_no_dispatch(self):
        self.ledger.capture(response(message(sender=999), {"update_id": 2, "poll": {}}, {"update_id": 3}), 0)
        self.assertEqual(self.ledger.event(1)["state"], "rejected")
        self.assertEqual(self.ledger.event(2)["state"], "held")
        self.assertEqual(self.ledger.materialize(), [])
        self.assertEqual(self.ledger.state()["next_offset"], 4)

    def test_valid_provider_float_coordinates_survive_without_relaxing_action_contracts(self):
        event = message(location={"latitude": 35.6892, "longitude": 51.3890})
        self.ledger.capture(response(event), 0)
        self.assertEqual(self.ledger.event(1)["update"], event)
        self.ledger.materialize()
        from relay_core.contracts import canonical_bytes, ContractError
        with self.assertRaises(ContractError):
            canonical_bytes({"payment_amount": 0.1})

    def test_forged_event_or_dispatch_body_cannot_disagree_with_original_spool(self):
        from relay_core.intake import provider_bytes, sha
        from relay_core.contracts import canonical_bytes
        self.ledger.capture(response(message()), 0)
        forged = provider_bytes(message(text="forged row"))
        self.ledger.db.execute("UPDATE events SET body=?,digest=? WHERE id=1", (forged, sha(forged)))
        with self.assertRaisesRegex(Denied, "original provider"):
            self.ledger.event(1)
        original = provider_bytes(message())
        self.ledger.db.execute("UPDATE events SET body=?,digest=? WHERE id=1", (original, sha(original)))
        self.ledger.materialize()
        job = self.ledger.pending_dispatches()[0]
        job["route"]["operation"] = "forged-operation"
        self.ledger.db.execute("UPDATE dispatches SET body=?", (canonical_bytes(job),))
        with self.assertRaisesRegex(Denied, "dispatch"):
            self.ledger.pending_dispatches()

    def test_one_hundred_message_batch_verifies_original_spool_once_per_materialization(self):
        self.ledger.capture(response(*(message(uid) for uid in range(1, 101))), 0)
        with mock.patch.object(self.ledger, "_read_batch", wraps=self.ledger._read_batch) as reads:
            self.assertEqual(len(self.ledger.materialize()), 100)
            self.assertEqual(reads.call_count, 1)

    def test_two_concurrent_materializers_create_each_logical_dispatch_once(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        self.ledger.capture(response(*(message(uid) for uid in range(1, 11))), 0)
        barrier = threading.Barrier(2)
        def materialize():
            # Connections are opened in their own threads. Ancestor observation
            # is mocked once by this test's outer context, not patched in parallel.
            ledger = IntakeLedger(self.folder, policy())
            try:
                barrier.wait(timeout=3)
                return ledger.materialize()
            finally:
                ledger.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(materialize) for _ in range(2)]
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(map(len, results)), [0, 10])
        self.assertEqual(len(self.ledger.pending_dispatches()), 10)

    def test_invalid_duplicate_nonfinite_or_malformed_provider_response_retains_cursor(self):
        samples = [b'{"ok":true,"ok":true,"result":[]}', b'{"ok":true,"result":NaN}',
                   b'{"ok":true,"result":[{"update_id":1,"message":{"x":Infinity}}]}',
                   b'{"ok":true,"result":[{"message":{}}]}', response(message(), message()), b"not-json"]
        for raw in samples:
            with self.assertRaises(Denied):
                self.ledger.capture(raw, 0)
            self.assertEqual(self.ledger.state()["next_offset"], 0)

    def test_owner_control_and_approval_priority_are_independent_of_normal_backlog(self):
        self.ledger.capture(response(message(1, sender=999)), 0)
        # The shared-chat variant authorizes ordinary users but not commands.
        shared = {**policy_fields(), "allow_chats": [-1003]}
        with tempfile.TemporaryDirectory(dir=self.folder) as location:
            ledger = open_ledger(Path(location), fields=shared)
            try:
                ledger.capture(response(message(1, sender=999), message(2), message(3, text="/pause"), callback(4)), 0)
                self.assertEqual(ledger.materialize(), ["tg-1002-4", "tg-1002-3", "tg-1002-2", "tg-1002-1"])
                self.assertEqual([job["route"]["lane"] for job in ledger.pending_dispatches()],
                                 ["owner_approval", "owner_control", "owner_steer", "message"])
            finally:
                ledger.close()

    def test_random_lower_update_ids_do_not_reset_old_dispatches_or_reorder_capture_sequence(self):
        self.ledger.capture(response(message(1000)), 0)
        self.ledger.capture(response(), 1001)
        self.assertEqual(self.ledger.state()["next_offset"], 0)
        self.ledger.capture(response(message(3)), 0)
        self.assertEqual(self.ledger.materialize(), ["tg-1002-1000", "tg-1002-3"])
        self.assertEqual(self.ledger.state()["next_offset"], 4)

    def test_unknown_schema_policy_legacy_offset_and_tampered_spool_fail_without_reset(self):
        self.ledger.capture(response(message()), 0)
        batch = self.ledger.event(1)["batch_id"]
        path = self.ledger.batches / (batch + ".batch")
        path.write_bytes(path.read_bytes() + b"corrupt")
        with self.assertRaises(Denied):
            self.ledger.event(1)
        self.ledger.db.execute("UPDATE metadata SET schema='ccrelay.intake_ledger.v999'")
        with self.assertRaises(Denied):
            open_ledger(self.folder)
        self.assertEqual(self.ledger.db.execute("SELECT schema FROM metadata").fetchone()[0], "ccrelay.intake_ledger.v999")
        with tempfile.TemporaryDirectory(dir=self.folder) as location:
            (Path(location) / "offset").write_text("999")
            with self.assertRaises(Denied):
                open_ledger(Path(location))
            self.assertEqual((Path(location) / "offset").read_text(), "999")

    def test_snapshot_retains_routes_batches_dispatches_and_cooldown_not_only_cursor(self):
        self.ledger.capture(response(message()), 0)
        self.ledger.materialize()
        self.ledger.poll_failure(429, 30)
        destination = self.folder / "snapshot.sqlite"
        self.ledger.snapshot(destination)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM responses").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0], 1)
            self.assertGreater(db.execute("SELECT retry_at FROM metadata").fetchone()[0], 0)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_actual_process_death_at_disk_db_and_dispatch_boundaries_recovers_one_logical_event(self):
        for boundary in ("after_file_flush", "after_spool", "before_db_commit", "after_db_commit", "before_dispatch_commit", "after_dispatch_commit"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(dir=self.folder) as scratch:
                location = Path(scratch)
                (location / "ledger").mkdir(mode=0o700)
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("intake_fault_fixture.py")), str(location), boundary],
                                        capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 73, result.stderr)
                ledger = open_ledger(location / "ledger")
                try:
                    ledger.reconcile_spool()
                    if boundary == "after_file_flush":
                        self.assertEqual(ledger.state()["next_offset"], 0)
                        self.assertEqual(len(list(ledger.batches.glob("pending-*"))), 1)
                        ledger.capture(response(message()), 0)  # Remote had never been ACKed.
                    ledger.materialize()
                    self.assertEqual(len(ledger.pending_dispatches()), 1)
                    self.assertEqual(ledger.event(1)["state"], "ready")
                finally:
                    ledger.close()

    def test_process_death_after_remote_ack_does_not_lose_or_repeat_durable_dispatch(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as scratch:
            location = Path(scratch)
            (location / "ledger").mkdir(mode=0o700)
            provider = FakeTelegram(location / "provider.sqlite")
            provider.add(message())
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("intake_fault_fixture.py")), str(location), "after_provider_ack"],
                                    capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertEqual(provider.offsets(), [0, 2])
            self.assertEqual(provider.pending_count(), 0)
            ledger = open_ledger(location / "ledger")
            try:
                ledger.reconcile_spool()
                ledger.materialize()
                self.assertEqual(len(ledger.pending_dispatches()), 1)
            finally:
                ledger.close()


class EntryTests(unittest.TestCase):
    def test_plan_reads_only_examples_and_calls_neither_network_nor_credentials(self):
        with mock.patch("ccrelay_intake.token_from_file", side_effect=AssertionError("no credentials")):
            planned = ccrelay_intake.plan()
        self.assertFalse(planned["enabled"])
        self.assertFalse(planned["network_calls"])
        self.assertFalse(planned["state_changes"])
        self.assertEqual(planned["test_bot"], "khadang")

    def test_isolated_python_cli_plan_works_without_native_or_bot_environment(self):
        result = subprocess.run([sys.executable, "-I", str(Path(ccrelay_intake.__file__)), "--plan"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["enabled"])

    def test_disabled_and_non_test_config_fail_before_token_access_or_polling(self):
        cfg = json.loads((Path(ccrelay_intake.__file__).parents[1] / "deploy/wsl/identities/intake-config.json.example").read_text())
        with mock.patch("ccrelay_intake.token_from_file", side_effect=AssertionError("must not read")):
            with self.assertRaises(Denied):
                ccrelay_intake.run(cfg)
            with self.assertRaises(Denied):
                ccrelay_intake.configuration({**cfg, "test_bot": "hamal"})


if __name__ == "__main__":
    unittest.main()
