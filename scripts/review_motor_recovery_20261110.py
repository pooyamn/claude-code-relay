"""Exact read-only owner recovery audit; never execute or rewrite native history."""
import copy
import hashlib
import io
import json
from pathlib import Path
import re

from pc_claude_stdio import no_session_writer, quiescent_history, reviewed_monitor_ids

PIN = '8cd2d34c-0805-4705-8197-d11de0728499'
WORKSPACE = '/Users/pouya/.openclaw/workspace/motorcontrol-plant'
CHECKPOINT = Path('/mnt/c/Users/pou/AppData/Local/Temp/motor-checkpoint-20261110.json')
CHECKPOINT_SHA = '2702841a79a54a13e9731a5872a0dce5f6f5778738fe804dd76abce6ec36cae9'
WAITER = 'b67rjbnzg'
LOG = WORKSPACE + '/build/regress/ab1-chain.log'
WAIT_COMMAND = f'until grep -q CHAIN_DONE {LOG}; do sleep 120; done; cat {LOG}'


def main():
    no_session_writer(PIN)
    raw = CHECKPOINT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CHECKPOINT_SHA:
        raise ValueError('Protected diagnostic checkpoint changed')
    checkpoint = json.loads(raw)
    if checkpoint['session_id'] != PIN or checkpoint['workspace'] != WORKSPACE:
        raise ValueError('Wrong exact checkpoint')
    path = Path(checkpoint['history']['path'])
    before = path.stat()
    body = path.read_bytes()
    boundary = checkpoint['history']['bytes']
    if hashlib.sha256(body[:boundary]).hexdigest() != checkpoint['history']['sha256'] or body[boundary-1:boundary] != b'\n':
        raise ValueError('Reviewed prefix changed')
    rows = [json.loads(line) for line in body[boundary:].splitlines()]
    normalized = copy.deepcopy(rows)
    uses, notifications, observers, agents = {}, [], [], []
    for row in normalized:
        origin = row.get('origin')
        if isinstance(origin, dict) and origin.get('kind') == 'task-notification':
            if set(origin) != {'kind', 'producer', 'runId'} or origin['producer'] != 'session-task' or not re.fullmatch(r'[a-z0-9]{9}-[a-f0-9]{8}', origin['runId']):
                raise ValueError('Unknown task-notification origin')
            notifications.append({'uuid': row.get('uuid'), 'runId': origin.pop('runId')})
        content = row.get('message', {}).get('content', [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get('type') == 'tool_use':
                uses[block['id']] = block
        result = row.get('toolUseResult')
        if row.get('type') != 'user' or not isinstance(result, dict):
            continue
        blocks = [b for b in content if b.get('type') == 'tool_result']
        if result.get('isAsync') is True and result.get('status') == 'async_launched':
            if len(blocks) != 1 or uses[blocks[0]['tool_use_id']].get('name') not in ('Agent', 'Task') or not re.fullmatch(r'a[0-9a-f]{16}', result.get('agentId', '')):
                raise ValueError('Unproven async agent identity')
            agents.append({'task': result['agentId'], 'tool': blocks[0]['tool_use_id']})
            blocks[0]['content'] = 'Command running in background with ID: ' + result['agentId'] + '.'
        if result.get('backgroundTaskId') == WAITER:
            if len(blocks) != 1:
                raise ValueError('Ambiguous waiter tool')
            use = uses[blocks[0]['tool_use_id']]
            if use.get('name') != 'Bash' or use.get('input', {}).get('command') != WAIT_COMMAND or use['input'].get('run_in_background') is not True:
                raise ValueError('Only the exact read-only grep/sleep observer is eligible')
            observers.append({'task': WAITER, 'tool': blocks[0]['tool_use_id'], 'command': WAIT_COMMAND,
                'disposition': 'observer interrupted; regression outcome not asserted, never rerun'})
            blocks[0]['content'] = 'Owner reconciled this exact interrupted read-only observer; no execution requested.'
    if len(observers) != 1 or len(agents) != 1 or len(notifications) != 8:
        raise ValueError('Exact reviewed tail changed')
    for process in Path('/proc').glob('[0-9]*'):
        try:
            argv = (process / 'cmdline').read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if LOG.encode() in argv or WAITER.encode() in argv:
            raise ValueError('Read-only observer still has a live producer')
    source = io.BytesIO(body)
    monitors = reviewed_monitor_ids(source, boundary, PIN, WORKSPACE)
    quiescent_history(io.BytesIO(b''.join((json.dumps(r)+'\n').encode() for r in normalized)),
        PIN, WORKSPACE, initially_terminal=True, reviewed_monitors=monitors)
    no_session_writer(PIN)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('History changed during review')
    print(json.dumps({'schema': 'ccrelay.owner_motor_recovery_audit.v1', 'session': PIN, 'workspace': WORKSPACE,
        'oldCheckpointSha256': CHECKPOINT_SHA,
        'history': {'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()},
        'notifications': notifications, 'asyncAgents': agents, 'interruptedReadOnlyObservers': observers,
        'recordsReviewed': len(rows), 'pendingTools': 0, 'pendingQueue': 0, 'historyQuiescent': True,
        'transcriptModified': False, 'inputReplay': 0, 'regressionChainCompletionClaimed': False}))


if __name__ == '__main__':
    main()
