"""Fake Bot API, actual flock/SQLite, and deterministic watchdog conformance."""
import io
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

from relay_core.identity import Denied
from relay_core.polling import (CycleHealth, DurablePoller, LivenessWatchdog, NoRedirect, PollError, PollerLock, ReadOnlyBot)
from intake_fixtures import FakeGuard, FakeTelegram, message, open_ledger, process, response


class PollingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        (self.folder / "ledger").mkdir(mode=0o700)
        self.now, self.monotonic = 1790913600, 0
        self.patcher = mock.patch("relay_core.intake.protected_path", side_effect=lambda path, **_: Path(path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.ledger = open_ledger(self.folder / "ledger", clock=lambda: self.now)
        self.addCleanup(self.ledger.close)
        self.bot = FakeTelegram(self.folder / "provider.sqlite")
        self.guard = FakeGuard()
        self.health = CycleHealth(grace_seconds=10, startup_seconds=60, availability_seconds=30, clock=lambda: self.monotonic)
        self.poller = self.new_poller()

    def new_poller(self):
        return DurablePoller(self.bot, self.ledger, self.guard, self.health, expected_username="SyntheticKhadang",
                             long_poll_seconds=10, conflict_limit=3, network_timeout=20, wall_clock=lambda: self.now)

    def test_verify_identity_then_start_at_zero_and_ack_only_after_durable_commit(self):
        with self.assertRaises(Denied):
            self.poller.step()
        self.bot.add(message())
        self.poller.verify()
        self.assertEqual(self.poller.step()["next_offset"], 2)
        self.assertEqual(self.bot.offsets(), [0])
        self.assertEqual(len(self.ledger.pending_dispatches()), 1)
        self.assertEqual(self.poller.step()["next_offset"], 0)
        self.assertEqual(self.bot.offsets(), [0, 2])
        self.assertEqual(self.bot.pending_count(), 0)

    def test_wrong_bot_id_username_or_webhook_never_calls_getupdates_or_mutates_wiring(self):
        for name, value in (("bot_id", 999), ("username", "OtherBot"), ("webhook_url", "https://synthetic-webhook.invalid")):
            original = getattr(self.bot, name)
            setattr(self.bot, name, value)
            with self.assertRaises(Denied):
                self.poller.verify()
            setattr(self.bot, name, original)
        self.assertEqual(self.bot.offsets(), [])

    def test_restarted_poller_observes_pending_low_id_before_any_old_high_ack(self):
        self.bot.add(message(1000))
        self.poller.verify()
        self.poller.step()
        # Simulate retention expiry followed by Telegram's documented random ID.
        with sqlite3.connect(self.bot.path) as db:
            db.execute("DELETE FROM pending")
        self.bot.add(message(3))
        restarted = self.new_poller()
        restarted.verify()
        restarted.step()
        self.assertEqual(self.bot.offsets(), [0, 0])
        self.assertEqual(self.ledger.event(3)["update_id"], 3)
        self.assertEqual(len(self.ledger.pending_dispatches()), 2)

    def test_disk_failure_never_allows_a_higher_offset_request(self):
        self.bot.add(message())
        self.poller.verify()
        with mock.patch.object(self.ledger, "capture", side_effect=OSError("synthetic full disk")):
            with self.assertRaises(OSError):
                self.poller.step()
        self.assertEqual(self.poller.offset, 0)
        self.assertEqual(self.bot.offsets(), [0])
        self.assertEqual(self.bot.pending_count(), 1)

    def test_sustained_409_is_terminal_and_restart_does_not_reset_conflict_count(self):
        self.poller.verify()
        self.bot.errors = [PollError(409), PollError(409), PollError(409)]
        self.assertEqual(self.poller.step()["code"], 409)
        self.assertEqual(self.poller.step()["code"], 409)
        with self.assertRaisesRegex(Denied, "409"):
            self.poller.step()
        self.assertEqual(self.ledger.state()["conflicts"], 3)
        restarted = self.new_poller()
        restarted.verify()
        with self.assertRaisesRegex(Denied, "conflict"):
            restarted.step()
        self.assertEqual(self.bot.offsets(), [])

    def test_success_resets_conflicts_but_network_errors_and_getme_do_not(self):
        self.poller.verify()
        self.bot.errors = [PollError(409), PollError(0)]
        self.poller.step()
        self.poller.step()
        self.assertEqual(self.ledger.state()["conflicts"], 1)
        self.poller.step()
        self.assertEqual(self.ledger.state()["conflicts"], 0)

    def test_rate_limit_persists_across_restart_without_a_second_poller_or_busy_api_calls(self):
        self.poller.verify()
        self.bot.errors = [PollError(429, 100)]
        self.assertEqual(self.poller.step()["wait_seconds"], 100)
        restarted = self.new_poller()
        restarted.verify()
        self.assertEqual(restarted.step()["status"], "provider_cooldown")
        self.assertEqual(self.bot.offsets(), [])
        self.now += 100
        self.monotonic += 100
        self.assertEqual(restarted.step()["status"], "durably_captured")

    def test_lost_lifetime_lock_or_replaced_process_generation_prevents_polling(self):
        self.poller.verify()
        self.guard.valid = False
        with self.assertRaises(Denied):
            self.poller.step()
        self.assertEqual(self.bot.offsets(), [])

    def test_busy_network_failure_loop_does_not_reset_durable_success_health(self):
        self.poller.verify()
        self.poller.step()
        self.bot.errors = [PollError(0)] * 100
        for _ in range(4):
            self.poller.step()
            self.monotonic += 11
        self.assertTrue(self.health.status()["stale"])
        with self.assertRaises(Denied):
            self.poller.step()
        self.assertEqual(self.health.status()["durable_cycles"], 1)

    def test_watchdog_observes_real_stalled_phase_and_known_cooldown_without_heartbeat_faking(self):
        fatal = []
        watchdog = LivenessWatchdog(self.health, fatal.append)
        self.health.phase_started("polling_and_commit", 20)
        self.monotonic = 29
        self.assertTrue(watchdog.tick())
        self.monotonic = 31
        self.assertFalse(watchdog.tick())
        self.assertEqual(fatal, ["intake cycle deadline exceeded"])
        self.health.phase_started("provider_cooldown", 100)
        self.monotonic = 80
        self.assertTrue(watchdog.tick())
        self.assertEqual(self.health.status()["durable_cycles"], 0)

    def test_initial_startup_allowance_is_explicit_and_does_not_count_as_a_durable_cycle(self):
        self.monotonic = 20
        self.assertFalse(self.health.status()["stale"])
        self.assertEqual(self.health.status()["durable_cycles"], 0)
        self.monotonic = 71
        self.assertTrue(self.health.status()["stale"])


class LockAndTransportTests(unittest.TestCase):
    def test_actual_cross_process_flock_is_per_bot_not_per_state_config_and_never_unlinked(self):
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            with mock.patch("relay_core.polling.protected_path", side_effect=lambda path, **_: Path(path)):
                with PollerLock(folder, bot_id=1002, owner_uid=os.geteuid(), observer=process) as guard:
                    result = subprocess.run([sys.executable, str(Path(__file__).with_name("intake_fault_fixture.py")), str(folder), "lock_probe"],
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 42, result.stderr)
                    guard.check()
                self.assertTrue((folder / "1002.lock").exists())
                with PollerLock(folder, bot_id=1002, owner_uid=os.geteuid(), observer=process):
                    pass

    def test_lock_inode_replacement_symlink_and_leaked_metadata_do_not_establish_ownership(self):
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            with mock.patch("relay_core.polling.protected_path", side_effect=lambda path, **_: Path(path)):
                with PollerLock(folder, bot_id=1002, owner_uid=os.geteuid(), observer=process) as guard:
                    guard.path.rename(folder / "old.lock")
                    guard.path.write_bytes(b"forged PID file")
                    with self.assertRaises(Denied):
                        guard.check()
                (folder / "1002.lock").unlink()
                (folder / "1002.lock").symlink_to(folder / "old.lock")
                with self.assertRaises(OSError):
                    with PollerLock(folder, bot_id=1002, owner_uid=os.geteuid(), observer=process):
                        pass

    def test_transport_has_no_send_webhook_mutation_download_or_automatic_redirect(self):
        bot = ReadOnlyBot("SYNTHETIC-NOT-A-TOKEN", timeout=20)
        for method in ("sendMessage", "deleteWebhook", "setWebhook", "getFile", "answerCallbackQuery"):
            with self.assertRaises(Denied):
                bot.request(method)
        with self.assertRaises(PollError):
            NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_transport_returns_original_wire_and_never_puts_secret_url_in_errors(self):
        secret = "SYNTHETIC-NOT-A-TOKEN"
        bot = ReadOnlyBot(secret, timeout=20)
        raw = response(message())
        stream = io.BytesIO(raw)
        with mock.patch("relay_core.polling.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value = stream
            self.assertEqual(bot.updates(0, 10), raw)
            self.assertIn(b'"offset":0', opener.return_value.open.call_args.args[0].data)
        exception = urllib.error.URLError("https://api.telegram.org/bot" + secret)
        with mock.patch("relay_core.polling.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = exception
            with self.assertRaises(PollError) as caught:
                bot.updates(0, 10)
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("https", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
