#!/usr/bin/env python3
"""Inspect native Claude's idle resume. Never send a prompt or authorize tools."""
import hashlib
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

OWNER = Path('/Users/pouya')
BINARY = OWNER / '.local/share/pc-migration-native/claude-2.1.288/claude'
BINARY_SHA256 = '0298068b686e7fdbaf9402a7a587bb7f49c0b0e084de09f69145a0719207640c'
READS = {'initialize', 'get_context_usage'}
COST_FIELDS = {'type', 'sessionId', 'hasUnknownModelCost', 'modelUsage', 'startTime',
               'totalAPIDuration', 'totalAPIDurationWithoutRetries', 'totalCostUSD',
               'totalDuration', 'totalLinesAdded', 'totalLinesRemoved', 'totalToolDuration'}


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Literal regular file required')
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def inspect_native_append(path, before, session_id):
    """Native idle exit appends cost-state; require all existing bytes intact."""
    prefix = hashlib.sha256()
    with path.open('rb') as source:
        remaining = before['bytes']
        while remaining:
            block = source.read(min(remaining, 262144))
            if not block:
                raise ValueError('Native resume truncated preserved history')
            prefix.update(block)
            remaining -= len(block)
        suffix = source.read()
    if prefix.hexdigest() != before['sha256']:
        raise ValueError('Native resume changed preserved history bytes')
    rows = [json.loads(line) for line in suffix.splitlines() if line.strip()]
    for row in rows:
        if not isinstance(row, dict) or row.get('type') != 'cost-state' or row.get('sessionId') != session_id or set(row) != COST_FIELDS:
            raise ValueError('Unexpected native transcript append; retain before accepting resume')
        if not isinstance(row['hasUnknownModelCost'], bool) or not isinstance(row['modelUsage'], dict):
            raise ValueError('Malformed native cost-state metadata')
        if any(not isinstance(row[key], (int, float)) or isinstance(row[key], bool)
               for key in COST_FIELDS - {'type', 'sessionId', 'hasUnknownModelCost', 'modelUsage'}):
            raise ValueError('Malformed native cost-state counts')
    return {'preservedPrefixIdentical': True, 'historyUnchanged': not suffix,
            'appendBytes': len(suffix), 'costStateRows': len(rows),
            'observedSessionIds': sorted({row['sessionId'] for row in rows})}


def summarize_context(response):
    categories = response.get('categories', [])
    messages = [row for row in categories if isinstance(row, dict) and row.get('name') == 'Messages']
    if len(messages) != 1 or not isinstance(messages[0].get('tokens'), int) or messages[0]['tokens'] <= 0:
        raise ValueError('Native original message context missing')
    return {'messageTokens': messages[0]['tokens'],
            'counts': {key: value for key, value in response.items()
                       if isinstance(value, (int, float)) and not isinstance(value, bool)}}


class IdleControl:
    def __init__(self, child, state, session_id):
        self.child, self.state = child, state
        self.session_id = session_id
        self.sequence = 0
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(child.stdout, selectors.EVENT_READ)
        self.events = []

    def call(self, subtype):
        if subtype not in READS:
            raise ValueError('Idle migration control permits initialization and context reads only')
        self.sequence += 1
        request_id = 'migration-read-' + str(self.sequence)
        request = {'subtype': subtype}
        if subtype == 'initialize':
            request['hooks'] = None
        payload = {'type': 'control_request', 'request_id': request_id, 'request': request}
        self.child.stdin.write(json.dumps(payload).encode() + b'\n')
        self.child.stdin.flush()
        deadline = time.monotonic() + 60
        while True:
            end = self.buffer.find(b'\n')
            if end < 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.selector.select(remaining):
                    raise TimeoutError('Native control outcome unavailable; retain attempt, no restart')
                data = os.read(self.child.stdout.fileno(), 65536)
                if not data:
                    raise OSError('Native control stream ended')
                self.buffer.extend(data)
                if len(self.buffer) > 16 * 1024 * 1024:
                    raise ValueError('Native control frame exceeds explicit bound')
                continue
            message = json.loads(bytes(self.buffer[:end]))
            del self.buffer[:end + 1]
            with (self.state / 'frames.private.jsonl').open('ab') as output:
                output.write(json.dumps(message).encode() + b'\n')
            kind = message.get('type')
            if kind == 'control_response':
                response = message.get('response', {})
                if response.get('request_id') != request_id or response.get('subtype') != 'success':
                    raise ValueError('Native control rejected or reply ID mismatched; private frame retained')
                return response.get('response', {})
            if kind != 'system' or message.get('subtype') not in ('init', 'session_state_changed', 'session_title_changed'):
                raise ValueError('Unexpected model/action/request during idle context check')
            if message.get('session_id') is not None and message['session_id'] != self.session_id:
                raise ValueError('Native event belongs to another session')
            if message.get('subtype') == 'session_title_changed' and message.get('session_id') != self.session_id:
                raise ValueError('Stored title must belong to the exact preserved session')
            if message.get('subtype') == 'session_state_changed' and message.get('state') != 'idle':
                raise ValueError('Native session unexpectedly active')
            self.events.append({key: message.get(key) for key in ('type', 'subtype', 'session_id', 'cwd', 'state')})


