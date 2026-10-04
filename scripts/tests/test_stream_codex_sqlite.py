import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

from scripts.stream_codex_sqlite import inspect_blob, stream_snapshot, verify_archive


class MemorySqliteStreamTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="codex-memory-snapshot-fixture-")
        self.root = Path(self.scratch.name)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)

    def tearDown(self):
        self.scratch.cleanup()  # ONLY generated fixture files, never a real capture root.

    def database(self, name="state_5.sqlite", wal=True, page_size=4096):
        connection = sqlite3.connect(self.source / name)
        connection.execute("PRAGMA page_size=" + str(page_size))
        if wal:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE facts(value TEXT)")
        connection.execute("INSERT INTO facts VALUES('committed WAL fixture')")
        connection.commit()
        return connection

    def capture(self, **kwargs):
        stream = io.BytesIO()
        report = stream_snapshot(self.source, stream, owner_uid=os.getuid(), **kwargs)
        self.assertEqual(report["sha256"], hashlib.sha256(stream.getvalue()).hexdigest())
        self.assertEqual(report["bytes"], len(stream.getvalue()))
        return stream.getvalue(), report

    def test_live_committed_wal_rows_and_source_preserved(self):
        c = self.database()
        try:
            self.assertGreater((self.source / "state_5.sqlite-wal").stat().st_size, 0)
            archive, report = self.capture()
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
                blob = tar.extractfile("state_5.sqlite").read()
                manifest = json.load(tar.extractfile("capture.json"))
            digest = hashlib.sha256(blob).hexdigest()
            inspect_blob(blob)
            self.assertEqual(digest, hashlib.sha256(blob).hexdigest())
            copy = sqlite3.connect(":memory:")
            try:
                copy.deserialize(blob[:18] + b"\x01\x01" + blob[20:])
                self.assertEqual(copy.execute("SELECT value FROM facts").fetchone()[0], "committed WAL fixture")
            finally:
                copy.close()
            self.assertEqual(c.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 1)
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertTrue(manifest["consistentPerDatabase"])
            self.assertFalse(manifest["sourceWritersStopped"])
            self.assertFalse(report["consistentFinalSnapshot"])
            self.assertFalse(report["sourceTemporaryDatabaseFiles"])
            self.assertEqual(list(self.root.iterdir()), [self.source])
        finally:
            c.close()

    def test_nondefault_page_size_and_closed_wal(self):
        c = self.database(page_size=8192)
        c.close()
        archive, _ = self.capture()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            inspect_blob(tar.extractfile("state_5.sqlite").read())

    def test_independent_target_verification_no_filesystem_extraction(self):
        c = self.database(wal=False)
        try:
            archive, _ = self.capture()
            path = self.root / "fixture.tar.gz"
            with path.open("xb") as output:
                output.write(archive)
            before = sorted(p.name for p in self.root.iterdir())
            checked = verify_archive(path)
            self.assertTrue(checked["verified"])
            self.assertFalse(checked["extractedToFilesystem"])
            self.assertFalse(checked["activeProfileChanged"])
            self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))
        finally:
            c.close()

    def test_database_and_total_byte_bounds(self):
        c = self.database()
        try:
            for bounds in ({"max_database_bytes": 4096}, {"max_total_bytes": 4096}, {"timeout_seconds": 0}):
                with self.assertRaises(ValueError):
                    self.capture(**bounds)
        finally:
            c.close()

    def test_symlink_source_and_database_are_not_followed(self):
        c = self.database()
        c.close()
        (self.root / "alias").symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            stream_snapshot(self.root / "alias", io.BytesIO(), owner_uid=os.getuid())
        (self.source / "queue_1.sqlite").symlink_to(self.source / "state_5.sqlite")
        with self.assertRaises(ValueError):
            self.capture()

    def test_hardlink_and_empty_source_rejected(self):
        with self.assertRaises(ValueError):
            self.capture()
        c = self.database()
        c.close()
        os.link(self.source / "state_5.sqlite", self.root / "alias.sqlite")
        with self.assertRaises(ValueError):
            self.capture()

    def test_unsafe_archive_members_and_corrupt_images_rejected(self):
        for name, kind in (("../state.sqlite", tarfile.REGTYPE), ("state.sqlite", tarfile.SYMTYPE)):
            path = self.root / ("bad-" + str(kind[0]) + ".tar.gz")
            with tarfile.open(path, mode="w:gz") as tar:
                member = tarfile.TarInfo(name)
                member.mode, member.type = 0o600, kind
                tar.addfile(member)
            with self.assertRaises(ValueError):
                verify_archive(path)
        with self.assertRaises(ValueError):
            inspect_blob(b"not sqlite")

    def test_target_manifest_digest_mismatch_rejected(self):
        c = self.database()
        try:
            archive, _ = self.capture()
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as original:
                members = [(m, original.extractfile(m).read()) for m in original]
            path = self.root / "mismatched.tar.gz"
            with tarfile.open(path, mode="w:gz") as tar:
                for member, value in members:
                    if member.name == "capture.json":
                        manifest = json.loads(value)
                        manifest["databases"][0]["sha256"] = "0" * 64
                        value = json.dumps(manifest).encode()
                        member.size = len(value)
                    tar.addfile(member, io.BytesIO(value))
            with self.assertRaises(ValueError):
                verify_archive(path)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
