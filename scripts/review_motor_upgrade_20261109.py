"""Read-only, exact Motor maintenance audit. Never edits history or runs work."""
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import time

from pc_claude_stdio import quiescent_history, reviewed_monitor_ids, _file_identity

PIN = '8cd2d34c-0805-4705-8197-d11de0728499'
ROOT = Path('/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-7193c3efd3344c4c976bff575b2a2734')


def audit():
    checkpoint = ROOT / ('handoff-' + PIN + '.json')
    raw = checkpoint.read_bytes()
    saved = json.loads(raw)
    path = Path(saved['history']['path'])
    before = path.stat()
    body = path.read_bytes()
    boundary = saved['history']['bytes']
    if hashlib.sha256(body[:boundary]).hexdigest() != saved['history']['sha256'] or not body[:boundary].endswith(b'\n'):
        raise ValueError('Authenticated prefix changed')
    rows = [json.loads(line) for line in body[boundary:].splitlines()]
    uses, monitors, notifications = {}, {}, []
    for row in rows:
        content = row.get('message', {}).get('content', [])
        blocks = content if isinstance(content, list) else [{'text': content}]
        if row.get('type') == 'assistant':
            for block in blocks:
                if block.get('type') == 'tool_use' and block.get('name') == 'Monitor':
                    if block['id'] in uses: raise ValueError('Repeated Monitor tool ID')
                    uses[block['id']] = row['uuid']
        result = row.get('toolUseResult')
        if row.get('type') == 'user' and isinstance(result, dict) and 'persistent' in result:
            if result.get('persistent') is not False or not 0 < result.get('timeoutMs', 0) <= 86400000:
                raise ValueError('Persistent or unbounded Monitor')
            results = [b for b in blocks if b.get('type') == 'tool_result' and b.get('tool_use_id') in uses
                       and uses[b['tool_use_id']] == row.get('sourceToolAssistantUUID')]
            if len(results) != 1 or len(blocks) != 1 or result['taskId'] in monitors:
                raise ValueError('Monitor lacks exact native use/result pair')
            from datetime import datetime
            stamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
            if time.time() <= stamp + result['timeoutMs'] / 1000:
                raise ValueError('Monitor still within its running window')
            monitors[result['taskId']] = results[0]['tool_use_id']
        texts = [b.get('text', '') for b in blocks]
        attachment = row.get('attachment', {})
        if isinstance(attachment.get('prompt'), str): texts.append(attachment['prompt'])
        for text in texts:
            if text.startswith('<task-notification>'):
                origin = attachment.get('origin') if text == attachment.get('prompt') else row.get('origin')
                notifications.append((text, origin, row.get('uuid')))
    replacements, reviewed = {}, []
    old_output = Path('/tmp/claude-1000/-Users-pouya--openclaw-workspace-motorcontrol-plant') / PIN / 'tasks/bzqrjuzzq.output'
    for text, origin, identity in notifications:
        ids = re.findall(r'<task-id>([^<]+)</task-id>', text)
        tool = re.findall(r'<tool-use-id>([^<]+)</tool-use-id>', text)
        status = re.findall(r'<status>([^<]+)</status>', text)
        if ids == ['bzqrjuzzq'] and tool == ['toolu_01Ff8Qq5DhZLUpFfZv5mAmrJ'] and status == ['stopped']:
            if identity != '6857e0d1-b56d-4b87-aed6-cfdef930bd11' or origin != {'kind': 'task-notification'} or \
                    hashlib.sha256(old_output.read_bytes()).hexdigest() != 'd88b950b223dda4ec3def5881274173209ada23ceed292ce235f9809c4550623':
                raise ValueError('Previously reviewed killed worker evidence changed')
            reason = 'Already reviewed November 7 cancellation, never completion or rerun'
        elif len(ids) == 1 and ids[0] in monitors:
            if origin != {'kind': 'task-notification', 'producer': 'session-task'} or \
                    tool and tool != [monitors[ids[0]]] or status and status != ['completed']:
                raise ValueError('Unverified Monitor notification')
            if not status and not re.search(r'<summary>Monitor event: [^<]+</summary>\n<event>', text):
                raise ValueError('Unknown Monitor event schema')
            reason = 'Authenticated nonpersistent Monitor, full timeout elapsed'
        else:
            continue  # Strict gate must still match every actual shell job.
        replacements[text] = text.replace('<task-notification>', '[reviewed non-action task metadata]', 1)
        reviewed.append({'uuid': identity, 'task': ids[0], 'reason': reason})

    def normalize(value):
        if isinstance(value, str): return replacements.get(value, value)
        if isinstance(value, list): return [normalize(v) for v in value]
        if isinstance(value, dict): return {k: normalize(v) for k, v in value.items()}
        return value
    normalized = normalize(copy.deepcopy(rows))
    stream = io.BytesIO(b''.join((json.dumps(r) + '\n').encode() for r in normalized))
    old_monitors = reviewed_monitor_ids(io.BytesIO(body), boundary, PIN, saved['workspace'])
    quiescent_history(stream, PIN, saved['workspace'], initially_terminal=True, reviewed_monitors=old_monitors)
    if _file_identity(path.stat()) != _file_identity(before): raise ValueError('History changed during review')
    print(json.dumps({'observedAt': time.time(), 'session': PIN, 'workspace': saved['workspace'],
        'oldCheckpointSha256': hashlib.sha256(raw).hexdigest(),
        'history': {'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()},
        'records': len(rows), 'reviewedMetadata': reviewed, 'pendingTools': 0, 'pendingQueue': 0,
        'unmatchedShellTasks': 0, 'quiescent': True, 'readOnly': True, 'historyEdited': False, 'nativeInputSent': False}))


if __name__ == '__main__':
    audit()
