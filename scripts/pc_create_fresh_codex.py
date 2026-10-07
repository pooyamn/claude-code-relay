#!/usr/bin/env python3
"""Allocate one fresh native session, with durable no-replay effect receipts.

Controller maintenance only. No daemon launch, model turn, Telegram request,
session fork, binding mutation, or automatic retry. An interrupted allocation
must be reconciled from its retained receipt rather than repeated.
"""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from pc_native_stdio import SOCKET, attest_workspaces, connect


def save_new(directory, name, value):
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, separators=(',', ':'), ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def checkpoint_persisted(raw, thread_id, expected):
    if len(raw) > 2_000_000:
        raise ValueError('Fresh enrollment rollout exceeds bound')
    identity = False
    checkpoint = False
    for line in raw.splitlines():
        item = json.loads(line)
        payload = item['payload']
        if item['type'] == 'session_meta':
            if payload['id'] != thread_id:
                return False
            identity = True
        if item['type'] == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
            checkpoint |= any(part.get('type') == 'input_text' and part.get('text') == expected
                              for part in payload.get('content', []))
    return identity and checkpoint


def create(args):
    directory = Path(args.receipt_directory)
    if directory.is_symlink() or directory.stat().st_uid != os.geteuid() or list(directory.iterdir()):
        raise ValueError('Fresh owner-controlled empty receipt directory required')
    os.chmod(directory, 0o700)
    attest_workspaces([args.workspace])
    checkpoint = ('[Enrollment checkpoint; not a request to start work.] '
                  f'Pouya requested a fresh session for the existing {args.name} topic '
                  f'in forum {args.chat}, topic {args.topic}. Workspace: {args.workspace}. '
                  'Do not replay historical messages or start project work or a goal. '
                  'Wait for the next human input. Other forum participants have conversation '
                  'access only when the router explicitly authorizes their accounts; they '
                  'do not inherit owner-only relay controls.')
    save_new(directory, 'plan.json', {
        'chat': args.chat, 'topic': args.topic, 'name': args.name,
        'workspace': args.workspace, 'sourceUpdate': args.source_update,
        'approvalPolicy': 'never', 'permissions': ':danger-full-access',
        'modelsStarted': 0, 'checkpoint': checkpoint})
    channel, verify, peer = connect(str(SOCKET))
    sequence = 0
    try:
        def call(method, parameters, effect=False):
            nonlocal sequence
            sequence += 1
            if effect:
                save_new(directory, f'{sequence}-attempt.json', {'method': method, 'params': parameters})
            verify()
            deadline = time.monotonic() + 30
            channel.send({'id': sequence, 'method': method, 'params': parameters}, deadline)
            while True:
                frame, _ = channel.receive(deadline)
                if frame.get('id') == sequence:
                    if 'error' in frame:
                        raise RuntimeError('Native request rejected; retain receipts and do not retry')
                    if effect:
                        save_new(directory, f'{sequence}-result.json', frame['result'])
                    return frame['result']

        call('initialize', {'clientInfo': {'name': 'ccrelay_fresh_enrollment', 'version': '1'},
                            'capabilities': {'experimentalApi': True}})
        channel.send({'method': 'initialized', 'params': {}}, time.monotonic() + 15)
        started = call('thread/start', {
            'cwd': args.workspace, 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
            'permissions': ':danger-full-access', 'allowProviderModelFallback': False}, effect=True)
        thread_id = started['thread']['id']
        uuid.UUID(thread_id)
        save_new(directory, 'created-native-thread.json', {'thread': thread_id, 'workspace': args.workspace})
        if started['cwd'] != args.workspace or started['approvalPolicy'] != 'never':
            raise RuntimeError('Native identity/permission mismatch; preserve allocated session')
        call('thread/inject_items', {'threadId': thread_id, 'items': [{
            'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': checkpoint}]}]}, effect=True)
        call('thread/name/set', {'threadId': thread_id,
                                'name': f'{args.name} (topic {args.topic})'}, effect=True)
        stored = call('thread/read', {'threadId': thread_id, 'includeTurns': True})['thread']
        path = Path(stored['path'])
        if (stored['id'] != thread_id or stored['cwd'] != args.workspace or
                not str(path).startswith('/Users/pouya/.codex/sessions/') or
                not path.name.endswith('-' + thread_id + '.jsonl') or '..' in path.parts or path.is_symlink()):
            raise RuntimeError('Exact persisted native session required')
        raw = path.read_text(encoding='utf-8')
        if not checkpoint_persisted(raw, thread_id, checkpoint):
            raise RuntimeError('Enrollment checkpoint not persisted; do not inject again')
        verify()
        result = {'phase': 'native-session-ready-existing-topic', 'thread': thread_id,
                  'chat': args.chat, 'topic': args.topic, 'name': args.name,
                  'workspace': args.workspace, 'sourceUpdate': args.source_update,
                  'backend': 'codex', 'runtime': 'linux', 'model': started['model'],
                  'approvalPolicy': 'never', 'permissions': ':danger-full-access',
                  'nativeOwnerUid': os.geteuid(), 'checkpointPersisted': True,
                  'modelsStarted': 0, 'unknownEffects': 0, 'complete': True}
        save_new(directory, 'result.json', result)
        return result
    finally:
        channel.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt-directory', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--chat', type=int, required=True)
    parser.add_argument('--topic', type=int, required=True)
    parser.add_argument('--source-update', type=int, required=True)
    args = parser.parse_args()
    if args.chat >= 0 or args.topic <= 0 or args.source_update <= 0 or not 1 <= len(args.name) <= 128 or any(ord(c) < 32 for c in args.name):
        parser.error('Exact existing forum/topic/name receipt required')
    print(json.dumps(create(args), separators=(',', ':')))
