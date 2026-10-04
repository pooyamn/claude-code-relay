#!/usr/bin/env python3
"""Personal-PC Claude stream owner; requires an exact reviewed handoff.

This is runtime glue, not a company broker or a diagnostic profile. The Windows
parent must separately prove its limited owner token and protected code/policy.
Resume only the exact saved ID, or create the exact ID in a protected explicit
owner-switch manifest. Never fork, copy credentials, reconnect or replay input.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pc_native_stdio import OWNER, WORKSPACE_ROOT, _file_identity, attest_workspaces, require_owner
from relay_core.identity import Denied, proc_stat

BINARY = OWNER / '.local/share/pc-migration-native/claude-2.1.288/claude'
BINARY_SHA256 = '0298068b686e7fdbaf9402a7a587bb7f49c0b0e084de09f69145a0719207640c'
MAXIMUM_FRAME_BYTES = 2_097_152
HELD_SESSION = 'b728b1bc-3d36-4178-aa01-fd9e9b056d9c'


def exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise Denied('Exact personal handoff object required')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Denied('Duplicate stream or handoff key')
        result[key] = value
    return result


def decode_frame(body):
    if not body or len(body) > MAXIMUM_FRAME_BYTES:
        raise Denied('Complete bounded native Claude frame required')
    value = json.loads(body.decode('utf-8', errors='strict'), object_pairs_hook=unique_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(Denied('Nonfinite native value')))
    if type(value) is not dict:
        raise Denied('Native Claude object required')
    return value


def session_id(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise Denied('Exact saved native Claude UUID required')
    if value == HELD_SESSION:
        # Actual migration evidence found a pending task_notification on this
        # legacy relay pin. Do not reopen it with auth until reconciled.
        raise Denied('Legacy relay Claude task requires explicit reconciliation')
    return value


def read_pinned(path, digest, *, load_json=False):
    if type(digest) is not str or not re.fullmatch('[a-f0-9]{64}', digest):
        raise Denied('Exact reviewed SHA-256 required')
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or load_json and before.st_size > 65536:
            raise Denied('Literal bounded reviewed file required')
        hasher, body = hashlib.sha256(), bytearray()
        for chunk in iter(lambda: source.read(65536), b''):
            hasher.update(chunk)
            if load_json:
                body.extend(chunk)
                if len(body) > 65536:
                    raise Denied('Handoff exceeds bound')
        if hasher.hexdigest() != digest or _file_identity(before) != _file_identity(os.fstat(source.fileno())) or \
                _file_identity(before) != _file_identity(Path(path).lstat()):
            raise Denied('Reviewed bytes or file identity changed')
    return before, json.loads(body.decode('utf-8'), object_pairs_hook=unique_object) if load_json else None


def validate_handoff(value, workspace, session):
    exact(value, {'schema', 'session_id', 'workspace', 'source_writer', 'uncertain_actions', 'history', 'profile'})
    if value['schema'] != 'ccrelay.personal_claude_handoff.v1' or value['session_id'] != session or \
            value['workspace'] != workspace or value['source_writer'] != 'quiesced' or value['uncertain_actions'] != [] or \
            type(value['uncertain_actions']) is not list or value['profile'] != str(OWNER / '.claude'):
        raise Denied('Exact quiesced handoff with resolved actions and preserved native profile required')
    exact(value['history'], {'path', 'bytes', 'sha256'})
    history = value['history']
    expected = OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')
    if history['path'] != str(expected) or type(history['bytes']) is not int or history['bytes'] <= 0 or \
            type(history['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', history['sha256']):
        raise Denied('Exact target native transcript and checkpoint digest required')
    return expected


def checked_handoff(path, digest, workspace, session):
    session_id(session)
    if type(path) is not str or not re.fullmatch(
            r'/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-[a-f0-9]{32}/handoff-' + re.escape(session) + r'\.json', path):
        raise Denied('Exact protected Windows handoff path required')
    _, value = read_pinned(path, digest, load_json=True)
    if value.get('schema') == 'ccrelay.personal_claude_start.v1':
        exact(value, {'schema', 'session_id', 'workspace', 'source_writer', 'uncertain_actions', 'history', 'profile'})
        if value != {'schema': 'ccrelay.personal_claude_start.v1', 'session_id': session, 'workspace': workspace,
                     'source_writer': 'owner_switch', 'uncertain_actions': [], 'history': None, 'profile': str(OWNER / '.claude')}:
            raise Denied('Exact protected owner-switch start receipt required')
        transcript = OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')
        if transcript.exists() or transcript.is_symlink():
            raise Denied('Fresh Claude ID already has history; never replace or fall back')
        return transcript, None
    transcript = validate_handoff(value, workspace, session)
    # No provider token is read or copied. Inspect actual native state only.
    for candidate in reversed([transcript, *transcript.parents]):
        metadata = candidate.lstat()
        expected_uid = 1000 if candidate == OWNER or OWNER in candidate.parents else 0
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != expected_uid or metadata.st_mode & 0o022 or \
                candidate != transcript and not stat.S_ISDIR(metadata.st_mode):
            raise Denied('Literal ordinary-owner native transcript path required')
    metadata, _ = read_pinned(transcript, value['history']['sha256'])
    if metadata.st_size != value['history']['bytes']:
        raise Denied('Target history differs from the reviewed source handoff')
    return transcript, metadata


def launch_arguments(session, owner_full_access=False):
    session_id(session)
    if type(owner_full_access) is not bool:
        raise Denied('Explicit boolean owner permission policy required')
    # Do NOT inherit the diagnostic's safe mode, empty tool/MCP list or empty
    # setting sources. Keep source profile/model/provider/customizations.
    settings = {'cleanupPeriodDays': 3650, 'env': {
        'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
        'CLAUDE_CODE_RESUME_INTERRUPTED_TURN': '0', 'CLAUDE_CODE_SDK_READS_SESSION_STATE': '1'}}
    return [str(BINARY), '--print', '--input-format', 'stream-json', '--output-format', 'stream-json',
            '--verbose', '--include-partial-messages', '--replay-user-messages', '--resume=' + session,
            '--setting-sources=user,project,local', '--permission-prompt-tool', 'stdio',
            '--permission-mode', 'bypassPermissions' if owner_full_access else 'default',
            '--settings', json.dumps(settings, separators=(',', ':'))]


def launch_environment():
    # Windows launcher must remove WSLENV/provider/router secrets. Native
    # profile files still supply the original project/provider configuration.
    # Native defaults pair HOME/.claude.json with HOME/.claude. Explicitly
    # setting CLAUDE_CONFIG_DIR relocates global JSON into that directory and
    # silently misses the migrated account, MCP and project configuration.
    return {'HOME': str(OWNER), 'USER': 'pou',
            'PATH': '/usr/bin:/bin:' + str(OWNER / '.local/bin'), 'LANG': 'C.UTF-8',
            'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
            'CLAUDE_CODE_RESUME_INTERRUPTED_TURN': '0', 'CLAUDE_CODE_SDK_READS_SESSION_STATE': '1'}


def acquire_lease(session):
    root = OWNER / '.native-remote' / 'claude-stream-leases'
    for directory in (root.parent, root):
        directory.mkdir(mode=0o700, exist_ok=True)
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 1000 or metadata.st_mode & 0o077:
            raise Denied('Private literal ordinary-owner stream lease directory required')
    path = root / (session_id(session) + '.lock')
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    lease = os.fdopen(descriptor, 'r+b')
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 1000 or metadata.st_mode & 0o077 or metadata.st_nlink != 1:
            raise Denied('Private single-link native stream lease required')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lease
    except BaseException:
        lease.close()
        raise


def child_guard(parent):
    # Linux parent-death notification covers an abruptly killed bridge. The
    # inherited kernel lease additionally stays held by the live native child.
    libc = ctypes.CDLL('libc.so.6', use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent:
        os._exit(126)


def native_observation(child, image, lease):
    folder = Path('/proc', str(child.pid))
    generation = proc_stat((folder / 'stat').read_text(), child.pid)
    expected_lease = os.fstat(lease.fileno())

    def verify(allow_exited=False):
        def finished():
            if child.poll() is None:
                return False
            if allow_exited:
                # Drain only the SAME already-owned private stdout pipe. No
                # input, reused PID, connection discovery or new producer.
                return True
            raise Denied('Owned native Claude generation ended or changed')

        if finished():
            return
        try:
            raw = (folder / 'stat').read_text()
            # The owned child may exit between poll() and any procfs read.
            # Only confirmed terminal output on its existing pipe may drain.
            if finished():
                return
            if proc_stat(raw, child.pid) != generation:
                raise Denied('Owned native Claude generation ended or changed')
            executable = (folder / 'exe').stat()
            if (executable.st_dev, executable.st_ino) != (image.st_dev, image.st_ino) or \
                    _file_identity(BINARY.lstat()) != _file_identity(image):
                raise Denied('Native Claude executable identity changed')
            rows = [line for line in (folder / 'status').read_text().splitlines() if line.startswith('Uid:')]
            inherited = (folder / 'fd' / str(lease.fileno())).stat()
            if len(rows) != 1 or rows[0].split()[1:] != ['1000'] * 4 or \
                    (inherited.st_dev, inherited.st_ino) != (expected_lease.st_dev, expected_lease.st_ino):
                raise Denied('Actual native UID and inherited kernel lease required')
        except FileNotFoundError:
            if not finished():
                raise  # Missing procfs while still live is NOT terminal proof.

    verify()
    return generation, verify


def stop_owned(child):
    # Only this Popen child/group; never kill unrelated native processes. An
    # interrupted action stays uncertain in the controller, never resubmitted.
    if child.stdin and not child.stdin.closed:
        try:
            child.stdin.close()
        except BrokenPipeError:
            pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # The same owned group exited between wait and signal.
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)


def run(workspace, session, checkpoint, checkpoint_sha256, owner_full_access=False, model=None):
    require_owner()
    session_id(session)
    if model is not None and (type(model) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._\[\]-]*', model)):
        raise Denied('Literal native model required')
    os.umask(0o077)
    verify_workspace = attest_workspaces([workspace])
    transcript, history = checked_handoff(checkpoint, checkpoint_sha256, workspace, session)
    image, _ = read_pinned(BINARY, BINARY_SHA256)
    lease, child = acquire_lease(session), None
    selector = None
    read_fd = write_fd = None
    try:
        selector = selectors.DefaultSelector()
        # Recheck after obtaining the exclusive lease, immediately before
        # native resume. No startup recovery is allowed to choose a fresh ID.
        verify_workspace()
        if history is not None and _file_identity(transcript.lstat()) != _file_identity(history) or history is None and (transcript.exists() or transcript.is_symlink()):
            raise Denied('Native history changed before exact resume')
        parent = os.getpid()
        arguments = launch_arguments(session, owner_full_access)
        if history is None:
            arguments[arguments.index('--resume=' + session)] = '--session-id=' + session
        if model is not None: arguments += ['--model', model]
        child = subprocess.Popen(arguments, cwd=workspace, env=launch_environment(),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 start_new_session=True, pass_fds=(lease.fileno(),), preexec_fn=lambda: child_guard(parent))
        generation, verify_native = native_observation(child, image, lease)
        verify_workspace()
        ready = {'type': 'ccrelay_claude_ready', 'session_id': session, 'workspace': workspace, 'uid': 1000,
                 'native_uid': 1000, 'native_pid': child.pid, 'native_generation': generation,
                 'binary_sha256': BINARY_SHA256, 'credential_denied': True, 'checkpoint_sha256': checkpoint_sha256,
                 'inherited_lease': True}
        read_fd, write_fd = os.dup(0), os.dup(1)
        os.set_blocking(read_fd, False)
        os.set_blocking(write_fd, False)
        os.set_blocking(child.stdin.fileno(), False)
        os.set_blocking(child.stdout.fileno(), False)
        forward(selector, child, read_fd, write_fd, ready, verify_workspace, verify_native, session)
    finally:
        try:
            if selector is not None:
                selector.close()
            if child is not None:
                stop_owned(child)
        finally:
            if child is not None:
                child.stdout.close()
            for descriptor in (read_fd, write_fd):
                if descriptor is not None:
                    os.close(descriptor)
            lease.close()


def write_frame(descriptor, body, verify):
    # A measured complete-frame delivery deadline, not a retry/recovery policy.
    view = memoryview(body)
    deadline = time.monotonic() + 30
    with selectors.DefaultSelector() as writable:
        writable.register(descriptor, selectors.EVENT_WRITE)
        while view:
            verify()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not writable.select(remaining):
                raise TimeoutError('Claude frame delivery outcome unavailable; never replay')
            try:
                count = os.write(descriptor, view)
            except BlockingIOError:
                continue
            if count <= 0:
                raise BrokenPipeError('Native/parent stream closed')
            view = view[count:]


def forward(selector, child, read_fd, write_fd, ready, verify_workspace, verify_native, session):
    def verify(allow_exited=False):
        verify_workspace()
        verify_native(allow_exited)

    write_frame(write_fd, json.dumps(ready, separators=(',', ':')).encode() + b'\n', verify)
    selector.register(read_fd, selectors.EVENT_READ, 'parent')
    selector.register(child.stdout.fileno(), selectors.EVENT_READ, 'native')
    buffers = {'parent': bytearray(), 'native': bytearray()}
    while True:
        for key, _ in selector.select(1):
            label = key.data
            body = os.read(key.fd, 65536)
            if not body:
                if buffers[label]:
                    raise Denied('Partial native/parent Claude frame at EOF; never replay')
                return  # Controller disposal interrupts only this owned stream.
            verify(label == 'native')
            buffers[label].extend(body)
            while b'\n' in buffers[label]:
                line, _, tail = buffers[label].partition(b'\n')
                buffers[label] = bytearray(tail)
                frame = decode_frame(line)
                if label == 'parent' and frame.get('type') == 'user' and frame.get('session_id') != session:
                    raise Denied('Parent input belongs to a different native session')
                write_frame(child.stdin.fileno() if label == 'parent' else write_fd, line + b'\n',
                            lambda: verify(label == 'native'))
            if len(buffers[label]) > MAXIMUM_FRAME_BYTES:
                raise Denied('Partial Claude frame exceeds bound')
        # An exited child can have a final complete result buffered in stdout.
        # Drain to actual EOF; poll() alone is not delivery/terminal evidence.
        verify_workspace()


def snapshot(workspace, session, checkpoint, checkpoint_sha256):
    """Bounded metadata only, under the same exclusive native-writer lease.

    A protected old checkpoint authenticates the saved scope, not today's
    evolving history hash. The privileged parent pins the new exact bytes
    before another explicit owner-requested launch. No model or auth read.
    """
    require_owner(); session_id(session)
    verify = attest_workspaces([workspace]); verify()
    if not re.fullmatch(r'/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-[a-f0-9]{32}/handoff-' + re.escape(session) + r'\.json', checkpoint):
        raise Denied('Exact protected checkpoint required')
    _, value = read_pinned(checkpoint, checkpoint_sha256, load_json=True)
    exact(value, {'schema', 'session_id', 'workspace', 'source_writer', 'uncertain_actions', 'history', 'profile'})
    if value['session_id'] != session or value['workspace'] != workspace or value['profile'] != str(OWNER / '.claude') or value['uncertain_actions'] != []:
        raise Denied('Saved checkpoint scope differs')
    if value['schema'] == 'ccrelay.personal_claude_handoff.v1':
        validate_handoff(value, workspace, session)
    elif value['schema'] != 'ccrelay.personal_claude_start.v1' or value['source_writer'] != 'owner_switch' or value['history'] is not None:
        raise Denied('Unknown checkpoint mode')
    lease = acquire_lease(session)
    try:
        history = OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')
        observation = None
        if history.exists():
            for candidate in reversed([history, *history.parents]):
                metadata = candidate.lstat()
                expected_uid = 1000 if candidate == OWNER or OWNER in candidate.parents else 0
                if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != expected_uid or metadata.st_mode & 0o022 or \
                        candidate != history and not stat.S_ISDIR(metadata.st_mode):
                    raise Denied('Literal ordinary-owner native transcript path required')
            metadata = history.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 1000 or metadata.st_mode & 0o022 or metadata.st_nlink != 1 or metadata.st_size <= 0:
                raise Denied('Literal private native history required')
            hasher = hashlib.sha256()
            descriptor = os.open(history, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as source:
                before = os.fstat(source.fileno())
                if _file_identity(before) != _file_identity(metadata): raise Denied('Native history identity changed before checkpoint')
                for body in iter(lambda: source.read(65536), b''): hasher.update(body)
                if _file_identity(before) != _file_identity(os.fstat(source.fileno())) or _file_identity(before) != _file_identity(history.lstat()):
                    raise Denied('Native history changed during checkpoint')
            observation = {'path': str(history), 'bytes': before.st_size, 'sha256': hasher.hexdigest()}
        elif history.is_symlink() or value['schema'] != 'ccrelay.personal_claude_start.v1':
            raise Denied('Saved native history missing; no fresh-session fallback')
        verify()
        print(json.dumps({'type': 'ccrelay_claude_snapshot', 'uid': 1000, 'session_id': session, 'workspace': workspace,
                          'history': observation, 'source_writer': 'quiesced', 'model_inference': False}), flush=True)
    finally: lease.close()
    # Keep the verified Windows owner process available for post-read token
    # attestation. The history lease is released; no input is executed.
    sys.stdin.buffer.read(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--checkpoint-sha256', required=True)
    parser.add_argument('--owner-full-access', action='store_true')
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--model')
    arguments = parser.parse_args()
    try:
        if arguments.snapshot:
            snapshot(arguments.workspace, arguments.session, arguments.checkpoint, arguments.checkpoint_sha256)
        else:
            run(arguments.workspace, arguments.session, arguments.checkpoint, arguments.checkpoint_sha256, arguments.owner_full_access, arguments.model)
    except BaseException as error:
        # Never mirror native args, profile, transcript, payloads or tokens.
        print('PC Claude stream stopped: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
