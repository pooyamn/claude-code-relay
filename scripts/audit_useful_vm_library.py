"""Read-only useful VM Library audit against the retained original archive.

No whole disk, app installation, cache backup, extraction, deletion or source
permission change. Hash/size agreement proves only the selected observed files,
not a final writer fence, live database consistency or portable Keychain login.
Private manifests/results must remain in administrator/SYSTEM-only PC storage.
"""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import tarfile
import time


ROOTS = tuple('Library/' + name for name in (
    'Preferences/kicad', 'Preferences/.wrangler', 'Preferences/astro', 'Preferences/tscircuit-nodejs',
    'Keychains', 'LaunchAgents', 'Shortcuts', 'Spelling', 'Fonts', 'FontCollections',
    'Mail', 'Messages', 'Contacts', 'Safari', 'Application Support/AddressBook',
    'Application Support/Autodesk/FusionAddins', 'Application Support/Autodesk/Neutron Platform',
    'Application Support/Autodesk/Autodesk Fusion 360', 'Application Support/MagicRemoteBridge',
    'Application Support/skidl', 'Application Support/fastmcp', 'Application Support/clawhub',
    'Application Support/jlcone', 'Application Support/Google/Chrome/Default',
    'Group Containers/group.com.apple.notes', 'Group Containers/group.com.apple.calendar',
    'Group Containers/group.com.apple.reminders',
    'Preferences/com.autodesk.EAGLE 9.7.0.plist', 'Preferences/com.autodesk.FusionApp.plist',
    'Preferences/com.autodesk.fusion360.plist', 'Preferences/com.google.Chrome.plist',
    'Preferences/com.jlcpcb.www.plist', 'Preferences/org.kicad.eeschema.plist',
    'Preferences/org.kicad.kicad.plist'))
ADDITIONAL_ROOTS = tuple('Library/' + name for name in (
    'Application Support/Fusion 360 CAM/Settings', 'Application Support/Adobe/Acrobat',
    'Application Support/Google/Chrome/Local State', 'Application Support/Google/Chrome/NativeMessagingHosts',
    'Application Support/Google/Chrome/External Extensions', 'Preferences/Adobe',
    'Preferences/com.adobe.Acrobat.Pro.plist', 'Preferences/com.adobe.Synchronizer.DC.plist',
    'Preferences/com.autodesk.AdskIdentityManager.plist', 'Preferences/com.philandro.anydesk.plist',
    'Preferences/org.python.python.plist', 'Autosave Information', 'Services', 'Application Scripts',
    'Group Containers/group.com.apple.Journal', 'Group Containers/group.com.apple.VoiceMemos.shared',
    'Group Containers/group.com.apple.shortcuts', 'Group Containers/group.is.workflow.my.app',
    'Group Containers/group.is.workflow.shortcuts', 'Group Containers/group.com.apple.contacts',
    'Group Containers/group.com.apple.mail', 'Group Containers/com.apple.MessagesLegacyTransferArchive',
    'Group Containers/group.com.apple.iCloudDrive',
    'Containers/com.apple.TextEdit/Data/Library/Autosave Information',
    'Containers/com.apple.Preview/Data/Library/Autosave Information',
    'Containers/com.apple.ScriptEditor2/Data/Library/Autosave Information',
    'Containers/com.apple.QuickTimePlayerX/Data/Library/Autosave Information',
    'Containers/com.adobe.Acrobat.Pro/Data/Documents'))
EXCLUDED_DIRS = frozenset(('Cache', 'Caches', 'Code Cache', 'GPUCache', 'DawnCache',
                         'DawnGraphiteCache', 'DawnWebGPUCache', 'ShaderCache', 'GrShaderCache',
                         'GraphiteDawnCache', 'Crashpad', 'logs', 'Logs', 'webdeploy',
                         'Extensions', 'Service Worker', 'blob_storage'))
MAX_ENTRIES = 10000
MAX_BYTES = 4 << 30
SCHEMA = 'ccrelay.useful_vm_library_observation.v1'
ARCHIVE = '/mnt/c/ProgramData/OracovaMigration/156ddf55eefb4b14bc6a2ef3ae84499b/vm-library.tar.gz'
OPAQUE_PARENT = 'Library/Application Support/Autodesk/Autodesk Fusion 360/B39EM5Y5L4Z85868'


