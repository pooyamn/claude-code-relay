"""Migration adapter path/owner gates only; never touch a native socket/profile."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import pc_native_stdio as adapter
from relay_core.identity import Denied


class PcNativeStdioTests(unittest.TestCase):
    @contextmanager
    def workspace_fixture(self):
        path = adapter.WORKSPACE_ROOT / 'fixture-repo'
        def metadata(candidate):
            uid = 1000 if candidate == adapter.OWNER or adapter.OWNER in candidate.parents else 0
            return SimpleNamespace(st_mode=stat.S_IFDIR | (0o700 if candidate == adapter.OWNER else 0o755),
                                   st_uid=uid, st_gid=uid, st_dev=1, st_ino=len(str(candidate)))
        entries = {candidate: metadata(candidate) for candidate in [path, *path.parents]}
        with mock.patch.object(adapter.Path, 'lstat', lambda candidate: entries[candidate]), \
                mock.patch.object(adapter.os, 'open', side_effect=PermissionError) as opened:
            yield path, entries, opened

    def test_operational_workspace_and_actual_denial_without_native_connection(self):
        with self.workspace_fixture() as (path, entries, opened):
            verify = adapter.attest_workspaces([str(path)])
            verify()
            opened.assert_called_once_with(adapter.CREDENTIAL, adapter.os.O_RDONLY | adapter.os.O_CLOEXEC)
            entries[path].st_ino += 1
            with self.assertRaisesRegex(Denied, 'directory identity changed'):
                verify()

    def test_failed_denial_closes_without_reading_credential_bytes(self):
        with self.workspace_fixture() as (path, entries, opened), \
                mock.patch.object(adapter.os, 'close') as closed, mock.patch.object(adapter.os, 'read') as read:
            opened.side_effect = None
            opened.return_value = 456
            with self.assertRaisesRegex(Denied, 'can open'):
                adapter.attest_workspaces([str(path)])
            closed.assert_called_once_with(456)
            read.assert_not_called()

    def test_missing_credential_is_not_a_denial_proof(self):
        with self.workspace_fixture() as (path, entries, opened):
            opened.side_effect = FileNotFoundError
            with self.assertRaises(FileNotFoundError):
                adapter.attest_workspaces([str(path)])

    def test_all_workspace_ancestors_are_literal_and_have_expected_ownership(self):
        for bad_kind in ('symlink', 'writable', 'wrong-owner', 'public-home'):
            with self.workspace_fixture() as (path, entries, opened):
                candidate = adapter.OWNER if bad_kind == 'public-home' else path
                if bad_kind == 'symlink': entries[candidate].st_mode = stat.S_IFLNK | 0o777
                elif bad_kind == 'writable': entries[candidate].st_mode |= 0o020
                elif bad_kind == 'wrong-owner': entries[candidate].st_uid = 0
                else: entries[candidate].st_mode |= 0o005
                with self.subTest(kind=bad_kind), self.assertRaises(Denied):
                    adapter.attest_workspaces([str(path)])
                opened.assert_not_called()

    def test_operational_workspaces_are_exact_unique_bounded_original_paths(self):
        value = str(adapter.WORKSPACE_ROOT / 'repo')
        for values in ([], [value, value], ['/tmp/repo'], [value + '/..'], [value + '/'],
                       [value.replace('/workspace/', '/workspace//')], [value + '\n'],
                       [value + str(n) for n in range(257)]):
            with self.subTest(values=values[:2]), mock.patch.object(adapter.Path, 'lstat') as observe, self.assertRaises(Denied):
                adapter.attest_workspaces(values)
            observe.assert_not_called()

    def test_operational_bridge_never_accepts_an_isolated_diagnostic_socket(self):
        value = '/Users/pouya/.migration/native-transport-' + 'a' * 32 + '/native.sock'
        with mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter, 'connect') as connected, self.assertRaises(Denied):
            adapter.bridge(value, [str(adapter.WORKSPACE_ROOT / 'repo')])
        connected.assert_not_called()

    def test_workspace_attestation_fails_before_connecting_or_sending_native_requests(self):
        with mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter, 'attest_workspaces', side_effect=Denied), \
                mock.patch.object(adapter, 'connect') as connected, self.assertRaises(Denied):
            adapter.bridge(str(adapter.SOCKET), [str(adapter.WORKSPACE_ROOT / 'repo')])
        connected.assert_not_called()

    def bridge_readiness(self, operational):
        metadata = {'uid': 1000, 'peerUid': 1000, 'peerPid': 789, 'peerGeneration': '12345',
                    'socket': str(adapter.SOCKET), 'socketEndpoint': str(adapter.SOCKET)}
        native = mock.Mock(fds=(123, 124), buffer=bytearray())
        stdio = mock.Mock(buffer=bytearray())
        selector = mock.MagicMock()
        selector.__enter__.return_value = selector
        selector.select.return_value = [(SimpleNamespace(data='input'), None)]
        peer_check, workspace_check = mock.Mock(), mock.Mock()
        workspaces = [str(adapter.WORKSPACE_ROOT / 'repo')]
        with mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter, 'connect', return_value=(native, peer_check, metadata)), \
                mock.patch.object(adapter, 'attest_workspaces', return_value=workspace_check) as attest, \
                mock.patch.object(adapter.os, 'dup', side_effect=[100, 101]), mock.patch.object(adapter.os, 'set_blocking'), \
                mock.patch.object(adapter.os, 'read', return_value=b''), mock.patch.object(adapter, 'JSONLChannel', return_value=stdio), \
                mock.patch.object(adapter.selectors, 'DefaultSelector', return_value=selector):
            observed = adapter.bridge(str(adapter.SOCKET), workspaces if operational else None)
        native.send.assert_not_called()  # EOF does not initialize or send work.
        native.close.assert_called_once()
        stdio.close.assert_called_once()
        self.assertEqual(stdio.send.call_args.args[0], {'method': 'ccrelay/transport/ready', 'params': observed})
        return observed, attest, peer_check, workspace_check, workspaces

    def test_operational_readiness_brackets_workspace_and_peer_before_any_native_request(self):
        observed, attest, peer_check, workspace_check, workspaces = self.bridge_readiness(True)
        attest.assert_called_once_with(workspaces)
        self.assertGreaterEqual(workspace_check.call_count, 2)
        self.assertGreaterEqual(peer_check.call_count, 2)
        self.assertEqual(observed['workspaces'], workspaces)
        self.assertEqual(observed['binarySha256'], adapter.BINARY_SHA256)
        self.assertIs(observed['credentialDenied'], True)

    def test_legacy_diagnostic_readiness_does_not_fabricate_production_attestation(self):
        observed, attest, peer_check, workspace_check, workspaces = self.bridge_readiness(False)
        attest.assert_not_called()
        workspace_check.assert_not_called()
        self.assertEqual(set(observed), {'uid', 'peerUid', 'peerPid', 'peerGeneration', 'socket', 'socketEndpoint'})

    @contextmanager
    def alias_fixture(self):
        path = adapter.socket_path('/Users/pouya/.migration/native-transport-' + 'b' * 32 + '/native.sock')
        endpoint = adapter.DAEMON_DIRECTORY / hashlib.sha256(str(path).encode()).hexdigest()
        def metadata(mode, uid=1000, inode=1):
            return SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=uid, st_dev=1, st_ino=inode)
        entries = {path.parent: metadata(stat.S_IFDIR | 0o700, inode=2),
                   adapter.OWNER / '.migration': metadata(stat.S_IFDIR | 0o700, inode=3),
                   path: metadata(stat.S_IFLNK | 0o777, inode=4),
                   Path('/tmp'): metadata(stat.S_IFDIR | 0o1777, uid=0, inode=5),
                   adapter.DAEMON_DIRECTORY: metadata(stat.S_IFDIR | 0o700, inode=6),
                   endpoint: metadata(stat.S_IFSOCK | 0o600, inode=7)}
        with mock.patch.object(adapter.Path, 'lstat', lambda candidate: entries[candidate]), \
                mock.patch.object(adapter.os, 'readlink', return_value=str(endpoint)) as link:
            yield path, endpoint, entries, link

    def test_only_exact_native_and_fresh_diagnostic_paths(self):
        self.assertEqual(str(adapter.socket_path(str(adapter.SOCKET))), str(adapter.SOCKET))
        value = '/Users/pouya/.migration/native-transport-' + 'a' * 32 + '/native.sock'
        self.assertEqual(str(adapter.socket_path(value)), value)
        for bad in ('/tmp/native.sock', value + '/..', value.replace('a' * 32, 'A' * 32),
                    value.replace('native.sock', 'other.sock'), str(adapter.SOCKET) + '\n',
                    str(adapter.SOCKET).replace('/.codex/', '/.codex/../.codex/')):
            with self.subTest(path=bad), self.assertRaises(Denied):
                adapter.socket_path(bad)

    def test_wrong_platform_uid_or_home_never_connects(self):
        for platform, uid, euid, home in (('darwin', 1000, 1000, '/Users/pouya'),
                                         ('linux', 0, 0, '/Users/pouya'),
                                         ('linux', 1000, 0, '/Users/pouya'),
                                         ('linux', 1000, 1000, '/root')):
            with mock.patch.object(adapter.sys, 'platform', platform), mock.patch.object(adapter.os, 'getuid', return_value=uid), \
                    mock.patch.object(adapter.os, 'geteuid', return_value=euid), mock.patch.dict(adapter.os.environ, {'HOME': home}), \
                    mock.patch.object(adapter.socket, 'socket') as socket, self.assertRaises(Denied):
                adapter.connect(str(adapter.SOCKET))
            socket.assert_not_called()

    def test_missing_daemon_never_spawns_a_private_fallback(self):
        with mock.patch.object(adapter, 'require_owner'), mock.patch.object(adapter.Path, 'lstat', side_effect=FileNotFoundError), \
                mock.patch.object(adapter.socket, 'socket') as socket, self.assertRaises(FileNotFoundError):
            adapter.connect(str(adapter.SOCKET))
        socket.assert_not_called()

    def test_measured_exact_path_hash_alias_is_checked_without_discovery(self):
        with self.alias_fixture() as (path, endpoint, entries, link):
            target, verify = adapter.socket_endpoint(path)
            self.assertEqual(target, endpoint)
            verify()
            entries[endpoint].st_ino += 1
            with self.assertRaisesRegex(Denied, 'identity changed'):
                verify()

    def test_arbitrary_relative_or_chained_alias_never_resolves(self):
        with self.alias_fixture() as (path, endpoint, entries, link):
            for bad in (str(endpoint) + '-other', '../other.sock', '/tmp/other.sock', str(endpoint.parent / ('a' * 64))):
                link.return_value = bad
                with self.subTest(link=bad), self.assertRaisesRegex(Denied, 'exact-path hash'):
                    adapter.socket_endpoint(path)

    def test_alias_target_must_be_a_literal_private_owner_socket(self):
        with self.alias_fixture() as (path, endpoint, entries, link):
            for mode, uid in ((stat.S_IFLNK | 0o600, 1000), (stat.S_IFREG | 0o600, 1000),
                              (stat.S_IFSOCK | 0o666, 1000), (stat.S_IFSOCK | 0o600, 0)):
                entries[endpoint].st_mode, entries[endpoint].st_uid = mode, uid
                with self.subTest(mode=mode, uid=uid), self.assertRaises(Denied):
                    adapter.socket_endpoint(path)

    def test_private_owner_daemon_directory_and_root_sticky_tmp_required(self):
        for candidate in (Path('/tmp'), adapter.DAEMON_DIRECTORY):
            with self.alias_fixture() as (path, endpoint, entries, link):
                for mode, uid in ((stat.S_IFLNK | 0o700, 1000), (stat.S_IFDIR | 0o777, 1000),
                                  (stat.S_IFDIR | 0o700, 0)):
                    entries[candidate].st_mode, entries[candidate].st_uid = mode, uid
                    with self.subTest(path=candidate, mode=mode, uid=uid), self.assertRaises(Denied):
                        adapter.socket_endpoint(path)

    def test_alias_and_parent_identity_rechecked_after_connect(self):
        for candidate_kind in ('alias', 'directory'):
            with self.alias_fixture() as (path, endpoint, entries, link):
                _, verify = adapter.socket_endpoint(path)
                candidate = path if candidate_kind == 'alias' else adapter.DAEMON_DIRECTORY
                entries[candidate].st_ino += 1
                with self.assertRaises(Denied):
                    verify()
        with self.alias_fixture() as (path, endpoint, entries, link):
            _, verify = adapter.socket_endpoint(path)
            link.return_value = '/tmp/other.sock'
            with self.assertRaisesRegex(Denied, 'alias changed'):
                verify()

    def test_private_literal_socket_needs_no_alias_or_temporary_directory(self):
        with self.alias_fixture() as (path, endpoint, entries, link):
            entries[path].st_mode = stat.S_IFSOCK | 0o600
            del entries[Path('/tmp')], entries[adapter.DAEMON_DIRECTORY], entries[endpoint]
            target, verify = adapter.socket_endpoint(path)
            self.assertEqual(target, path)
            verify()
            link.assert_not_called()

    def test_native_hash_and_identity_come_from_same_no_follow_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture-native'
            body = b'Credential-free inert binary-pin fixture'
            path.write_bytes(body)
            with mock.patch.object(adapter, 'BINARY', path), \
                    mock.patch.object(adapter, 'BINARY_SHA256', hashlib.sha256(body).hexdigest()):
                metadata = adapter.pinned_binary()
                self.assertEqual(adapter._file_identity(metadata), adapter._file_identity(path.lstat()))
                path.write_bytes(body + b'changed')
                with self.assertRaises(Denied):
                    adapter.pinned_binary()
            alias = Path(directory) / 'alias'
            alias.symlink_to(path)
            with mock.patch.object(adapter, 'BINARY', alias), self.assertRaises(OSError):
                adapter.pinned_binary()

    def test_only_source_or_exact_managed_package_can_be_pinned(self):
        with mock.patch.object(adapter.os, 'open') as opened, self.assertRaises(Denied):
            adapter.pinned_binary(Path('/tmp/other-native'))
        opened.assert_not_called()

    def test_source_peer_retains_exact_original_inode_pin(self):
        source = SimpleNamespace(st_dev=1, st_ino=42)
        with mock.patch.object(adapter.Path, 'stat', return_value=source), \
                mock.patch.object(adapter, 'pinned_binary') as pinned:
            path, metadata = adapter.peer_binary(Path('/proc/789'), source)
        self.assertEqual(path, adapter.BINARY)
        self.assertIs(metadata, source)
        pinned.assert_not_called()

    def test_managed_peer_needs_exact_path_and_matching_bytes(self):
        source = SimpleNamespace(st_dev=1, st_ino=42)
        managed = SimpleNamespace(st_dev=1, st_ino=43)
        with mock.patch.object(adapter.Path, 'stat', return_value=managed), \
                mock.patch.object(adapter.Path, 'lstat', return_value=managed), \
                mock.patch.object(adapter, 'pinned_binary', return_value=managed) as pinned:
            path, metadata = adapter.peer_binary(Path('/proc/789'), source)
            self.assertEqual(path, adapter.MANAGED_BINARY)
            self.assertIs(metadata, managed)
            pinned.assert_called_once_with(adapter.MANAGED_BINARY)
            pinned.side_effect = Denied('Changed package')
            with self.assertRaises(Denied):
                adapter.peer_binary(Path('/proc/789'), source)

    def test_other_kernel_executable_is_not_accepted_as_managed(self):
        source = SimpleNamespace(st_dev=1, st_ino=42)
        managed = SimpleNamespace(st_dev=1, st_ino=43)
        other = SimpleNamespace(st_dev=1, st_ino=44)
        with mock.patch.object(adapter.Path, 'stat', return_value=other), \
                mock.patch.object(adapter.Path, 'lstat', return_value=managed), \
                mock.patch.object(adapter, 'pinned_binary') as pinned, self.assertRaises(Denied):
            adapter.peer_binary(Path('/proc/789'), source)
        pinned.assert_not_called()


if __name__ == '__main__':
    unittest.main()
