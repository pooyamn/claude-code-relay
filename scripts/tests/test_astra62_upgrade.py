import unittest
from pathlib import Path
from unittest import mock
import upgrade_codex_astra62_20261117 as upgrade


class UpgradeTests(unittest.TestCase):
    def thread(self, model='gpt-6-astra', state='idle', tid='existing-topic'):
        return {'id': tid, 'model': model, 'status': {'type': state},
                'cwd': '/Users/pouya/.openclaw/workspace/example'}

    def test_migrates_astra_without_touching_permissions_or_reasoning(self):
        self.assertEqual(upgrade.changes(self.thread()), {
            'threadId': 'existing-topic', 'model': 'gpt-6.2-astra', 'serviceTier': 'default'})

    def test_preserves_other_model_roles(self):
        for model in ['gpt-6.1-sol', 'gpt-6.1-terra', 'gpt-6-luna']:
            self.assertIsNone(upgrade.changes(self.thread(model=model)))

    def test_no_duplicate_settings_write_for_target(self):
        self.assertIsNone(upgrade.changes(self.thread(model=upgrade.MODEL)))

    def test_does_not_interrupt_active_topics(self):
        with self.assertRaises(RuntimeError):
            upgrade.changes(self.thread(state='active'))

    def test_controller_changes_subsequent_turn_default_only(self):
        self.assertEqual(upgrade.changes(self.thread(model='gpt-6.1-sol', state='active',
                                                   tid=upgrade.CONTROLLER))['model'], upgrade.MODEL)

    def test_rejects_unexpected_workspace(self):
        thread = self.thread(); thread['cwd'] = '/tmp/other'
        with self.assertRaises(RuntimeError):
            upgrade.changes(thread)

    def test_connector_and_supervisor_keep_the_same_exact_image_pin(self):
        repository = Path(__file__).resolve().parents[2]
        for relative in ('scripts/pc_native_stdio.py', 'pc-router/codex-wsl-host.ps1',
                         'pc-router/KhadangRouter/LinuxCodexRuntime.cs'):
            self.assertIn(upgrade.DIGEST, (repository / relative).read_text())

    def test_package_activation_refuses_a_different_previous_release(self):
        with mock.patch.object(upgrade.os, 'getuid', return_value=1000), \
             mock.patch.object(upgrade.os, 'geteuid', return_value=1000), \
             mock.patch.object(upgrade.Path, 'is_symlink', return_value=True), \
             mock.patch.object(upgrade.os, 'readlink', return_value='/unreviewed'), \
             mock.patch.object(upgrade.os, 'replace') as replace:
            with self.assertRaisesRegex(RuntimeError, 'previous managed package'):
                upgrade.activate_package()
            replace.assert_not_called()

    def test_package_activation_checks_all_copied_files_not_just_codex(self):
        with mock.patch.object(upgrade.os, 'getuid', return_value=1000), \
             mock.patch.object(upgrade.os, 'geteuid', return_value=1000), \
             mock.patch.object(upgrade.Path, 'is_symlink', return_value=True), \
             mock.patch.object(upgrade.os, 'readlink', return_value=str(upgrade.PREVIOUS)), \
             mock.patch.object(upgrade, 'package_inventory', side_effect=[
                 {'bin/codex': upgrade.DIGEST, 'resource': 'reviewed'},
                 {'bin/codex': upgrade.DIGEST, 'resource': 'changed'}]), \
             mock.patch.object(upgrade.os, 'replace') as replace:
            with self.assertRaisesRegex(RuntimeError, 'package copy differs'):
                upgrade.activate_package()
            replace.assert_not_called()

    def test_unloaded_topics_are_verified_by_identity_not_loaded_count(self):
        expected = [self.thread(tid=str(index)) for index in range(11)]
        actual = [dict(item, status={'type': 'notLoaded'}) for item in expected]
        upgrade.validate_snapshot(actual, expected, require_idle=True)

    def test_unloaded_topic_with_changed_workspace_is_rejected(self):
        previous = self.thread()
        actual = dict(previous, cwd='/tmp/unexpected', status={'type': 'notLoaded'})
        with self.assertRaises(RuntimeError):
            upgrade.validate_snapshot([actual], [previous], require_idle=True)

    def test_missing_saved_topic_is_rejected(self):
        with self.assertRaises(RuntimeError):
            upgrade.validate_snapshot([], [self.thread()])

    def test_active_unrelated_thread_blocks_restart(self):
        saved = self.thread()
        active = self.thread(tid='unrelated', state='active')
        with self.assertRaisesRegex(RuntimeError, 'still active'):
            upgrade.validate_snapshot([saved, active], [saved], require_idle=True)

    def test_model_restoration_is_verified_not_assumed(self):
        saved = self.thread(model=upgrade.MODEL)
        with self.assertRaisesRegex(RuntimeError, 'selection differs'):
            upgrade.validate_snapshot([self.thread()], [saved], require_models=True)

    def test_inspection_of_unloaded_astra_topic_never_attempts_a_write(self):
        native = mock.Mock()
        native.threads.return_value = [self.thread(state='notLoaded')]
        native.call.side_effect = [{'data': [{'model': upgrade.MODEL}]}, {'status': 'connected'}]
        with mock.patch.object(upgrade, 'Native', return_value=native):
            result = upgrade.run('inspect')
        self.assertEqual(result['threads'][0]['status']['type'], 'notLoaded')
        self.assertEqual([call.args[0] for call in native.call.call_args_list],
                         ['model/list', 'remoteControl/status/read'])
