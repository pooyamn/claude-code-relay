"""Hash current dirty/untracked paths for private Mac-to-PC comparison.

This is not an ignored-file inventory, deletion instruction or final snapshot.
Repository paths arrive from the separately retained Git inventory. Contents
are hashed through no-follow descriptors; only private metadata goes to stdout.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

from inventory_migration_git import git, ROOT

MAX_PATHS = 100000
MAX_FILE_BYTES = 64 << 30


def relative(value):
    if not isinstance(value, str) or not value or value.startswith('/') or '\0' in value or \
            any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('Literal workspace-relative path required')
    return value


def status_paths(raw):
    fields = raw.split(b'\0')
    if fields[-1] != b'':
        raise ValueError('Truncated NUL-delimited status')
    index, result = 0, []
    while index < len(fields) - 1:
        field = fields[index]
        index += 1
        if len(field) < 4 or field[2:3] != b' ' or any(c not in b' MADRCUT?!' for c in field[:2]):
            raise ValueError('Invalid porcelain status record')
        result.append(relative(os.fsdecode(field[3:].removesuffix(b'/'))))
        if b'R' in field[:2] or b'C' in field[:2]:
            if index >= len(fields) - 1:
                raise ValueError('Missing rename/copy origin')
            result.append(relative(os.fsdecode(fields[index])))
            index += 1
    return result


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def observe(root, paths, *, max_bytes=MAX_FILE_BYTES, timeout_seconds=850):
    if type(max_bytes) is not int or max_bytes <= 0 or not 0 < len(paths) <= MAX_PATHS or len(set(paths)) != len(paths):
        raise ValueError('Unique bounded source selection required')
    root = Path(root)
    if root.is_symlink() or not root.is_absolute() or root.resolve() != root:
        raise ValueError('Literal workspace root required')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    rows, total, deadline = [], 0, time.monotonic() + timeout_seconds
    try:
        for name in sorted(paths):
            relative(name)
            if time.monotonic() >= deadline:
                raise TimeoutError('Selected file observation deadline')
            descriptors, parent = [], root_fd
            row = {'name': name}
            try:
                parts = name.split('/')
                for component in parts[:-1]:
                    descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    descriptors.append(descriptor)
                    parent = descriptor
                before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                row['mode'] = stat.S_IMODE(before.st_mode)
                if stat.S_ISREG(before.st_mode):
                    if before.st_size > max_bytes - total:
                        raise ValueError('Selected file byte bound')
                    descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    with os.fdopen(descriptor, 'rb', buffering=0) as stream:
                        if identity(os.fstat(stream.fileno())) != identity(before):
                            raise ValueError('Selected file replaced before read')
                        digest, count = hashlib.sha256(), 0
                        while chunk := stream.read(65536):
                            if time.monotonic() >= deadline:
                                raise TimeoutError('Selected file read deadline')
                            count += len(chunk)
                            if count > before.st_size:
                                raise ValueError('Selected file grew during read')
                            digest.update(chunk)
                        if count != before.st_size or identity(os.fstat(stream.fileno())) != identity(before):
                            raise ValueError('Selected file changed during read')
                    row.update(kind='file', bytes=count, sha256=digest.hexdigest())
                    total += count
                elif stat.S_ISLNK(before.st_mode):
                    row.update(kind='symlink', target=os.readlink(parts[-1], dir_fd=parent))
                elif stat.S_ISDIR(before.st_mode):
                    row.update(kind='directory', contentsEnumerated=False)
                else:
                    row.update(kind='special', contentsPreserved=False)
                if identity(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != identity(before):
                    raise ValueError('Selected entry changed during observation')
            except FileNotFoundError:
                row.update(kind='absent', deletePcFile=False)
            except (OSError, ValueError, TimeoutError) as error:
                row = {'name': name, 'error': type(error).__name__}
            finally:
                for descriptor in reversed(descriptors):
                    os.close(descriptor)
            rows.append(row)
    finally:
        os.close(root_fd)
    return {'entries': rows, 'fileBytesHashed': total, 'sourceWritersFrozen': False,
            'consistentFinalSnapshot': False, 'ignoredContentsInventoried': False,
            'directoryContentsEnumerated': False, 'workspaceModified': False}


def dirty(root, specs):
    if not isinstance(specs, list) or not 1 <= len(specs) <= 4096:
        raise ValueError('Bounded repository selection required')
    selections, statuses = set(), []
    for spec in specs:
        prefix = spec['path']
        if prefix != '.':
            relative(prefix)
        if spec['marker'] == 'bare':
            continue
        repository = root if prefix == '.' else Path(root) / prefix
        code, raw = git(repository, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=all')
        statuses.append({'path': prefix, 'exit': code, 'base64': base64.b64encode(raw).decode()})
        if code:
            continue
        for path in status_paths(raw):
            selections.add(path if prefix == '.' else prefix + '/' + path)
        if len(selections) > MAX_PATHS:
            raise ValueError('Dirty source selection bound')
    report = observe(root, sorted(selections)) if selections else {'entries': [], 'fileBytesHashed': 0}
    report.update(schema='ccrelay.migration_dirty_observation.v1', statuses=statuses,
                  statusErrors=sum(row['exit'] != 0 for row in statuses), selectedPaths=len(selections),
                  sourceWritersFrozen=False, consistentFinalSnapshot=False, workspaceModified=False)
    return report


if __name__ == '__main__':
    if len(sys.argv) != 1 or sys.platform not in ('linux', 'darwin') or os.getuid() not in (501, 1000):
        raise SystemExit('Only literal personal Mac/PC dirty-work observation admitted')
    request = sys.stdin.buffer.read(4 << 20)
    if sys.stdin.buffer.read(1):
        raise SystemExit('Request bound exceeded')
    json.dump(dirty(ROOT, json.loads(request)), sys.stdout, ensure_ascii=True, separators=(',', ':'))
    print()
