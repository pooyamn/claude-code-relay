import io
import base64
import hashlib
import json
import os
import socket
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.audit_useful_vm_library import (observe, compare, OPAQUE_PARENT,
    opaque_selection, capture_opaque, verify_opaque)


class UsefulLibraryAuditTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='useful-library-fixture-')
        self.root = Path(self.scratch.name)
        self.home = self.root / 'home'
        self.path = self.home / 'Library/Preferences/kicad'
        self.path.mkdir(parents=True)
        (self.path / 'settings.json').write_bytes(b'old')
        self.archive = self.root / 'library.tar.gz'

    def tearDown(self):
        self.scratch.cleanup()  # Only this generated fixture tree.

    def source(self, **kwargs):
        return observe(self.home, roots=('Library/Preferences/kicad',), **kwargs)

    def backup(self):
        with tarfile.open(self.archive, 'w:gz') as archive:
            archive.add(self.home / 'Library', arcname='Library')

    def test_match_does_not_claim_whole_library_db_consistency_or_keychain_login(self):
        self.backup()
        result = compare(self.archive, self.source())
        self.assertTrue(result['selectedContentsMatch'])
        for key in ('wholeLibraryVerified', 'keychainPortableLoginVerified', 'consistentFinalSnapshot', 'targetModified'):
            self.assertFalse(result[key])

    def test_same_size_change_and_new_file_are_detected(self):
        self.backup()
        (self.path / 'settings.json').write_bytes(b'new')
        (self.path / 'unsaved').write_bytes(b'preserve')
        result = compare(self.archive, self.source())
        self.assertFalse(result['selectedContentsMatch'])
        self.assertEqual([r['name'].split('/')[-1] for r in result['changed']], ['settings.json'])
        self.assertEqual([r['name'].split('/')[-1] for r in result['missing']], ['unsaved'])

    def test_cache_directories_excluded_not_backed_up_or_deleted(self):
        cache = self.path / 'Caches'
        cache.mkdir(); (cache / 'downloadable').write_bytes(b'not useful')
        source = self.source()
        self.assertEqual(source['excludedCacheDirectories'], ['Library/Preferences/kicad/Caches'])
        self.assertNotIn('downloadable', repr(source['entries']))
        self.assertEqual((cache / 'downloadable').read_bytes(), b'not useful')

    def test_live_sockets_are_explicit_metadata_not_lost_files_or_fake_payloads(self):
        endpoint = socket.socket(socket.AF_UNIX)
        endpoint.bind(str(self.path / 'app.sock'))
        try:
            source = self.source()
            self.assertEqual(source['issues'], [])
            row = next(r for r in source['entries'] if r['name'].endswith('/app.sock'))
            self.assertEqual(row['kind'], 'socket')
            self.assertEqual(row['representation'], 'metadata-only')
            self.assertNotIn('sha256', row)
            self.assertNotIn('bytes', row)
            self.assertFalse(row['socketKernelStatePreserved'])
            self.assertFalse(source['socketKernelStatePreserved'])
        finally:
            endpoint.close()

    def test_symlinks_not_followed_and_parent_alias_not_admitted(self):
        (self.path / 'external').symlink_to('/not/followed', target_is_directory=True)
        self.backup()
        self.assertTrue(compare(self.archive, self.source())['selectedContentsMatch'])
        (self.home / 'alias').symlink_to(self.path, target_is_directory=True)
        source = observe(self.home, roots=('alias/settings.json',))
        self.assertEqual(len(source['issues']), 1)
        self.assertFalse(source['entries'])

    def test_private_errors_and_missing_roots_cannot_certify_lost_data(self):
        self.backup()
        source = self.source()
        source['issues'].append({'name': 'private', 'error': 'PermissionError'})
        self.assertFalse(compare(self.archive, source)['selectedContentsMatch'])
        missing = observe(self.home, roots=('Library/absent',))
        self.assertEqual(missing['absentRoots'], ['Library/absent'])

    def test_bounds_and_literal_roots(self):
        with self.assertRaises(TimeoutError): self.source(max_entries=1)
        with self.assertRaises(TimeoutError): self.source(max_bytes=1)
        with self.assertRaises(TimeoutError): self.source(timeout=0)
        with self.assertRaises(ValueError): observe(self.home / '..' / 'home')

    def test_selected_hardlinks_resolve_without_extraction(self):
        os.link(self.path / 'settings.json', self.path / 'second.json')
        self.backup()
        result = compare(self.archive, self.source())
        self.assertTrue(result['selectedContentsMatch'])
        self.assertEqual(result['unresolvedHardlinks'], [])

    def test_duplicate_selected_archive_members_rejected(self):
        with tarfile.open(self.archive, 'w:gz') as archive:
            for _ in range(2):
                member = tarfile.TarInfo('Library/Preferences/kicad/settings.json')
                member.size = 3
                archive.addfile(member, io.BytesIO(b'old'))
        with self.assertRaisesRegex(ValueError, 'Duplicate selected'):
            compare(self.archive, self.source())

    def opaque(self):
        path = self.home / OPAQUE_PARENT / 'valid-mac\\filename'
        path.parent.mkdir(parents=True)
        data = b'\x00preserve original bytes\xff'
        path.write_bytes(data)
        row = {'name': str(path.relative_to(self.home)), 'kind': 'file', 'bytes': len(data),
               'sha256': hashlib.sha256(data).hexdigest()}
        return path, row

    def test_opaque_filename_and_bytes_preserved_without_source_rename_or_extraction(self):
        path, row = self.opaque()
        value = capture_opaque(self.home, row)
        self.assertEqual(value['original']['name'], row['name'])
        self.assertEqual(base64.b64decode(value['contentBase64']), path.read_bytes())
        checked = verify_opaque(json.dumps(value).encode(), row)
        self.assertTrue(checked['verified'])
        self.assertFalse(checked['extractedToFilesystem'])
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_opaque_scope_bounds_and_traversal_are_not_global_archive_grants(self):
        _, row = self.opaque()
        for changes in ({'name': 'Library/Keychains/a\\b'}, {'name': OPAQUE_PARENT+'/../a\\b'},
                        {'name': OPAQUE_PARENT+'/a\\b\n'}, {'bytes': 4097}, {'kind': 'symlink'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                opaque_selection(json.dumps({'schema': 'ccrelay.dirty_source_selection.v1',
                                             'entries': [dict(row, **changes)]}).encode())
        from scripts.stream_owner_tools import safe_name
        with self.assertRaises(ValueError): safe_name(row['name'])

    def test_opaque_source_change_or_parent_symlink_fails(self):
        path, row = self.opaque()
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError): capture_opaque(self.home, row)
        alias = self.root / 'alias-home'
        alias.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(ValueError): capture_opaque(alias, row)
        parent = self.home / 'Library/Application Support/Autodesk/Autodesk Fusion 360'
        outside = self.root / 'outside'; outside.mkdir()
        parent.rename(outside / 'original')
        parent.symlink_to(outside / 'original', target_is_directory=True)
        with self.assertRaises(OSError): capture_opaque(self.home, row)

    def test_opaque_target_payload_or_original_mapping_tampering_rejected(self):
        _, row = self.opaque()
        value = capture_opaque(self.home, row)
        for changes in ({'contentBase64': base64.b64encode(b'bad').decode()},
                        {'original': dict(value['original'], name='different')},
                        {'consistentFinalSnapshot': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                verify_opaque(json.dumps(dict(value, **changes)).encode(), row)


if __name__ == '__main__':
    unittest.main()
