import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
from inventory_migration_dirty import observe, status_paths


class DirtyObservationTests(unittest.TestCase):
    def test_nul_paths_include_rename_origin_and_literal_newline(self):
        self.assertEqual(status_paths(b'M  staged\0 M unstaged\0?? new\nfile\0R  renamed\0original\0'),
                         ['staged', 'unstaged', 'new\nfile', 'renamed', 'original'])

    def test_invalid_or_truncated_paths_rejected(self):
        for raw in (b' M ../../outside\0', b' M /absolute\0', b' M truncated', b'R  new\0', b'bad\0'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                status_paths(raw)

    def test_contents_links_absent_and_unenumerated_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'data').write_bytes(b'\0fixture\xff')
            (root / 'link').symlink_to('/outside/not-read')
            (root / 'directory').mkdir()
            result = observe(root, ['data', 'link', 'directory', 'missing'])
            rows = {row['name']: row for row in result['entries']}
            self.assertEqual(rows['data']['bytes'], 9)
            self.assertEqual(rows['link']['target'], '/outside/not-read')
            self.assertFalse(rows['directory']['contentsEnumerated'])
            self.assertFalse(rows['missing']['deletePcFile'])
            self.assertFalse(result['workspaceModified'])

    def test_parent_symlink_not_followed_and_bounds_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'data').write_bytes(b'large')
            (root / 'link').symlink_to(root, target_is_directory=True)
            result = observe(root, ['data', 'link/data'], max_bytes=1)
            self.assertTrue(all('error' in row for row in result['entries']))
            self.assertEqual(result['fileBytesHashed'], 0)


if __name__ == '__main__':
    unittest.main()
