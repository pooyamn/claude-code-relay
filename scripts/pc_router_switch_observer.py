#!/usr/bin/env python3
"""Read the exact PC controller turn; no input, inference, approvals or replay."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pc_native_stdio import connect, SOCKET

THREAD = '01a0facd-1bc0-7d23-95d6-c32fde0c62db'
WORKSPACE = '/Users/pouya/.openclaw/workspace/claude-code-relay'


def observe():
    channel, verify, peer = connect(str(SOCKET))
    sequence = 0
    try:
        def call(method, parameters):
            nonlocal sequence
            sequence += 1
            verify()
            channel.send({'id': sequence, 'method': method, 'params': parameters}, time.monotonic() + 15)
            while True:
                frame, _ = channel.receive(time.monotonic() + 15)
                if frame.get('id') == sequence:
                    if 'error' in frame: raise RuntimeError('Read-only native controller observation rejected')
                    return frame['result']
        call('initialize', {'clientInfo': {'name': 'ccrelay_switch_read', 'version': '1'}, 'capabilities': {'experimentalApi': True}})
        channel.send({'method': 'initialized', 'params': {}}, time.monotonic() + 15)
        thread = call('thread/read', {'threadId': THREAD, 'includeTurns': False})['thread']
        if thread['id'] != THREAD or thread['cwd'] != WORKSPACE:
            raise RuntimeError('Exact PC controller identity/workspace required')
        turns = call('thread/turns/list', {'threadId': THREAD, 'limit': 1, 'sortDirection': 'desc', 'itemsView': 'notLoaded'})['data']
        if len(turns) != 1: raise RuntimeError('One exact latest controller turn required')
        goal = call('thread/goal/get', {'threadId': THREAD})['goal']
        verify()
        return {'thread': THREAD, 'workspace': WORKSPACE, 'turn': turns[0]['id'], 'turnStatus': turns[0]['status'],
                'activeFlags': thread['status'].get('activeFlags', []), 'goalStatus': goal['status'] if goal else None,
                'modelInference': False}
    finally:
        channel.close()


if __name__ == '__main__':
    print(json.dumps(observe(), separators=(',', ':')))
