"""One approved ready-and-wait turn; never retry an uncertain registration."""
import json
from pathlib import Path
import time

from pc_create_fresh_codex import save_new
from pc_native_stdio import SOCKET, attest_workspaces, connect

WORKSPACE = '/Users/pouya/.openclaw/workspace/trivial-topics'
THREAD = '01a1e147-661e-7250-967f-7f608708a617'
DIRECTORY = Path('/Users/pouya/.migration/topic-request-759325549')


def main():
    verify_workspace = attest_workspaces([WORKSPACE])
    channel, verify, _ = connect(str(SOCKET))
    sequence = 0
    try:
        def call(method, params, effect=False):
            nonlocal sequence
            sequence += 1
            if effect:
                save_new(DIRECTORY, 'remote-registration-attempt.json', {'method': method, 'params': params})
            verify_workspace()
            verify()
            deadline = time.monotonic() + 30
            channel.send({'id': sequence, 'method': method, 'params': params}, deadline)
            while True:
                frame, _ = channel.receive(deadline)
                if frame.get('id') != sequence:
                    continue
                if 'error' in frame:
                    raise RuntimeError('Native registration rejected; preserve attempt and do not retry')
                if effect:
                    save_new(DIRECTORY, 'remote-registration-ack.json', frame['result'])
                return frame['result']

        call('initialize', {'clientInfo': {'name': 'topic_registration', 'version': '1'},
                            'capabilities': {'experimentalApi': True}})
        channel.send({'method': 'initialized', 'params': {}}, time.monotonic() + 15)
        thread = call('thread/read', {'threadId': THREAD, 'includeTurns': False})['thread']
        if thread['id'] != THREAD or thread['cwd'] != WORKSPACE:
            raise RuntimeError('Exact allocated thread identity required')
        listing_params = {'cwd': WORKSPACE, 'limit': 30, 'useStateDbOnly': True}

        def listed():
            return any(item['id'] == THREAD and item.get('name') == 'Trivial Topics'
                       and item['cwd'] == WORKSPACE
                       for item in call('thread/list', listing_params)['data'])

        visible = listed()
        attempt = DIRECTORY / 'remote-registration-attempt.json'
        ack = DIRECTORY / 'remote-registration-ack.json'
        if not visible and not attempt.exists():
            call('turn/start', {'threadId': THREAD, 'input': [{'type': 'text', 'text':
                'Topic registration for Pouya: Trivial Topics. This is a fresh independent topic. '
                'Do not import other topics, personal/shared memories or project context. '
                'Reply only "Trivial Topics is ready.", then wait for the next human message. '
                'Do not use tools, start a goal, delegate or perform project work.'}]}, effect=True)
        elif not visible and not ack.exists():
            raise RuntimeError('Uncertain registration; do not resend')
        for _ in range(15):
            if visible:
                break
            time.sleep(1)
            visible = listed()
        if not visible:
            raise RuntimeError('Native-list visibility unconfirmed; preserve same session')
        result = {'thread': THREAD, 'name': 'Trivial Topics', 'workspace': WORKSPACE,
                  'nativeListVisible': True, 'registrationAckRetained': ack.exists(),
                  'copiedHistory': False, 'copiedMemories': False}
        result_path = DIRECTORY / 'remote-registration-verified.json'
        if not result_path.exists():
            save_new(DIRECTORY, result_path.name, result)
        print(json.dumps(result))
    finally:
        channel.close()


if __name__ == '__main__':
    main()
