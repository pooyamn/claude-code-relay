"""Read-only Git inventory for private migration evidence, never an action replay.

Includes nested repositories, bare repositories and linked-worktree markers.
Does not fetch, refresh/write indexes, run fsmonitor/hooks, follow directory
symlinks, read credential configuration or claim a quiescent filesystem snapshot.
Stdout contains private paths/refs/status: save it privately, not in public Git.
"""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


ROOT = Path('/Users/pouya/.openclaw/workspace')
MAX_DIRECTORIES = 250000
MAX_REPOSITORIES = 4096
MAX_OUTPUT = 16 << 20


def git(root, *arguments, bare=False):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    environment.update(GIT_CONFIG_SYSTEM='/dev/null', GIT_CONFIG_GLOBAL='/dev/null',
                       GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', GIT_PAGER='cat', LC_ALL='C')
    command = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
               '-c', 'core.untrackedCache=false', '-c', 'core.hooksPath=/dev/null',
               '-C', str(root), '--git-dir=' + str(root if bare else Path(root) / '.git')]
    if not bare:
        command.append('--work-tree=' + str(root))
    command.extend(arguments)
    # Temporary stdout is not used: a bounded streaming pipe prevents both
    # source disk writes and unbounded status/ref output allocations.
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    import selectors
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    chunks, total, deadline = [], 0, time.monotonic() + 30
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise TimeoutError('Git observation deadline')
            for key, _ in selector.select(0.5):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                total += len(data)
                if total > MAX_OUTPUT:
                    raise ValueError('Git observation output bound')
                chunks.append(data)
        code = process.wait(timeout=2)
        return code, b''.join(chunks)
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def repositories(root):
    result, problems, count = [], [], 0
    root = Path(root)

    def visit(directory, descriptor, depth):
        nonlocal count
        count += 1
        if count > MAX_DIRECTORIES or len(result) >= MAX_REPOSITORIES or depth > 256:
            raise ValueError('Repository discovery bound')
        try:
            before = os.fstat(descriptor)
            with os.scandir(descriptor) as entries:
                children = {entry.name: entry.stat(follow_symlinks=False) for entry in entries}
            marker = children.get('.git')
            bare = not marker and all(name in children for name in ('HEAD', 'objects', 'refs')) and \
                stat.S_ISREG(children['HEAD'].st_mode) and stat.S_ISDIR(children['objects'].st_mode)
            if marker:
                if not (stat.S_ISDIR(marker.st_mode) or stat.S_ISREG(marker.st_mode)):
                    raise ValueError('Unsupported Git marker')
                result.append((directory, 'linked-marker' if stat.S_ISREG(marker.st_mode) else 'directory-marker'))
            elif bare:
                result.append((directory, 'bare'))
            if not bare:
                for name, value in sorted(children.items()):
                    if name == '.git' or not stat.S_ISDIR(value.st_mode):
                        continue
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                    try:
                        actual = os.fstat(child)
                        if (value.st_dev, value.st_ino) != (actual.st_dev, actual.st_ino):
                            raise ValueError('Child directory replaced during discovery')
                        visit(directory / name, child, depth + 1)
                    finally:
                        os.close(child)
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != \
                    (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('Directory changed during discovery')
        except (OSError, ValueError) as error:
            problems.append({'path': directory.relative_to(root).as_posix(), 'error': type(error).__name__})

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(root, descriptor, 0)
    finally:
        os.close(descriptor)
    return sorted(result), problems, count


def inventory(root):
    root = Path(root)
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
        raise ValueError('Literal root required')
    found, problems, directories = repositories(root)
    observations = []
    for path, marker in found:
        row = {'path': path.relative_to(root).as_posix(), 'marker': marker}
        try:
            commands = {'head': ('rev-parse', '--verify', 'HEAD'),
                        'refs': ('for-each-ref', '--format=%(refname) %(objectname)'),
                        'worktrees': ('worktree', 'list', '--porcelain'),
                        'gitDirectories': ('rev-parse', '--git-dir', '--git-common-dir')}
            if marker != 'bare':
                commands['status'] = ('status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=all')
            for name, arguments in commands.items():
                code, output = git(path, *arguments, bare=marker == 'bare')
                row[name] = {'exit': code, 'base64': base64.b64encode(output).decode('ascii')}
            row['refsStableAcrossRead'] = git(path, *commands['refs'], bare=marker == 'bare') == \
                (row['refs']['exit'], base64.b64decode(row['refs']['base64']))
            row['headStableAcrossRead'] = git(path, *commands['head'], bare=marker == 'bare') == \
                (row['head']['exit'], base64.b64decode(row['head']['base64']))
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
            row['error'] = type(error).__name__
        observations.append(row)
    return {'schema': 'ccrelay.migration_git_inventory.v1', 'root': str(root), 'uid': os.getuid(),
            'directoriesObserved': directories, 'repositories': observations, 'discoveryProblems': problems,
            'sourceWritersFrozen': False, 'consistentFinalSnapshot': False,
            'symlinkDirectoriesFollowed': False, 'ignoredFileContentsInventoried': False,
            'gitOptionalLocks': False, 'fsmonitorAndHooksEnabled': False, 'networkFetchPerformed': False}


if __name__ == '__main__':
    if len(sys.argv) != 1 or os.getuid() not in (501, 1000) or sys.platform not in ('darwin', 'linux'):
        raise SystemExit('Only literal Mac/PC workspace inventory is admitted')
    json.dump(inventory(ROOT), sys.stdout, ensure_ascii=True, separators=(',', ':'))
    print()
