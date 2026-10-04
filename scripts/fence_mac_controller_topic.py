#!/usr/bin/env python3
"""Fence ONLY the old Mac controller's topic; never stop its shared daemon.

The independently running PC retains this exact native thread ID. Inspect the
old copy's idle turn/paused goal and absent topic watchers before changing the
source ingress. Keep complete private config and pointer preimages.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path('/Users/pouya/.openclaw')
CHAT = '-1003550185469'
TOPIC = 816
THREAD = '01a0facd-1bc0-7d23-95d6-c32fde0c62db'
WORKSPACE = str(ROOT / 'workspace/claude-code-relay')
KEY = 'a8012a3205'


def fenced(original):
    selected = [r for r in original['bindings'] if r.get('match', {}).get('channel') == 'telegram' and
                r.get('match', {}).get('peer', {}).get('id') == CHAT + ':topic:816']
    if len(selected) != 1 or selected[0].get('agentId') != 'claude-claude-code-relay-2dcb689d1a':
        raise ValueError('Exact existing controller ingress required; no repeated retirement')
    updated = copy.deepcopy(original)
    updated['bindings'] = [r for r in original['bindings'] if r not in selected]
    group = updated['channels']['telegram']['groups'][CHAT]
    group.setdefault('topics', {}).setdefault('816', {})['enabled'] = False
    restored = copy.deepcopy(updated)
    restored['bindings'] = original['bindings']
    restored['channels']['telegram']['groups'][CHAT] = original['channels']['telegram']['groups'][CHAT]
    if restored != original:
        raise ValueError('Unrelated source settings changed')
    return updated


def idle_source():
    sys.path.insert(0, str(ROOT / 'workspace/scripts'))
    from relay_ws import UnixWS
    channel = UnixWS(timeout=10)
    sequence = 0
    def call(method, params):
        nonlocal sequence
        if method not in {'initialize', 'thread/read', 'thread/turns/list', 'thread/goal/get'}:
            raise ValueError('Source observation is read-only')
        sequence += 1
        channel.sock.settimeout(10)
        channel.write(json.dumps({'id': sequence, 'method': method, 'params': params}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            frame = json.loads(channel.recv())
            if 'method' in frame:
                continue
            if frame.get('id') != sequence or 'error' in frame:
                raise ValueError('Source observation unconfirmed')
            return frame['result']
        raise TimeoutError('Source read deadline exceeded')
    try:
        call('initialize', {'clientInfo': {'name': 'controller_source_fence', 'version': '1'},
                            'capabilities': {'experimentalApi': True}})
        channel.write(json.dumps({'method': 'initialized'}))
        thread = call('thread/read', {'threadId': THREAD, 'includeTurns': False})['thread']
        turns = call('thread/turns/list', {'threadId': THREAD, 'limit': 1, 'sortDirection': 'desc', 'itemsView': 'notLoaded'})['data']
        goal = call('thread/goal/get', {'threadId': THREAD}).get('goal')
        if thread['id'] != THREAD or thread['cwd'] != WORKSPACE or thread['status']['type'] != 'idle' or \
                len(turns) != 1 or turns[0]['status'] not in {'completed', 'interrupted'} or goal and goal['status'] == 'active':
            raise ValueError('Source controller is not quiesced; preserve it')
        return {'thread': THREAD, 'turn': turns[0]['id'], 'status': turns[0]['status'], 'goal': goal['status'] if goal else None}
    finally:
        channel.close()


def main(generation, apply=False):
    if sys.platform != 'darwin' or os.getuid() == 0 or not re.fullmatch('[0-9a-f]{32}', generation):
        raise ValueError('Exact ordinary source Mac/generation required')
    os.umask(0o077)
    path = ROOT / 'openclaw.json'; info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Literal owned source configuration required')
    before = path.read_bytes(); original = json.loads(before); candidate = fenced(original)
    work = ROOT / 'workspace/scripts/relay-work'
    if (work / ('codex-thread-cr-' + KEY + '.txt')).read_text().strip() != THREAD:
        raise ValueError('Source controller pointer changed')
    panes = subprocess.check_output(['/opt/homebrew/bin/tmux', 'list-sessions', '-F', '#{session_name}'], text=True).splitlines()
    processes = subprocess.check_output(['/bin/ps', '-A', '-o', 'command='], text=True).splitlines()
    if any(name in panes for name in ('cr-' + KEY, 'crw-' + KEY)) or any(
            'cr-' + KEY in line and any(tool in line for tool in ('relay-codex', 'claude-relay-send', 'relay-watch')) for line in processes):
        raise ValueError('Source controller topic watcher remains active')
    observation = idle_source()
    if not apply:
        print(json.dumps({'phase': 'source-controller-quiesced', **observation, 'ingressChanged': False})); return
    recovery = ROOT / ('controller-topic-cutover.' + generation)
    recovery.mkdir(mode=0o700)
    (recovery / 'previous-openclaw.json').write_bytes(before)
    for pointer in work.glob('*cr-' + KEY + '*'):
        if pointer.is_file() and not pointer.is_symlink() and pointer.name.startswith(
                ('target-', 'backend-', 'codex-thread-', 'claude-session-', 'default-model-', 'menu-', 'transport-')):
            shutil.copy2(pointer, recovery / pointer.name)
    body = (json.dumps(candidate, ensure_ascii=False, indent=2) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.controller-cutover-', dir=ROOT)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode)); output.write(body); output.flush(); os.fsync(output.fileno())
        if path.read_bytes() != before:
            raise ValueError('Concurrent source edit; no replacement')
        os.replace(temporary, path)
        validation = subprocess.run(['/opt/homebrew/bin/openclaw', 'config', 'validate', '--json'],
            env=dict(os.environ, PATH='/opt/homebrew/bin:/usr/bin:/bin'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (recovery / 'validation.private.txt').write_bytes(validation.stdout)
        if validation.returncode:
            raise ValueError('Source validation failed; preserve fence/preimages and inspect, never activate PC blindly')
        idle_source()
        receipt = {'phase': 'controller-source-fenced', 'chat': int(CHAT), 'topic': TOPIC, 'thread': THREAD,
            'remainingBindings': len(candidate['bindings']), 'beforeSha256': hashlib.sha256(before).hexdigest(),
            'afterSha256': hashlib.sha256(body).hexdigest(), 'recoveryDirectory': str(recovery),
            'unrelatedConfigPreserved': True, 'sharedDaemonRestarted': False, 'sourceObservation': observation}
        (recovery / 'receipt.json').write_text(json.dumps(receipt)); print(json.dumps(receipt))
    finally:
        if os.path.exists(temporary):
            # Exact unused owned staging file; no source/history deletion.
            os.unlink(temporary)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:] == ['--apply'])
