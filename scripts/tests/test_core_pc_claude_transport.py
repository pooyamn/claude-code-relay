"""Credential-free mocked Claude probe; no CLI, network or host profile access."""
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'claude_transport_probe', Path(__file__).resolve().parents[1] / 'check-pc-claude-transport.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PcClaudeTransportTests(unittest.TestCase):
    @contextmanager
    def fixture(self, *, state='idle', native_uid='1000', exit_code=0, call_error=None, timed_out=False):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryFile() as stdout:
            root = Path(directory)
            child = SimpleNamespace(pid=12345, stdin=io.BytesIO(), stdout=stdout, returncode=None)
            waits = []
            def wait(timeout):
                waits.append(timeout)
                if timed_out and len(waits) == 1:
                    raise subprocess.TimeoutExpired('synthetic-native', timeout)
                child.returncode = exit_code
                return exit_code
            child.wait = wait
            child.poll = lambda: child.returncode
            control = SimpleNamespace(selector=SimpleNamespace(close=mock.Mock()), events=[])
            control.call = mock.Mock(side_effect=call_error, return_value={'session_state': state})
            context = SimpleNamespace(IdleControl=mock.Mock(return_value=control))
            image = SimpleNamespace(st_dev=1, st_ino=2)
            # These exact /proc reads are synthesized; fixture files use their
            # real sandbox paths. No host PID or binary is consulted.
            original_stat, original_read = Path.stat, Path.read_text
            def stat(path, *args, **kwargs):
                return image if str(path) == '/proc/12345/exe' else original_stat(path, *args, **kwargs)
            def read(path, *args, **kwargs):
                if str(path) == '/proc/12345/status':
                    return 'Uid:\t' + '\t'.join([native_uid] * 4) + '\n'
                return original_read(path, *args, **kwargs)
            with mock.patch.object(probe, 'pinned_binary', return_value=image), \
                    mock.patch.object(probe.os, 'getuid', return_value=1000), \
                    mock.patch.object(probe.Path, 'stat', stat), mock.patch.object(probe.Path, 'read_text', read), \
                    mock.patch.object(probe.subprocess, 'Popen', return_value=child) as launch, \
                    mock.patch.object(probe.os, 'killpg') as kill:
                yield root, context, control, launch, kill, waits

    def test_fresh_modes_initialize_only_and_never_claim_phone_acceptance(self):
        for mode in ('headless', 'headless-remote-control'):
            with self.subTest(mode=mode), self.fixture() as (root, context, control, launch, kill, waits):
                result = probe.check_mode(root, mode, context)
                control.call.assert_called_once_with('initialize')
                self.assertTrue(result['controlReadComplete'])
                self.assertFalse(result['phoneContinuityVerified'])
                self.assertFalse(result['existingConversationsResumed'])
                self.assertEqual(result['modelPromptsSent'], 0)
                self.assertEqual(waits, [10])
                kill.assert_not_called()
                args = launch.call_args.args[0]
                self.assertEqual('--remote-control' in args, mode == 'headless-remote-control')
                self.assertNotIn('--resume', args)
                self.assertNotIn('--continue', args)
                self.assertEqual(json.loads((root / mode / 'result.json').read_text()), result)

    def test_child_environment_never_inherits_credentials_or_host_home(self):
        with mock.patch.dict(probe.os.environ, {'HOME': '/private-owner', 'ANTHROPIC_API_KEY': 'SYNTHETIC',
                                              'CLAUDE_CODE_OAUTH_TOKEN': 'SYNTHETIC', 'PRIVATE_TOKEN': 'SYNTHETIC'}), \
                self.fixture() as (root, context, control, launch, kill, waits):
            probe.check_mode(root, 'headless', context)
            env = launch.call_args.kwargs['env']
            self.assertEqual(env['HOME'], str(root / 'headless/empty-owner-home'))
            self.assertEqual(env['CLAUDE_CONFIG_DIR'], env['HOME'] + '/.claude')
            self.assertNotIn('ANTHROPIC_API_KEY', env)
            self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', env)
            self.assertNotIn('PRIVATE_TOKEN', env)
            self.assertNotIn('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', env)
            self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_reusing_an_attempt_never_launches_again(self):
        with self.fixture() as (root, context, control, launch, kill, waits):
            probe.check_mode(root, 'headless', context)
            with self.assertRaises(FileExistsError):
                probe.check_mode(root, 'headless', context)
            launch.assert_called_once()

    def test_nonowner_native_child_is_reaped_without_control_or_model_input(self):
        with self.fixture(native_uid='0') as (root, context, control, launch, kill, waits):
            result = probe.check_mode(root, 'headless', context)
            context.IdleControl.assert_not_called()
            self.assertEqual(result['failureType'], 'ValueError')
            self.assertFalse(result['controlReadComplete'])
            self.assertTrue(result['nativeStopped'])

    def test_nonidle_initialization_is_not_accepted(self):
        with self.fixture(state='working') as (root, context, control, launch, kill, waits):
            result = probe.check_mode(root, 'headless', context)
            self.assertFalse(result['initialized'])
            self.assertFalse(result['controlReadComplete'])
            self.assertTrue(result['nativeStopped'])
            control.call.assert_called_once_with('initialize')

    def test_failed_control_retains_failure_and_does_not_retry(self):
        with self.fixture(call_error=ValueError('Synthetic rejected control')) as (root, context, control, launch, kill, waits):
            result = probe.check_mode(root, 'headless', context)
            self.assertFalse(result['controlReadComplete'])
            self.assertIn('Synthetic rejected control', (root / 'headless/failure.private.txt').read_text())
            control.call.assert_called_once_with('initialize')
            launch.assert_called_once()

    def test_nonzero_exit_is_not_a_completed_measurement(self):
        with self.fixture(exit_code=7) as (root, context, control, launch, kill, waits):
            result = probe.check_mode(root, 'headless', context)
            self.assertTrue(result['initialized'])
            self.assertFalse(result['controlReadComplete'])
            self.assertEqual(result['nativeExitCode'], 7)

    def test_only_owned_child_group_is_terminated_after_measured_exit_timeout(self):
        with self.fixture(exit_code=-15, timed_out=True) as (root, context, control, launch, kill, waits):
            result = probe.check_mode(root, 'headless', context)
            kill.assert_called_once_with(12345, signal.SIGTERM)
            self.assertEqual(waits, [10, 5])
            self.assertFalse(result['controlReadComplete'])
            self.assertTrue(result['nativeStopped'])

    def test_pin_reads_same_no_follow_image_and_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic-native'
            body = b'Inert native identity fixture; never executed'
            path.write_bytes(body)
            with mock.patch.object(probe, 'BINARY', path), \
                    mock.patch.object(probe, 'BINARY_SHA256', hashlib.sha256(body).hexdigest()):
                self.assertEqual(probe.pinned_binary().st_ino, path.lstat().st_ino)
                path.write_bytes(body + b'changed')
                with self.assertRaisesRegex(ValueError, 'Pinned native Claude'):
                    probe.pinned_binary()
            alias = Path(directory) / 'alias'
            alias.symlink_to(path)
            with mock.patch.object(probe, 'BINARY', alias), self.assertRaises(OSError):
                probe.pinned_binary()


if __name__ == '__main__':
    unittest.main()
