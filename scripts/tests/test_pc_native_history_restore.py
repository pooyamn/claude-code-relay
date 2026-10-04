import importlib.util
import json
from contextlib import closing
from pathlib import Path
import sqlite3
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

    def make_state(self, path, enrollments=True, wal=False):
        with closing(sqlite3.connect(path)) as db:
            if wal:
                db.execute('PRAGMA journal_mode=WAL')
            db.executescript('CREATE TABLE threads(id TEXT PRIMARY KEY, content TEXT); INSERT INTO threads VALUES("same-id", "private history");')
            if enrollments:
                db.executescript('CREATE TABLE remote_control_enrollments(server_id TEXT); INSERT INTO remote_control_enrollments VALUES("mac-host"),("another-source-host");')

    def test_new_copy_excludes_registrations_preserves_source_and_histories(self):
        source = self.root / 'source.sqlite'
        self.make_state(source)
        original = source.read_bytes()
        target = self.root / 'state_5.sqlite'
        RESTORE.mirror_component(source, target, 'fixture')
        receipt = RESTORE.detach_migrated_remote_registration(target)
        self.assertEqual(receipt['copiedRemoteEnrollmentsExcluded'], 2)
        self.assertTrue(receipt['nativeReenrollmentRequired'])
        self.assertEqual(source.read_bytes(), original)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('SELECT * FROM threads').fetchall(), [('same-id', 'private history')])
            self.assertEqual(db.execute('SELECT * FROM remote_control_enrollments').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        self.assertNotIn('private history', json.dumps(receipt))

    def test_wal_changes_visible_to_later_immutable_history_reader(self):
        target = self.root / 'state_5.sqlite'
        self.make_state(target, wal=True)
        RESTORE.detach_migrated_remote_registration(target)
        with closing(sqlite3.connect(target.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM remote_control_enrollments').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT id FROM threads').fetchone()[0], 'same-id')

    def test_older_state_without_registration_table_is_preserved(self):
        target = self.root / 'state_5.sqlite'
        self.make_state(target, enrollments=False)
        original = target.read_bytes()
        self.assertEqual(RESTORE.detach_migrated_remote_registration(target)['copiedRemoteEnrollmentsExcluded'], 0)
        self.assertEqual(target.read_bytes(), original)

    def test_empty_registration_table_keeps_existing_schema(self):
        target = self.root / 'state_5.sqlite'
        self.make_state(target)
        with closing(sqlite3.connect(target)) as db:
            with db:
                db.execute('DELETE FROM remote_control_enrollments')
        self.assertEqual(RESTORE.detach_migrated_remote_registration(target)['copiedRemoteEnrollmentsExcluded'], 0)
        with closing(sqlite3.connect(target)) as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='remote_control_enrollments'").fetchone())

    def test_redirected_state_is_not_mutated(self):
        source = self.root / 'source.sqlite'
        self.make_state(source)
        original = source.read_bytes()
        target = self.root / 'state_5.sqlite'
        target.symlink_to(source)
        with self.assertRaises(ValueError):
            RESTORE.detach_migrated_remote_registration(target)
        self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
