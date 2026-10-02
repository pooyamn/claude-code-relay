"""Joined component recovery: real SQLite/files/deaths, no live/model calls."""
import copy
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest import mock

from relay_core.artifacts import write_new
from relay_core.contracts import canonical_bytes
from relay_core.identity import Denied
from relay_core.telegram_authority import SourceGrants
from relay_core.telegram_outbound import AssetStore
from relay_core.telegram_producers import TelegramProducers
from relay_core.telegram_repair import recipe
from relay_core.telegram_scheduler import TelegramScheduler
from relay_core.telegram_snapshot import DEPENDENCIES, capture, inspect_snapshot, restore_snapshot
from source_grant_fixtures import CONTROLLER, sources
from telegram_fixtures import open_telegram, rejected, reply
from test_core_telegram import TelegramFixture
from test_core_telegram_repair import authorization


def dependencies():
    return {key: "sha256:" + "d" * 64 for key in DEPENDENCIES}  # Explicitly invented references.


class SnapshotTests(TelegramFixture):
    def setUp(self):
        super().setUp()
        protection = mock.patch("relay_core.telegram_snapshot.protected_path", side_effect=lambda path, **_: Path(path))
        protection.start()
        self.addCleanup(protection.stop)
        self.joined = sources(self.folder / "authority", self.ledger)
        self.grants, self.authority = self.joined.__enter__()
        self.addCleanup(lambda: self.joined.__exit__(None, None, None))
        self.scheduler = TelegramScheduler(self.ledger, self.bot, self.store, ownership_check=self.guard.check,
                                            authorize_dispatch=self.grants.authorize)
        self.producer = TelegramProducers(self.ledger, authorize_source=self.grants.enrollment_allowed)
        self.snapshot = self.folder / "snapshot"

    def enroll(self, **kwargs):
        body = reply(**kwargs)
        self.grants.issue(CONTROLLER, body, expires_ms=self.now + 86400000)
        self.producer.enqueue(body)
        return body

    def capture(self, **kwargs):
        return capture(self.ledger, self.grants, self.store, self.snapshot, cohort_id="fixture-cohort",
                       external_digests=dependencies(), **kwargs)

    def inspect(self):
        return inspect_snapshot(self.snapshot, owner_uid=os.geteuid())

    def restored(self):
        target = self.folder / "restored"
        restore_snapshot(self.snapshot, target, owner_uid=os.geteuid())
        ledger = open_telegram(target / "outbox", now=lambda: self.now)
        grants = SourceGrants(target / "source-grants", ledger=ledger, authority=self.authority,
                              current_check=lambda body, binding: False)
        self.addCleanup(ledger.close)
        self.addCleanup(grants.close)
        return target, ledger, grants

    def test_complete_capture_retains_sources_spool_assets_cursors_and_grant_history(self):
        body = self.enroll(count=2, cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.send()
        self.grants.revoke(CONTROLLER, body["id"])
        self.tick()
        reference = self.store.stage(b"invented upload bytes", filename="original.pdf", mime_type="application/pdf")
        upload = self.enroll(bundle_id="upload", operations=[{"method": "sendDocument", "args": {
            "chat_id": -1003, "message_thread_id": 5, "document": "attach://document", "caption": "full caption"},
            "assets": {"document": reference}}])
        self.grants.revoke(CONTROLLER, "upload")
        self.grants.renew(CONTROLLER, upload, expires_ms=self.now + 100000)
        write_new(self.store.folder / ("f" * 32 + ".pending"), b"interrupted upload", mode=0o600)
        write_new(self.ledger.responses / ("e" * 32 + ".pending"), b"interrupted response", mode=0o400)
        manifest = self.capture()
        self.assertEqual({p.relative_to(self.snapshot).as_posix() for p in self.snapshot.rglob("*") if p.is_file()},
                         {item["path"] for item in manifest["files"]} | {"manifest.json"})
        self.assertEqual(self.inspect(), manifest)
        self.assertEqual(sum(item["forensic_only"] for item in manifest["files"]), 2)
        self.assertFalse(manifest["full_system_backup"])
        self.assertEqual(manifest["external_digests"], dependencies())
        target, ledger, grants = self.restored()
        self.assertEqual(ledger.bundle("upload")["body"], upload)
        self.assertEqual(ledger.status("reply-1")["operation_states"], ["confirmed", "stored"])
        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(ledger.stream("stream-1")["tail_cursor"], 50)
        self.assertTrue(grants.grant("reply-1")["revoked"])
        self.assertEqual(grants.grant("upload")["revision"], 3)
        self.assertEqual(grants.db.execute("SELECT count(*) FROM grant_events").fetchone()[0], 5)
        store = AssetStore(target / "assets", owner_uid=os.geteuid(), max_bytes=100000)
        self.assertEqual(store.read(reference), b"invented upload bytes")
        intent = ledger.items("reply-1")[0]["current"]["record"].id
        self.assertEqual(ledger.read_response(intent)[1].status, 200)
        scheduler = TelegramScheduler(ledger, self.bot, store, ownership_check=self.guard.check,
                                      authorize_dispatch=grants.authorize)
        scheduler.verify()
        self.assertFalse(scheduler.step()["submitted"])
        self.assertEqual(self.bot.count(), 1)

    def test_lost_ack_restore_never_replays_unknown_or_resets_offsets(self):
        self.enroll(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        self.bot.lost_ack = True
        self.assertEqual(self.send()["state"], "unknown")
        self.capture()
        target, ledger, grants = self.restored()
        # Even an explicitly supplied positive checker cannot make unknown stored.
        grants.current_check = lambda body, binding: True
        scheduler = TelegramScheduler(ledger, self.bot, AssetStore(target / "assets", owner_uid=os.geteuid(), max_bytes=100000),
                                      ownership_check=self.guard.check, authorize_dispatch=grants.authorize)
        scheduler.verify()
        for _ in range(3):
            self.assertFalse(scheduler.step()["submitted"])
        self.assertEqual(ledger.status("reply-1")["operation_states"], ["unknown"])
        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(self.bot.count(), 1)

    def test_captured_response_can_reconcile_restored_attempt_without_network(self):
        self.enroll(cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        class Interrupted(BaseException):
            pass
        def stop(name):
            if name == "after_response_spool":
                raise Interrupted()
        self.ledger.checkpoint = stop
        with self.assertRaises(Interrupted):
            self.send()
        self.ledger.checkpoint = lambda _: None
        self.capture()
        target, ledger, grants = self.restored()
        scheduler = TelegramScheduler(ledger, self.bot, AssetStore(target / "assets", owner_uid=os.geteuid(), max_bytes=100000),
                                      ownership_check=self.guard.check, authorize_dispatch=grants.authorize)
        intent = ledger.items("reply-1")[0]["current"]["record"].id
        self.assertEqual(ledger.status("reply-1")["operation_states"], ["unknown"])
        calls = self.bot.calls()
        scheduler.reconcile_spooled(intent)
        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 50)
        self.assertEqual(ledger.status("reply-1")["operation_states"], ["confirmed"])
        self.assertEqual(self.bot.calls(), calls)

    def test_repair_child_negative_evidence_and_original_upload_survive_together(self):
        reference = self.store.stage(b"invented photo", filename="original.png", mime_type="image/png")
        operation = {"method": "sendPhoto", "args": {"chat_id": -1003, "message_thread_id": 5,
                     "photo": "attach://photo"}, "assets": {"photo": reference}}
        body = reply(operations=[operation], cursor={"stream_id": "stream-1", "expected": 0, "new": 50})
        body["repair_plans"] = [recipe(operation, kind="photo_to_document")]
        self.grants.issue(CONTROLLER, body, expires_ms=self.now + 100000)
        self.producer.enqueue(body)
        self.scheduler.authorize_repair = authorization
        self.bot.responses = [rejected(400)]
        self.assertEqual(self.send()["state"], "pending")
        original = self.ledger.items("reply-1")[0]["current"]["record"].id
        before = self.ledger.status("reply-1")
        self.capture()
        target, ledger, grants = self.restored()
        self.assertEqual(ledger.status("reply-1"), before)
        self.assertEqual(ledger.load(original)["record"].fields["state"], "failed")
        self.assertEqual(ledger.read_response(original)[1].status, 400)
        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 0)
        self.assertEqual(AssetStore(target / "assets", owner_uid=os.geteuid(), max_bytes=100000).read(reference), b"invented photo")
        self.assertEqual(self.bot.count(), 0)

    def test_snapshot_is_read_only_and_restore_itself_never_opens_runtime_or_sends(self):
        self.enroll()
        self.capture()
        before = {p.relative_to(self.snapshot): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.snapshot.rglob("*") if p.is_file()}
        calls = self.bot.calls()
        with mock.patch("relay_core.telegram_scheduler.TelegramLedger.__init__", side_effect=AssertionError("runtime opened")):
            self.inspect()
            restore_snapshot(self.snapshot, self.folder / "new-only", owner_uid=os.geteuid())
        after = {p.relative_to(self.snapshot): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.snapshot.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(self.bot.calls(), calls)
        self.assertFalse((self.folder / "new-only/outbox/outbox.lock").exists())
        self.assertIn(b'"activation_performed":false', (self.folder / "new-only/restore.json").read_bytes())

    def test_real_independent_writers_are_fenced_during_both_wal_copies(self):
        self.enroll()
        def probe(name):
            if name == "after_snapshot_freeze":
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("telegram_snapshot_fault_fixture.py")),
                    str(self.folder), "writer_probe"], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 42, result.stderr)
        self.capture(checkpoint=probe)
        self.grants.revoke(CONTROLLER, "reply-1")  # Writers resume after capture.
        with sqlite3.connect((self.snapshot / "source-grants/source-grants.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            self.assertIn(b'"revoked":false', db.execute("SELECT body FROM grants").fetchone()[0])

    def test_caller_owned_transactions_are_refused_without_rollback(self):
        for connection in (self.ledger.connection, self.grants.db):
            with self.subTest(connection=connection):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    with self.assertRaises(Denied):
                        capture(self.ledger, self.grants, self.store, self.folder / ("busy-" + str(id(connection))),
                                cohort_id="fixture", external_digests=dependencies())
                    self.assertTrue(connection.in_transaction)
                finally:
                    connection.execute("ROLLBACK")

    def test_missing_dependency_owner_mismatch_and_overlapping_destination_refused(self):
        for fields in ({}, {**dependencies(), "unexpected": "sha256:" + "d" * 64},
                       {**dependencies(), "adapter_artifact": "not-a-digest"}):
            with self.subTest(fields=fields), self.assertRaises(Denied):
                capture(self.ledger, self.grants, self.store, self.snapshot, cohort_id="fixture", external_digests=fields)
        with mock.patch("relay_core.telegram_snapshot.os.geteuid", return_value=os.geteuid() + 1), self.assertRaises(Denied):
            self.capture()
        with self.assertRaises(Denied):
            capture(self.ledger, self.grants, self.store, self.store.folder / "snapshot", cohort_id="fixture", external_digests=dependencies())
        self.assertFalse(self.snapshot.exists())

    def test_new_destination_only_never_overwrites_existing_or_symlink(self):
        self.snapshot.mkdir(mode=0o700)
        write_new(self.snapshot / "keep", b"existing bytes")
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual((self.snapshot / "keep").read_bytes(), b"existing bytes")
        link = self.folder / "link"
        link.symlink_to(self.snapshot)
        with self.assertRaises(FileExistsError):
            capture(self.ledger, self.grants, self.store, link, cohort_id="fixture", external_digests=dependencies())

    def test_missing_original_upload_fails_without_complete_manifest(self):
        reference = self.store.stage(b"source bytes", filename="original.bin", mime_type="application/octet-stream")
        self.enroll(operations=[{"method": "sendDocument", "args": {"chat_id": -1003,
            "message_thread_id": 5, "document": "attach://document"}, "assets": {"document": reference}}])
        (self.store.folder / (reference["digest"][7:] + ".blob")).unlink()  # Synthetic fault, not user data.
        with self.assertRaises(FileNotFoundError):
            self.capture()
        self.assertFalse((self.snapshot / "manifest.json").exists())
        self.assertIsNotNone(self.ledger.bundle("reply-1"))

    def test_mutating_payloads_or_adding_files_during_copy_refuses_complete_manifest(self):
        for change in ("change", "add"):
            with self.subTest(change=change):
                reference = self.store.stage(change.encode(), filename="source.bin", mime_type="application/octet-stream")
                source = self.store.folder / (reference["digest"][7:] + ".blob")
                def mutate(name):
                    if name == "after_snapshot_file":
                        if change == "change":
                            source.chmod(0o600)
                            source.write_bytes(b"changed")
                            source.chmod(0o400)
                        elif not (self.store.folder / ("1" * 32 + ".pending")).exists():
                            write_new(self.store.folder / ("1" * 32 + ".pending"), b"new interruption")
                with self.assertRaises(Denied):
                    capture(self.ledger, self.grants, self.store, self.folder / change, cohort_id="fixture",
                            external_digests=dependencies(), checkpoint=mutate)
                self.assertFalse((self.folder / change / "manifest.json").exists())
                if change == "change":
                    source.unlink()  # Remove only the invented corrupt fixture for the next subcase.

    def test_linked_or_unknown_components_are_not_silently_skipped(self):
        reference = self.store.stage(b"source", filename="source.bin", mime_type="application/octet-stream")
        source = self.store.folder / (reference["digest"][7:] + ".blob")
        alias = self.store.folder / ("f" * 64 + ".blob")
        for kind in ("hardlink", "symlink", "unknown"):
            with self.subTest(kind=kind):
                if kind == "hardlink":
                    os.link(source, alias)
                elif kind == "symlink":
                    alias.symlink_to(source)
                else:
                    alias = self.store.folder / "future-state.json"
                    write_new(alias, b"future format")
                with self.assertRaises(Denied):
                    capture(self.ledger, self.grants, self.store, self.folder / kind, cohort_id="fixture", external_digests=dependencies())
                alias.unlink()
        write_new(self.ledger.folder / "future-metadata", b"must not drop")
        with self.assertRaises(Denied):
            self.capture()

    def test_unknown_database_schema_is_preserved_but_not_published_as_supported(self):
        self.ledger.connection.execute("UPDATE telegram_metadata SET schema='future'")
        with self.assertRaises(Denied):
            self.capture()
        self.assertEqual(self.ledger.connection.execute("SELECT schema FROM telegram_metadata").fetchone()[0], "future")
        self.assertFalse((self.snapshot / "manifest.json").exists())

    def test_tampered_or_unlisted_snapshot_files_are_refused_before_restore(self):
        self.enroll()
        self.capture()
        policy = self.snapshot / "policy/outbound.json"
        original = policy.read_bytes()
        policy.chmod(0o600)
        policy.write_bytes(original + b" ")
        policy.chmod(0o400)
        with self.assertRaises(Denied):
            self.inspect()
        with self.assertRaises(Denied):
            restore_snapshot(self.snapshot, self.folder / "bad-restore", owner_uid=os.geteuid())
        self.assertFalse((self.folder / "bad-restore").exists())
        policy.chmod(0o600)
        policy.write_bytes(original)
        policy.chmod(0o400)
        write_new(self.snapshot / "unlisted", b"not in manifest")
        with self.assertRaises(Denied):
            self.inspect()

    def test_duplicate_unsafe_unknown_scope_and_forensic_promotion_manifests_denied(self):
        write_new(self.store.folder / ("f" * 32 + ".pending"), b"partial")
        self.capture()
        baseline = self.inspect()
        changes = [lambda m: m["files"].append(copy.deepcopy(m["files"][0])),
                   lambda m: m["files"][0].update(path="../escape"),
                   lambda m: m.update(schema="future"), lambda m: m.update(full_system_backup=True),
                   lambda m: m["files"][0].update(forensic_only=False)]
        for change in changes:
            manifest = copy.deepcopy(baseline)
            change(manifest)
            path = self.snapshot / "manifest.json"
            path.chmod(0o600)
            path.write_bytes(canonical_bytes(manifest))
            path.chmod(0o400)
            with self.subTest(manifest=manifest), self.assertRaises(Denied):
                self.inspect()

    def test_actual_capture_and_restore_process_deaths_leave_incomplete_work_visible(self):
        boundaries = ("after_snapshot_freeze", "after_snapshot_database", "after_snapshot_file",
                      "before_snapshot_manifest", "after_snapshot_manifest", "after_restore_file",
                      "before_restore_manifest", "after_restore_manifest")
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                folder = self.folder / boundary
                folder.mkdir(mode=0o700)
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("telegram_snapshot_fault_fixture.py")),
                    str(folder), boundary], capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 73, result.stderr)
                snapshot_complete = boundary == "after_snapshot_manifest" or "restore" in boundary
                if snapshot_complete:
                    manifest = inspect_snapshot(folder / "snapshot", owner_uid=os.geteuid())
                    self.assertEqual(manifest["restore_mode"], "paused")
                else:
                    with self.assertRaises(FileNotFoundError):
                        inspect_snapshot(folder / "snapshot", owner_uid=os.geteuid())
                restored = folder / "restored"
                self.assertEqual((restored / "restore.json").exists(), boundary == "after_restore_manifest")
                for path in (folder / "ledger/outbox.sqlite", folder / "authority/grants/source-grants.sqlite"):
                    with sqlite3.connect(path, timeout=0) as db:
                        db.execute("BEGIN IMMEDIATE")  # Dead capture cannot strand a writer lock.
                        db.rollback()
                with sqlite3.connect(folder / "provider.sqlite") as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM effects").fetchone()[0], 1)
                if boundary == "after_restore_manifest":
                    ledger = open_telegram(restored / "outbox")
                    try:
                        self.assertEqual(ledger.status("reply-1")["operation_states"], ["unknown"])
                        self.assertEqual(ledger.stream("stream-1")["committed_cursor"], 0)
                    finally:
                        ledger.close()
