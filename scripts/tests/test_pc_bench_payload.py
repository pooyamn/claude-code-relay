import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('bench_payload', Path(__file__).resolve().parents[1] / 'check_pc_bench_payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


class BenchPayloadTests(unittest.TestCase):
    def value(self):
        return {'schema': 'ccrelay.personal_bench_payload.v1', 'source': '/Users/oracova/oracova-bench',
                'excludedDarwinTool': payload.EXCLUDED, 'directories': ['', 'tools'],
                'files': {'tools/probe.py': {'bytes': 4, 'sha256': hashlib.sha256(b'test').hexdigest()}}}

    def test_fixed_source_and_darwin_exclusion(self):
        value = self.value(); self.assertEqual(payload.inventory(value), value)
        for key in ['schema', 'source', 'excludedDarwinTool']:
            bad = copy.deepcopy(value); bad[key] = 'different'
            with self.assertRaises(ValueError): payload.inventory(bad)

    def test_path_escape_control_and_darwin_inventory_rejected(self):
        for path in ['../escape', '/outside', 'tools/../escape', 'tools//probe', 'tools/./probe',
                     'tools/probe\n', payload.EXCLUDED + '/bin/openocd']:
            with self.assertRaises(ValueError): payload.relative_path(path)

    def test_missing_parent_duplicates_and_nonhex_metadata_rejected(self):
        for change in ['parent', 'duplicate', 'digest', 'size']:
            value = self.value()
            if change == 'parent': value['directories'] = ['']
            if change == 'duplicate': value['directories'].append('tools')
            if change == 'digest': value['files']['tools/probe.py']['sha256'] = 'z' * 64
            if change == 'size': value['files']['tools/probe.py']['bytes'] = True
            with self.assertRaises(ValueError): payload.inventory(value)

    def test_directory_ancestry_is_complete(self):
        value = self.value(); value['directories'].append('missing/child')
        with self.assertRaises(ValueError): payload.inventory(value)

    def test_only_the_two_explicit_bench_working_roots_are_selected(self):
        value = self.value(); value['source'] = payload.SOURCE_ROOTS['supervisor-tools']
        self.assertEqual(payload.inventory(value)['source'], '/Users/oracova/supervisor-tools')
        value['source'] = '/Users/oracova'
        with self.assertRaises(ValueError): payload.inventory(value)

    @unittest.skipUnless(os.getuid() == 1000, 'PC owner fixture requires UID1000')
    def test_verified_private_copy_and_changed_file_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); os.chmod(root, 0o700)
            (root / 'tools').mkdir(mode=0o700)
            file = root / 'tools/probe.py'; file.write_bytes(b'test'); file.chmod(0o600)
            self.assertEqual(payload.verify(self.value(), root)['files'], 1)
            file.write_bytes(b'evil')
            with self.assertRaises(ValueError): payload.verify(self.value(), root)

    @unittest.skipUnless(os.getuid() == 1000, 'PC owner fixture requires UID1000')
    def test_symlink_and_public_permissions_are_not_a_private_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); os.chmod(root, 0o700)
            (root / 'tools').mkdir(mode=0o700)
            outside = root / 'original'; outside.write_bytes(b'test'); outside.chmod(0o600)
            file = root / 'tools/probe.py'; file.symlink_to(outside)
            with self.assertRaises(ValueError): payload.verify(self.value(), root)
            file.unlink(); file.write_bytes(b'test'); file.chmod(0o644)
            with self.assertRaises(ValueError): payload.verify(self.value(), root)


if __name__ == '__main__': unittest.main()
