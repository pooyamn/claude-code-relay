"""Pure fresh-enrollment protocol fixtures; no native CLI or actual login."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'claude_remote_probe', Path(__file__).resolve().parents[1] / 'check-pc-claude-remote.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PcClaudeRemoteTests(unittest.TestCase):
    def control(self, directory, response):
        value = probe.DiagnosticControl.__new__(probe.DiagnosticControl)
        value.child = SimpleNamespace(stdin=io.BytesIO())
        value.state, value.session = Path(directory), 'fresh-fixture-session'
        value.sequence, value.events = 0, []
        value.buffer = bytearray(json.dumps(response).encode() + b'\n')
        value.selector = mock.Mock()
        return value

    def test_exact_fresh_remote_control_envelope_and_matched_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            control = self.control(directory, {'type': 'control_response', 'response': {
                'subtype': 'success', 'request_id': 'migration-remote-1', 'response': {'bridge_session_id': 'fresh'}}})
            self.assertEqual(control.call(probe.ENABLE_REQUEST), {'bridge_session_id': 'fresh'})
            sent = json.loads(control.child.stdin.getvalue())
            self.assertEqual(sent['request'], probe.ENABLE_REQUEST)
            self.assertNotIn('reattach_session_id', sent['request'])
            self.assertNotIn('work_secret', sent['request'])
            self.assertFalse(sent['request']['keep_session_on_exit'])

    def test_foreign_reattach_prompts_and_nondiagnostic_envelopes_are_not_written(self):
        for request in ({'subtype': 'initialize'}, {'subtype': 'interrupt'}, {'subtype': 'set_model'},
                        {**probe.ENABLE_REQUEST, 'reattach_session_id': 'existing'},
                        {**probe.ENABLE_REQUEST, 'work_secret': 'SYNTHETIC'},
                        {**probe.ENABLE_REQUEST, 'enabled': 1},
                        {**probe.ENABLE_REQUEST, 'name': 'production'}):
            with self.subTest(request=request), tempfile.TemporaryDirectory() as directory:
                control = self.control(directory, {})
                with self.assertRaises(ValueError):
                    control.call(request)
                self.assertEqual(control.child.stdin.getvalue(), b'')

    def test_rejection_mismatch_or_model_request_is_retained_without_automatic_answer(self):
        for message in ({'type': 'control_response', 'response': {'subtype': 'error', 'request_id': 'migration-remote-1'}},
                        {'type': 'control_response', 'response': {'subtype': 'success', 'request_id': 'foreign'}},
                        {'type': 'control_request', 'request': {'subtype': 'can_use_tool'}},
                        {'type': 'user', 'message': {'content': 'Synthetic unexpected prompt'}},
                        {'type': 'system', 'subtype': 'init', 'session_id': 'foreign'}):
            with self.subTest(kind=message['type']), tempfile.TemporaryDirectory() as directory:
                control = self.control(directory, message)
                with self.assertRaises(ValueError):
                    control.call({'subtype': 'initialize', 'hooks': None})
                self.assertEqual(len(control.child.stdin.getvalue().splitlines()), 1)
                self.assertEqual(json.loads((Path(directory) / 'frames.private.jsonl').read_text()), message)

    def test_only_literal_private_owner_documents_are_captured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.json'
            path.write_text('{"fixture":true}')
            path.chmod(0o600)
            original = Path.lstat
            def metadata(entry):
                value = original(entry)
                # The source fixture really belongs to this sandbox's host UID;
                # synthesize only its owner field, never read an actual profile.
                return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino, st_size=value.st_size,
                    st_mtime_ns=value.st_mtime_ns, st_ctime_ns=value.st_ctime_ns, st_mode=value.st_mode,
                    st_uid=1000, st_gid=value.st_gid, st_nlink=value.st_nlink)
            original_fstat = probe.os.fstat
            def descriptor_metadata(descriptor):
                value = original_fstat(descriptor)
                return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino, st_size=value.st_size,
                    st_mtime_ns=value.st_mtime_ns, st_ctime_ns=value.st_ctime_ns, st_mode=value.st_mode,
                    st_uid=1000, st_gid=value.st_gid, st_nlink=value.st_nlink)
            with mock.patch.object(probe.Path, 'lstat', metadata), mock.patch.object(probe.os, 'fstat', descriptor_metadata):
                self.assertEqual(probe.private_document(path), {'fixture': True})
                path.chmod(0o644)
                with self.assertRaisesRegex(ValueError, 'Private ordinary-owner'):
                    probe.private_document(path)
            alias = Path(directory) / 'alias'
            alias.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'Literal owner'):
                probe.private_document(alias)


if __name__ == '__main__':
    unittest.main()