def inspect_session(history, migration_run, run, relative):
    os.umask(0o077)
    if not all(re.fullmatch('[0-9a-f]{32}', value) for value in (migration_run, run)) or os.getuid() != 1000:
        raise ValueError('Exact migration runs and ordinary Linux owner required')
    if digest(BINARY) != BINARY_SHA256:
        raise ValueError('Signed pinned native Claude required')
    for entry in Path('/proc').glob('[0-9]*/exe'):
        try:
            if entry.resolve() == BINARY:
                raise ValueError('Existing Linux Claude preserved; no second writer')
        except (OSError, RuntimeError):
            continue
    workspace = history.WORKSPACE / relative
    key = 'cr-' + hashlib.md5(str(workspace).encode()).hexdigest()[:10]
    session_id = history.pin(history.WORKSPACE / 'scripts/relay-work' / ('claude-session-' + key + '.txt'))
    if not session_id:
        raise ValueError('Exact preserved Claude pin required')
    transcript = OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', str(workspace)) / (session_id + '.jsonl')
    preserved = history.inspect_history(transcript, 'claude', session_id, str(workspace))
    state = OWNER / '.migration' / migration_run / ('claude-idle-context-' + run) / key
    state.mkdir(mode=0o700)
    report = {'complete': False, 'requestedSessionId': session_id, 'workspace': str(workspace),
              'uid': os.getuid(), 'modelPromptsSent': 0, 'routingChanged': False,
              'toolsEnabled': False, 'customizationsEnabled': False, 'beforeHistory': preserved}
    child = control = None
    try:
        environment = {'HOME': str(OWNER), 'USER': 'pou', 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                       'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
                       'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                       'CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL': '1',
                       'CLAUDE_CODE_RESUME_INTERRUPTED_TURN': '0',
                       'CLAUDE_CODE_SDK_READS_SESSION_STATE': '1'}
        arguments = [str(BINARY), '--print', '--output-format', 'stream-json', '--verbose',
                     '--input-format', 'stream-json', '--resume=' + session_id, '--safe-mode',
                     '--setting-sources=', '--settings', '{"cleanupPeriodDays":3650,"disableAllHooks":true}',
                     '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
        with (state / 'stderr.private.txt').open('xb') as error:
            child = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error,
                                     cwd=workspace, env=environment, start_new_session=True)
            report['pid'] = child.pid
            uids = next(line for line in Path('/proc', str(child.pid), 'status').read_text().splitlines() if line.startswith('Uid:'))
            if any(value != '1000' for value in uids.split()[1:]):
                raise ValueError('Native child must be the ordinary Linux owner')
            control = IdleControl(child, state, session_id)
            for subtype in ('initialize', 'get_context_usage'):
                response = control.call(subtype)
                with (state / (subtype + '.private.json')).open('x') as output:
                    json.dump(response, output)
                report[subtype + 'Keys'] = sorted(response)
                if subtype == 'initialize':
                    report['initialSessionState'] = response.get('session_state')
                    if report['initialSessionState'] != 'idle':
                        raise ValueError('Native initialization must stay idle')
                else:
                    report['context'] = summarize_context(response)
            report['events'] = control.events
            report['controlReadComplete'] = True
    except Exception as error:
        report['failureType'] = type(error).__name__
        with (state / 'failure.private.txt').open('x') as output:
            output.write(str(error))
    finally:
        if control:
            control.selector.close()
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
            report['nativeExitCode'] = child.returncode
        report['afterHistorySha256'] = digest(transcript)
        try:
            report['history'] = inspect_native_append(transcript, preserved, session_id)
        except (ValueError, OSError) as error:
            report['failureType'] = type(error).__name__
            with (state / 'history-failure.private.txt').open('x') as output:
                output.write(str(error))
        report['complete'] = bool(report.get('controlReadComplete') and report.get('nativeStopped')
                                  and report.get('nativeExitCode') == 0 and report.get('history', {}).get('preservedPrefixIdentical'))
        with (state / 'result.json').open('x') as output:
            json.dump(report, output)
    return report


