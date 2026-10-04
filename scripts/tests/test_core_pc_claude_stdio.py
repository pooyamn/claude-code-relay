"""Operational bridge fixtures; no native CLI, credentials or live handoff."""
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import pc_claude_stdio as bridge
from relay_core.identity import Denied

SESSION = '98b493a3-a1a4-4ef2-b7da-b9bf48ece0fe'
WORKSPACE = str(bridge.WORKSPACE_ROOT / 'duts')


class PcClaudeStdioTests(unittest.TestCase):
    def test_fresh_start_requires_exact_protected_owner_manifest_and_unused_native_id(self):
        value = {'schema': 'ccrelay.personal_claude_start.v1', 'session_id': SESSION, 'workspace': WORKSPACE,
                 'source_writer': 'owner_switch', 'uncertain_actions': [], 'history': None, 'profile': str(bridge.OWNER / '.claude')}
        path = '/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-' + 'a' * 32 + '/handoff-' + SESSION + '.json'
        with mock.patch.object(bridge, 'read_pinned', return_value=(None, value)), \
                mock.patch.object(bridge.Path, 'exists', return_value=False), mock.patch.object(bridge.Path, 'is_symlink', return_value=False):
            history, metadata = bridge.checked_handoff(path, 'a' * 64, WORKSPACE, SESSION)
            self.assertTrue(str(history).endswith(SESSION + '.jsonl')); self.assertIsNone(metadata)
        for key, bad in [('source_writer', 'agent'), ('profile', '/tmp/empty-home'), ('session_id', 'other'),
                         ('history', {}), ('uncertain_actions', ['unconfirmed']), ('workspace', WORKSPACE + '-other')]:
            with self.subTest(key=key), mock.patch.object(bridge, 'read_pinned', return_value=(None, {**value, key: bad})), self.assertRaises(Denied):
                bridge.checked_handoff(path, 'a' * 64, WORKSPACE, SESSION)
        for exists, link in [(True, False), (False, True)]:
            with mock.patch.object(bridge, 'read_pinned', return_value=(None, value)), \
                    mock.patch.object(bridge.Path, 'exists', return_value=exists), mock.patch.object(bridge.Path, 'is_symlink', return_value=link), self.assertRaises(Denied):
                bridge.checked_handoff(path, 'a' * 64, WORKSPACE, SESSION)

    def test_model_is_a_literal_not_an_additional_option_or_prompt(self):
        for model in ('opus\n--continue', '--fork-session', 'opus;whoami', 'opus sonnet', 1):
            with self.subTest(model=model), mock.patch.object(bridge, 'require_owner'), mock.patch.object(bridge.subprocess, 'Popen') as launch, self.assertRaises(Denied):
                bridge.run(WORKSPACE, SESSION, '/unused', 'a' * 64, model=model)
            launch.assert_not_called()

    def test_fresh_id_appearing_after_the_lease_never_resumes_or_replaces_it(self):
        lease = mock.Mock()
        with mock.patch.object(bridge, 'require_owner'), mock.patch.object(bridge, 'attest_workspaces', return_value=mock.Mock()), \
                mock.patch.object(bridge, 'checked_handoff', return_value=(Path('/synthetic-history'), None)), \
                mock.patch.object(bridge, 'read_pinned', return_value=(None, None)), mock.patch.object(bridge, 'acquire_lease', return_value=lease), \
                mock.patch.object(bridge.Path, 'exists', return_value=True), mock.patch.object(bridge.subprocess, 'Popen') as launch, self.assertRaises(Denied):
            bridge.run(WORKSPACE, SESSION, '/synthetic-checkpoint', 'a' * 64, model='opus')
        launch.assert_not_called(); lease.close.assert_called_once()

    def handoff(self):
        return {'schema': 'ccrelay.personal_claude_handoff.v1', 'session_id': SESSION, 'workspace': WORKSPACE,
                'source_writer': 'quiesced', 'uncertain_actions': [], 'profile': str(bridge.OWNER / '.claude'),
                'history': {'path': str(bridge.OWNER / '.claude/projects' / '-Users-pouya--openclaw-workspace-duts' / (SESSION + '.jsonl')),
                            'bytes': 1234, 'sha256': 'a' * 64}}

    def test_exact_quiesced_native_handoff_and_no_fresh_session(self):
        value = self.handoff()
        self.assertEqual(str(bridge.validate_handoff(value, WORKSPACE, SESSION)), value['history']['path'])
        for key, bad in [('schema','v2'), ('session_id','other'), ('workspace',WORKSPACE+'-other'),
                         ('source_writer','running'), ('uncertain_actions',['unconfirmed-action']),
                         ('uncertain_actions',{}), ('profile','/tmp/empty-home')]:
            with self.subTest(key=key), self.assertRaises(Denied):
                bridge.validate_handoff({**value,key:bad}, WORKSPACE, SESSION)

    def test_handoff_exact_fields_and_original_target_transcript(self):
        value = self.handoff()
        for bad in ({**value,'role':'reviewer'}, {key:item for key,item in value.items() if key != 'uncertain_actions'}):
            with self.assertRaises(Denied): bridge.validate_handoff(bad, WORKSPACE, SESSION)
        for key, bad in [('path','/tmp/history.jsonl'), ('bytes',True), ('bytes',0), ('sha256','g'*64)]:
            with self.subTest(key=key), self.assertRaises(Denied):
                bridge.validate_handoff({**value,'history':{**value['history'],key:bad}}, WORKSPACE, SESSION)

    def test_protected_checkpoint_path_is_exact_and_checked_before_history_reads(self):
        for path in ('/tmp/handoff.json', '/mnt/c/Users/pou/handoff.json',
                     '/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-'+'a'*32+'/handoff-other.json'):
            with self.subTest(path=path), mock.patch.object(bridge,'read_pinned') as read, self.assertRaises(Denied):
                bridge.checked_handoff(path,'a'*64,WORKSPACE,SESSION)
            read.assert_not_called()

    def test_known_unreconciled_legacy_task_cannot_resume_with_auth(self):
        for value in ('', SESSION.upper(), 'not-a-uuid', bridge.HELD_SESSION):
            with self.subTest(session=value), self.assertRaises((Denied,ValueError)):
                bridge.launch_arguments(value)

    def test_native_arguments_keep_profile_customizations_and_exact_pin(self):
        args = bridge.launch_arguments(SESSION)
        self.assertIn('--resume='+SESSION,args)
        self.assertIn('--replay-user-messages',args)
        self.assertIn('--include-partial-messages',args)
        self.assertIn('--setting-sources=user,project,local',args)
        self.assertEqual(args[args.index('--permission-prompt-tool')+1],'stdio')
        for bad in ('--session-id','--fork-session','--continue','--safe-mode','--tools','--strict-mcp-config','--mcp-config','--model','--no-session-persistence'):
            self.assertNotIn(bad,args)
        settings = json.loads(args[args.index('--settings')+1])
        self.assertNotIn('disableAllHooks',settings)
        self.assertEqual(settings['env']['CLAUDE_CODE_RESUME_INTERRUPTED_TURN'],'0')

    def test_full_access_requires_explicit_owner_policy_not_profile_default(self):
        for full, expected in ((False,'default'), (True,'bypassPermissions')):
            args = bridge.launch_arguments(SESSION,full)
            self.assertEqual(args[args.index('--permission-mode')+1],expected)
        for value in ('false',1,None):
            with self.assertRaises(Denied): bridge.launch_arguments(SESSION,value)

    def test_kernel_lease_prevents_a_second_bridge_until_inherited_fd_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = Path(directory)
            original_lstat, original_fstat = Path.lstat, os.fstat
            def directory_metadata(path,*args,**kwargs):
                result = original_lstat(path,*args,**kwargs)
                return SimpleNamespace(st_mode=result.st_mode,st_uid=1000)
            def file_metadata(fd):
                result = original_fstat(fd)
                return SimpleNamespace(st_mode=result.st_mode,st_uid=1000,st_nlink=result.st_nlink,
                                       st_dev=result.st_dev,st_ino=result.st_ino)
            with mock.patch.object(bridge,'OWNER',owner), mock.patch.object(bridge.Path,'lstat',directory_metadata), \
                    mock.patch.object(bridge.os,'fstat',file_metadata):
                first = bridge.acquire_lease(SESSION)
                inherited = os.dup(first.fileno())
                try:
                    with self.assertRaises(BlockingIOError): bridge.acquire_lease(SESSION)
                    first.close()
                    with self.assertRaises(BlockingIOError): bridge.acquire_lease(SESSION)
                finally:
                    first.close(); os.close(inherited)
                next_owner = bridge.acquire_lease(SESSION)
                next_owner.close()

    def test_history_change_after_lease_acquisition_closes_lease_without_native_resume(self):
        before = SimpleNamespace(st_dev=1,st_ino=2,st_mode=stat.S_IFREG|0o600,st_uid=1000,st_gid=1000,
                                 st_size=123,st_mtime_ns=1,st_ctime_ns=1)
        changed = SimpleNamespace(**{**vars(before),'st_ino':3})
        lease = mock.Mock()
        with mock.patch.object(bridge,'require_owner'),mock.patch.object(bridge,'attest_workspaces',return_value=mock.Mock()), \
                mock.patch.object(bridge,'checked_handoff',return_value=(Path('/synthetic-transcript'),before)), \
                mock.patch.object(bridge,'read_pinned',return_value=(before,None)), mock.patch.object(bridge,'acquire_lease',return_value=lease), \
                mock.patch.object(bridge.Path,'lstat',return_value=changed),mock.patch.object(bridge.subprocess,'Popen') as launch,self.assertRaises(Denied):
            bridge.run(WORKSPACE,SESSION,'/synthetic-checkpoint','a'*64)
        launch.assert_not_called()
        lease.close.assert_called_once()

    def test_launch_env_never_copies_parent_tokens_or_creates_diagnostic_home(self):
        with mock.patch.dict(os.environ,{'ANTHROPIC_API_KEY':'PRIVATE-FIXTURE','CCRELAY_BOT_TOKEN':'PRIVATE-FIXTURE','WSLENV':'PRIVATE-FIXTURE',
                                       'CLAUDE_CONFIG_DIR':'/tmp/wrong-global-config'}):
            environment = bridge.launch_environment()
        self.assertEqual(environment['HOME'],str(bridge.OWNER))
        self.assertNotIn('CLAUDE_CONFIG_DIR',environment)
        self.assertFalse(set(environment)&{'ANTHROPIC_API_KEY','CCRELAY_BOT_TOKEN','WSLENV'})
        self.assertNotIn('PRIVATE-FIXTURE',json.dumps(environment))

    def test_pin_uses_same_no_follow_inode_and_strict_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'checkpoint'
            body = json.dumps(self.handoff()).encode()
            path.write_bytes(body)
            metadata,value = bridge.read_pinned(path,hashlib.sha256(body).hexdigest(),load_json=True)
            self.assertEqual(metadata.st_size,len(body))
            self.assertEqual(value,self.handoff())
            with self.assertRaises(Denied): bridge.read_pinned(path,'0'*64)
            alias = Path(directory)/'alias'; alias.symlink_to(path)
            with self.assertRaises(OSError): bridge.read_pinned(alias,hashlib.sha256(body).hexdigest())
            path.write_bytes(b'{"key":1,"key":2}')
            with self.assertRaises(Denied): bridge.read_pinned(path,hashlib.sha256(path.read_bytes()).hexdigest(),load_json=True)

    def test_handoff_size_is_bounded_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'large'
            path.write_bytes(b'x'*65537)
            with self.assertRaises(Denied): bridge.read_pinned(path,hashlib.sha256(path.read_bytes()).hexdigest(),load_json=True)

    def test_native_framing_preserves_complete_data_and_rejects_duplicate_or_invalid_utf8(self):
        frame = {'type':'user','message':{'role':'user','content':'🙂'},'session_id':SESSION}
        self.assertEqual(bridge.decode_frame(json.dumps(frame).encode()),frame)
        for body in (b'',b'[]',b'{"type":"user","type":"assistant"}',b'{"number":NaN}',b'\xff',b'x'*2_097_153):
            with self.subTest(body=body[:50]), self.assertRaises((Denied,ValueError,UnicodeError)):
                bridge.decode_frame(body)

    def test_unapproved_handoff_or_owner_fails_before_native_spawn(self):
        for gate in ('require_owner','attest_workspaces','checked_handoff'):
            with mock.patch.object(bridge,'require_owner'),mock.patch.object(bridge,'attest_workspaces'), \
                    mock.patch.object(bridge,'checked_handoff'),mock.patch.object(bridge,gate,side_effect=Denied), \
                    mock.patch.object(bridge.subprocess,'Popen') as launch,self.assertRaises(Denied):
                bridge.run(WORKSPACE,SESSION,'/tmp/not-approved','a'*64)
            launch.assert_not_called()

    def forward_fixture(self, reads, *, exited=False):
        selector = mock.Mock()
        selector.select.side_effect = [[(SimpleNamespace(fd=100 if label=='parent' else 200,data=label),None)] for label,_ in reads]
        child = SimpleNamespace(stdin=SimpleNamespace(fileno=lambda:201),stdout=SimpleNamespace(fileno=lambda:200),poll=lambda:0 if exited else None)
        workspace, native, write = mock.Mock(),mock.Mock(),mock.Mock()
        with mock.patch.object(bridge.os,'read',side_effect=[body for _,body in reads]),mock.patch.object(bridge,'write_frame',write):
            bridge.forward(selector,child,100,101,{'type':'ccrelay_claude_ready'},workspace,native,SESSION)
        return workspace,native,write

    def test_native_final_frame_is_drained_even_if_child_has_already_exited(self):
        body = b'{"type":"result","result":"complete"}\n'
        _,native,write = self.forward_fixture([('native',body),('native',b'')],exited=True)
        self.assertEqual(write.call_args_list[1].args[:2],(101,body))
        native.assert_any_call(True)
        self.assertEqual(write.call_count,2) # Ready + unchanged final frame.

    def test_parent_input_is_forwarded_once_without_new_ids_or_replay(self):
        body = json.dumps({'type':'user','session_id':SESSION,'message':{'role':'user','content':'hello'}}).encode()+b'\n'
        _,_,write = self.forward_fixture([('parent',body),('parent',b'')])
        self.assertEqual(write.call_args_list[1].args[:2],(201,body))
        self.assertEqual(write.call_count,2)

    def test_foreign_session_partial_eof_and_oversized_frame_fail_closed(self):
        for reads in ([('parent',b'{"type":"user","session_id":"other"}\n')],
                      [('native',b'{"type":"result"'),('native',b'')],
                      [('parent',b'x'*2_097_153)]):
            with self.assertRaises(Denied): self.forward_fixture(reads)

    def observation_fixture(self):
        image = SimpleNamespace(st_dev=1,st_ino=2,st_mode=stat.S_IFREG|0o700,st_uid=1000,st_gid=1000,
                                st_size=123,st_mtime_ns=1,st_ctime_ns=1)
        lease = SimpleNamespace(fileno=lambda:40)
        child = SimpleNamespace(pid=123,poll=mock.Mock(return_value=None))
        identity = SimpleNamespace(st_dev=1,st_ino=3)
        def read_text(path,*args,**kwargs):
            return 'Uid:\t1000\t1000\t1000\t1000\n' if path.name == 'status' else 'process-generation-fixture'
        def metadata(path,*args,**kwargs):
            return image if path.name == 'exe' else identity
        return image,lease,child,identity,read_text,metadata

    def test_native_observation_requires_actual_uid_image_generation_and_inherited_fd(self):
        image,lease,child,identity,read_text,metadata = self.observation_fixture()
        with mock.patch.object(bridge.Path,'read_text',read_text),mock.patch.object(bridge.Path,'stat',metadata), \
                mock.patch.object(bridge.Path,'lstat',return_value=image),mock.patch.object(bridge.os,'fstat',return_value=identity), \
                mock.patch.object(bridge,'proc_stat',return_value='10') as generation:
            observed,verify = bridge.native_observation(child,image,lease)
            self.assertEqual(observed,'10')
            verify()
            with mock.patch.object(bridge.Path,'read_text',return_value='Uid:\t0\t0\t0\t0\n'),self.assertRaises(Denied): verify()
            with mock.patch.object(bridge.Path,'stat',return_value=SimpleNamespace(st_dev=1,st_ino=99)),self.assertRaises(Denied): verify()
            with mock.patch.object(bridge.Path,'stat',side_effect=[image,SimpleNamespace(st_dev=1,st_ino=99)]),self.assertRaises(Denied): verify()
            generation.return_value = '11'
            with self.assertRaises(Denied): verify()

    def test_procfs_exit_race_allows_only_confirmed_owned_terminal_output(self):
        image,lease,child,identity,read_text,metadata = self.observation_fixture()
        with mock.patch.object(bridge.Path,'read_text',read_text),mock.patch.object(bridge.Path,'stat',metadata), \
                mock.patch.object(bridge.Path,'lstat',return_value=image),mock.patch.object(bridge.os,'fstat',return_value=identity), \
                mock.patch.object(bridge,'proc_stat',return_value='10'):
            _,verify = bridge.native_observation(child,image,lease)
            with mock.patch.object(bridge.Path,'read_text',side_effect=FileNotFoundError):
                with self.assertRaises(FileNotFoundError): verify(True) # No terminal evidence.
                child.poll.side_effect = [None,0]
                verify(True) # The original child exited during the procfs read.
                child.poll.side_effect = [None,0]
                with self.assertRaises(Denied): verify(False) # Never forward input after exit.

    def test_owned_child_cleanup_closes_input_and_never_restarts(self):
        child = SimpleNamespace(pid=123,stdin=io.BytesIO(),wait=mock.Mock(return_value=0))
        with mock.patch.object(bridge.os,'killpg') as kill:
            bridge.stop_owned(child)
        self.assertTrue(child.stdin.closed)
        child.wait.assert_called_once_with(timeout=10)
        kill.assert_not_called()

    def test_owned_cleanup_escalation_targets_only_original_child_group(self):
        child = SimpleNamespace(pid=123,stdin=io.BytesIO(),wait=mock.Mock(side_effect=[subprocess.TimeoutExpired('owned',10),subprocess.TimeoutExpired('owned',5),-9]))
        with mock.patch.object(bridge.os,'killpg') as kill:
            bridge.stop_owned(child)
        self.assertEqual(kill.call_args_list,[mock.call(123,signal.SIGTERM),mock.call(123,signal.SIGKILL)])
        self.assertTrue(child.stdin.closed)

    def test_owned_cleanup_reaps_same_child_when_group_exits_before_signal(self):
        child = SimpleNamespace(pid=123,stdin=io.BytesIO(),wait=mock.Mock(side_effect=[subprocess.TimeoutExpired('owned',10),0]))
        with mock.patch.object(bridge.os,'killpg',side_effect=ProcessLookupError) as kill:
            bridge.stop_owned(child)
        kill.assert_called_once_with(123,signal.SIGTERM)
        self.assertEqual(child.wait.call_args_list,[mock.call(timeout=10),mock.call(timeout=5)])

    def test_parent_death_guard_refuses_pid_race(self):
        libc = SimpleNamespace(prctl=mock.Mock(return_value=0))
        with mock.patch.object(bridge.ctypes,'CDLL',return_value=libc),mock.patch.object(bridge.os,'getppid',return_value=2), \
                mock.patch.object(bridge.os,'_exit',side_effect=RuntimeError) as exit_process,self.assertRaises(RuntimeError):
            bridge.child_guard(1)
        libc.prctl.assert_called_once_with(1,signal.SIGTERM,0,0,0)
        exit_process.assert_called_once_with(126)


if __name__ == '__main__':
    unittest.main()
