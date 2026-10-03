import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('native_restore', Path(__file__).parents[1] / 'restore-pc-native-histories.py')
RESTORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESTORE)


class NativeRestoreChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_tree_copy_preserves_data_and_symlinks(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'private.jsonl').write_text('private history')
        (source / 'alias').symlink_to('private.jsonl')
        target = self.root / 'target'
        receipt = RESTORE.mirror_component(source, target, 'fixture')
        self.assertEqual(receipt, RESTORE.tree_signature(source))
        self.assertEqual(receipt, RESTORE.tree_signature(target))
        self.assertTrue((target / 'alias').is_symlink())
        self.assertNotIn('private history', json.dumps(receipt))

    def test_existing_destination_and_partial_copy_are_not_overwritten(self):
        source = self.root / 'source'
        source.write_text('new')
        target = self.root / 'target'
        target.write_text('old')
        with self.assertRaises(ValueError):
            RESTORE.mirror_component(source, target, 'fixture')
        self.assertEqual(target.read_text(), 'old')
        staging = self.root / '.other.migration-fixture'
        staging.write_text('partial')
        with self.assertRaises(ValueError):
            RESTORE.mirror_component(source, self.root / 'other', 'fixture')
        self.assertEqual(staging.read_text(), 'partial')

    def test_signature_detects_same_size_corruption(self):
        source = self.root / 'source'
        source.write_bytes(b'original')
        before = RESTORE.tree_signature(source)
        source.write_bytes(b'modified')
        self.assertNotEqual(before, RESTORE.tree_signature(source))

    def test_native_summary_retains_identity_without_message_contents(self):
        thread = {'id': 'exact-id', 'cwd': '/work', 'status': {'type': 'notLoaded'},
                  'turns': [{'items': [{'type': 'userMessage', 'text': 'private'},
                                       {'type': 'agentMessage', 'text': 'private'}]}]}
        result = RESTORE.summarize_thread(thread, 'exact-id', '/work')
        self.assertEqual(result['items'], 2)
        self.assertNotIn('private', json.dumps(result))
        for key, bad in (('id', 'other'), ('cwd', '/other'), ('status', {'type': 'active'}), ('turns', [])):
            with self.assertRaises(ValueError):
                RESTORE.summarize_thread({**thread, key: bad}, 'exact-id', '/work')

    def test_client_cannot_issue_actions(self):
        rpc = RESTORE.ReadOnlyRPC.__new__(RESTORE.ReadOnlyRPC)
        for method in ('thread/resume', 'thread/start', 'turn/start', 'turn/steer', 'thread/goal/set', 'command/exec'):
            with self.assertRaises(ValueError):
                rpc.call(method, {})


if __name__ == '__main__':
    unittest.main()
