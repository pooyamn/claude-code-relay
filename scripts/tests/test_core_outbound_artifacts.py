"""Actual bounded owner-file reads. No Telegram, credentials or provider work."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pc_native_stdio as adapter
from relay_core.identity import Denied


class OutboundArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ccrelay-artifact-test-')
        self.root = Path(self.temporary.name)
        self.file = self.root / 'photo with spaces.png'
        self.content = b'\x89PNG\r\n\x1a\n' + b'x' * 600000
        self.file.write_bytes(self.content)

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, path=None, offset=0, sha=None):
        return dict(workspace=str(self.root), path=str(path or self.file), offset=offset, sha256=sha)

    def test_actual_multichunk_read_pins_content_and_never_sends_provider_rpc(self):
        first = adapter.artifact_read(self.request(), [str(self.root)])
        second = adapter.artifact_read(self.request(offset=524288, sha=first['sha256']), [str(self.root)])
        self.assertEqual(base64.b64decode(first['data']) + base64.b64decode(second['data']), self.content)
        self.assertEqual(first['sha256'], hashlib.sha256(self.content).hexdigest())
        self.assertLess(len(first['data']), adapter.MAX_FRAME)
        response = adapter.local_artifact_response(dict(id=10, method='ccrelay/artifact/read', params=self.request()), [str(self.root)])
        self.assertEqual(response['id'], 10)
        self.assertEqual(response['result']['size'], len(self.content))
        self.assertIsNone(adapter.local_artifact_response(dict(id=1, method='thread/read'), [str(self.root)]))

    def test_outside_workspace_and_path_tricks_fail_before_open(self):
        for path in ('/etc/passwd', str(self.root) + '-other/a', str(self.root) + '/../a', str(self.root) + '//a',
                     str(self.root) + '/.git/config', str(self.root) + '/x\na', 'https://example.invalid/a'):
            with self.subTest(path=path), mock.patch.object(adapter.os, 'open') as opened, self.assertRaises(Denied):
                adapter.artifact_read(self.request(path=path), [str(self.root)])
            opened.assert_not_called()

    def test_symlink_and_hardlink_refused(self):
        symlink = self.root / 'link.png'; symlink.symlink_to(self.file)
        with self.assertRaises(OSError): adapter.artifact_read(self.request(path=symlink), [str(self.root)])
        hardlink = self.root / 'hard.png'; os.link(self.file, hardlink)
        with self.assertRaises(Denied): adapter.artifact_read(self.request(path=hardlink), [str(self.root)])

    def test_symlink_directory_refused(self):
        directory = self.root / 'directory'; directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): adapter.artifact_read(self.request(path=directory / self.file.name), [str(self.root)])

    def test_changed_file_between_chunks_rejected(self):
        first = adapter.artifact_read(self.request(), [str(self.root)])
        self.file.write_bytes(b'y' * len(self.content))
        with self.assertRaises(Denied): adapter.artifact_read(self.request(offset=524288, sha=first['sha256']), [str(self.root)])

    def test_root_generated_project_file_still_opens_as_ordinary_owner(self):
        real_fstat = adapter.os.fstat
        def root_output(descriptor):
            original = real_fstat(descriptor)
            from types import SimpleNamespace
            values = {name: getattr(original, name) for name in ('st_mode', 'st_nlink', 'st_size', 'st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns')}
            return SimpleNamespace(st_uid=0, **values)
        with mock.patch.object(adapter.os, 'fstat', side_effect=root_output):
            result = adapter.artifact_read(self.request(), [str(self.root)])
        self.assertEqual(result['sha256'], hashlib.sha256(self.content).hexdigest())

    def test_root_private_or_foreign_role_output_is_not_granted_read_access(self):
        with mock.patch.object(adapter.os, 'open', side_effect=PermissionError):
            response = adapter.local_artifact_response(dict(id=3, method='ccrelay/artifact/read', params=self.request()), [str(self.root)])
        self.assertIn('error', response)
        real_fstat = adapter.os.fstat
        def foreign_output(descriptor):
            original = real_fstat(descriptor)
            from types import SimpleNamespace
            values = {name: getattr(original, name) for name in ('st_mode', 'st_nlink', 'st_size', 'st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns')}
            return SimpleNamespace(st_uid=2000, **values)
        with mock.patch.object(adapter.os, 'fstat', side_effect=foreign_output), self.assertRaises(Denied):
            adapter.artifact_read(self.request(), [str(self.root)])

    def test_writable_empty_oversize_and_device_refused(self):
        self.file.chmod(0o666)
        with self.assertRaises(Denied): adapter.artifact_read(self.request(), [str(self.root)])
        self.file.chmod(0o600); self.file.write_bytes(b'')
        with self.assertRaises(Denied): adapter.artifact_read(self.request(), [str(self.root)])
        with self.file.open('wb') as target: target.truncate(20 * 1024 * 1024 + 1)
        with self.assertRaises(Denied): adapter.artifact_read(self.request(), [str(self.root)])
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        with self.assertRaises(Denied): adapter.artifact_read(self.request(path=fifo), [str(self.root)])

    def test_error_does_not_disconnect_transport_or_leak_path(self):
        response = adapter.local_artifact_response(dict(id=2, method='ccrelay/artifact/read', params=self.request(path='/secret/token')), [str(self.root)])
        self.assertEqual(response, dict(id=2, error=dict(code=-32602, message='Project artifact read refused')))


if __name__ == '__main__': unittest.main()
