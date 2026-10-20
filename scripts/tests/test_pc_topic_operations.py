"""Local-operation denial/receipt tests; no Telegram, native daemon or models."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import pc_native_stdio as adapter
from relay_core.identity import Denied


class TopicOperationsTests(unittest.TestCase):
    def test_prepare_rejects_unbounded_paths_before_effects(self):
        for value in ['/tmp/demo', str(adapter.WORKSPACE_ROOT), str(adapter.WORKSPACE_ROOT) + '/../escape',
                      str(adapter.WORKSPACE_ROOT) + '/nested/child', str(adapter.WORKSPACE_ROOT) + '/.codex']:
            with self.subTest(value=value), mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter.os, 'mkdir') as mkdir:
                with self.assertRaises(Denied):
                    adapter.prepare_workspace({'workspace': value}, ['existing'])
                mkdir.assert_not_called()

    def test_prepare_admits_only_after_actual_denial_verifier(self):
        workspaces = ['existing']; target = str(adapter.WORKSPACE_ROOT) + '/new-project'
        verify = mock.Mock()
        with mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter, 'attest_workspaces', return_value=verify) as attest, \
                mock.patch.object(adapter.os, 'open', return_value=99), mock.patch.object(adapter.os, 'close'), mock.patch.object(adapter.os, 'mkdir') as mkdir:
            observed_verify, result = adapter.prepare_workspace({'workspace': target}, workspaces)
            self.assertEqual(workspaces, ['existing', target])
            self.assertIs(observed_verify, verify)
            self.assertTrue(result['credentialDenied'])
            mkdir.assert_called_once_with('new-project', mode=0o700, dir_fd=99)
            self.assertEqual(attest.call_count, 2)
        workspaces = ['existing']
        with mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter, 'attest_workspaces', side_effect=[verify, Denied('denial failed')]), \
                mock.patch.object(adapter.os, 'open', return_value=99), mock.patch.object(adapter.os, 'close'), mock.patch.object(adapter.os, 'mkdir'):
            with self.assertRaises(Denied): adapter.prepare_workspace({'workspace': target}, workspaces)
            self.assertEqual(workspaces, ['existing'])

    @unittest.skipUnless(hasattr(os, 'getuid') and os.getuid() == 1000, 'Pinned Linux owner fixture')
    def test_checkpoint_requires_exact_owner_history_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(adapter, 'OWNER', Path(temp)), mock.patch.object(adapter, 'require_owner'):
            thread = '01a158ac-b686-7011-b706-8549a7f8e6d2'; workspace = 'project'
            root = Path(temp) / '.codex/sessions/2026/10/20'; root.mkdir(parents=True)
            path = root / ('rollout-test-' + thread + '.jsonl')
            values = [dict(type='session_meta', payload=dict(id=thread, cwd=workspace)), dict(type='response_item',
                payload=dict(type='message', role='user', content=[dict(type='input_text', text='checkpoint')]))]
            path.write_text('\n'.join(json.dumps(v) for v in values))
            params = dict(workspace=workspace, threadId=thread, path=str(path), checkpoint='checkpoint')
            self.assertTrue(adapter.verify_checkpoint(params, [workspace])['persisted'])
            with self.assertRaises(Denied): adapter.verify_checkpoint(dict(params, checkpoint='different'), [workspace])
            moved = path.with_suffix('.saved'); path.rename(moved); path.symlink_to(moved)
            with self.assertRaises(OSError): adapter.verify_checkpoint(params, [workspace])

    @unittest.skipUnless(hasattr(os, 'getuid') and os.getuid() == 1000, 'Pinned Linux owner fixture')
    def test_catalog_append_is_idempotent_and_never_repoints_existing(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(adapter, 'OWNER', Path(temp)), mock.patch.object(adapter, 'require_owner'):
            root = Path(temp) / '.config/ccrelay'; root.mkdir(parents=True, mode=0o700)
            original = dict(Alias='original', Chat=-100123, Topic=42, ThreadId='original')
            path = root / 'pc-topics.json'; path.write_text(json.dumps(dict(schema='ccrelay.pc_topics.v1', bindings=[original])))
            entry = dict(Chat=-100123, Topic=777, Name='Fixture', Workspace='project/fixture',
                         ThreadId='01a158ac-b686-7011-b706-8549a7f8e6d2', Backend='codex', Runtime='linux')
            self.assertTrue(adapter.add_catalog_binding(entry, [entry['Workspace']])['published'])
            first = path.read_bytes()
            self.assertTrue(adapter.add_catalog_binding(entry, [entry['Workspace']])['published'])
            self.assertEqual(first, path.read_bytes())
            self.assertEqual(json.loads(first)['bindings'][0], original)
            with self.assertRaises(Denied): adapter.add_catalog_binding(dict(entry, ThreadId='01a158ac-b686-7011-b706-8549a7f8e6d3'), [entry['Workspace']])
            self.assertEqual(first, path.read_bytes())


if __name__ == '__main__': unittest.main()
