"""Synthetic crash/CAS fixtures, NOT the production ledger or runtime adapter.

SQLite files and provider effects live only in the isolated test scratch tree.
The fixture deliberately demonstrates a contract; it does not prove that the
existing router already uses durable storage, recovery or external idempotency.
"""
import os
from pathlib import Path
import sqlite3
import sys

from relay_core.contracts import ContractError, StaleRevision, decode, fingerprint, recovered, transition


def _connection(path):
    scratch = Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()
    if not Path(path).resolve().is_relative_to(scratch):
        raise RuntimeError("fixture database must be inside test scratch")
    con = sqlite3.connect(str(path), timeout=5)
    con.execute("PRAGMA synchronous=FULL")
    return con


class SyntheticLedger:
    def __init__(self, path):
        self.path = str(path)
        with _connection(self.path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, origin TEXT, revision INTEGER, body BLOB)")

    def insert(self, record):
        if record.revision != 0:
            raise ContractError("new fixture record must start at revision zero")
        with _connection(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT origin, body FROM records WHERE id=?", (record.id,)).fetchone()
            origin = fingerprint(record.to_dict())
            if existing:
                if existing[0] != origin:
                    raise ContractError("duplicate identity has different immutable intent")
                return decode(existing[1])
            con.execute("INSERT INTO records VALUES (?,?,?,?)", (record.id, origin, record.revision, record.encode()))
        return record

    def load(self, id):
        with _connection(self.path) as con:
            row = con.execute("SELECT body FROM records WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        return decode(row[0])

    def compare_and_swap(self, previous, next_record, *, die_before_commit=False):
        if previous.id != next_record.id or previous.kind != next_record.kind or next_record.revision != previous.revision + 1:
            raise ContractError("invalid CAS identity/revision")
        with _connection(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            cursor = con.execute("UPDATE records SET revision=?, body=? WHERE id=? AND revision=? AND body=?",
                                 (next_record.revision, next_record.encode(), previous.id, previous.revision, previous.encode()))
            if cursor.rowcount != 1:
                raise StaleRevision("another writer changed the fixture snapshot")
            if die_before_commit:
                os._exit(73)
        return next_record

    def recover(self, id):
        old = self.load(id)
        next_record = recovered(old)
        if next_record == old:
            return old
        return self.compare_and_swap(old, next_record)


class SyntheticProvider:
    """An independently persisted fake remote effect, without any network call."""
    def __init__(self, path):
        self.path = str(path)
        with _connection(self.path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS effects (attempt TEXT PRIMARY KEY, digest TEXT, receipt TEXT)")

    def submit(self, record):
        attempt = record.fields["attempt_id"]
        digest = record.fields["intent_digest"]
        receipt = "receipt-" + attempt
        with _connection(self.path) as con:
            con.execute("INSERT INTO effects VALUES (?,?,?)", (attempt, digest, receipt))
        return receipt

    def receipt(self, record):
        with _connection(self.path) as con:
            row = con.execute("SELECT digest, receipt FROM effects WHERE attempt=?", (record.fields["attempt_id"],)).fetchone()
        if row is None:
            return None  # Absence from this query is not proof the action did not happen.
        if row[0] != record.fields["intent_digest"]:
            raise ContractError("provider evidence binds a different intent")
        return row[1]

    def effect_count(self):
        with _connection(self.path) as con:
            return con.execute("SELECT count(*) FROM effects").fetchone()[0]


def submit_fixture(ledger, provider, id, crash=None):
    old = ledger.load(id)
    if old.fields["state"] == "confirmed":
        return old
    if old.fields["state"] != "stored":
        raise ContractError("fixture refuses resubmission of an uncertain/terminal intent")
    next_record = transition(old, "delivering", expected_revision=old.revision, attempt_id="attempt-1")
    ledger.compare_and_swap(old, next_record, die_before_commit=crash == "before_commit")
    if crash == "after_commit":
        os._exit(73)
    receipt = provider.submit(next_record)
    if crash == "after_effect":
        os._exit(73)
    result = transition(next_record, "confirmed", expected_revision=next_record.revision, receipt_id=receipt)
    ledger.compare_and_swap(next_record, result)
    if crash == "after_receipt":
        os._exit(73)
    return result


def reconcile_fixture(ledger, provider, id):
    old = ledger.recover(id)
    if old.fields["state"] != "unknown":
        return old
    receipt = provider.receipt(old)
    if receipt is None:
        return old
    result = transition(old, "confirmed", expected_revision=old.revision, receipt_id=receipt,
                        outcome_evidence_id="synthetic-provider-query-1")
    return ledger.compare_and_swap(old, result)


if __name__ == "__main__":
    submit_fixture(SyntheticLedger(sys.argv[1]), SyntheticProvider(sys.argv[2]), sys.argv[3], sys.argv[4])
