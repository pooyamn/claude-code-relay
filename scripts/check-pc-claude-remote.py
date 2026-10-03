#!/usr/bin/env python3
"""Enroll and disconnect one fresh native Claude diagnostic; never resume work.

Pinned SDK 0.3.288's enableRemoteControl() sends the explicit remote_control
request below. The CLI flag alone is not enrollment evidence. No model input,
API-key substitution, imported history, hook, tool or MCP is enabled here.
"""
import argparse
import errno
import importlib.util
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
import traceback
from urllib.parse import urlsplit
import uuid

OWNER = Path('/Users/pouya')
ENABLE_REQUEST = {'subtype': 'remote_control', 'enabled': True,
                  'name': 'PC migration diagnostic - no tasks', 'keep_session_on_exit': False}


def load_probe():
    spec = importlib.util.spec_from_file_location('transport_probe', Path(__file__).with_name('check-pc-claude-transport.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_document(path):
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ValueError('Literal owner profile required')
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 1000 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError('Private ordinary-owner profile required')
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
                value.st_mode, value.st_uid, value.st_gid, value.st_nlink)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        if identity(os.fstat(source.fileno())) != identity(metadata):
            raise ValueError('Profile changed before capture')
        body = source.read(1_048_577)
        if len(body) > 1_048_576 or identity(os.fstat(source.fileno())) != identity(metadata) or identity(path.lstat()) != identity(metadata):
            raise ValueError('Oversized or changing profile refused')
    return json.loads(body)


def prepare_profile(state):
    credentials = private_document(OWNER / '.claude/.credentials.json')
    oauth = credentials.get('claudeAiOauth') or {}
    if not all(isinstance(oauth.get(key), str) and oauth[key] for key in ('accessToken', 'refreshToken')) or \
            oauth.get('expiresAt', 0) <= (time.time() + 120) * 1000:
        raise ValueError('Unexpired subscription credentials required; do not refresh source implicitly')
    account = private_document(OWNER / '.claude.json').get('oauthAccount')
    if not isinstance(account, dict) or not account.get('emailAddress'):
        raise ValueError('Existing owner subscription account required')
    home = state / 'fresh-owner-home'
    home.mkdir(mode=0o700)
    config = home / '.claude'
    config.mkdir(mode=0o700)
    with (config / '.credentials.json').open('x') as output:
        json.dump({'claudeAiOauth': oauth}, output)
    # Only account identity and this fresh diagnostic directory's trust. No
    # existing history, plugins, instructions, projects or executable settings.
    with (home / '.claude.json').open('x') as output:
        json.dump({'oauthAccount': account, 'hasCompletedOnboarding': True, 'autoUpdates': False,
                   'projects': {str(state): {'hasTrustDialogAccepted': True}}}, output)
    return home, config


class DiagnosticControl:
    def __init__(self, child, state, session):
        self.child, self.state, self.session = child, state, session
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(child.stdout, selectors.EVENT_READ)
        self.sequence = 0
        self.events = []

    def call(self, request):
        if request not in ({'subtype': 'initialize', 'hooks': None}, ENABLE_REQUEST,
                           {'subtype': 'remote_control', 'enabled': False}) or \
                (request.get('subtype') == 'remote_control' and type(request.get('enabled')) is not bool):
            raise ValueError('Only initialization and fresh Remote Control are permitted')
        self.sequence += 1
        request_id = 'migration-remote-' + str(self.sequence)
        self.child.stdin.write(json.dumps({'type': 'control_request', 'request_id': request_id,
                                          'request': request}).encode() + b'\n')
        self.child.stdin.flush()
        deadline = time.monotonic() + 45
        while True:
            end = self.buffer.find(b'\n')
            if end < 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.selector.select(remaining):
                    raise TimeoutError('Remote request outcome unavailable; retain attempt, never re-enable')
                body = os.read(self.child.stdout.fileno(), 65536)
                if not body:
                    raise OSError('Owned native control stream ended')
                self.buffer.extend(body)
                if len(self.buffer) > 2_097_152:
                    raise ValueError('Diagnostic control frame exceeds bound')
                continue
            message = json.loads(self.buffer[:end])
            del self.buffer[:end + 1]
            with (self.state / 'frames.private.jsonl').open('ab') as output:
                output.write(json.dumps(message).encode() + b'\n')
            if message.get('type') == 'control_response':
                response = message.get('response', {})
                if response.get('request_id') != request_id or response.get('subtype') != 'success':
                    raise ValueError('Native request rejected or reply mismatched; private frame retained')
                return response.get('response') or {}
            if message.get('type') != 'system':
                raise ValueError('Unexpected model, user or authorization request; do not answer automatically')
            if message.get('session_id') not in (None, self.session):
                raise ValueError('Diagnostic event has a foreign local session ID')
            if message.get('subtype') == 'session_state_changed' and message.get('state') != 'idle':
                raise ValueError('Diagnostic must stay idle')
            self.events.append({'type': 'system', 'subtype': message.get('subtype')})


def run_probe(run):
    if not re.fullmatch('[0-9a-f]{32}', run) or sys.platform != 'linux' or os.getuid() != 1000 or \
            os.geteuid() != 1000 or os.environ.get('HOME') != str(OWNER):
        raise ValueError('Fresh run and exact ordinary Linux owner required')
    os.umask(0o077)
    state = OWNER / '.migration' / ('claude-remote-' + run)
    state.mkdir(mode=0o700)
    result = {'run': run, 'uid': 1000, 'complete': False, 'modelPromptsSent': 0,
              'existingConversationsResumed': False, 'routingChanged': False, 'phoneRoundTripVerified': False}
    child = control = None
    try:
        denied = False
        try:
            descriptor = os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi', os.O_RDONLY)
            os.close(descriptor)  # Never read any credential bytes on boundary failure.
        except OSError as error:
            denied = error.errno in (errno.EACCES, errno.EPERM)
        result['credentialReadDenied'] = denied
        if not denied:
            raise ValueError('Actual protected bot credential denial required')
        home, config = prepare_profile(state)
        transport = load_probe()
        image = transport.pinned_binary()
        session = str(uuid.uuid4())
        result['nativeSessionId'] = session
        environment = {'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(config), 'USER': 'pou', 'PATH': '/usr/bin:/bin',
                       'LANG': 'C.UTF-8', 'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
                       'CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL': '1',
                       'CLAUDE_CODE_RESUME_INTERRUPTED_TURN': '0', 'CLAUDE_CODE_SDK_READS_SESSION_STATE': '1'}
        arguments = [str(transport.BINARY), '--print', '--input-format', 'stream-json', '--output-format', 'stream-json',
                     '--verbose', '--include-partial-messages', '--session-id', session, '--setting-sources=',
                     '--settings', '{"disableAllHooks":true,"cleanupPeriodDays":3650}', '--tools', '',
                     '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
        with (state / 'stderr.private.txt').open('xb') as error:
            child = subprocess.Popen(arguments, cwd=state, env=environment, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=error, start_new_session=True)
            result['nativePid'] = child.pid
            executable = Path('/proc', str(child.pid), 'exe').stat()
            if (image.st_dev, image.st_ino) != (executable.st_dev, executable.st_ino):
                raise ValueError('Actual native child differs from the pinned image')
            rows = [line for line in Path('/proc', str(child.pid), 'status').read_text().splitlines() if line.startswith('Uid:')]
            if len(rows) != 1 or rows[0].split()[1:] != ['1000'] * 4:
                raise ValueError('Actual native child must be ordinary owner')
            result['nativeUid'] = 1000
            control = DiagnosticControl(child, state, session)
            initialized = control.call({'subtype': 'initialize', 'hooks': None})
            with (state / 'initialize.private.json').open('x') as output:
                json.dump(initialized, output)
            result['initialSessionState'] = initialized.get('session_state')
            result['remoteAvailable'] = initialized.get('remote_control_available')
            if result['initialSessionState'] != 'idle':
                raise ValueError('Fresh native session must initialize idle')
            remote = control.call(ENABLE_REQUEST)
            with (state / 'remote-enabled.private.json').open('x') as output:
                json.dump(remote, output)
            url = urlsplit(remote.get('session_url', ''))
            if url.scheme != 'https' or url.netloc != 'claude.ai' or not url.path.startswith('/code/') or \
                    not isinstance(remote.get('bridge_session_id'), str) or not remote['bridge_session_id']:
                raise ValueError('Native remote enrollment evidence missing')
            result['remoteEnabled'] = True
            result['remoteResponseKeys'] = sorted(remote)
            disconnected = control.call({'subtype': 'remote_control', 'enabled': False})
            with (state / 'remote-disabled.private.json').open('x') as output:
                json.dump(disconnected, output)
            result['remoteDisabled'] = True
            result['events'] = control.events
    except Exception as error:
        result['failureType'] = type(error).__name__
        with (state / 'failure.private.txt').open('x') as output:
            traceback.print_exc(file=output)
    finally:
        if control:
            control.selector.close()
        if child:
            try:
                child.stdin.close()
            except BrokenPipeError:
                pass
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
            child.stdout.close()
            result['nativeStopped'] = child.poll() is not None
            result['nativeExitCode'] = child.returncode
        result['complete'] = bool(result.get('remoteEnabled') and result.get('remoteDisabled')
                                  and result.get('nativeStopped') and result.get('nativeExitCode') == 0)
        with (state / 'result.json').open('x') as output:
            json.dump(result, output)
    print(json.dumps(result), flush=True)
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    arguments = parser.parse_args()
    try:
        sys.exit(run_probe(arguments.run))
    except (ValueError, OSError) as error:
        print(json.dumps({'complete': False, 'failureType': type(error).__name__, 'modelPromptsSent': 0}), flush=True)
        sys.exit(2)
