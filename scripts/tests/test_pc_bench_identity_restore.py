import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench_restore', ROOT / 'restore_pc_bench_identity.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class BenchIdentityTests(unittest.TestCase):
    expected = {'keys/dev.pem': (4, hashlib.sha256(b'test').hexdigest())}

    def archive(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, body, kind in entries:
                entry = tarfile.TarInfo(name); entry.type = kind
                if kind == tarfile.REGTYPE:
                    entry.size = len(body); archive.addfile(entry, io.BytesIO(body))
                else:
                    entry.linkname = 'outside'; archive.addfile(entry)
        output.seek(0)
        return output

    def test_only_pinned_file_is_returned_without_extracting_siblings(self):
        source = self.archive([('oracova-bench/keys/dev.pem', b'test', tarfile.REGTYPE),
                               ('../../untrusted', b'ignored', tarfile.REGTYPE)])
        self.assertEqual(restore.gather(source, self.expected), {'keys/dev.pem': b'test'})

    def test_missing_or_wrong_contents_or_size_fail(self):
        for body in [b'evil', b'too-long']:
            with self.assertRaises(ValueError):
                restore.gather(self.archive([('oracova-bench/keys/dev.pem', body, tarfile.REGTYPE)]), self.expected)
        with self.assertRaises(ValueError):
            restore.gather(self.archive([]), self.expected)

    def test_duplicate_symlink_hardlink_and_directory_fail(self):
        good = ('oracova-bench/keys/dev.pem', b'test', tarfile.REGTYPE)
        with self.assertRaises(ValueError):
            restore.gather(self.archive([good, good]), self.expected)
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE]:
            with self.assertRaises(ValueError):
                restore.gather(self.archive([('oracova-bench/keys/dev.pem', b'', kind)]), self.expected)

    def test_original_fixed_inventory_includes_all_signing_and_enrollment_files(self):
        self.assertEqual(len(restore.FILES), 21)
        for name in ['keys/dev.pem', 'keys/operator.pem', 'keys/policy.pem',
                     'pki/nucleo1/device_ca_key.pem', 'pki/nucleo1/pouya.p12']:
            self.assertIn(name, restore.FILES)
        for size, digest in restore.FILES.values():
            self.assertGreater(size, 0); self.assertEqual(len(digest), 64)


if __name__ == '__main__': unittest.main()
