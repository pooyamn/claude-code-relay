import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('migration_tree', Path(__file__).parents[1] / 'inventory_migration_tree.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TreeInventoryTests(unittest.TestCase):
    def test_ignored_nested_binary_and_external_link_are_included_without_following(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / '.ignored').mkdir()
            (root / '.ignored/data\n.bin').write_bytes(b'\0private\xff')
            (root / 'external').symlink_to('/etc', target_is_directory=True)
            rows = module.tree(root)
            self.assertEqual(rows['problems'], [])
            self.assertEqual({r['name'] for r in rows['entries']}, {'.ignored', '.ignored/data\n.bin', 'external'})
            self.assertFalse(rows['fileContentsHashed'])

    def test_same_size_is_never_claimed_as_same_contents_and_missing_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as scratch:
            source, target = Path(scratch) / 'source', Path(scratch) / 'target'
            source.mkdir(); target.mkdir()
            (source / 'same-size').write_text('old')
            (target / 'same-size').write_text('new')
            (source / 'missing').write_text('preserve')
            result = module.compare(module.tree(source), target)
            self.assertEqual(result['sameTypeAndSizeUnverified'], ['same-size'])
            self.assertEqual(len(result['missing']), 1)
            self.assertFalse(result['fileContentsVerified'])
            self.assertFalse(result['targetModified'])

    def test_symlink_ancestor_in_target_is_not_followed(self):
        with tempfile.TemporaryDirectory() as scratch:
            source, target = Path(scratch) / 'source', Path(scratch) / 'target'
            source.mkdir(); target.mkdir(); (source / 'nested').mkdir()
            (source / 'nested/file').write_bytes(b'x')
            (target / 'nested').symlink_to(source / 'nested', target_is_directory=True)
            result = module.compare(module.tree(source), target)
            self.assertEqual(len(result['different']), 1)
            self.assertEqual(len(result['errors']), 1)

    def test_bounds_duplicates_and_unsafe_root_fail(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch); (root / 'one').write_bytes(b'1'); (root / 'two').write_bytes(b'2')
            with self.assertRaises(TimeoutError): module.tree(root, max_entries=1)
            with self.assertRaises(TimeoutError): module.tree(root, timeout_seconds=0)
            source = module.tree(root); source['entries'].append(source['entries'][0])
            with self.assertRaises(ValueError): module.compare(source, root)
            with self.assertRaises(ValueError): module.tree(root / '..' / root.name)

    def test_candidate_content_comparison_uses_hash_not_size_and_never_deletes(self):
        source = {'entries': [{'name': 'changed', 'kind': 'file', 'bytes': 3, 'sha256': 'old'},
                              {'name': 'gone', 'kind': 'absent'},
                              {'name': 'link', 'kind': 'symlink', 'target': '/Mac/path'},
                              {'name': 'failed', 'error': 'PermissionError'}]}
        target = {'entries': [{'name': 'changed', 'kind': 'file', 'bytes': 3, 'sha256': 'new'},
                              {'name': 'gone', 'kind': 'file', 'bytes': 1, 'sha256': 'keep'},
                              {'name': 'link', 'kind': 'symlink', 'target': '/PC/path'},
                              {'name': 'failed', 'kind': 'absent'}]}
        result = module.leaf_differences(source, target)
        self.assertEqual([r['name'] for r in result['differentOrMissing']], ['changed', 'link'])
        self.assertEqual(result['sourceAbsent'][0]['name'], 'gone')
        self.assertEqual(len(result['errors']), 1)


if __name__ == '__main__':
    unittest.main()