def opaque_selection(raw):
    """One small Mac-only filename, represented as JSON data, never a tar path."""
    if len(raw) > 4 << 20:
        raise ValueError('Opaque selection byte bound')
    value = json.loads(raw)
    if value.get('schema') != 'ccrelay.dirty_source_selection.v1' or \
            not isinstance(value.get('entries'), list) or not 1 <= len(value['entries']) <= 5000:
        raise ValueError('Independent source selection required')
    rows = [r for r in value['entries'] if '\\' in r.get('name', '')]
    if len(rows) != 1:
        raise ValueError('Exactly one observed opaque leaf required')
    row = rows[0]
    name = name_ok(row.get('name'))
    if name.rsplit('/', 1)[0] != OPAQUE_PARENT or \
            any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name) or \
            row.get('kind') != 'file' or type(row.get('bytes')) is not int or \
            not 0 <= row['bytes'] <= 4096 or not re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')):
        raise ValueError('Literal bounded opaque Fusion file required')
    return row


def capture_opaque(root, expected):
    """No source rename/temp files; no-follow read with the independent hash."""
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or root.is_symlink():
        raise ValueError('Literal source home required')
    # Revalidate the row even for fixture/library callers.
    expected = opaque_selection(json.dumps({'schema': 'ccrelay.dirty_source_selection.v1',
                                           'entries': [expected]}).encode())
    fds = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    try:
        parts = expected['name'].split('/')
        for part in parts[:-1]:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        before = os.stat(parts[-1], dir_fd=fds[-1], follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected['bytes']:
            raise ValueError('Opaque source type/size changed')
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1])
        with os.fdopen(fd, 'rb') as stream:
            if identity(os.fstat(stream.fileno())) != identity(before):
                raise ValueError('Opaque source replaced')
            data = stream.read(4097)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256'] or \
                    identity(os.fstat(stream.fileno())) != identity(before):
                raise ValueError('Opaque source differs from observation')
        if identity(os.stat(parts[-1], dir_fd=fds[-1], follow_symlinks=False)) != identity(before):
            raise ValueError('Opaque source changed')
        return {'schema': 'ccrelay.mac_opaque_leaf.v1',
                'original': {k: expected[k] for k in ('name', 'kind', 'bytes', 'sha256')},
                'contentBase64': base64.b64encode(data).decode('ascii'),
                'mode': stat.S_IMODE(before.st_mode), 'uid': before.st_uid, 'gid': before.st_gid,
                'mtimeNs': before.st_mtime_ns, 'sourceModified': False, 'sourceWritersFrozen': False,
                'consistentFinalSnapshot': False, 'extractedToFilesystem': False}
    finally:
        for fd in reversed(fds):
            os.close(fd)


def verify_opaque(raw, expected):
    if len(raw) > 16384:
        raise ValueError('Opaque representation bound')
    value = json.loads(raw)
    expected = opaque_selection(json.dumps({'schema': 'ccrelay.dirty_source_selection.v1',
                                           'entries': [expected]}).encode())
    original = {k: expected[k] for k in ('name', 'kind', 'bytes', 'sha256')}
    if value.get('schema') != 'ccrelay.mac_opaque_leaf.v1' or value.get('original') != original or \
            any(value.get(k) is not False for k in ('sourceModified', 'sourceWritersFrozen',
                                                  'consistentFinalSnapshot', 'extractedToFilesystem')):
        raise ValueError('Opaque original-name mapping differs')
    data = base64.b64decode(value['contentBase64'], validate=True)
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError('Opaque bytes differ from independent observation')
    return {'schema': 'ccrelay.mac_opaque_leaf_verification.v1', 'verified': True,
            'fileBytes': len(data), 'originalNameMappingVerified': True,
            'extractedToFilesystem': False, 'consistentFinalSnapshot': False}


def name_ok(name):
    if not isinstance(name, str) or not name or name.startswith('/') or '\0' in name or \
            any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Literal relative library path required')
    return name


