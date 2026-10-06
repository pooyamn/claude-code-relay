"""Personal-PC Unix WebSocket to stdio adapter; never launch or replace native.

Reuses the existing bounded framing, not the deferred role/broker machinery.
The Windows parent must be the limited owner. UID/peer checks here do not grant
company authority or substitute for Windows credential/code ACLs. No fallback,
reconnect, login, enrollment, initialization or action replay is performed.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import selectors
import socket
import stat
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.identity import Denied, peer_credentials, proc_stat
from relay_core.native_rpc import JSONLChannel
from relay_core.native_ws import UnixWSChannel

OWNER = Path('/Users/pouya')
BINARY = OWNER / '.local/share/pc-migration-native/codex-0.160.0/package/bin/codex'
MANAGED_BINARY = OWNER / '.codex/packages/app-server-daemon/releases/local-45a1f15dbce3c1e4ba0d0eb5d8026f1fc75a42f173fad82a6c7520861a9f0f28-x86_64-unknown-linux-musl/bin/codex'
BINARY_SHA256 = '12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad'
SOCKET = OWNER / '.codex/app-server-control/app-server-control.sock'
MAX_FRAME = 2_097_152
DAEMON_DIRECTORY = Path('/tmp/codex-daemon-1000')
WORKSPACE_ROOT = OWNER / '.openclaw/workspace'
# One owner-requested existing project outside the migrated workspace tree.
# Admit this literal directory only, never the whole home or adjacent paths.
ANDROID_WORKSPACE = OWNER / 'android router'
CREDENTIAL = Path('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi')


def attest_workspaces(values):
    """Actual literal directory/UID and OS denial checks, no native/tool action."""
    if not 1 <= len(values) <= 256 or len(set(values)) != len(values):
        raise Denied('Exact unique ordinary-owner workspaces required')
    observed = {}
    for value in values:
        if type(value) is not str or not (value.startswith(str(WORKSPACE_ROOT) + '/') or value == str(ANDROID_WORKSPACE)) or \
                '\\' in value or '//' in value or any(ord(c) < 32 or ord(c) == 127 for c in value) or \
                any(part in ('', '.', '..') for part in value.split('/')[1:]) or value.endswith('/'):
            raise Denied('Exact preserved workspace path required')
        path = Path(value)
        for candidate in reversed([path, *path.parents]):
            metadata = candidate.lstat()
            expected_uid = 1000 if candidate == OWNER or OWNER in candidate.parents else 0
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != expected_uid or metadata.st_mode & 0o022 or \
                    candidate == OWNER and metadata.st_mode & 0o077:
                raise Denied('Literal ordinary-owner workspace and trusted ancestors required')
            observed[candidate] = _identity(metadata)
    try:
        descriptor = os.open(CREDENTIAL, os.O_RDONLY | os.O_CLOEXEC)
    except PermissionError:
        pass
    else:
        os.close(descriptor)  # Never read even one credential byte on failure.
        raise Denied('Ordinary Linux owner can open the protected router credential')

    def verify():
        for candidate, expected in observed.items():
            if _identity(candidate.lstat()) != expected:
                raise Denied('Attested workspace directory identity changed')

    verify()
    return verify


def socket_path(value):
    if value == str(SOCKET) or re.fullmatch(r'/Users/pouya/\.migration/native-transport-[0-9a-f]{32}/native\.sock', value):
        return Path(value)
    raise Denied('Only the native control socket or an explicit migration diagnostic socket is permitted')


def require_owner():
    if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000 or os.environ.get('HOME') != str(OWNER):
        raise Denied('Exact ordinary PC Linux owner required; Windows parent identity needs separate verification')


def _identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid, metadata.st_gid)


def socket_endpoint(path):
    """Accept only the pinned daemon's measured SHA-256 short-socket alias.

    Codex 0.160.0 publishes an owner symlink to /tmp/codex-daemon-UID/HASH,
    where HASH is the exact requested path's SHA-256. Never resolve an arbitrary
    symlink chain. Both the alias and literal target stay checked after connect.
    """
    observed = {}
    parents = (path.parent, OWNER / '.codex' if path == SOCKET else OWNER / '.migration')
    for parent in parents:
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 1000 or metadata.st_mode & 0o077:
            raise Denied('Private literal owner socket directory required')
        observed[parent] = _identity(metadata)
    metadata = path.lstat()
    observed[path] = _identity(metadata)
    alias = stat.S_ISLNK(metadata.st_mode)
    endpoint = path
    if alias:
        endpoint = DAEMON_DIRECTORY / hashlib.sha256(os.fsencode(str(path))).hexdigest()
        if metadata.st_uid != 1000 or os.readlink(path) != str(endpoint):
            raise Denied('Native socket alias differs from pinned exact-path hash')
        temporary = Path('/tmp')
        root_metadata = temporary.lstat()
        daemon_metadata = DAEMON_DIRECTORY.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or root_metadata.st_uid != 0 or stat.S_IMODE(root_metadata.st_mode) != 0o1777 or \
                not stat.S_ISDIR(daemon_metadata.st_mode) or daemon_metadata.st_uid != 1000 or daemon_metadata.st_mode & 0o077:
            raise Denied('Literal sticky temporary root and private ordinary-owner daemon directory required')
        observed[temporary] = _identity(root_metadata)
        observed[DAEMON_DIRECTORY] = _identity(daemon_metadata)
        metadata = endpoint.lstat()
        observed[endpoint] = _identity(metadata)
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != 1000 or metadata.st_mode & 0o077:
        raise Denied('Literal private existing owner socket required; no daemon startup fallback')

    def verify():
        for candidate, expected in observed.items():
            if _identity(candidate.lstat()) != expected:
                raise Denied('Native socket path identity changed')
        if alias and os.readlink(path) != str(endpoint):
            raise Denied('Native socket alias changed')

    verify()
    return endpoint, verify


def _file_identity(metadata):
    return (*_identity(metadata), metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def pinned_binary(path=None):
    # Hash the SAME opened no-follow inode whose identity is later compared to
    # procfs. A hash-then-stat pathname race must not accept substituted bytes.
    path = BINARY if path is None else path
    if path not in (BINARY, MANAGED_BINARY):
        raise Denied('Only the exact reviewed source or managed native package is permitted')
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise Denied('Literal pinned native file required')
        expected = _file_identity(metadata)
        hasher = hashlib.sha256()
        for chunk in iter(lambda: source.read(65536), b''):
            hasher.update(chunk)
        if hasher.hexdigest() != BINARY_SHA256 or _file_identity(os.fstat(source.fileno())) != expected or \
                _file_identity(path.lstat()) != expected:
            raise Denied('Pinned Linux native executable changed')
    return metadata


def peer_binary(process, source_metadata):
    # Native bootstrap copies the pinned CLI to its versioned managed package.
    # Verify that exact copy's bytes AND kernel executable inode, not a guessed
    # PID/path, a current symlink, or any same-version binary found on disk.
    executable = (process / 'exe').stat()
    for path in (BINARY, MANAGED_BINARY):
        if path == BINARY:
            metadata = source_metadata
        else:
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
        if (executable.st_dev, executable.st_ino) != (metadata.st_dev, metadata.st_ino):
            continue
        if path != BINARY:
            metadata = pinned_binary(path)
        return path, metadata
    raise Denied('Socket peer does not execute a reviewed pinned native package')


def connect(value):
    require_owner()
    path = socket_path(value)
    endpoint, verify_socket = socket_endpoint(path)
    expected_exe = pinned_binary()
    if _file_identity(BINARY.lstat()) != _file_identity(expected_exe):
        raise Denied('Pinned Linux native executable changed')
    stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel, channel_fd = None, None
    try:
        stream.settimeout(10)
        stream.connect(str(endpoint))
        peer = peer_credentials(stream)
        if peer.uid != 1000 or peer.gid != 1000:
            raise Denied('Native peer is not the ordinary PC owner')
        process = Path('/proc', str(peer.pid))
        generation = proc_stat((process / 'stat').read_text(), peer.pid)
        executable_path, expected_peer_exe = peer_binary(process, expected_exe)

        def verify():
            verify_socket()
            if _file_identity(BINARY.lstat()) != _file_identity(expected_exe):
                raise Denied('Pinned native file identity changed')
            if _file_identity(executable_path.lstat()) != _file_identity(expected_peer_exe):
                raise Denied('Pinned native peer file identity changed')
            if proc_stat((process / 'stat').read_text(), peer.pid) != generation:
                raise Denied('Native peer generation changed')
            executable = (process / 'exe').stat()
            if (executable.st_dev, executable.st_ino) != (expected_peer_exe.st_dev, expected_peer_exe.st_ino):
                raise Denied('Socket peer does not execute the pinned native binary')
            rows = [line for line in (process / 'status').read_text().splitlines() if line.startswith('Uid:')]
            if len(rows) != 1 or rows[0].split()[1:] != ['1000'] * 4:
                raise Denied('Native peer credentials changed')

        verify()
        stream.setblocking(False)
        channel_fd = stream.detach()
        channel = UnixWSChannel(channel_fd, timeout_ms=30000, max_frame_bytes=MAX_FRAME)
        channel.prepare(time.monotonic() + 10, verify)
        return channel, verify, {'uid': 1000, 'peerUid': peer.uid, 'peerPid': peer.pid,
                                 'peerGeneration': generation, 'socket': str(path), 'socketEndpoint': str(endpoint)}
    except BaseException:
        if channel:
            channel.close()
        elif channel_fd is not None:
            os.close(channel_fd)
        stream.close()
        raise


def bridge(value, workspaces=None):
    verify_workspaces = None
    if workspaces is not None:
        require_owner()
        if value != str(SOCKET):
            raise Denied('Operational connector requires the exact native control socket')
        verify_workspaces = attest_workspaces(workspaces)
    native, verify_peer, observed = connect(value)
    def verify():
        if verify_workspaces is not None:
            verify_workspaces()
        verify_peer()

    if verify_workspaces is not None:
        observed.update(binarySha256=BINARY_SHA256, credentialDenied=True, workspaces=list(workspaces))
    stdio = None
    read_fd, write_fd = None, None
    try:
        verify()  # Bracket workspace and peer observations before readiness.
        read_fd, write_fd = os.dup(0), os.dup(1)
        os.set_blocking(read_fd, False)
        os.set_blocking(write_fd, False)
        stdio = JSONLChannel(read_fd, write_fd, timeout_ms=30000, max_frame_bytes=MAX_FRAME)
        # Adapter metadata is not a native response or authorization evidence.
        stdio.send({'method': 'ccrelay/transport/ready', 'params': observed}, time.monotonic() + 10)
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ, 'input')
            selector.register(native.fds[0], selectors.EVENT_READ, 'native')
            while True:
                verify()
                if b'\n' in stdio.buffer:
                    message, _ = stdio.receive(time.monotonic() + 30)
                    verify()
                    native.send(message, time.monotonic() + 30)
                    continue
                if native.buffer:
                    message, _ = native.receive(time.monotonic() + 30)
                    verify()
                    stdio.send(message, time.monotonic() + 30)
                    continue
                for key, _ in selector.select():
                    if key.data == 'input':
                        body = os.read(read_fd, min(65536, MAX_FRAME + 1 - len(stdio.buffer)))
                        if not body:
                            if stdio.buffer:
                                raise Denied('Incomplete native request at parent EOF; no replay')
                            return observed
                        stdio.buffer.extend(body)
                        if len(stdio.buffer) > MAX_FRAME and b'\n' not in stdio.buffer:
                            raise Denied('Native request exceeds complete-frame bound')
                    else:
                        message, _ = native.receive(time.monotonic() + 30)
                        verify()
                        stdio.send(message, time.monotonic() + 30)
    finally:
        native.close()
        if stdio:
            stdio.close()
        else:
            for descriptor in (read_fd, write_fd):
                if descriptor is not None:
                    os.close(descriptor)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', default=str(SOCKET))
    parser.add_argument('--attest', action='store_true', help='Require operational workspace/credential OS checks')
    parser.add_argument('--workspace', action='append', default=[])
    arguments = parser.parse_args()
    try:
        if arguments.workspace and not arguments.attest:
            raise Denied('Operational workspace checks must not be silently skipped')
        bridge(arguments.socket, arguments.workspace if arguments.attest else None)
    except BaseException as error:
        # Private stderr contains no native payload, credentials or argv.
        print('PC native transport stopped: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
