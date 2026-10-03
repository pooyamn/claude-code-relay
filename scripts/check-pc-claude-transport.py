#!/usr/bin/env python3
"""Measure native Claude headless/Remote Control compatibility, not production.

Fresh credential-free profiles only. No prompt, imported session, tools, hook,
MCP connection or automatic retry. The exact native parser/control outcome is
retained privately so the operational transport can preserve phone continuity.
"""
import argparse
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import traceback
import uuid

OWNER = Path('/Users/pouya')
BINARY = OWNER / '.local/share/pc-migration-native/claude-2.1.288/claude'
BINARY_SHA256 = '0298068b686e7fdbaf9402a7a587bb7f49c0b0e084de09f69145a0719207640c'


def pinned_binary():
    descriptor = os.open(BINARY, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        hasher = hashlib.sha256()
        for chunk in iter(lambda: source.read(65536), b''):
            hasher.update(chunk)
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_mode)
        if hasher.hexdigest() != BINARY_SHA256 or identity(before) != identity(os.fstat(source.fileno())) or identity(before) != identity(BINARY.lstat()):
            raise ValueError('Pinned native Claude bytes/identity changed')
    return before


def check_mode(root, mode, context):
    state = root / mode
    state.mkdir(mode=0o700)
    fresh_home = state / 'empty-owner-home'
    fresh_home.mkdir(mode=0o700)
    config = fresh_home / '.claude'
    config.mkdir(mode=0o700)
    session = str(uuid.uuid4())
    environment = {'HOME': str(fresh_home), 'USER': 'pou', 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                   'CLAUDE_CONFIG_DIR': str(config), 'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
                   'CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL': '1',
                   'CLAUDE_CODE_RESUME_INTERRUPTED_TURN': '0', 'CLAUDE_CODE_SDK_READS_SESSION_STATE': '1'}
    arguments = [str(BINARY), '--print', '--output-format', 'stream-json', '--verbose',
                 '--input-format', 'stream-json', '--include-partial-messages', '--session-id', session,
                 '--setting-sources=', '--settings', '{"disableAllHooks":true,"cleanupPeriodDays":3650}',
                 '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
    if mode == 'headless-remote-control':
        arguments += ['--remote-control', 'Isolated compatibility probe']
    result = {'mode': mode, 'uid': os.getuid(), 'credentialsCopied': False, 'modelPromptsSent': 0,
              'existingConversationsResumed': False, 'phoneContinuityVerified': False, 'initialized': False}
    child = control = None
    try:
        binary = pinned_binary()
        with (state / 'stderr.private.txt').open('xb') as error:
            child = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error,
                                     env=environment, cwd=state, start_new_session=True)
            result['nativePid'] = child.pid
            executable = Path('/proc', str(child.pid), 'exe').stat()
            if (executable.st_dev, executable.st_ino) != (binary.st_dev, binary.st_ino):
                raise ValueError('Owned child does not execute the pinned Claude image')
            rows = [line for line in Path('/proc', str(child.pid), 'status').read_text().splitlines() if line.startswith('Uid:')]
            if len(rows) != 1 or rows[0].split()[1:] != ['1000'] * 4:
                raise ValueError('Actual native child must have ordinary owner credentials')
            result['nativeUid'] = 1000
            control = context.IdleControl(child, state, session)
            initialized = control.call('initialize')
            with (state / 'initialize.private.json').open('x') as output:
                json.dump(initialized, output)
            result['initializeKeys'] = sorted(initialized)
            result['initialSessionState'] = initialized.get('session_state')
            if result['initialSessionState'] != 'idle':
                raise ValueError('Diagnostic native session must remain idle')
            result['initialized'] = True
            result['observedEvents'] = control.events
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
            # Any remaining stdout is private argument/control diagnostics,
            # never a prompt response (no user/model input was sent).
            with (state / 'remaining-stdout.private.txt').open('xb') as output:
                descriptor = child.stdout.fileno()
                os.set_blocking(descriptor, False)
                retained = 0
                while retained <= 2_097_152:
                    try:
                        body = os.read(descriptor, min(65536, 2_097_153 - retained))
                    except BlockingIOError:
                        result['remainingStdoutEnded'] = False
                        break
                    if not body:
                        result['remainingStdoutEnded'] = True
                        break
                    output.write(body)
                    retained += len(body)
                result['remainingStdoutBytes'] = retained
                result['remainingStdoutExceededBound'] = retained > 2_097_152
            child.stdout.close()
            result['nativeStopped'] = child.poll() is not None
            result['nativeExitCode'] = child.returncode
        result['controlReadComplete'] = bool(result['initialized'] and result.get('nativeStopped') and result.get('nativeExitCode') == 0
                                            and result.get('remainingStdoutEnded') and not result.get('remainingStdoutExceededBound'))
        with (state / 'result.json').open('x') as output:
            json.dump(result, output)
    return result


def check(run):
    if not re.fullmatch('[0-9a-f]{32}', run) or sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000 or os.environ.get('HOME') != str(OWNER):
        raise ValueError('Exact ordinary Linux owner and fresh run required')
    os.umask(0o077)
    root = OWNER / '.migration' / ('claude-transport-' + run)
    root.mkdir(mode=0o700)
    denied = False
    try:
        descriptor = os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi', os.O_RDONLY)
        os.close(descriptor)  # Never read credential bytes even on boundary failure.
    except OSError as error:
        denied = error.errno in (errno.EACCES, errno.EPERM)
    if not denied:
        raise ValueError('Actual protected bot credential denial required')
    spec = importlib.util.spec_from_file_location('context', Path(__file__).with_name('check-pc-claude-context.py'))
    context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context)
    result = {'run': run, 'uid': 1000, 'credentialReadDenied': True, 'modelPromptsSent': 0,
              'routingChanged': False, 'phoneContinuityVerified': False, 'checks': []}
    for mode in ('headless', 'headless-remote-control'):
        observed = check_mode(root, mode, context)
        result['checks'].append(observed)
        if not observed.get('nativeStopped'):
            break
    result['nativeStopped'] = all(item.get('nativeStopped') for item in result['checks'])
    result['complete'] = len(result['checks']) == 2 and all(item['controlReadComplete'] for item in result['checks'])
    with (root / 'result.json').open('x') as output:
        json.dump(result, output)
    print(json.dumps(result), flush=True)
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    arguments = parser.parse_args()
    try:
        sys.exit(check(arguments.run))
    except (ValueError, OSError) as error:
        print(json.dumps({'complete': False, 'failureType': type(error).__name__, 'modelPromptsSent': 0}), flush=True)
        sys.exit(2)
