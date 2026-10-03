#!/usr/bin/env python3
"""Own one fresh native stream for the C# migration client's acceptance check.

No imported history, source writer, tool, hook, MCP or Remote Control is enabled.
Only initialize and one fixed inert subscription prompt are accepted. This is
not an operational launcher and cannot resume or replay a project task.
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
import subprocess
import sys
import time
import traceback
import uuid

OWNER = Path('/Users/pouya')
PROMPT = 'Reply exactly MIGRATION_CLAUDE_WIRE_OK. Do not use any tools.'
MAXIMUM_FRAME_BYTES = 2_097_152


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate diagnostic JSON key')
        result[key] = value
    return result


def validate_input(frame, session, initialized, sent):
    if not isinstance(frame, dict):
        raise ValueError('Diagnostic object required')
    if frame.get('type') == 'control_request' and not initialized:
        if set(frame) != {'type', 'request_id', 'request'} or \
                not isinstance(frame['request_id'], str) or not re.fullmatch('khadang-claude-[0-9]+', frame['request_id']) or \
                frame['request'] != {'subtype': 'initialize', 'hooks': None}:
            raise ValueError('Only one native initialization is allowed')
        return 'initialize'
    if frame.get('type') == 'user' and initialized and not sent:
        if set(frame) != {'type', 'message', 'parent_tool_use_id', 'session_id', 'uuid', 'priority', 'origin'} or \
                frame['message'] != {'role': 'user', 'content': PROMPT} or frame['parent_tool_use_id'] is not None or \
                frame['origin'] != {'kind': 'human'} or \
                frame['session_id'] != session or frame['priority'] != 'now' or \
                not isinstance(frame['uuid'], str) or str(uuid.UUID(frame['uuid'])) != frame['uuid']:
            raise ValueError('Only one exact fresh diagnostic input is allowed')
        return 'user'
    raise ValueError('No control, prompt, approval or replay outside this diagnostic')


def run(run_id):
    if not re.fullmatch('[0-9a-f]{32}', run_id) or sys.platform != 'linux' or os.getuid() != 1000 or \
            os.geteuid() != 1000 or os.environ.get('HOME') != str(OWNER):
        raise ValueError('Exact ordinary Linux owner and fresh run required')
    os.umask(0o077)
    state = OWNER / '.migration' / ('claude-wire-' + run_id)
    state.mkdir(mode=0o700)
    report = {'run': run_id, 'uid': 1000, 'complete': False, 'modelPromptsSent': 0,
              'existingConversationsResumed': False, 'routingChanged': False, 'remoteEnrollment': False}
    child = None
    selector = selectors.DefaultSelector()
    try:
        denied = False
        try:
            descriptor = os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi', os.O_RDONLY)
            os.close(descriptor)  # Never read any bytes on boundary failure.
        except OSError as error:
            denied = error.errno in (errno.EACCES, errno.EPERM)
        if not denied:
            raise ValueError('Actual protected credential denial required')
        report['credentialReadDenied'] = True
        profile = module('wire_profile', 'check-pc-claude-remote.py')
        transport = module('wire_transport', 'check-pc-claude-transport.py')
        home, config = profile.prepare_profile(state)
        image = transport.pinned_binary()
        session = str(uuid.uuid4())
        report['nativeSessionId'] = session
        environment = {'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(config), 'USER': 'pou', 'PATH': '/usr/bin:/bin',
                       'LANG': 'C.UTF-8', 'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
                       'CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL': '1',
                       'CLAUDE_CODE_RESUME_INTERRUPTED_TURN': '0', 'CLAUDE_CODE_SDK_READS_SESSION_STATE': '1'}
        arguments = [str(transport.BINARY), '--print', '--input-format', 'stream-json', '--output-format', 'stream-json',
                     '--verbose', '--include-partial-messages', '--replay-user-messages', '--session-id', session,
                     '--setting-sources=', '--settings', '{"disableAllHooks":true,"cleanupPeriodDays":3650}',
                     '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
        with (state / 'stderr.private.txt').open('xb') as error:
            child = subprocess.Popen(arguments, cwd=state, env=environment, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=error, start_new_session=True)
            report['nativePid'] = child.pid
            executable = Path('/proc', str(child.pid), 'exe').stat()
            rows = [line for line in Path('/proc', str(child.pid), 'status').read_text().splitlines() if line.startswith('Uid:')]
            if (image.st_dev, image.st_ino) != (executable.st_dev, executable.st_ino) or \
                    len(rows) != 1 or rows[0].split()[1:] != ['1000'] * 4:
                raise ValueError('Pinned ordinary-owner native child required')
            report['nativeUid'] = 1000
            print(json.dumps({'type': 'migration_claude_ready', 'session_id': session, 'uid': 1000,
                              'native_uid': 1000, 'native_pid': child.pid, 'credential_read_denied': True}), flush=True)
            selector.register(sys.stdin.buffer, selectors.EVENT_READ, 'parent')
            selector.register(child.stdout, selectors.EVENT_READ, 'native')
            buffers = {'parent': bytearray(), 'native': bytearray()}
            initialized = sent = False
            deadline = time.monotonic() + 90
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Diagnostic deadline reached; never replay')
                for key, _ in selector.select(min(remaining, 1)):
                    body = os.read(key.fd, 65536)
                    label = key.data
                    if not body:
                        if buffers[label]:
                            raise ValueError('Partial native/parent diagnostic frame')
                        selector.unregister(key.fileobj)
                        if label == 'parent':
                            child.stdin.close()
                        elif 'parent' in [entry.data for entry in selector.get_map().values()]:
                            selector.unregister(sys.stdin.buffer)
                        continue
                    buffers[label].extend(body)
                    while b'\n' in buffers[label]:
                        line, _, tail = buffers[label].partition(b'\n')
                        buffers[label] = bytearray(tail)
                        if len(line) > MAXIMUM_FRAME_BYTES:
                            raise ValueError('Oversized diagnostic frame')
                        if label == 'parent':
                            frame = json.loads(line, object_pairs_hook=unique_object)
                            kind = validate_input(frame, session, initialized, sent)
                            initialized |= kind == 'initialize'
                            sent |= kind == 'user'
                            if kind == 'user':
                                report['modelPromptsSent'] = 1
                            child.stdin.write(line + b'\n')
                            child.stdin.flush()
                        else:
                            with (state / 'frames.private.jsonl').open('ab') as output:
                                output.write(line + b'\n')
                            sys.stdout.buffer.write(line + b'\n')
                            sys.stdout.buffer.flush()
                    if len(buffers[label]) > MAXIMUM_FRAME_BYTES:
                        raise ValueError('Oversized partial diagnostic frame')
            report['streamEnded'] = True
    except Exception as error:
        report['failureType'] = type(error).__name__
        with (state / 'failure.private.txt').open('x') as output:
            traceback.print_exc(file=output)
    finally:
        selector.close()
        if child:
            if not child.stdin.closed:
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
            report['nativeStopped'] = child.poll() is not None
            report['nativeExitCode'] = child.returncode
        report['complete'] = bool(report.get('streamEnded') and report.get('nativeStopped') and
                                  report.get('nativeExitCode') == 0 and report['modelPromptsSent'] == 1)
        with (state / 'result.json').open('x') as output:
            json.dump(report, output)
        print(json.dumps(report), file=sys.stderr, flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    arguments = parser.parse_args()
    sys.exit(run(arguments.run))
