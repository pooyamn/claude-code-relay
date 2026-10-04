#!/usr/bin/env python3
"""Retire only Hardware Lite and MPU6000 source ingress after PC acceptance.

Fixed addresses and identities; private preimages, no shared process restart.
An existing attempt must be reconciled, not replayed.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path('/Users/pouya/.openclaw')
CHAT = '-1003550185469'
TOPICS = {
    '6333': ('claude-hardware-lite-e83ee50eb1', 'c072815230', '9e452652-73b0-4a6e-a81a-47f7b02365e9', False),
    '8653': ('claude-mpu6000-i9-97565f5561', '6604d9871a', '51a51775-0996-4e70-a293-0bcf14b0917d', True),
}


def fenced(original):
    candidate = copy.deepcopy(original)
    selected = []
    for number, (agent, _, _, _) in TOPICS.items():
        rows = [row for row in original['bindings'] if row.get('match', {}).get('peer', {}).get('id') ==
                CHAT + ':topic:' + number and row.get('match', {}).get('channel') == 'telegram']
        if len(rows) != 1 or rows[0].get('agentId') != agent:
            raise ValueError('Exact source binding required; no retirement replay')
        selected.append(rows[0])
    candidate['bindings'] = [row for row in original['bindings'] if row not in selected]
    group = candidate['channels']['telegram']['groups'][CHAT]
    for number in TOPICS:
        group.setdefault('topics', {}).setdefault(number, {})['enabled'] = False
    restored = copy.deepcopy(candidate)
    restored['bindings'] = original['bindings']
    restored['channels']['telegram']['groups'][CHAT] = original['channels']['telegram']['groups'][CHAT]
    if restored != original or len(original['bindings']) - len(candidate['bindings']) != 2:
        raise ValueError('Unrelated source configuration changed')
    return candidate


def main():
    if os.uname().sysname != 'Darwin' or os.getuid() == 0:
        raise ValueError('Ordinary source Mac owner required')
    os.umask(0o077)
    config = ROOT / 'openclaw.json'
    if config.is_symlink() or config.stat().st_uid != os.getuid():
        raise ValueError('Literal owner source configuration required')
    before = config.read_bytes()
    original = json.loads(before)
    if len(original['bindings']) != 8:
        raise ValueError('Expected eight remaining source bindings required')
    updated = fenced(original)
    work = ROOT / 'workspace/scripts/relay-work'
    processes = subprocess.check_output(['/bin/ps', '-A', '-o', 'command='], text=True)
    tmux = subprocess.run(['/opt/homebrew/bin/tmux', 'list-sessions', '-F', '#{session_name}'],
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.splitlines()
    for _, key, source_id, pinned in TOPICS.values():
        if source_id in processes or any(name in tmux for name in ('cr-' + key, 'crw-' + key)):
            raise ValueError('Source writer/watchers active; no transfer')
        pointer = work / ('claude-session-cr-' + key + '.txt')
        if pointer.exists() != pinned or pinned and pointer.read_text().strip() != source_id:
            raise ValueError('Source native pointer changed')
        if json.loads((work / ('backend-cr-' + key + '.json')).read_text()).get('backend') != 'claude':
            raise ValueError('Selected source backend changed')
        if (work / ('default-model-cr-' + key + '.txt')).exists():
            raise ValueError('Unexpected active model override; reconcile it first')
    recovery = Path(tempfile.mkdtemp(prefix='additional-topic-cutover.', dir=ROOT))
    (recovery / 'previous-openclaw.json').write_bytes(before)
    for _, key, _, _ in TOPICS.values():
        for source in work.glob('*' + key + '*'):
            if source.is_file() and not source.is_symlink():
                shutil.copy2(source, recovery / source.name)
    content = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.additional-cutover-', dir=ROOT)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(config.stat().st_mode))
            output.write(content); output.flush(); os.fsync(output.fileno())
        if config.read_bytes() != before:
            raise ValueError('Concurrent source config change; no replacement')
        os.replace(temporary, config)
        check = subprocess.run(['/opt/homebrew/bin/openclaw', 'config', 'validate', '--json'],
                               env=dict(os.environ, PATH='/opt/homebrew/bin:/usr/bin:/bin'),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (recovery / 'validation.private.txt').write_bytes(check.stdout)
        if check.returncode:
            if config.read_bytes() != content:
                raise ValueError('Invalid candidate and concurrent change; preserve for manual repair')
            rollback = recovery / 'rollback-openclaw.json'
            rollback.write_bytes(before); os.chmod(rollback, stat.S_IMODE(config.stat().st_mode))
            os.replace(rollback, config)
            raise ValueError('Invalid source candidate; exact prior configuration restored')
        for _, key, _, pinned in TOPICS.values():
            if pinned:
                source = work / ('claude-session-cr-' + key + '.txt')
                os.replace(source, recovery / ('retired-' + source.name))
        receipt = {'phase': 'source-topics-fenced', 'topics': [6333, 8653], 'remainingBindings': len(updated['bindings']),
                   'beforeSha256': hashlib.sha256(before).hexdigest(), 'afterSha256': hashlib.sha256(content).hexdigest(),
                   'recoveryDirectory': str(recovery), 'sharedDaemonRestarted': False, 'gatewayRestarted': False}
        (recovery / 'receipt.json').write_text(json.dumps(receipt))
        print(json.dumps(receipt))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Exact unused owned temporary file only.


if __name__ == '__main__':
    main()
