#!/usr/bin/env python3
"""One-shot personal migration checks for fixed retained project topics.

Create a fresh native history only in fresh mode; continuity resumes that exact
ID. Each mode has one durable claim/input intent and never retries. This does
not poll Telegram, alter routing, copy credentials, or run project work.
"""
import argparse
import hashlib
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pc_claude_stdio as native

PROJECTS = {
    'schematic-pipeline-lab': (-1004395661179, 2697, '0639c6d69c75e8d3e134d99d553fc20defa51ec8dc37e40630640d34b61769a9'),
    'mimic-fast-pcb': (-1004395661179, 3315, 'f3d549789ff8bd2c405fd8f9a98de4a205c6d713a5df23d298308a31b325e61c'),
    'hardware-lite': (-1003550185469, 6333, 'f07f21030466a16ded5fc424a6295ae9e39a43c1afe2759280af609442e600e0'),
    'ai-hil/demos/fpga/mpu6000-i9': (-1003550185469, 8653, '83a2a46049dbf7dd1d8844f2183895fc73a24fbeb4222fd243858b87ec82f414'),
}
COMMAND = 'id -u && sha256sum -- PC-MIGRATION-HANDOFF.md'


def durable(path, value):
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, separators=(',', ':'))
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Evidence:
    def __init__(self, workspace, session, digest, marker, text, continuity):
        self.workspace, self.session, self.digest = workspace, session, digest
        self.marker, self.text, self.continuity = marker, text, continuity
        self.calls, self.results = {}, set()

    def observe(self, frame):
        if frame.get('type') == 'control_request':
            raise ValueError('Unexpected question or approval; do not answer or replay')
        if frame.get('type') not in ('assistant', 'user'):
            return
        blocks = frame.get('message', {}).get('content', [])
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if block.get('type') == 'tool_use':
                name, data, key = block.get('name'), block.get('input', {}), block.get('id')
                if self.continuity or name not in ('Read', 'Bash') or key in self.calls or name in self.calls.values():
                    raise ValueError('Unexpected or repeated migration tool')
                if name == 'Bash' and data.get('command') != COMMAND or name == 'Read' and (
                        data.get('file_path') != self.workspace + '/PC-MIGRATION-HANDOFF.md' or
                        'offset' in data or 'limit' in data):
                    raise ValueError('Migration tool arguments differ')
                self.calls[key] = name
            elif block.get('type') == 'tool_result':
                key = block.get('tool_use_id')
                if key not in self.calls or key in self.results or block.get('is_error'):
                    raise ValueError('Unmatched or failed migration tool result')
                body = block.get('content', '')
                text = body if isinstance(body, str) else '\n'.join(part.get('text', '') for part in body)
                if self.calls[key] == 'Bash' and text.strip().replace('\r\n', '\n') != (
                        '1000\n' + self.digest + '  PC-MIGRATION-HANDOFF.md'):
                    raise ValueError('Actual tool UID or handoff hash mismatch')
                if self.calls[key] == 'Read' and not all(line in text for line in self.text.splitlines() if line):
                    raise ValueError('Handoff read did not contain the full checked file')
                self.results.add(key)

    def complete(self, frame):
        if frame.get('session_id') != self.session or frame.get('subtype') != 'success' or frame.get('is_error') or \
                frame.get('result', '').strip() != self.marker or \
                not self.continuity and (len(self.calls) != 2 or len(self.results) != 2):
            raise ValueError('Exact successful migration result required')


