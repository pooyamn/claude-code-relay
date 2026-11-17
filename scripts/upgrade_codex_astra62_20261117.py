"""Owner-authorized 6.2 migration: exact package activation and settings only.

Never sends input, resumes a history, changes a binding, or replays work.
Daemon lifecycle is deliberately separate, under the limited Windows owner.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))

OWNER = Path('/Users/pouya')
ROOT = OWNER / '.codex/packages/app-server-daemon'
SOURCE = OWNER / '.local/share/pc-migration-native/codex-0.169.0/package/vendor/x86_64-unknown-linux-musl'
DESTINATION = ROOT / 'releases/0.169.0-x86_64-unknown-linux-musl'
PREVIOUS = ROOT / 'releases/local-45a1f15dbce3c1e4ba0d0eb5d8026f1fc75a42f173fad82a6c7520861a9f0f28-x86_64-unknown-linux-musl'
DIGEST = 'b452ca20f838a8855a88a41050ee4a694033fff4ea3ecdad5633e6e0e8d13f2b'
MODEL = 'gpt-6.2-astra'
CONTROLLER = '01a0facd-1bc0-7d23-95d6-c32fde0c62db'
EVIDENCE = OWNER / '.migration/astra62-default-20261117'
OLD_ADAPTER = '/mnt/c/ProgramData/OracovaNativeRemote/codex-connector-fa07dcaa2ff24f828d78f1a745ac862d'


def save(name, value):
    destination = EVIDENCE / name
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(value, output, indent=2)


def target(thread):
    return thread.get('model') == 'gpt-6-astra' or thread['id'] == CONTROLLER


def changes(thread):
    if not target(thread) or thread.get('model') == MODEL:
        return None
    if thread.get('status', {}).get('type') != 'idle' and thread['id'] != CONTROLLER:
        raise RuntimeError('A target topic is active; preserve it')
    cwd = thread.get('cwd', '')
    if not cwd.startswith(str(OWNER / '.openclaw/workspace') + '/'):
        raise RuntimeError('Unexpected target workspace')
    return {'threadId': thread['id'], 'model': MODEL, 'serviceTier': 'default'}


def package_inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Unexpected package symlink')
        if path.is_file():
            if path.stat().st_uid != 1000 or path.stat().st_mode & 0o022:
                raise RuntimeError('Untrusted package file permissions')
            with path.open('rb') as source:
                result[str(path.relative_to(root))] = hashlib.file_digest(source, 'sha256').hexdigest()
    return result


def activate_package():
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise RuntimeError('Ordinary owner required')
    current = ROOT / 'current'
    if not current.is_symlink() or os.readlink(current) != str(PREVIOUS):
        raise RuntimeError('Expected previous managed package required')
    source = package_inventory(SOURCE)
    if source.get('bin/codex') != DIGEST or source != package_inventory(DESTINATION):
        raise RuntimeError('Complete reviewed package copy differs')
    manifest = json.loads((DESTINATION / 'codex-package.json').read_text())
    if manifest.get('version') != '0.169.0' or manifest.get('entrypoint') != 'bin/codex':
        raise RuntimeError('Unexpected package manifest')
    if (ROOT / 'auto-update-version').exists():
        raise RuntimeError('Unexpected package auto-update setting')
    # Caller must stop the old daemon first. Never silently replace a live writer.
    import socket
    socket_path = OWNER / '.codex/app-server-control/app-server-control.sock'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.connect(str(socket_path))
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        else:
            raise RuntimeError('Native daemon is still running')
    temporary = ROOT / 'current.astra62-20261117'
    os.symlink(str(DESTINATION), temporary)
    os.replace(temporary, current)
    result = {'previous': str(PREVIOUS), 'current': str(DESTINATION), 'binarySha256': DIGEST,
              'packageFilesVerified': len(source), 'autoUpdate': False, 'at': time.time()}
    save('package-activated.json', result)
    return result


class Native:
    def __init__(self, old_runtime=False):
        if old_runtime:
            sys.path.insert(0, OLD_ADAPTER)
        from pc_native_stdio import connect, SOCKET
        self.channel, self.verify, self.peer = connect(str(SOCKET))
        self.sequence = 0
        self.call('initialize', {'clientInfo': {'name': 'astra62_owner_migration', 'version': '1'},
                                 'capabilities': {'experimentalApi': True}})
        self.channel.send({'method': 'initialized'}, time.monotonic() + 20)

    def call(self, method, parameters):
        self.sequence += 1
        self.verify()
        deadline = time.monotonic() + 25
        self.channel.send({'id': self.sequence, 'method': method, 'params': parameters}, deadline)
        while True:
            frame, _ = self.channel.receive(deadline)
            self.verify()
            if frame.get('id') == self.sequence:
                if 'error' in frame:
                    raise RuntimeError(str(frame['error']))
                return frame['result']

    def threads(self):
        loaded = self.call('thread/loaded/list', {})
        if loaded.get('nextCursor'):
            raise RuntimeError('Unexpected additional loaded-thread page')
        return [self.call('thread/read', {'threadId': value, 'includeTurns': False})['thread']
                for value in loaded['data']]


def run(mode, old_runtime=False):
    if mode == 'activate-package':
        return activate_package()
    native = Native(old_runtime)
    try:
        models = native.call('model/list', {'includeHidden': False})
        before = native.threads()
        selected = [changes(thread) for thread in before]
        selected = [value for value in selected if value]
        if mode == 'inspect':
            remote = native.call('remoteControl/status/read', {})
            return {'peer': native.peer, 'models': [item['model'] for item in models['data']],
                    'remote': {'status': remote.get('status'), 'serverName': remote.get('serverName'),
                               'environmentPresent': bool(remote.get('environmentId'))},
                    'threads': [{key: item.get(key) for key in ('id', 'name', 'model', 'cwd', 'status')}
                                for item in before], 'plannedSettingsUpdates': selected}
        if not old_runtime and MODEL not in [item['model'] for item in models['data']]:
            raise RuntimeError('New remote catalog must advertise Astra 6.2')
        configuration = tomllib.loads((OWNER / '.codex/config.toml').read_text())
        if configuration.get('model') != MODEL or configuration.get('service_tier') not in (None, 'default'):
            raise RuntimeError('Expected standard-speed global defaults')
        snapshot = EVIDENCE / 'topics-before.json'
        if snapshot.exists():
            original = json.loads(snapshot.read_text())['threads']
            if {(item['id'], item.get('cwd')) for item in original} != {(item['id'], item.get('cwd')) for item in before}:
                raise RuntimeError('Topic identities changed since the migration snapshot')
        else:
            save('topics-before.json', {'threads': before, 'planned': selected, 'at': time.time()})
        completed = []
        for parameters in selected:
            native.call('thread/settings/update', parameters)
            deadline = time.monotonic() + 10
            while True:
                actual = native.call('thread/read', {'threadId': parameters['threadId'], 'includeTurns': False})['thread']
                if actual.get('model') == MODEL or time.monotonic() >= deadline:
                    break
                time.sleep(.1)  # Wait for metadata publication, never repeat the settings write.
            previous = next(item for item in before if item['id'] == actual['id'])
            if actual.get('model') != MODEL or actual.get('cwd') != previous.get('cwd'):
                raise RuntimeError('Settings readback differs; do not replay')
            completed.append({'id': actual['id'], 'name': actual.get('name'), 'model': actual['model']})
        result = {'changed': completed, 'alreadyOnTarget': [item['id'] for item in before if item.get('model') == MODEL],
                  'preservedOtherModels': [item['id'] for item in before if not target(item) and item.get('model') != MODEL],
                  'newWorkTurns': 0, 'historiesReplaced': 0, 'at': time.time()}
        save('topics-updated.json', result)
        return result
    finally:
        native.channel.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['inspect', 'migrate', 'activate-package'])
    parser.add_argument('--old-runtime', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.mode, args.old_runtime)))