def retained_evidence(state, history, migration_run, previous_run):
    if not re.fullmatch('[0-9a-f]{32}', previous_run):
        raise ValueError('Exact prior inspection run required')
    prior = OWNER / '.migration' / migration_run / ('claude-idle-context-' + previous_run)
    receipt = json.loads((prior / 'result.json').read_text())
    retained = {}
    for result in receipt['checks']:
        session_id = result['requestedSessionId']
        workspace = result['workspace']
        if workspace not in {str(history.WORKSPACE / relative) for relative, _, _ in history.PROJECTS} or workspace in retained:
            raise ValueError('Prior evidence has a foreign or duplicate workspace')
        key = 'cr-' + hashlib.md5(workspace.encode()).hexdigest()[:10]
        if history.pin(history.WORKSPACE / 'scripts/relay-work' / ('claude-session-' + key + '.txt')) != session_id:
            raise ValueError('Prior evidence differs from the exact preserved pin')
        transcript = OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', workspace) / (session_id + '.jsonl')
        if result['uid'] != 1000 or result['modelPromptsSent'] != 0 or not result.get('nativeStopped') or digest(transcript) != result['afterHistorySha256']:
            raise ValueError('Prior native evidence changed; retain without relaunch')
        if result['complete']:
            if result['initialSessionState'] != 'idle' or result['nativeExitCode'] != 0 or not result['history']['preservedPrefixIdentical'] or result['context']['messageTokens'] <= 0:
                raise ValueError('Prior idle resume evidence incomplete')
        retained[workspace] = {**result, 'evidenceRun': previous_run, 'reusedEvidence': True,
                               'heldForReconciliation': not result['complete']}
    with (state / 'retained-evidence.json').open('x') as output:
        json.dump(retained, output)
    return retained


def main(migration_run, run, previous_run=None):
    os.umask(0o077)
    if not all(re.fullmatch('[0-9a-f]{32}', value) for value in (migration_run, run)) or os.getuid() != 1000:
        raise ValueError('Exact migration runs and ordinary Linux owner required')
    spec = importlib.util.spec_from_file_location('history', Path(__file__).with_name('verify-pc-migration-histories.py'))
    history = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(history)
    relative_paths = []
    for relative, _, _ in history.PROJECTS:
        workspace = history.WORKSPACE / relative
        key = 'cr-' + hashlib.md5(str(workspace).encode()).hexdigest()[:10]
        if history.pin(history.WORKSPACE / 'scripts/relay-work' / ('claude-session-' + key + '.txt')):
            relative_paths.append(relative)
    if len(relative_paths) != 10:
        raise ValueError('All ten preserved Claude pins required')
    state = OWNER / '.migration' / migration_run / ('claude-idle-context-' + run)
    state.mkdir(mode=0o700)
    retained = retained_evidence(state, history, migration_run, previous_run) if previous_run else {}
    report = {'complete': False, 'uid': os.getuid(), 'modelPromptsSent': 0, 'routingChanged': False, 'checks': []}
    for relative in relative_paths:
        result = retained.get(str(history.WORKSPACE / relative))
        if result is None:
            result = inspect_session(history, migration_run, run, relative)
            result['evidenceRun'] = run
            result['heldForReconciliation'] = not result['complete']
        report['checks'].append(result)
        # A rejected/held idle resume is not retried. Other independent pins
        # may be inspected only after the owned child is confirmed stopped.
        if not result.get('nativeStopped'):
            break
    report['nativeStopped'] = all(result.get('nativeStopped') for result in report['checks'])
    report['complete'] = len(report['checks']) == 10 and all(result['complete'] for result in report['checks'])
    with (state / 'result.json').open('x') as output:
        json.dump(report, output)
    print(json.dumps(report))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    try:
        if len(sys.argv) not in (3, 4):
            raise ValueError('Migration and inspection runs required')
        sys.exit(main(*sys.argv[1:]))
    except (OSError, ValueError) as error:
        print(json.dumps({'failureType': type(error).__name__, 'modelPromptsSent': 0}))
        sys.exit(2)
