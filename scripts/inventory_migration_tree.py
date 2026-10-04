"""Private whole-workspace metadata comparison, including ignored/nested files.

Matching type/size is NOT content verification. No source writes, extraction,
activation, permissions changes, deletion or source writer fence is performed.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import time

ROOT = Path('/Users/pouya/.openclaw/workspace')
MAX_ENTRIES = 1000000
MAX_OUTPUT = 256 << 20


def relative(name):
    if not isinstance(name, str) or not name or name.startswith('/') or '\0' in name or \
            any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Literal relative workspace entry required')
    return name


def identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def record(name, info):
    kind = 'file' if stat.S_ISREG(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else \
        'symlink' if stat.S_ISLNK(info.st_mode) else 'socket' if stat.S_ISSOCK(info.st_mode) else 'special'
    return {'name': name, 'kind': kind, 'bytes': info.st_size, 'mode': stat.S_IMODE(info.st_mode),
            'uid': info.st_uid, 'gid': info.st_gid, 'mtimeNs': info.st_mtime_ns, 'ctimeNs': info.st_ctime_ns}


def tree(root, *, max_entries=MAX_ENTRIES, timeout_seconds=540):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or type(max_entries) is not int or max_entries <= 0:
        raise ValueError('Literal root and positive bound required')
    entries, problems = [], []
    encoded_bytes = 0
    deadline = time.monotonic() + timeout_seconds
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        def visit(fd, prefix, depth):
            nonlocal encoded_bytes
            if depth > 128 or time.monotonic() >= deadline:
                raise TimeoutError('Metadata traversal depth/deadline bound')
            before = os.fstat(fd)
            names = sorted(os.listdir(fd))
            for name in names:
                if len(entries) >= max_entries or time.monotonic() >= deadline:
                    raise TimeoutError('Metadata traversal entry/deadline bound')
                path = relative(prefix + '/' + name if prefix else name)
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    row = record(path, info)
                    if row['kind'] == 'symlink':
                        row['target'] = os.readlink(name, dir_fd=fd)
                    encoded_bytes += len(json.dumps(row, ensure_ascii=True, separators=(',', ':')).encode()) + 1
                    if encoded_bytes > MAX_OUTPUT - 65536:
                        raise TimeoutError('Metadata output byte bound')
                    entries.append(row)
                    if row['kind'] == 'directory':
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            if identity(os.fstat(child)) != identity(info):
                                raise ValueError('Directory replaced before traversal')
                            visit(child, path, depth + 1)
                        finally:
                            os.close(child)
                    if identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != identity(info):
                        raise ValueError('Entry identity changed during traversal')
                except TimeoutError:
                    raise
                except (OSError, ValueError) as error:
                    problems.append({'name': path, 'error': type(error).__name__})
            after = os.fstat(fd)
            if identity(before) != identity(after) or before.st_mtime_ns != after.st_mtime_ns or names != sorted(os.listdir(fd)):
                problems.append({'name': prefix or '.', 'error': 'DirectoryChangedDuringTraversal'})
        visit(descriptor, '', 0)
    finally:
        os.close(descriptor)
    return {'schema': 'ccrelay.workspace_metadata_inventory.v1', 'entries': entries, 'problems': problems,
            'traversalCompleteWithoutProblems': not problems,
            'directorySymlinksFollowed': False, 'ignoredAndNestedEntriesIncluded': True,
            'fileContentsHashed': False, 'sourceWritersFrozen': False, 'consistentFinalSnapshot': False}


def target_entry(root_fd, name):
    parts = relative(name).split('/')
    descriptors, parent = [], root_fd
    try:
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(fd)
            parent = fd
        result = record(name, os.stat(parts[-1], dir_fd=parent, follow_symlinks=False))
        if result['kind'] == 'symlink':
            result['target'] = os.readlink(parts[-1], dir_fd=parent)
        return result
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def compare(source, root):
    if source.get('schema') != 'ccrelay.workspace_metadata_inventory.v1' or len(source['entries']) > MAX_ENTRIES:
        raise ValueError('Bounded metadata inventory required')
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Literal target root required')
    output = {key: [] for key in ('missing', 'different', 'sameTypeAndSizeUnverified', 'sameLinkTarget', 'directories', 'special', 'errors')}
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    seen = set()
    try:
        for row in source['entries']:
            name = relative(row['name'])
            if name in seen:
                raise ValueError('Duplicate source metadata path')
            seen.add(name)
            try:
                actual = target_entry(fd, name)
            except FileNotFoundError:
                output['missing'].append(row)
                continue
            except (OSError, ValueError) as error:
                output['errors'].append({'name': name, 'error': type(error).__name__})
                continue
            if actual['kind'] != row['kind'] or row['kind'] == 'file' and actual['bytes'] != row['bytes'] or \
                    row['kind'] == 'symlink' and actual['target'] != row['target']:
                output['different'].append({'source': row, 'pc': actual})
            elif row['kind'] == 'file':
                output['sameTypeAndSizeUnverified'].append(name)
            elif row['kind'] == 'symlink':
                output['sameLinkTarget'].append(name)
            elif row['kind'] == 'directory':
                output['directories'].append(name)
            else:
                output['special'].append(row)
    finally:
        os.close(fd)
    output.update(schema='ccrelay.workspace_metadata_comparison.v1', at=time.time(),
                  sourceProblems=len(source['problems']), fileContentsVerified=False,
                  sourceWritersFrozen=False, consistentFinalSnapshot=False, targetModified=False)
    return output


def save_private(path, value):
    raw = json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()
    if len(raw) > MAX_OUTPUT:
        raise ValueError('Private inventory byte bound')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def private_directory(directory):
    if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000:
        raise ValueError('Ordinary PC owner required')
    directory = Path(directory)
    if directory.parent != Path('/Users/pouya/.migration') or not directory.name.startswith('tree-audit-'):
        raise ValueError('Fresh private audit directory required')
    for path in (directory, directory.parent, Path('/Users/pouya')):
        info = path.lstat()
        if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Literal owner-private audit ancestors required')
    return directory


def capture(directory):
    directory = private_directory(directory)
    code = Path(__file__).read_bytes()
    payload = base64.b64encode(code).decode()
    command = '/opt/homebrew/bin/python3.14 -I -B -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(payload) + '))')
    started = time.time()
    result = subprocess.run(['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                             '-o', 'ConnectTimeout=10', '-T', 'mac', command],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if len(result.stdout) > MAX_OUTPUT or len(result.stderr) > (1 << 20):
        raise ValueError('Source observation output bound')
    if result.returncode or result.stderr:
        receipt = {'schema': 'ccrelay.workspace_metadata_failed_capture.v1', 'exit': result.returncode,
                   'stdoutBase64': base64.b64encode(result.stdout).decode(), 'stderrBase64': base64.b64encode(result.stderr).decode()}
        save_private(directory / 'source-failure.private.json', receipt)
        raise RuntimeError('Source metadata observation failed; private receipt retained')
    source = json.loads(result.stdout)
    proof = {'schema': 'ccrelay.workspace_metadata_capture.v1', 'startedAt': started, 'finishedAt': time.time(),
             'producerSha256': hashlib.sha256(code).hexdigest(), 'source': save_private(directory / 'mac-metadata.private.json', source)}
    comparison = compare(source, ROOT)
    proof['comparison'] = save_private(directory / 'comparison.private.json', comparison)
    proof['counts'] = {key: len(value) for key, value in comparison.items() if isinstance(value, list)}
    proof['sourceProblems'] = len(source['problems'])
    proof['fileContentsVerified'] = False
    save_private(directory / 'capture-receipt.json', proof)
    print(json.dumps(proof))


def leaf_differences(source, target):
    actual = {row['name']: row for row in target['entries']}
    output = {key: [] for key in ('differentOrMissing', 'sameContentsOrLink', 'sourceAbsent', 'errors')}
    for row in source['entries']:
        other = actual.get(row['name'])
        if 'error' in row or other is None or 'error' in other:
            output['errors'].append({'source': row, 'pc': other})
        elif row['kind'] == 'absent':
            output['sourceAbsent'].append(row)  # Never a PC deletion instruction.
        elif row['kind'] not in ('file', 'symlink'):
            output['errors'].append({'source': row, 'pc': other})
        else:
            keys = ('kind', 'bytes', 'sha256') if row['kind'] == 'file' else ('kind', 'target')
            key = 'sameContentsOrLink' if all(row.get(field) == other.get(field) for field in keys) else 'differentOrMissing'
            output[key].append(row)
    return output


def hash_candidates(directory):
    # Hash the complete missing/size/type/link-different candidate set from the
    # private metadata walk, not just Git status. Same-size files remain OPEN.
    from inventory_migration_dirty import observe, MAX_PATHS
    from stream_owner_tools import safe_name
    directory = private_directory(directory)
    raw = (directory / 'comparison.private.json').read_bytes()
    if len(raw) > MAX_OUTPUT:
        raise ValueError('Metadata comparison byte bound')
    comparison = json.loads(raw)
    if comparison.get('schema') != 'ccrelay.workspace_metadata_comparison.v1' or comparison['sourceProblems'] or comparison['errors']:
        raise ValueError('Problem-free metadata observation required')
    candidates = comparison['missing'] + [row['source'] for row in comparison['different']]
    names = sorted(relative(row['name']) for row in candidates if row['kind'] in ('file', 'symlink'))
    if not 0 < len(names) <= MAX_PATHS or len(set(names)) != len(names):
        raise ValueError('Unique bounded metadata candidate leaves required')
    code = {name: Path(__file__).with_name(name + '.py').read_text() for name in ('inventory_migration_git', 'inventory_migration_dirty')}
    # Native modules run from memory only; no Mac helper/temp files are written.
    program = "import json,sys,types,os; assert sys.platform=='darwin' and os.getuid()==501\n"
    for name, text in code.items():
        program += 'm=types.ModuleType(' + repr(name) + ');sys.modules[m.__name__]=m;exec(' + repr(text) + ',m.__dict__)\n'
    program += "names=json.loads(sys.stdin.buffer.read());json.dump(m.observe(m.ROOT,names),sys.stdout,separators=(',',':'))"
    payload = base64.b64encode(program.encode()).decode()
    command = '/opt/homebrew/bin/python3.14 -I -B -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(payload) + '))')
    started = time.time()
    result = subprocess.run(['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                             '-o', 'ConnectTimeout=10', '-T', 'mac', command], input=json.dumps(names).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if result.returncode or result.stderr or len(result.stdout) > MAX_OUTPUT:
        raise RuntimeError('Selected source contents observation failed; no archive selection emitted')
    source = json.loads(result.stdout)
    if [row['name'] for row in source['entries']] != names:
        raise ValueError('Source observation changed the requested path set')
    target = observe(ROOT, names)
    differences = leaf_differences(source, target)
    proof = {'schema': 'ccrelay.workspace_candidate_content_capture.v1', 'startedAt': started, 'finishedAt': time.time(),
             'source': save_private(directory / 'candidate-source.private.json', source),
             'pc': save_private(directory / 'candidate-pc.private.json', target),
             'comparison': save_private(directory / 'candidate-content-differences.private.json', differences),
             'counts': {key: len(value) for key, value in differences.items()},
             'sourceBytesHashed': source['fileBytesHashed'], 'pcBytesHashed': target['fileBytesHashed'],
             'allWorkspaceContentsVerified': False, 'sourceWritersFrozen': False, 'targetModified': False}
    rows, incompatible = [], []
    for row in differences['differentOrMissing']:
        try:
            safe_name(row['name'])
        except ValueError:
            incompatible.append(row)
            continue
        rows.append(row)
    proof['incompatibleNames'] = len(incompatible)
    if incompatible:
        proof['incompatible'] = save_private(directory / 'incompatible-capture-names.private.json', incompatible)
    proof['selections'] = []
    # Existing protected receiver independently validates exact leaves and
    # forbids activation. Its legacy schema name does not imply Git-status scope.
    for index in range(0, len(rows), 4000):
        batch = rows[index:index + 4000]
        name = 'candidate-selection-' + str(index // 4000 + 1) + '.private.json'
        selection = {'schema': 'ccrelay.dirty_source_selection.v1', 'entries': batch}
        encoded = json.dumps(selection, ensure_ascii=True, separators=(',', ':')).encode()
        if len(encoded) > 4 << 20:
            raise ValueError('Existing exact-leaf receiver selection byte bound')
        proof['selections'].append({'name': name, 'entries': len(batch), 'fileBytes': sum(r.get('bytes', 0) for r in batch if r['kind'] == 'file'),
                                    **save_private(directory / name, selection)})
    save_private(directory / 'candidate-content-receipt.json', proof)
    print(json.dumps(proof))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--compare-source':
        capture(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == '--hash-candidates':
        hash_candidates(sys.argv[2])
    elif len(sys.argv) == 1 and (sys.platform == 'darwin' and os.getuid() == 501 or sys.platform == 'linux' and os.getuid() == 1000):
        print(json.dumps(tree(ROOT), ensure_ascii=True, separators=(',', ':')))
    else:
        raise SystemExit('Only literal personal Mac/PC metadata inventory admitted')
