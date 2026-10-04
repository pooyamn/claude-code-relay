import hashlib
import io
import json
import os
from pathlib import Path
import socket
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.stream_owner_tools import capture, verify, DigestReader


class OwnerToolsStreamTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="owner-tools-stream-fixture-")
        self.root = Path(self.scratch.name)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        (self.source / ".config").mkdir()
        self.file = self.source / ".config" / "private.txt"
        self.file.write_bytes(b"\x00private-fixture\xff\n")
        self.file.chmod(0o600)
        os.utime(self.file, ns=(1750000000123456789, 1750000000123456789))

    def tearDown(self):
        self.scratch.cleanup()  # Only the generated fixture tree.

    def capture(self, **kwargs):
        output = io.BytesIO()
        report = capture(self.source, output, owner_uid=os.getuid(), members=(".config",), **kwargs)
        self.assertEqual(report["sha256"], hashlib.sha256(output.getvalue()).hexdigest())
        self.assertEqual(report["bytes"], len(output.getvalue()))
        path = self.root / "capture.tar.gz"
        with path.open("wb") as target:
            target.write(output.getvalue())
        return path, report

    def rewrite(self, path, change):
        with tarfile.open(path, "r:gz") as archive:
            records = [(member, archive.extractfile(member).read() if member.isfile() else None) for member in archive]
        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for member, data in records:
                if member.name == "capture.json":
                    manifest = json.loads(data)
                    change(manifest)
                    data = json.dumps(manifest).encode()
                    member.size = len(data)
                archive.addfile(member, io.BytesIO(data) if data is not None else None)

    def test_socket_metadata_files_links_and_independent_verification(self):
        (self.source / ".config" / "external").symlink_to("/not/a/real/target")
        os.link(self.file, self.source / ".config" / "hardcopy")
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(self.source / ".config" / "live.sock"))
        before = self.file.read_bytes()
        try:
            path, report = self.capture()
            checked = verify(path)
            self.assertTrue(checked["verified"])
            self.assertEqual(checked["socketCount"], 1)
            self.assertEqual(checked["fileBytes"], 2 * len(before))
            self.assertFalse(checked["socketKernelStatePreserved"])
            self.assertFalse(checked["extractedToFilesystem"])
            self.assertFalse(checked["activeProfileChanged"])
            self.assertFalse(report["consistentFinalSnapshot"])
            with tarfile.open(path, "r:gz") as archive:
                manifest = json.load(archive.extractfile("capture.json"))
                self.assertNotIn(".config/live.sock", archive.getnames())
                rows = {r["name"]: r for r in manifest["entries"]}
                self.assertEqual(rows[".config/live.sock"]["representation"], "metadata-only")
                self.assertEqual(rows[".config/private.txt"]["mtimeNs"], 1750000000123456789)
                self.assertEqual(rows[".config/private.txt"]["sourceInode"], rows[".config/hardcopy"]["sourceInode"])
                self.assertEqual(archive.extractfile(".config/private.txt").read(), before)
                self.assertEqual(archive.extractfile(".config/hardcopy").read(), before)
            self.assertEqual(self.file.read_bytes(), before)
            self.assertTrue((self.source / ".config" / "live.sock").is_socket())
            self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["capture.tar.gz", "source"])
        finally:
            endpoint.close()

    def test_unknown_special_file_not_omitted(self):
        os.mkfifo(self.source / ".config" / "pipe")
        with self.assertRaisesRegex(ValueError, "unsupported source object"):
            self.capture()

    def test_missing_source_member_fails(self):
        with self.assertRaises(FileNotFoundError):
            capture(self.source, io.BytesIO(), owner_uid=os.getuid(), members=("missing",))

    def test_symlink_root_not_followed(self):
        link = self.root / "alias"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "literal owner"):
            capture(link, io.BytesIO(), owner_uid=os.getuid(), members=(".config",))

    def test_symlink_directory_is_not_traversed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret").write_text("not selected")
        (self.source / ".config" / "alias").symlink_to(outside, target_is_directory=True)
        path, _ = self.capture()
        self.assertTrue(verify(path)["verified"])
        with tarfile.open(path, "r:gz") as archive:
            self.assertNotIn(".config/alias/secret", archive.getnames())
            self.assertTrue(archive.getmember(".config/alias").issym())

    def test_content_mutation_during_read_rejected(self):
        original = DigestReader.read
        changed = False
        def mutate(reader, size):
            nonlocal changed
            value = original(reader, size)
            if not changed:
                changed = True
                self.file.write_bytes(b"changed fixture")
            return value
        with patch.object(DigestReader, "read", mutate):
            with self.assertRaisesRegex(ValueError, "file changed"):
                self.capture()

    def test_entry_archive_manifest_file_and_deadline_bounds(self):
        for bound in ({"max_entries": 1}, {"max_archive": 1}, {"max_manifest": 1},
                      {"max_file_bytes": 1}, {"timeout_seconds": 0}):
            with self.assertRaises(ValueError):
                self.capture(**bound)

    def test_unsafe_or_duplicate_source_selection_rejected(self):
        for members in (("../outside",), ("/outside",), (".config", ".config"), ("capture.json",)):
            with self.assertRaises(ValueError):
                capture(self.source, io.BytesIO(), owner_uid=os.getuid(), members=members)

    def test_manifest_file_digest_mismatch_rejected(self):
        path, _ = self.capture()
        self.rewrite(path, lambda m: m["entries"][-1].update(sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "differ"):
            verify(path)

    def test_false_final_snapshot_claim_rejected(self):
        path, _ = self.capture()
        self.rewrite(path, lambda m: m.update(consistentFinalSnapshot=True))
        with self.assertRaisesRegex(ValueError, "incompatible"):
            verify(path)

    def test_unsafe_target_and_nonportable_socket_claim_rejected(self):
        path, _ = self.capture()
        self.rewrite(path, lambda m: m["entries"][-1].update(name="../private.txt"))
        with self.assertRaises(ValueError):
            verify(path)
        path, _ = self.capture()
        self.rewrite(path, lambda m: m.update(socketKernelStatePreserved=True))
        with self.assertRaisesRegex(ValueError, "incompatible"):
            verify(path)

    def test_target_logical_byte_bound(self):
        path, _ = self.capture()
        with self.assertRaisesRegex(ValueError, "logical file byte bound"):
            verify(path, max_file_bytes=1)


if __name__ == "__main__":
    unittest.main()
