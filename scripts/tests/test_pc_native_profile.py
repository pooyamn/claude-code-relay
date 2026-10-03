"""Pure profile merge/private-write tests: no real logins, network or models."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import tomllib
import unittest

spec = importlib.util.spec_from_file_location('profile_activation', Path(__file__).parents[1] / 'activate-pc-native-profile.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class NativeProfile(unittest.TestCase):
    def test_codex_root_merge_preserves_model_tables_and_comments(self):
        source = '# keep\nmodel="original-model"\nsandbox_mode="read-only"\n[projects."/work"]\ntrust_level="trusted"\n[profiles.old]\napproval_policy="on-request"\n'
        result = profile.codex_settings(source).decode()
        values = tomllib.loads(result)
        self.assertEqual(values['model'], 'original-model')
        self.assertEqual(values['profiles']['old']['approval_policy'], 'on-request')
        self.assertEqual(values['projects']['/work']['trust_level'], 'trusted')
        self.assertIn('# keep', result)
        for key, value in profile.ROOT_SETTINGS.items():
            self.assertEqual(values[key], value)

    def test_claude_merge_preserves_hooks_model_and_denials(self):
        source = {'model': 'opus[1m]', 'hooks': {'UserPromptSubmit': []},
                  'permissions': {'defaultMode': 'auto', 'deny': ['fixture']},
                  'env': {'SAMPLE': 'unchanged'}, 'cleanupPeriodDays': 3650}
        result = json.loads(profile.claude_settings(source))
        self.assertEqual(result['permissions']['defaultMode'], 'bypassPermissions')
        self.assertEqual(result['permissions']['deny'], ['fixture'])
        self.assertEqual(result['model'], source['model'])
        self.assertEqual(result['hooks'], source['hooks'])
        self.assertEqual(result['cleanupPeriodDays'], 3650)
        self.assertEqual(result['env']['SAMPLE'], 'unchanged')
        self.assertEqual(result['env']['DISABLE_AUTOUPDATER'], '1')
        self.assertEqual(source['permissions']['defaultMode'], 'auto')
        self.assertNotIn('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', result['env'])

    def test_current_subscription_caches_required(self):
        codex = {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'fake', 'refresh_token': 'fake', 'account_id': 'fake'}}
        claude = {'claudeAiOauth': {'accessToken': 'fake', 'refreshToken': 'fake', 'expiresAt': int(time.time() * 1000) + 60000}}
        self.assertEqual(profile.login_documents(json.dumps(codex), json.dumps(claude)), (codex, claude))
        codex['OPENAI_API_KEY'] = 'fixture-only'
        with self.assertRaises(ValueError):
            profile.login_documents(json.dumps(codex), json.dumps(claude))
        codex.pop('OPENAI_API_KEY')
        claude['claudeAiOauth']['expiresAt'] = 1
        with self.assertRaises(ValueError):
            profile.login_documents(json.dumps(codex), json.dumps(claude))

    def test_account_merge_preserves_linux_identity_and_projects(self):
        original = {'machineID': 'linux-fixture', 'projects': {'/fixture': {'hasTrustDialogAccepted': True}}}
        account = {'emailAddress': 'fake@example.invalid'}
        result = json.loads(profile.claude_account_settings(original, account))
        self.assertEqual(result['machineID'], original['machineID'])
        self.assertEqual(result['projects'], original['projects'])
        self.assertEqual(result['oauthAccount'], account)
        self.assertFalse(result['autoUpdates'])
        self.assertNotIn('oauthAccount', original)

    def test_exclusive_private_write_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credential.fixture'
            profile.exclusive(path, b'fake')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                profile.exclusive(path, b'replacement')
            self.assertEqual(path.read_bytes(), b'fake')

    def test_redirected_input_and_destination_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir()
            (root / 'real/file').write_text('fixture')
            (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            with self.assertRaises(ValueError):
                profile.regular(root / 'link/file')
            with self.assertRaises(ValueError):
                profile.exclusive(root / 'link/new', b'fixture')


if __name__ == '__main__':
    unittest.main()
