"""Real multiple WALs/files/crashes; writer guard and host permissions synthetic."""
import base64
from dataclasses import replace
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from relay_core.artifacts import digest, write_new
from relay_core.contracts import canonical_bytes
from relay_core.identity import Denied, strict_json
from relay_core.system_snapshot import Component, SnapshotPolicy, _path, inspect_snapshot
from system_snapshot_fixtures import capture_fixture, fixture, policy_for


class SystemSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.folder.chmod(0o700)
        protection = mock.patch("relay_core.system_snapshot.protected_path", side_effect=lambda path, **_: Path(path))
        protection.start()
        self.addCleanup(protection.stop)
        self.components, self.policy = fixture(self.folder)
        for component in self.components:
            self.addCleanup(component.databases[b"state.sqlite"].close)
        self.destination = self.folder / "capture"

    def capture(self, **kwargs):
        return capture_fixture(self.components, self.policy, self.destination, **kwargs)

    def rows(self, key="broker"):
        return [strict_json(line) for line in (self.destination / key / "entries.jsonl").read_bytes().splitlines()]

    def inspect(self):
        return inspect_snapshot(self.destination, self.policy, owner_uid=os.geteuid())

    def test_complete_cohort_copies_memory_dirty_bytes_links_modes_and_unknown_actions(self):
        manifest = self.capture()
        self.assertEqual(self.inspect(), manifest)
        self.assertFalse(manifest["full_system_backup"])
        self.assertFalse(manifest["encrypted"])
        self.assertEqual(manifest["restore_mode"], "paused")
        for key in ("broker", "worker"):
            rows = {base64.b64decode(row["path"]): row for row in self.rows(key)}
            self.assertEqual(rows[b"empty"]["kind"], "directory")
            self.assertEqual(rows[b"empty"]["mode"], 0o500)
            self.assertEqual(base64.b64decode(rows[b"literal-link"]["link"]), b"../outside-never-read")
            self.assertEqual(rows[b"runtime.lock"]["kind"], "excluded")
            self.assertEqual(rows[b"state.sqlite-wal"]["exclusion"]["recovery"], "generated")
            dirty = rows[b"uncommitted\nnotes"]
            self.assertEqual((self.destination / key / dirty["payload"]).read_bytes(), b"uncommitted\0binary")
            self.assertEqual(dirty["mode"], 0o400)
            row = rows[b"state.sqlite"]
            db = sqlite3.connect((self.destination / key / row["payload"]).as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                self.assertEqual(db.execute("SELECT * FROM state").fetchall(), [("action-1", b"unknown external outcome; do not replay")])
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone(), ("delete",))
            finally:
                db.close()

    def test_independent_writers_are_blocked_on_both_databases_during_capture(self):
        def probe(name):
            if name == "after_system_snapshot_database":
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("system_snapshot_fault_fixture.py")),
                    str(self.folder), "writer_probe"], capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 42, result.stderr)
        self.capture(checkpoint=probe)
        for component in self.components:
            component.databases[b"state.sqlite"].execute("INSERT INTO state VALUES ('after-capture',?)", (b"writers released",))
        self.inspect()

    def test_replaced_database_path_cannot_escape_the_held_sqlite_writer_fence(self):
        component = self.components[1]
        connection = component.databases[b"state.sqlite"]
        connection.execute("PRAGMA journal_mode=DELETE")
        replacement = self.folder / "replacement.sqlite"
        write_new(replacement, b"", mode=0o600)
        with sqlite3.connect(replacement) as db:
            db.execute("CREATE TABLE state(id TEXT PRIMARY KEY,body BLOB)")
            db.execute("INSERT INTO state VALUES ('injected-replacement',?)", (b"outside held writer fence",))
        def change(name):
            if name == "after_system_snapshot_freeze":
                (component.root / "state.sqlite").rename(self.folder / "retained-original.sqlite")
                replacement.rename(component.root / "state.sqlite")
        with self.assertRaisesRegex(Denied, "database.*changed"):
            self.capture(checkpoint=change)
        self.assertFalse((self.destination / "manifest.json").exists())
        self.assertTrue((self.folder / "retained-original.sqlite").exists())

    def test_failed_second_writer_lock_releases_only_capture_owned_transactions(self):
        component = self.components[1]
        component.databases[b"state.sqlite"].execute("PRAGMA busy_timeout=0")
        other = sqlite3.connect(component.root / "state.sqlite", isolation_level=None)
        try:
            other.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.OperationalError):
                self.capture()
            self.assertTrue(other.in_transaction)
            self.assertTrue(all(not db.in_transaction for c in self.components for db in c.databases.values()))
            with sqlite3.connect(self.components[0].root / "state.sqlite", timeout=0) as probe:
                probe.execute("INSERT INTO state VALUES ('first-lock-released',?)", (b"retained",))
        finally:
            other.execute("ROLLBACK")
            other.close()
        self.assertFalse((self.destination / "manifest.json").exists())

    def test_missing_extra_duplicate_and_changed_version_components_fail_before_capture(self):
        cohorts = (self.components[:1], self.components + (self.components[0],),
                   (replace(self.components[0], id="unexpected"), self.components[1]),
                   (replace(self.components[0], version_digest="sha256:" + "b" * 64), self.components[1]))
        for cohort in cohorts:
            with self.subTest(cohort=tuple(c.id for c in cohort)), self.assertRaises(Denied):
                capture_fixture(cohort, self.policy, self.destination)
        self.assertFalse(self.destination.exists())

    def test_source_root_database_and_exclusion_changes_cannot_shrink_protected_coverage(self):
        component = self.components[0]
        for changed in (replace(component, root=self.components[1].root), replace(component, databases={}),
                        replace(component, exclusions={**component.exclusions,
                            b"memory.md": {"reason": "injected omission", "recovery": "generated"}})):
            with self.subTest(changed=changed.id), self.assertRaises(Denied):
                capture_fixture((changed, self.components[1]), self.policy, self.destination)
        self.assertFalse(self.destination.exists())

    def test_reserved_component_id_and_falsely_claimed_root_owner_are_rejected(self):
        with self.assertRaises(Denied):
            policy_for((replace(self.components[0], id="manifest.json"), self.components[1]))
        # Describing root-owned configuration does not grant this UID access.
        cohort = (replace(self.components[0], owner_uid=0), self.components[1])
        policy = policy_for(cohort)
        with self.assertRaises(Denied):
            capture_fixture(cohort, policy, self.destination)
        self.assertFalse(self.destination.exists())

    def test_caller_transaction_is_not_rolled_back_and_other_locks_not_taken(self):
        db = self.components[1].databases[b"state.sqlite"]
        db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(Denied):
                self.capture()
            self.assertTrue(db.in_transaction)
            self.assertFalse(self.components[0].databases[b"state.sqlite"].in_transaction)
        finally:
            db.execute("ROLLBACK")

    def test_attached_or_wrong_path_database_cannot_be_mistaken_for_registered_state(self):
        component = self.components[0]
        db = component.databases[b"state.sqlite"]
        db.execute("ATTACH DATABASE ':memory:' AS unexpected")
        with self.assertRaises(Denied):
            self.capture()
        db.execute("DETACH DATABASE unexpected")
        cohort = (replace(component, databases={b"memory.md": db}), self.components[1])
        with self.assertRaises(Denied):
            capture_fixture(cohort, self.policy, self.destination)

    def test_overlap_existing_and_link_destinations_are_never_overwritten(self):
        with self.assertRaises(Denied):
            capture_fixture(self.components, self.policy, self.components[0].root / "capture")
        self.destination.mkdir(mode=0o700)
        write_new(self.destination / "keep", b"existing work")
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual((self.destination / "keep").read_bytes(), b"existing work")
        link = self.folder / "linked"
        link.symlink_to(self.destination)
        with self.assertRaises(FileExistsError):
            capture_fixture(self.components, self.policy, link)

    def test_literal_newlines_tabs_and_pathspec_names_are_not_payload_paths(self):
        root = self.components[0].root
        names = (b"-leading", b"line\nfeed", b"tab\tpath", b":(glob)*")
        for name in names:
            write_new(root / os.fsdecode(name), name, mode=0o600)
        self.capture()
        rows = {base64.b64decode(row["path"]): row for row in self.rows()}
        for name in names:
            row = rows[name]
            self.assertRegex(row["payload"], r"^[0-9]{8}\.blob$")
            self.assertEqual((self.destination / "broker" / row["payload"]).read_bytes(), name)
        self.inspect()

    def test_invalid_utf8_path_encoding_is_lossless_with_native_linux_capture(self):
        name = b"invalid-\xff"
        self.assertEqual(_path(base64.b64encode(name).decode()), name)
        if sys.platform.startswith("linux"):
            write_new(self.components[0].root / os.fsdecode(name), name, mode=0o600)
            self.capture()
            row = next(row for row in self.rows() if base64.b64decode(row["path"]) == name)
            self.assertEqual((self.destination / "broker" / row["payload"]).read_bytes(), name)
            self.inspect()

    def test_file_changes_and_new_entries_invalidate_capture_without_manifest(self):
        root = self.components[0].root
        changed = False
        def mutate(name):
            nonlocal changed
            if name == "after_system_snapshot_entry" and not changed:
                changed = True
                (root / "memory.md").write_bytes(b"changed decision")
                write_new(root / "new-handoff", b"new context", mode=0o600)
        with self.assertRaises(Denied):
            self.capture(checkpoint=mutate)
        self.assertFalse((self.destination / "manifest.json").exists())
        self.assertEqual((root / "memory.md").read_bytes(), b"changed decision")

    def test_unregistered_sqlite_is_not_raw_copied_or_silently_skipped(self):
        root = self.components[0].root
        path = root / "unknown.db"
        write_new(path, b"", mode=0o600)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE future_state(value TEXT)")
            db.execute("INSERT INTO future_state VALUES ('must survive')")
        with self.assertRaisesRegex(Denied, "unregistered SQLite"):
            self.capture()
        self.assertFalse((self.destination / "manifest.json").exists())
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT * FROM future_state").fetchall(), [("must survive",)])

    def test_large_binary_payload_streams_and_explicit_bounds_leave_source_intact(self):
        root = self.components[0].root
        large = b"\x00\xff\x01" * (128 * 1024)
        write_new(root / "large", large, mode=0o600)
        self.capture()
        row = next(row for row in self.rows() if base64.b64decode(row["path"]) == b"large")
        self.assertEqual((self.destination / "broker" / row["payload"]).read_bytes(), large)
        small = SnapshotPolicy({**self.policy.body, "max_bytes": 16})
        with self.assertRaises(Denied):
            capture_fixture(self.components, small, self.folder / "too-small")
        self.assertFalse((self.folder / "too-small/manifest.json").exists())
        self.assertEqual((root / "large").read_bytes(), large)

    def test_explicit_credential_exclusion_is_recorded_and_requires_owner_relogin(self):
        component = self.components[0]
        write_new(component.root / "auth.json", b"invented credential, never printed", mode=0o600)
        cohort = (replace(component, exclusions={**component.exclusions,
            b"auth.json": {"reason": "native authentication re-established by owner", "recovery": "owner_relogin"}}), self.components[1])
        capture_fixture(cohort, policy_for(cohort), self.destination)
        row = next(row for row in self.rows() if base64.b64decode(row["path"]) == b"auth.json")
        self.assertEqual(row["exclusion"]["recovery"], "owner_relogin")
        self.assertIsNone(row["payload"])
        self.assertNotIn(b"invented credential", b"".join(p.read_bytes() for p in self.destination.rglob("*") if p.is_file()))

    def test_missing_exclusions_hardlinks_and_special_files_do_not_publish_partial_success(self):
        component = self.components[0]
        cohort = (replace(component, exclusions={**component.exclusions,
            b"missing": {"reason": "must not silently ignore a typo", "recovery": "generated"}}), self.components[1])
        with self.assertRaises(Denied):
            capture_fixture(cohort, policy_for(cohort), self.folder / "missing-rule")
        os.link(component.root / "memory.md", component.root / "hardlinked")
        with self.assertRaises(Denied):
            self.capture()
        self.assertFalse((self.destination / "manifest.json").exists())
        (component.root / "hardlinked").unlink()  # Only the invented hardlink fixture.
        os.mkfifo(component.root / "fifo", mode=0o600)
        with self.assertRaises(Denied):
            capture_fixture(self.components, self.policy, self.folder / "fifo-case")
        self.assertFalse((self.folder / "fifo-case/manifest.json").exists())

    def test_rehashed_forged_exclusion_cannot_hide_required_memory(self):
        manifest = self.capture()
        rows = self.rows()
        row = next(row for row in rows if base64.b64decode(row["path"]) == b"memory.md")
        payload, size = row["payload"], row["size"]
        row.update(kind="excluded", payload=None, size=0, digest=None,
                   exclusion={"reason": "forged omission", "recovery": "generated"})
        raw = b"".join(canonical_bytes(item) + b"\n" for item in rows)
        index = self.destination / "broker/entries.jsonl"
        index.chmod(0o600)
        index.write_bytes(raw)
        index.chmod(0o400)
        (self.destination / "broker" / payload).unlink()  # Only an invented snapshot corruption fixture.
        manifest["components"][0]["entries_digest"] = digest(raw)
        manifest["components"][0]["total_bytes"] -= size
        path = self.destination / "manifest.json"
        path.chmod(0o600)
        path.write_bytes(canonical_bytes(manifest))
        path.chmod(0o400)
        with self.assertRaisesRegex(Denied, "protected source policy"):
            self.inspect()

    def test_tampered_payload_extra_paths_and_modes_fail_inspection(self):
        self.capture()
        row = next(row for row in self.rows() if base64.b64decode(row["path"]) == b"memory.md")
        path = self.destination / "broker" / row["payload"]
        original = path.read_bytes()
        path.chmod(0o600)
        with self.assertRaises(Denied):
            self.inspect()
        path.write_bytes(b"tampered")
        path.chmod(0o400)
        with self.assertRaises(Denied):
            self.inspect()
        path.chmod(0o600)
        path.write_bytes(original)
        path.chmod(0o400)
        write_new(self.destination / "extra", b"unlisted")
        with self.assertRaises(Denied):
            self.inspect()

    def test_missing_component_and_false_encryption_activation_or_schema_claims_fail_inspection(self):
        manifest = self.capture()
        path = self.destination / "manifest.json"
        for changed in ({**manifest, "components": manifest["components"][:1]},
                        {**manifest, "scope": "full-system"}, {**manifest, "encrypted": True},
                        {**manifest, "restore_mode": "running"}, {**manifest, "schema": "future"}):
            with self.subTest(scope=changed["scope"]):
                path.chmod(0o600)
                path.write_bytes(canonical_bytes(changed))
                path.chmod(0o400)
                with self.assertRaises(Denied):
                    self.inspect()

    def test_capture_and_inspection_leave_original_files_modes_and_sql_rows_unchanged(self):
        before = {c.id: {(p.relative_to(c.root).as_posix()): (p.read_bytes(), p.stat().st_mode)
            for p in c.root.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm"))}
            for c in self.components}
        self.capture()
        self.inspect()
        after = {c.id: {(p.relative_to(c.root).as_posix()): (p.read_bytes(), p.stat().st_mode)
            for p in c.root.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm"))}
            for c in self.components}
        self.assertEqual(before, after)
        self.assertTrue(all(not db.in_transaction for c in self.components for db in c.databases.values()))

    def test_real_process_deaths_publish_only_after_final_manifest(self):
        boundaries = ("after_system_snapshot_freeze", "after_system_snapshot_database", "after_system_snapshot_entry",
                      "before_system_snapshot_manifest", "after_system_snapshot_manifest")
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                folder = self.folder / boundary
                folder.mkdir(mode=0o700)
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("system_snapshot_fault_fixture.py")),
                    str(folder), boundary], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 73, result.stderr)
                capture_root = folder / "capture"
                if boundary == "after_system_snapshot_manifest":
                    expected = policy_for(tuple(replace(c, root=folder / c.id) for c in self.components))
                    self.assertEqual(inspect_snapshot(capture_root, expected, owner_uid=os.geteuid())["cohort_id"], "fixture")
                else:
                    self.assertFalse((capture_root / "manifest.json").exists())
                for key in ("broker", "worker"):
                    with sqlite3.connect(folder / key / "state.sqlite", timeout=0) as db:
                        db.execute("INSERT INTO state VALUES ('death-released-lock',?)", (b"original retained",))


if __name__ == "__main__":
    unittest.main()
