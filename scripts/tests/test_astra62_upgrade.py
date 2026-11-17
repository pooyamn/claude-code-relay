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
