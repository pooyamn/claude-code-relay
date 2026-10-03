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


if __name__ == '__main__':
    unittest.main()
