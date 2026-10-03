import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('history_check', Path(__file__).parents[1] / 'verify-pc-migration-histories.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
ID = '01a0ee66-b1e1-75b1-8a15-eb2e5175f6dd'


class HistoryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def history(self, rows):
        path = self.root / 'history.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def test_codex_identity_and_workspace(self):
        path = self.history([{'type': 'session_meta', 'payload': {'id': ID, 'cwd': '/work'}},
                             {'type': 'response_item', 'payload': {'private': 'not printed'}}])
        result = CHECK.inspect_history(path, 'codex', ID, '/work')
        self.assertEqual(result['records'], 2)
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(result['sha256'], CHECK.digest(path))

    def test_wrong_identity_or_workspace_fails(self):
        path = self.history([{'type': 'session_meta', 'payload': {'id': ID, 'cwd': '/other'}},
                             {'type': 'response_item'}])
        with self.assertRaises(ValueError):
            CHECK.inspect_history(path, 'codex', ID, '/work')

    def test_truncated_json_fails(self):
        path = self.root / 'partial.jsonl'
        path.write_text('{"type":"response_item"')
        with self.assertRaises(ValueError):
            CHECK.inspect_history(path, 'codex', ID, '/work')

    def test_cannot_combine_identity_and_workspace_from_different_records(self):
        path = self.history([
            {'type': 'session_meta', 'payload': {'id': ID, 'cwd': '/other'}},
            {'type': 'session_meta', 'payload': {'id': 'other', 'cwd': '/work'}},
            {'type': 'response_item'},
        ])
        with self.assertRaises(ValueError):
            CHECK.inspect_history(path, 'codex', ID, '/work')

    def test_claude_identity_and_workspace(self):
        path = self.history([{'type': 'assistant', 'sessionId': ID, 'cwd': '/work', 'message': 'private'}])
        result = CHECK.inspect_history(path, 'claude', ID, '/work')
        self.assertEqual(result['messageRecords'], 1)
        self.assertNotIn('private', json.dumps(result))

    def test_missing_pin_does_not_choose_history(self):
        self.assertIsNone(CHECK.pin(self.root / 'missing.txt'))
        path = self.root / 'invalid.txt'
        path.write_text('latest')
        with self.assertRaises(ValueError):
            CHECK.pin(path)

    def test_symlink_pin_fails(self):
        path = self.root / 'pin.txt'
        path.write_text(ID)
        link = self.root / 'link.txt'
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            CHECK.pin(link)

    def test_all_six_closed_databases_and_tamper(self):
        entries = []
        for name in sorted(CHECK.DB_NAMES):
            path = self.root / name
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute('CREATE TABLE fixture (value TEXT)')
                    db.execute('INSERT INTO fixture VALUES (?)', ('private',))
            entries.append({'name': name, 'bytes': path.stat().st_size, 'sha256': CHECK.digest(path)})
        (self.root / 'capture.json').write_text(json.dumps({'databases': entries}))
        self.assertEqual(len(CHECK.inspect_databases(self.root)), 6)
        (self.root / entries[0]['name']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            CHECK.inspect_databases(self.root)


if __name__ == '__main__':
    unittest.main()