def identity(s):
    return s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def observe(root, *, roots=ROOTS, max_entries=MAX_ENTRIES, max_bytes=MAX_BYTES, timeout=300):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or root.is_symlink():
        raise ValueError('Literal source home required')
    if not roots or len(set(roots)) != len(roots):
        raise ValueError('Unique selected roots required')
    rows, issues, absent, excluded = [], [], [], []
    total = 0
    deadline = time.monotonic() + timeout
    top = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        def visit(parent, base, name):
            nonlocal total
            if len(rows) >= max_entries or time.monotonic() >= deadline:
                raise TimeoutError('Useful library entry/time bound')
            before = os.stat(base, dir_fd=parent, follow_symlinks=False)
            row = {'name': name, 'mode': stat.S_IMODE(before.st_mode)}
            rows.append(row)
            if stat.S_ISDIR(before.st_mode):
                row['kind'] = 'directory'
                fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    names = sorted(os.listdir(fd))
                    for child in names:
                        s = os.stat(child, dir_fd=fd, follow_symlinks=False)
                        if child in EXCLUDED_DIRS and stat.S_ISDIR(s.st_mode):
                            excluded.append(name + '/' + child)
                            continue
                        try:
                            visit(fd, child, name + '/' + child)
                        except TimeoutError:
                            raise
                        except (OSError, ValueError) as error:
                            issues.append({'name': name + '/' + child, 'error': type(error).__name__})
                    if names != sorted(os.listdir(fd)):
                        raise ValueError('Selected directory changed')
                finally:
                    os.close(fd)
            elif stat.S_ISLNK(before.st_mode):
                row.update(kind='symlink', target=os.readlink(base, dir_fd=parent))
            elif stat.S_ISSOCK(before.st_mode):
                row.update(kind='socket', representation='metadata-only',
                           uid=before.st_uid, gid=before.st_gid,
                           socketKernelStatePreserved=False,
                           restore='recreate via its owning application; kernel state is not portable')
            elif stat.S_ISREG(before.st_mode):
                if before.st_size > max_bytes - total:
                    raise TimeoutError('Useful library logical byte bound')
                fd = os.open(base, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                h, count = hashlib.sha256(), 0
                with os.fdopen(fd, 'rb', buffering=0) as source:
                    if identity(os.fstat(source.fileno())) != identity(before):
                        raise ValueError('Selected file replaced')
                    while chunk := source.read(1048576):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Useful library read deadline')
                        h.update(chunk); count += len(chunk)
                    if count != before.st_size or identity(os.fstat(source.fileno())) != identity(before):
                        raise ValueError('Selected file changed')
                row.update(kind='file', bytes=count, sha256=h.hexdigest())
                total += count
            else:
                raise ValueError('Selected special object is not portable file data')
            if identity(os.stat(base, dir_fd=parent, follow_symlinks=False)) != identity(before):
                raise ValueError('Selected object changed')

        for selected in roots:
            parts = name_ok(selected).split('/')
            fds, parent = [], top
            try:
                for part in parts[:-1]:
                    fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    fds.append(fd); parent = fd
                visit(parent, parts[-1], selected)
            except FileNotFoundError:
                absent.append(selected)
            except TimeoutError:
                raise
            except (OSError, ValueError) as error:
                issues.append({'name': selected, 'error': type(error).__name__})
            finally:
                for fd in reversed(fds):
                    os.close(fd)
    finally:
        os.close(top)
    return {'schema': SCHEMA, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'roots': list(roots), 'entries': rows, 'issues': issues, 'absentRoots': absent,
            'excludedCacheDirectories': excluded, 'fileBytesHashed': total,
            'sourceWritersFrozen': False, 'consistentFinalSnapshot': False,
            'sourceModified': False, 'macAclAndXattrClosure': False,
            'socketKernelStatePreserved': False}


def compare(archive_path, source, *, timeout=300):
    if source.get('schema') != SCHEMA or not 0 < len(source['entries']) <= MAX_ENTRIES:
        raise ValueError('Bounded useful-library source observation required')
    expected = {name_ok(r['name']): r for r in source['entries']}
    if len(expected) != len(source['entries']):
        raise ValueError('Duplicate source observation')
    actual, links, archived_bytes = {}, {}, 0
    deadline = time.monotonic() + timeout
    with tarfile.open(archive_path, 'r|gz') as archive:
        for member in archive:
            if time.monotonic() >= deadline:
                raise TimeoutError('Useful library archive deadline')
            name = member.name.removesuffix('/')
            if name not in expected:
                continue
            if name in actual or name in links:
                raise ValueError('Duplicate selected archive member')
            if member.isfile():
                if member.size < 0 or member.size > MAX_BYTES - archived_bytes:
                    raise ValueError('Selected archive byte bound')
                archived_bytes += member.size
                h, count = hashlib.sha256(), 0
                stream = archive.extractfile(member)
                while chunk := stream.read(1048576):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Useful library member deadline')
                    count += len(chunk); h.update(chunk)
                if count != member.size:
                    raise ValueError('Truncated selected archive member')
                actual[name] = {'kind': 'file', 'bytes': count, 'sha256': h.hexdigest()}
            elif member.isdir():
                actual[name] = {'kind': 'directory'}
            elif member.issym():
                actual[name] = {'kind': 'symlink', 'target': member.linkname}
            elif member.islnk():
                links[name] = name_ok(member.linkname)
            else:
                actual[name] = {'kind': 'unsupported'}
    while links:
        resolved = [name for name, target in links.items() if actual.get(target, {}).get('kind') == 'file']
        if not resolved:
            break
        for name in resolved:
            actual[name] = dict(actual[links.pop(name)])
    missing, changed, same, unresolved = [], [], [], []
    for name, row in expected.items():
        if name in links:
            unresolved.append(name)
        elif name not in actual:
            missing.append(row)
        else:
            keys = ('kind', 'bytes', 'sha256') if row.get('kind') == 'file' else \
                ('kind', 'target') if row.get('kind') == 'symlink' else ('kind',)
            (same if all(row.get(k) == actual[name].get(k) for k in keys) else changed).append(row)
    return {'schema': 'ccrelay.useful_vm_library_comparison.v1', 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'missing': missing, 'changed': changed, 'same': same, 'unresolvedHardlinks': unresolved,
            'sourceIssues': len(source['issues']), 'sourceFileBytesHashed': source['fileBytesHashed'],
            'selectedContentsMatch': not (missing or changed or unresolved or source['issues']),
            'sourceModified': False, 'targetModified': False, 'consistentFinalSnapshot': False,
            'keychainPortableLoginVerified': False, 'wholeLibraryVerified': False}


if __name__ == '__main__':
    if sys.argv[1:] == ['--opaque-source']:
        if sys.platform != 'darwin' or os.geteuid() != 501 or pwd.getpwuid(501).pw_name != 'pouya':
            raise SystemExit('Literal ordinary VM owner required')
        try:
            expected = opaque_selection(sys.stdin.buffer.read((4 << 20) + 1))
            print(json.dumps(capture_opaque('/Users/pouya', expected), separators=(',', ':')))
        except Exception as error:
            print(json.dumps({'errorType': type(error).__name__, 'captured': False}), file=sys.stderr)
            raise SystemExit(1)
    elif len(sys.argv) == 4 and sys.argv[1] == '--opaque-verify':
        selected, stored = sys.argv[2:]
        if sys.platform != 'linux' or os.geteuid() != 1000 or not re.fullmatch(
                r'/mnt/c/ProgramData/OracovaMigration/stream-helper-[0-9a-f]{32}/dirty-selection\.json', selected) or not re.fullmatch(
                r'/mnt/c/ProgramData/OracovaMigration/[0-9a-f]{32}/useful-library-opaque\.private\.json', stored):
            raise SystemExit('Literal protected PC opaque inputs required')
        with open(selected, 'rb') as stream:
            expected = opaque_selection(stream.read((4 << 20) + 1))
        with open(stored, 'rb') as stream:
            checked = verify_opaque(stream.read(16385), expected)
        print(json.dumps(checked, separators=(',', ':')))
    elif sys.argv[1:] in (['--source'], ['--additional-source']):
        if sys.platform != 'darwin' or os.geteuid() != 501 or pwd.getpwuid(501).pw_name != 'pouya':
            raise SystemExit('Literal ordinary VM owner required')
        selected = ADDITIONAL_ROOTS if sys.argv[1] == '--additional-source' else ROOTS
        print(json.dumps(observe('/Users/pouya', roots=selected), separators=(',', ':')))
    elif len(sys.argv) == 3 and sys.argv[1] == '--compare':
        source_path = sys.argv[2]
        if sys.platform != 'linux' or os.geteuid() != 1000 or not re.fullmatch(
                r'/mnt/c/ProgramData/OracovaMigration/[0-9a-f]{32}/useful-library-source.private.json', source_path):
            raise SystemExit('Literal protected PC observation required')
        with open(source_path, 'rb') as stream:
            raw = stream.read(8 << 20)
            if stream.read(1):
                raise SystemExit('Private observation byte bound')
        print(json.dumps(compare(ARCHIVE, json.loads(raw)), separators=(',', ':')))
    else:
        raise SystemExit('Only fixed useful VM Library audit modes admitted')
