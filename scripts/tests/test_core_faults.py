import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from relay_core.contracts import ContractError, StaleRevision, recovered, transition
from contract_fixtures import example
from fault_fixtures import SyntheticLedger, SyntheticProvider, reconcile_fixture, submit_fixture


class FaultFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = SyntheticLedger(Path(self.tmp.name) / "ledger.sqlite")
        self.provider = SyntheticProvider(Path(self.tmp.name) / "provider.sqlite")
        self.message = example("message")
        self.ledger.insert(self.message)

    def crash_at(self, point):
        process = subprocess.run([sys.executable, str(Path(__file__).with_name("fault_fixtures.py")),
                                  self.ledger.path, self.provider.path, self.message.id, point],
                                 timeout=5)
        self.assertEqual(process.returncode, 73, "fixture must actually terminate at requested crash point")

    def test_process_death_before_commit_rolls_back_without_provider_effect(self):
        self.crash_at("before_commit")
        self.assertEqual(self.ledger.load(self.message.id), self.message)
        self.assertEqual(self.provider.effect_count(), 0)

    def test_committed_dispatch_before_process_death_stays_unknown_not_retried(self):
        self.crash_at("after_commit")
        unknown = reconcile_fixture(self.ledger, self.provider, self.message.id)
        self.assertEqual(unknown.fields["state"], "unknown")
        self.assertEqual(self.provider.effect_count(), 0)
        with self.assertRaises(ContractError):
            submit_fixture(self.ledger, self.provider, self.message.id)

    def test_effect_before_ack_reconciles_without_repeating_remote_action(self):
        self.crash_at("after_effect")
        self.assertEqual(self.ledger.load(self.message.id).fields["state"], "delivering")
        self.assertEqual(self.provider.effect_count(), 1)
        confirmed = reconcile_fixture(self.ledger, self.provider, self.message.id)
        self.assertEqual(confirmed.fields["state"], "confirmed")
        self.assertEqual(confirmed.fields["outcome_evidence_id"], "synthetic-provider-query-1")
        self.assertEqual(submit_fixture(self.ledger, self.provider, self.message.id), confirmed)
        self.assertEqual(self.provider.effect_count(), 1)

    def test_process_death_after_receipt_preserves_confirmation(self):
        self.crash_at("after_receipt")
        before = self.ledger.load(self.message.id)
        self.assertEqual(before.fields["state"], "confirmed")
        self.assertEqual(reconcile_fixture(self.ledger, self.provider, self.message.id), before)
        self.assertEqual(self.provider.effect_count(), 1)

    def test_duplicate_event_retains_original_outcome_and_changed_intent_conflicts(self):
        confirmed = submit_fixture(self.ledger, self.provider, self.message.id)
        self.assertEqual(self.ledger.insert(self.message), confirmed)
        self.assertEqual(self.provider.effect_count(), 1)
        with self.assertRaises(ContractError):
            self.ledger.insert(example("message", body="changed but same ID"))

    def test_two_concurrent_writers_cannot_both_acquire_execution(self):
        barrier = threading.Barrier(2)

        def contender(attempt):
            previous = self.ledger.load(self.message.id)
            next_record = transition(previous, "delivering", expected_revision=0, attempt_id=attempt)
            barrier.wait(timeout=5)
            try:
                self.ledger.compare_and_swap(previous, next_record)
                return "won"
            except StaleRevision:
                return "fenced"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contender, ["attempt-1", "attempt-2"]))
        self.assertCountEqual(results, ["won", "fenced"])
        self.assertEqual(self.ledger.load(self.message.id).revision, 1)

    def test_provider_receipt_cannot_confirm_another_fingerprint(self):
        other = example("message", body="other intent", state="delivering", attempt_id="attempt-1")
        self.provider.submit(other)
        ours = transition(self.message, "delivering", expected_revision=0, attempt_id="attempt-1")
        self.ledger.compare_and_swap(self.message, ours)
        unknown = self.ledger.recover(self.message.id)
        with self.assertRaises(ContractError):
            reconcile_fixture(self.ledger, self.provider, self.message.id)
        self.assertEqual(self.ledger.load(self.message.id), unknown)

    def test_corrupt_persisted_schema_fails_without_overwriting_bytes(self):
        import sqlite3
        raw = b'{"schema":"ccrelay.message.v999","id":"preserve-me"}'
        with sqlite3.connect(self.ledger.path) as con:
            con.execute("UPDATE records SET body=? WHERE id=?", (raw, self.message.id))
        with self.assertRaises(ContractError):
            self.ledger.recover(self.message.id)
        with sqlite3.connect(self.ledger.path) as con:
            preserved = con.execute("SELECT body FROM records WHERE id=?", (self.message.id,)).fetchone()[0]
        self.assertEqual(raw, preserved)


if __name__ == "__main__":
    unittest.main()
