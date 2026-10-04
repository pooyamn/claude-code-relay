import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('migration_git', Path(__file__).parents[1] / 'inventory_migration_git.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def test_nested_bare_linked_and_external_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'workspace'
            root.mkdir()
            for name in ('project', 'nested/child'):
                path = root / name
                path.mkdir(parents=True)
                (path / '.git').mkdir()
            linked = root / 'linked'
            linked.mkdir()
            (linked / '.git').write_text('gitdir: ../common/worktrees/linked\n')
            bare = root / 'bare.git'
            bare.mkdir()
            (bare / 'HEAD').write_text('ref: refs/heads/main\n')
            (bare / 'objects').mkdir()
            (bare / 'refs').mkdir()
            outside = Path(temporary) / 'outside'
            (outside / '.git').mkdir(parents=True)
            (root / 'outside-link').symlink_to(outside, target_is_directory=True)
            found, problems, count = inventory.repositories(root)
            self.assertEqual({p.relative_to(root).as_posix(): kind for p, kind in found},
                             {'project': 'directory-marker', 'nested/child': 'directory-marker',
                              'linked': 'linked-marker', 'bare.git': 'bare'})
            self.assertEqual(problems, [])
            self.assertGreater(count, 4)

    def test_status_does_not_refresh_index_or_run_fsmonitor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['/usr/bin/git', 'init', '-q', str(root)], check=True)
            (root / 'tracked').write_text('before\n')
            subprocess.run(['/usr/bin/git', '-C', str(root), 'add', 'tracked'], check=True)
            index = root / '.git/index'
            before = index.read_bytes()
            metadata = index.stat()
            (root / 'tracked').write_text('after\n')
            hook = root / 'should-not-run'
            hook.write_text('#!/bin/sh\ntouch "' + str(root / 'hook-ran') + '"\n')
            hook.chmod(0o700)
            subprocess.run(['/usr/bin/git', '-C', str(root), 'config', 'core.fsmonitor', str(hook)], check=True)
            with mock.patch.dict(os.environ, {'GIT_DIR': '/not/the/repository', 'GIT_CONFIG_COUNT': '99'}):
                code, output = inventory.git(root, 'status', '--porcelain=v1', '-z')
            self.assertEqual(code, 0)
            self.assertIn(b'AM tracked\0', output)
            self.assertEqual(index.read_bytes(), before)
            self.assertEqual(index.stat().st_mtime_ns, metadata.st_mtime_ns)
            self.assertFalse((root / 'hook-ran').exists())
            self.assertFalse((root / '.git/index.lock').exists())

    def test_symlink_root_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                inventory.inventory(root / 'link')

    def test_invalid_nested_marker_never_inherits_parent_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['/usr/bin/git', 'init', '-q', str(root)], check=True)
            child = root / 'dependency'
            (child / '.git').mkdir(parents=True)
            code, output = inventory.git(child, 'rev-parse', '--git-dir')
            self.assertNotEqual(code, 0)
            self.assertEqual(output, b'')


if __name__ == '__main__':
    unittest.main()
