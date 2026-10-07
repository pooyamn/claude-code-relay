import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('fresh_codex', ROOT / 'pc_create_fresh_codex.py')
fresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fresh)


class EnrollmentReceiptsTests(unittest.TestCase):
    def raw(self, identity='exact', role='user', text='checkpoint'):
        return '\n'.join(json.dumps(value) for value in [
            {'type': 'session_meta', 'payload': {'id': identity}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': role,
                'content': [{'type': 'input_text', 'text': text}]}}])

    def test_checkpoint_has_exact_identity_role_and_text(self):
        self.assertTrue(fresh.checkpoint_persisted(self.raw(), 'exact', 'checkpoint'))
        for raw in (self.raw(identity='other'), self.raw(role='assistant'),
                    self.raw(text='checkpoint plus more'), self.raw(text='different')):
            self.assertFalse(fresh.checkpoint_persisted(raw, 'exact', 'checkpoint'))

    def test_checkpoint_without_native_metadata_is_rejected(self):
        self.assertFalse(fresh.checkpoint_persisted(self.raw().splitlines()[1], 'exact', 'checkpoint'))

    def test_rollout_is_bounded(self):
        with self.assertRaises(ValueError):
            fresh.checkpoint_persisted(' ' * 2_000_001, 'exact', 'checkpoint')

    def test_effect_receipt_never_overwrites_previous_attempt(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            fresh.save_new(directory, 'attempt.json', {'phase': 'attempting'})
            with self.assertRaises(FileExistsError):
                fresh.save_new(directory, 'attempt.json', {'phase': 'retry'})
            self.assertEqual(json.loads((directory / 'attempt.json').read_text()), {'phase': 'attempting'})
            self.assertEqual((directory / 'attempt.json').stat().st_mode & 0o777, 0o600)

    def test_reusing_receipt_directory_cannot_allocate_another_session(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            fresh.save_new(directory, '2-attempt.json', {'method': 'thread/start'})
            class Args:
                receipt_directory = name
            with self.assertRaises(ValueError):
                fresh.create(Args())


if __name__ == '__main__':
    unittest.main()
