#!/usr/bin/env python3
"""Read-only PC seed checks. Never resume a session, run hooks or print messages."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

OWNER_ROOT = Path('/Users/pouya')
WORKSPACE = OWNER_ROOT / '.openclaw/workspace'
PROJECTS = (
    ('startup-ideas', -5238984877, None),
    ('ai-hil', -1003550185469, 1876),
    ('ai-hil/.worktrees/supervisor-fw', -1003550185469, 5786),
    ('claude-code-relay', -1003550185469, 816),
    ('kicad-copilot-research', -1003550185469, 6004),
    ('hardware-lite', -1003550185469, 6333),
    ('marginal-requests', -1004395661179, 427),
    ('qwen-lab', -1003550185469, 10656),
    ('schematic-pipeline-lab', -1004395661179, 2697),
    ('ai-hil/demos/fpga/mpu6000-i9', -1003550185469, 8653),
    ('ai-hil/web', -1003550185469, 8660),
    ('ai-hil/hardware/augur-1', -1004395661179, 18),
    ('ai-hil/hardware/duts', -1004395661179, 53),
    ('mimic-fast-pcb', -1004395661179, 3315),
)
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
DB_NAMES = {'goals_1.sqlite', 'logs_2.sqlite', 'memories_1.sqlite',
            'queue_1.sqlite', 'state_5.sqlite', 'thread_history_1.sqlite'}


def regular_file(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Regular non-symlink file required')
    return path


def digest(path):
    with regular_file(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def pin(path):
    if not path.exists() and not path.is_symlink():
        return None
    value = regular_file(path).read_text().strip()
    if not UUID.fullmatch(value):
        raise ValueError('Invalid exact session pin')
    return value


def inspect_history(path, tool, session_id, workspace):
    regular_file(path)
    sha = hashlib.sha256()
    records = 0
    identity_seen = False
    cwd_seen = False
    messages = 0
    with path.open('rb') as source:
        for line in source:
            sha.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('Invalid transcript record')
            records += 1
            if tool == 'codex':
                payload = row.get('payload')
                if row.get('type') == 'session_meta' and isinstance(payload, dict):
                    if payload.get('id') != session_id or payload.get('cwd') != workspace:
                        raise ValueError('Codex session metadata mismatch')
                    identity_seen = cwd_seen = True
                messages += row.get('type') in ('response_item', 'event_msg')
            elif tool == 'claude':
                identity_seen |= row.get('sessionId') == session_id
                cwd_seen |= row.get('cwd') == workspace
                messages += row.get('type') in ('user', 'assistant')
            else:
                raise ValueError('Unknown native history format')
    if not identity_seen or not cwd_seen or not messages:
        raise ValueError('Pinned history identity, workspace or messages missing')
    return {'id': session_id, 'records': records, 'messageRecords': messages,
            'bytes': path.stat().st_size, 'sha256': sha.hexdigest(),
            'identityMatched': True, 'workspaceMatched': True}


def inspect_databases(root):
    receipt = json.loads(regular_file(root / 'capture.json').read_text())
    entries = receipt['databases']
    if len(entries) != 6 or {item['name'] for item in entries} != DB_NAMES:
        raise ValueError('All six captured databases required')
    output = []
    for item in entries:
        path = regular_file(root / item['name'])
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Captured database digest mismatch')
        # These are closed backup-API snapshots, never a live WAL database.
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Captured database integrity failure')
        output.append({'name': item['name'], 'sha256': item['sha256'], 'quickCheck': 'ok'})
    return output


def inspect_binding(workspace, state, codex_root, claude_root, state_db):
    key = 'cr-' + hashlib.md5(str(workspace).encode()).hexdigest()[:10]
    output = {'workspace': str(workspace), 'key': key, 'workspaceExists': workspace.is_dir(),
              'backend': None, 'histories': {}, 'reconciliation': []}
    if not output['workspaceExists']:
        raise ValueError('Bound workspace missing')
    backend_path = state / ('backend-' + key + '.json')
    if backend_path.exists():
        backend = json.loads(regular_file(backend_path).read_text()).get('backend')
        if backend not in ('codex', 'claude', 'opencode'):
            raise ValueError('Unrecognized selected backend; explicit reconciliation required')
        output['backend'] = backend
    else:
        output['reconciliation'].append('selected-backend-missing')
    for tool, kind in (('codex', 'codex-thread'), ('claude', 'claude-session')):
        session_id = pin(state / (kind + '-' + key + '.txt'))
        if session_id is None:
            if output['backend'] == tool:
                output['reconciliation'].append('selected-session-pin-missing')
            continue
        if tool == 'codex':
            matches = list(codex_root.glob('sessions/**/*' + session_id + '.jsonl'))
            matches += list(codex_root.glob('archived_sessions/**/*' + session_id + '.jsonl'))
            if len(matches) != 1:
                raise ValueError('Exact Codex rollout absent or ambiguous')
            history = matches[0]
            with closing(sqlite3.connect(state_db.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                row = db.execute('SELECT id, cwd FROM threads WHERE id = ?', (session_id,)).fetchone()
            if row != (session_id, str(workspace)):
                raise ValueError('Exact Codex state record absent or mismatched')
        else:
            project = re.sub('[^a-zA-Z0-9]', '-', str(workspace))
            history = claude_root / 'projects' / project / (session_id + '.jsonl')
        output['histories'][tool] = inspect_history(history, tool, session_id, str(workspace))
    return output


def main():
    if len(sys.argv) != 2 or not re.fullmatch('[0-9a-f]{32}', sys.argv[1]):
        raise ValueError('Exact migration run required')
    if os.getuid() != 1000 or OWNER_ROOT.is_symlink() or OWNER_ROOT.stat().st_uid != 1000:
        raise ValueError('Ordinary PC owner required')
    if stat.S_IMODE(OWNER_ROOT.stat().st_mode) != 0o700:
        raise ValueError('Private PC owner home required')
    seeds = OWNER_ROOT / '.migration' / sys.argv[1] / 'native-seeds'
    for directory in (OWNER_ROOT / '.migration', seeds.parent, seeds,
                      seeds / 'codex-home-file', seeds / 'claude-home-file',
                      seeds / 'codex-sqlite-snapshot'):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Expected preserved native seed directory')
    databases = inspect_databases(seeds / 'codex-sqlite-snapshot')
    bindings = []
    for relative, chat, topic in PROJECTS:
        record = {'chat': chat, 'topic': topic, 'project': relative}
        try:
            record.update(inspect_binding(WORKSPACE / relative, WORKSPACE / 'scripts/relay-work',
                                         seeds / 'codex-home-file', seeds / 'claude-home-file',
                                         seeds / 'codex-sqlite-snapshot/state_5.sqlite'))
            record['validCapturedHistory'] = True
        except (OSError, ValueError, sqlite3.Error) as error:
            # Never echo a malformed record, conversation text or exception message.
            record.update(validCapturedHistory=False, errorType=type(error).__name__)
        bindings.append(record)
    print(json.dumps({'schema': 'ccrelay.migration.history_seed_check.v1', 'uid': os.getuid(),
                      'migrationRun': sys.argv[1], 'databases': databases, 'bindings': bindings,
                      'modelsStarted': False, 'sessionsResumed': False,
                      'consistentFinalSnapshot': False, 'routingChanged': False}))
    return 0 if all(item['validCapturedHistory'] for item in bindings) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(json.dumps({'errorType': type(error).__name__, 'modelsStarted': False}))
        sys.exit(2)