def run(project, session, mode):
    native.require_owner()
    native.session_id(session)
    os.umask(0o077)
    chat, topic, digest = PROJECTS[project]
    workspace = str(native.WORKSPACE_ROOT / project)
    verify_workspace = native.attest_workspaces([workspace])
    handoff = Path(workspace) / 'PC-MIGRATION-HANDOFF.md'
    native.read_pinned(handoff, digest)
    text = handoff.read_text()
    marker = project.upper().replace('-', '_').replace('/', '_') + '_PC_HANDOFF_READY'
    history = native.OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')
    root = native.OWNER / '.migration' / ('topic-native-' + session)
    root.mkdir(mode=0o700, exist_ok=True)
    state = root / mode
    state.mkdir(mode=0o700)  # Existing attempt must be inspected, never repeated.
    durable(state / 'claim.json', {'session': session, 'project': project, 'mode': mode, 'topic': topic,
                                 'chat': chat, 'handoffSha256': digest, 'at': time.time()})
    report = {'complete': False, 'session': session, 'project': project, 'workspace': workspace,
              'chat': chat, 'topic': topic, 'mode': mode, 'routingChanged': False,
              'handoffSha256': digest, 'modelPromptsAttempted': 0, 'uncertain': False}
    child, lease, selector = None, None, None
    try:
        if mode == 'fresh' and history.exists():
            raise ValueError('Fresh native ID already has history; do not replace it')
        if mode == 'continuity':
            prior = json.loads((root / 'fresh/result.json').read_text())
            if not prior.get('complete') or prior['session'] != session or prior['project'] != project:
                raise ValueError('Successful exact fresh check required before continuity')
            native.read_pinned(history, prior['history']['sha256'])
        lease = native.acquire_lease(session)
        image, _ = native.read_pinned(native.BINARY, native.BINARY_SHA256)
        arguments = native.launch_arguments(session, True)
        if mode == 'fresh':
            arguments[arguments.index('--resume=' + session)] = '--session-id=' + session
        settings_index = arguments.index('--settings') + 1
        settings = json.loads(arguments[settings_index])
        settings['disableAllHooks'] = True
        arguments[settings_index] = json.dumps(settings, separators=(',', ':'))
        # Bootstrap has no reason to use other tools or contact project MCPs.
        arguments += ['--tools', 'Read,Bash' if mode == 'fresh' else '',
                      '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
        prompt = ('Migration verification only. Do not change files, delegate, publish, or start project work. '
                  'Use Read without offset/limit to read all of ' + str(handoff) + '. '
                  'Then use Bash with exactly: ' + COMMAND + '. '
                  'After checking UID 1000 and handoff SHA256 ' + digest + ', reply exactly ' + marker + '.') \
            if mode == 'fresh' else (
                'Migration continuity verification only. Do not use tools or start project work. '
                'Reply with the exact migration-ready marker from your previous successful verification turn.')
        with (state / 'stderr.private.txt').open('xb') as error:
            verify_workspace()
            parent = os.getpid()
            child = subprocess.Popen(arguments, cwd=workspace, env=native.launch_environment(),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error,
                                     start_new_session=True, pass_fds=(lease.fileno(),),
                                     preexec_fn=lambda: native.child_guard(parent))
            generation, verify_native = native.native_observation(child, image, lease)
            report.update(nativePid=child.pid, nativeGeneration=generation, nativeUid=1000)
            print(json.dumps({'state': str(state), 'pid': child.pid, 'session': session, 'mode': mode}), flush=True)
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            buffer, deadline, initialized, submitted, completed = bytearray(), time.monotonic() + 150, False, False, False
            evidence = Evidence(workspace, session, digest, marker, text, mode == 'continuity')
            initialize = {'type': 'control_request', 'request_id': 'topic-migration-initialize',
                          'request': {'subtype': 'initialize', 'hooks': None}}
            child.stdin.write(json.dumps(initialize).encode() + b'\n'); child.stdin.flush()
            while not completed:
                verify_native()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Migration check timed out; inspect this attempt, never replay')
                if not selector.select(min(remaining, 1)):
                    continue
                body = os.read(child.stdout.fileno(), 65536)
                if not body:
                    raise ValueError('Native ended before complete result and idle observation')
                buffer.extend(body)
                while b'\n' in buffer:
                    line, _, tail = buffer.partition(b'\n'); buffer = bytearray(tail)
                    frame = native.decode_frame(line)
                    with (state / 'frames.private.jsonl').open('ab') as output:
                        output.write(line + b'\n')
                    evidence.observe(frame)
                    if frame.get('type') == 'control_response':
                        response = frame.get('response', {})
                        if initialized or response.get('request_id') != 'topic-migration-initialize' or \
                                response.get('subtype') != 'success' or response.get('response', {}).get('session_state') != 'idle':
                            raise ValueError('Native must initialize exactly once and idle')
                        initialized = True
                        input_id = str(uuid.uuid4())
                        payload = {'type': 'user', 'session_id': session, 'uuid': input_id, 'parent_tool_use_id': None,
                                   'message': {'role': 'user', 'content': prompt}, 'priority': 'now', 'origin': {'kind': 'human'}}
                        durable(state / 'input-intent.json', payload)
                        report.update(modelPromptsAttempted=1, uncertain=True, inputId=input_id)
                        child.stdin.write(json.dumps(payload).encode() + b'\n'); child.stdin.flush()
                    if frame.get('type') == 'result':
                        evidence.complete(frame); submitted = True
                    if submitted and frame.get('type') == 'system' and frame.get('subtype') == 'session_state_changed' and \
                            frame.get('state') == 'idle':
                        completed = True
                if len(buffer) > native.MAXIMUM_FRAME_BYTES:
                    raise ValueError('Oversized partial native migration frame')
            report.update(nativeIdleAfterResult=True, uncertain=False, toolOwnerVerified=mode == 'fresh',
                          continuityVerified=mode == 'continuity')
    except BaseException as error:
        report['failureType'] = type(error).__name__
        with (state / 'failure.private.txt').open('x') as output:
            traceback.print_exc(file=output)
    finally:
        if selector:
            selector.close()
        if child:
            native.stop_owned(child)
            child.stdout.close()
            report.update(nativeStopped=child.poll() is not None, nativeExitCode=child.returncode)
        if lease:
            lease.close()
        if history.exists():
            with history.open('rb') as source:
                report['history'] = {'path': str(history), 'bytes': history.stat().st_size,
                                     'sha256': hashlib.file_digest(source, 'sha256').hexdigest()}
        report['complete'] = bool(report.get('nativeIdleAfterResult') and report.get('nativeStopped') and
                                  report.get('nativeExitCode') == 0 and not report['uncertain'])
        report['at'] = time.time()
        durable(state / 'result.json', report)
        print(json.dumps(report), flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', choices=PROJECTS, required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--mode', choices=('fresh', 'continuity'), required=True)
    options = parser.parse_args()
    sys.exit(run(options.project, options.session, options.mode))
