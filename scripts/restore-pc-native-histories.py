#!/usr/bin/env python3
"""Restore preserved histories, then read exact Codex IDs without resuming work."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time

OWNER = Path('/Users/pouya')
PACKAGE_DIGEST = '4fcc47ab57f52ff75363951a8761146cd10c8288bd86fed45487dbb204a16b71'
READ_METHODS = {'initialize', 'thread/read', 'thread/loaded/list'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree_signature(root):
    """Hash regular data and symlink targets; never follow a source symlink."""
    entries = []
    paths = [root] + sorted(root.rglob('*')) if root.is_dir() and not root.is_symlink() else [root]
    for path in paths:
        info = path.lstat()
        relative = str(path.relative_to(root))
        if stat.S_ISLNK(info.st_mode):
            entries.append((relative, 'link', os.readlink(path)))
        elif stat.S_ISDIR(info.st_mode):
            entries.append((relative, 'dir', stat.S_IMODE(info.st_mode)))
        elif stat.S_ISREG(info.st_mode):
            entries.append((relative, 'file', info.st_size, digest(path)))
        else:
            raise ValueError('Unsupported object in preserved history')
    encoded = json.dumps(entries, separators=(',', ':')).encode()
    return {'sha256': hashlib.sha256(encoded).hexdigest(),
            'files': sum(entry[1] == 'file' for entry in entries),
            'bytes': sum(entry[2] for entry in entries if entry[1] == 'file')}


def mirror_component(source, target, run):
    if target.exists() or target.is_symlink():
        raise ValueError('Existing destination preserved; reconcile before continuing')
    staging = target.with_name('.' + target.name + '.migration-' + run)
    if staging.exists() or staging.is_symlink():
        raise ValueError('Partial copy preserved; never replay it')
    before = tree_signature(source)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, staging, symlinks=True)
    elif source.is_symlink():
        staging.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, staging)
    if tree_signature(staging) != before or tree_signature(source) != before:
        raise ValueError('History copy changed; retain staging for reconciliation')
    staging.rename(target)
    return before


def detach_migrated_remote_registration(database_path):
    """Exclude host-bound enrollment from a NEW copy, retaining its raw seed.

    Codex's enrollment key excludes installation_id. Copying these rows makes
    a new computer impersonate the source host and yields HTTP 409 when that
    host is online. Native enrollment regenerates them for the new computer;
    conversation/history rows and the archived source are not modified.
    main() calls this only after fresh-destination and stopped-native checks.
    """
    if database_path.is_symlink() or not database_path.is_file():
        raise ValueError('Literal freshly copied state database required')
    with closing(sqlite3.connect(str(database_path))) as db:
        present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remote_control_enrollments'").fetchone()
        removed = 0
        if present:
            with db:
                removed = db.execute('SELECT COUNT(*) FROM remote_control_enrollments').fetchone()[0]
                db.execute('DELETE FROM remote_control_enrollments')
                if db.execute('SELECT COUNT(*) FROM remote_control_enrollments').fetchone()[0]:
                    raise ValueError('Copied host registration was not excluded')
            # Later immutable history checks read the standalone copy, not WAL.
            if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise ValueError('Fresh copy unexpectedly has another database reader/writer')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Sanitized history database failed integrity check')
    return {'copiedRemoteEnrollmentsExcluded': removed, 'sourceSnapshotChanged': False,
            'nativeReenrollmentRequired': bool(removed), 'sanitizedStateSha256': digest(database_path)}


def pinned_executable(install):
    archive = install / 'package.tar.gz'
    if archive.is_symlink() or digest(archive) != PACKAGE_DIGEST:
        raise ValueError('Published Codex package digest required')
    package = install / 'package'
    candidates = [p for p in package.rglob('codex') if p.is_file() and not p.is_symlink()]
    if len(candidates) != 1:
        raise ValueError('Exact installed native executable required')
    binary = candidates[0]
    relative = str(binary.relative_to(package))
    with tarfile.open(archive, 'r:gz') as tar:
        members = [m for m in tar.getmembers() if m.isfile() and m.name.removeprefix('./') == relative]
        if len(members) != 1:
            raise ValueError('Installed executable absent from pinned package')
        with tar.extractfile(members[0]) as stream:
            expected = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest(binary) != expected or binary.read_bytes()[:4] != b'\x7fELF':
        raise ValueError('Installed executable differs from pinned package')
    return binary


def summarize_thread(thread, session_id, workspace):
    if thread.get('id') != session_id or thread.get('cwd') != workspace:
        raise ValueError('Native thread identity or workspace mismatch')
    if thread.get('status', {}).get('type') != 'notLoaded':
        raise ValueError('Read unexpectedly loaded a thread')
    turns = thread.get('turns')
    if not isinstance(turns, list) or not turns:
        raise ValueError('Native full history missing')
    items = [item for turn in turns for item in turn.get('items', [])]
    kinds = sorted({item['type'] for item in items})
    if 'userMessage' not in kinds or 'agentMessage' not in kinds:
        raise ValueError('Native conversation messages missing')
    return {'id': session_id, 'workspace': workspace, 'turns': len(turns),
            'items': len(items), 'itemTypes': kinds, 'status': 'notLoaded'}


class ReadOnlyRPC:
    def __init__(self, child, private_state):
        self.child = child
        self.state = private_state
        self.sequence = 0
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(child.stdout, selectors.EVENT_READ)

    def call(self, method, parameters):
        if method not in READ_METHODS:
            raise ValueError('Migration client permits reads only')
        self.sequence += 1
        request = {'id': self.sequence, 'method': method, 'params': parameters}
        self.child.stdin.write(json.dumps(request).encode() + b'\n')
        self.child.stdin.flush()
        deadline = time.monotonic() + 60
        while True:
            end = self.buffer.find(b'\n')
            if end < 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.selector.select(remaining):
                    raise TimeoutError('Native read outcome unavailable; no restart')
                data = os.read(self.child.stdout.fileno(), 65536)
                if not data:
                    raise OSError('Native stream ended')
                self.buffer.extend(data)
                # The controller seed is 209 MB. Allow its complete read without
                # truncating history; stay bounded below the PC's memory budget.
                if len(self.buffer) > 512 * 1024 * 1024:
                    raise ValueError('Native frame exceeds explicit resource bound')
                continue
            message = json.loads(bytes(self.buffer[:end]))
            del self.buffer[:end + 1]
            if 'method' in message:
                method_name = message['method']
                if 'id' in message or method_name.startswith(('turn/', 'item/')) or method_name == 'thread/started':
                    raise ValueError('Unexpected action/request during read-only inspection')
                continue
            if message.get('id') != self.sequence:
                raise ValueError('Native reply ID mismatch')
            if 'error' in message:
                with (self.state / 'rpc-error.private.json').open('x') as output:
                    json.dump(message['error'], output)
                raise ValueError('Native read rejected; private error retained')
            return message['result']

    def initialized(self):
        self.child.stdin.write(b'{"method":"initialized","params":{}}\n')
        self.child.stdin.flush()

    def close(self):
        self.selector.close()


def main(migration_run, run):
    os.umask(0o077)
    if not all(re.fullmatch('[0-9a-f]{32}', value) for value in (migration_run, run)):
        raise ValueError('Exact migration and inspection runs required')
    if os.getuid() != 1000 or OWNER.is_symlink() or OWNER.stat().st_uid != 1000 or stat.S_IMODE(OWNER.stat().st_mode) != 0o700:
        raise ValueError('Private ordinary PC owner required')
    spec = importlib.util.spec_from_file_location('verified_history', Path(__file__).with_name('verify-pc-migration-histories.py'))
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    seeds = OWNER / '.migration' / migration_run / 'native-seeds'
    checker.inspect_databases(seeds / 'codex-sqlite-snapshot')
    binary = pinned_executable(OWNER / '.local/share/pc-migration-native/codex-0.160.0')
    for entry in Path('/proc').glob('[0-9]*/exe'):
        try:
            if entry.resolve() == binary.resolve():
                raise ValueError('Existing Linux Codex preserved; do not become another writer')
        except (OSError, RuntimeError):
            continue
    codex = OWNER / '.codex'
    claude = OWNER / '.claude'
    for home in (codex, claude):
        if home.is_symlink() or home.exists() and (not home.is_dir() or home.stat().st_uid != 1000):
            raise ValueError('Literal owner-native home required')
    if codex.exists() and set(p.name for p in codex.iterdir()) - {'tmp'}:
        raise ValueError('Existing Codex data/settings preserved; inspect before restoring')
    state = seeds.parent / ('native-history-restore-' + run)
    state.mkdir(mode=0o700)
    report = {'schema': 'ccrelay.migration.native_history_restore.v1', 'complete': False,
              'uid': os.getuid(), 'routingChanged': False, 'sessionsResumed': False,
              'modelTurnsStarted': 0, 'settingsChanged': False, 'loginsChanged': False,
              'components': [], 'nativeReads': [], 'consistentFinalSnapshot': False}
    child = None
    rpc = None
    try:
        for home in (codex, claude):
            home.mkdir(mode=0o700, exist_ok=True)
            home.chmod(0o700)
        components = [(seeds / 'claude-home-file/projects', claude / 'projects')]
        for name in ('sessions', 'archived_sessions', 'history.jsonl', 'session_index.jsonl'):
            source = seeds / 'codex-home-file' / name
            if source.exists() or source.is_symlink():
                components.append((source, codex / name))
        components += [(seeds / 'codex-sqlite-snapshot' / name, codex / name) for name in sorted(checker.DB_NAMES)]
        if any(target.exists() or target.is_symlink() for _, target in components):
            raise ValueError('Existing history component preserved; no overwrite')
        for source, target in components:
            evidence = mirror_component(source, target, run)
            report['components'].append({'component': target.name, **evidence})
            with (state / ('copied-' + target.name + '.json')).open('x') as output:
                json.dump(evidence, output)
        report['hostBoundRegistration'] = detach_migrated_remote_registration(codex / 'state_5.sqlite')
        expected = []
        for relative, _, _ in checker.PROJECTS:
            workspace = checker.WORKSPACE / relative
            key = 'cr-' + hashlib.md5(str(workspace).encode()).hexdigest()[:10]
            session_id = checker.pin(checker.WORKSPACE / 'scripts/relay-work' / ('codex-thread-' + key + '.txt'))
            if session_id:
                with closing(sqlite3.connect((codex / 'state_5.sqlite').as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                    row = db.execute('SELECT cwd, rollout_path FROM threads WHERE id = ?', (session_id,)).fetchone()
                if not row or row[0] != str(workspace) or not Path(row[1]).is_relative_to(codex):
                    raise ValueError('Native state must resolve original local history paths')
                checker.inspect_history(Path(row[1]), 'codex', session_id, str(workspace))
                expected.append((session_id, str(workspace)))
        if len(expected) != 5:
            raise ValueError('All five captured Codex pins required')
        report['nativeExecutableSha256'] = digest(binary)
        with (state / 'native-stderr.private.txt').open('xb') as error:
            environment = {'HOME': str(OWNER), 'CODEX_HOME': str(codex), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
            arguments = [str(binary), '-c', 'cli_auth_credentials_store="file"',
                         '-c', 'check_for_update_on_startup=false', '-c', 'analytics.enabled=false',
                         '-c', 'feedback.enabled=false', 'app-server']
            child = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error,
                                     cwd=state, env=environment, start_new_session=True)
            report['nativePid'] = child.pid
            uids = next(line for line in Path('/proc', str(child.pid), 'status').read_text().splitlines() if line.startswith('Uid:'))
            if any(value != '1000' for value in uids.split()[1:]):
                raise ValueError('Native child must be the ordinary Linux owner')
            rpc = ReadOnlyRPC(child, state)
            initialized = rpc.call('initialize', {'clientInfo': {'name': 'oracova-migration-read', 'version': '1'}})
            report['nativePlatform'] = {key: initialized.get(key) for key in ('platformFamily', 'platformOs')}
            rpc.initialized()
            if rpc.call('thread/loaded/list', {})['data']:
                raise ValueError('Fresh reader unexpectedly owns loaded threads')
            for session_id, workspace in expected:
                reply = rpc.call('thread/read', {'threadId': session_id, 'includeTurns': True})
                report['nativeReads'].append(summarize_thread(reply['thread'], session_id, workspace))
                del reply
            report['loadedThreadsAfterReads'] = rpc.call('thread/loaded/list', {})['data']
            if report['loadedThreadsAfterReads']:
                raise ValueError('Read unexpectedly acquired thread ownership')
        report['complete'] = True
    except Exception as error:
        report['failureType'] = type(error).__name__
        with (state / 'failure.private.txt').open('x') as output:
            output.write(str(error))
    finally:
        if rpc:
            rpc.close()
        if child:
            child.stdin.close()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            child.stdout.close()
            report['nativeStopped'] = child.poll() is not None
        with (state / 'result.json').open('x') as output:
            json.dump(report, output)
    print(json.dumps(report))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ValueError('Migration and inspection runs required')
        sys.exit(main(*sys.argv[1:]))
    except (OSError, ValueError) as error:
        print(json.dumps({'failureType': type(error).__name__, 'modelTurnsStarted': 0}))
        sys.exit(2)
