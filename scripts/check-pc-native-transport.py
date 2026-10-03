"""Own one isolated credential-free Linux native server for the Windows probe.

Only fresh diagnostic state is used. Closing the probe's stdin stops its owned
server; existing native processes, profiles and conversations are never used.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pc_native_stdio import BINARY, BINARY_SHA256, OWNER, bridge, require_owner


def check(run):
    require_owner()
    if not re.fullmatch('[0-9a-f]{32}', run) or BINARY.is_symlink() or hashlib.sha256(BINARY.read_bytes()).hexdigest() != BINARY_SHA256:
        raise ValueError('Exact run and native executable required')
    os.umask(0o077)
    state = OWNER / '.migration' / ('native-transport-' + run)
    state.mkdir(mode=0o700)  # No exist_ok: prior attempts are preserved, not replayed.
    empty_home = state / 'empty-native-home'
    empty_home.mkdir(mode=0o700)
    denied = False
    try:
        descriptor = os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi', os.O_RDONLY)
        os.close(descriptor)  # Never read credential bytes even if the boundary fails.
    except OSError as error:
        denied = error.errno in (errno.EACCES, errno.EPERM)
    if not denied:
        raise ValueError('Actual protected bot credential denial required')
    environment = {'HOME': str(OWNER), 'USER': 'pou', 'PATH': '/usr/bin:/bin',
                   'LANG': 'C.UTF-8', 'CODEX_HOME': str(empty_home)}
    child = None
    result = {'run': run, 'uid': os.getuid(), 'credentialReadDenied': denied,
              'isolatedCredentialFreeHome': True, 'existingConversationsResumed': False,
              'modelsStarted': False, 'productionChanged': False, 'complete': False,
              'stage': 'launch-isolated-native'}
    try:
        with (state / 'native.stdout.private.txt').open('xb') as output, (state / 'native.stderr.private.txt').open('xb') as error:
            child = subprocess.Popen([str(BINARY), '-c', 'cli_auth_credentials_store="file"',
                                      'app-server', '--listen', 'unix://' + str(state / 'native.sock')],
                                     env=environment, cwd=state, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=error, start_new_session=True)
            result['nativePid'] = child.pid
            deadline = time.monotonic() + 15
            while not (state / 'native.sock').exists():
                if child.poll() is not None:
                    raise OSError('Owned native listener exited before readiness')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned native listener never became ready')
                time.sleep(.05)  # Observe only this confirmed live child; no RPC replay.
            result['stage'] = 'connect-isolated-native'
            metadata = (state / 'native.sock').lstat()
            result['socketUid'] = metadata.st_uid
            result['socketGid'] = metadata.st_gid
            result['socketMode'] = oct(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                result['socketLinkTarget'] = os.readlink(state / 'native.sock')
                target = (state / 'native.sock').resolve(strict=True)
                target_metadata = target.lstat()
                parent_metadata = target.parent.lstat()
                result['socketResolvedPath'] = str(target)
                result['socketResolvedMode'] = oct(target_metadata.st_mode)
                result['socketResolvedUid'] = target_metadata.st_uid
                result['socketResolvedParentMode'] = oct(parent_metadata.st_mode)
                result['socketResolvedParentUid'] = parent_metadata.st_uid
            bridge(str(state / 'native.sock'))
            result['complete'] = True
            result['stage'] = 'parent-closed'
    except BaseException as error:
        # This fixture has no credentials, model output or existing history.
        # Retain the actual failed gate privately, not just its exception class.
        result['errorType'] = type(error).__name__
        if hasattr(error, 'native_envelope_shape'):
            result['nativeEnvelopeShape'] = error.native_envelope_shape
        with (state / 'failure.private.txt').open('x') as output:
            traceback.print_exc(file=output)
        raise
    finally:
        if child:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=10)
            result['nativeStopped'] = child.poll() is not None
            result['nativeExitCode'] = child.returncode
        with (state / 'result.json').open('x') as output:
            json.dump(result, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    arguments = parser.parse_args()
    try:
        check(arguments.run)
    except BaseException as error:
        print('PC native diagnostic stopped: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
