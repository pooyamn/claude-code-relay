"""Read the exact owner's managed native Remote state; no models or mutations."""
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pc_native_stdio import SOCKET, connect


def observe():
    channel, verify, observed = connect(str(SOCKET))
    sequence = 0
    def call(method, params):
        nonlocal sequence
        sequence += 1
        verify()
        deadline = time.monotonic() + 15
        channel.send({'id': sequence, 'method': method, 'params': params}, deadline)
        for _ in range(4096):
            verify()
            frame, _ = channel.receive(deadline)
            verify()
            if 'method' in frame:
                # Never answer questions/approvals or mirror foreign content.
                continue
            if type(frame.get('id')) is not int or frame['id'] != sequence:
                raise ValueError('Unexpected native receipt')
            if 'error' in frame:
                raise ValueError('Native read rejected')
            return frame['result']
        raise ValueError('Native notification inspection bound exceeded')
    try:
        call('initialize', {'clientInfo': {'name': 'oracova_remote_observer', 'version': '1'},
                            'capabilities': {'experimentalApi': True}})
        verify()
        channel.send({'method': 'initialized'}, time.monotonic() + 15)
        account = call('account/read', {'refreshToken': False})
        remote = call('remoteControl/status/read', {})
        loaded = call('thread/loaded/list', {})
        value = account.get('account')
        if remote.get('status') not in ('disabled', 'connecting', 'connected', 'errored') or \
                not isinstance(remote.get('serverName'), str) or not 1 <= len(remote['serverName']) <= 256 or \
                any(ord(c) < 32 for c in remote['serverName']) or not isinstance(remote.get('installationId'), str) or \
                not remote['installationId'] or not isinstance(loaded.get('data'), list):
            raise ValueError('Invalid native observation')
        return {**observed, 'nativeRemoteState': remote['status'], 'serverName': remote['serverName'],
                'installationFingerprint': hashlib.sha256(remote['installationId'].encode()).hexdigest(),
                'environmentPresent': bool(remote.get('environmentId')), 'accountPresent': value is not None,
                'accountType': value.get('type') if isinstance(value, dict) else None,
                'accountFingerprint': hashlib.sha256(value['email'].lower().encode()).hexdigest()
                    if isinstance(value, dict) and isinstance(value.get('email'), str) else None,
                'packageAutoUpdateEnabled': (Path('/Users/pouya/.codex/packages/app-server-daemon') / 'auto-update-version').exists(),
                'loadedThreads': len(loaded['data']), 'modelsStarted': False, 'phoneRoundTripVerified': False}
    finally:
        channel.close()


if __name__ == '__main__':
    try:
        print(json.dumps(observe(), separators=(',', ':')))
    except Exception as error:
        print('Native daemon observation failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
