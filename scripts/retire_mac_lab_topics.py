#!/usr/bin/env python3
"""Fence only the two accepted PC lab topics on the source Mac.

Keep complete private preimages, all unrelated config and native histories.
Never stop a shared daemon or gateway. Reject an existing source writer.
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
TOPICS = {
    '2697': ('claude-schematic-pipeline-lab-814e33b36a', 'a78a2ed904', '241b74eb-ca20-4f4b-b419-dafec1c539c0'),
    '3315': ('claude-mimic-fast-pcb-5791152db8', '879969c7a8', 'decdfe03-731a-4654-9513-07e35d3b6c12'),
}


def fenced(original):
    candidate = copy.deepcopy(original)
    selected = []
    for number, (agent, _, _) in TOPICS.items():
        rows = [row for row in original['bindings'] if row.get('match', {}).get('peer', {}).get('id') ==
                '-1004395661179:topic:' + number and row.get('match', {}).get('channel') == 'telegram']
        if len(rows) != 1 or rows[0].get('agentId') != agent:
            raise ValueError('Exact original topic binding required; no retirement replay')
        selected.append(rows[0])
    candidate['bindings'] = [row for row in original['bindings'] if row not in selected]
    group = candidate['channels']['telegram']['groups']['-1004395661179']
    for number in TOPICS:
        group.setdefault('topics', {}).setdefault(number, {})['enabled'] = False
    # Reverse precisely the intended changes, then compare every unrelated field.
    restored = copy.deepcopy(candidate)
    restored['bindings'] = original['bindings']
    restored['channels']['telegram']['groups']['-1004395661179'] = original['channels']['telegram']['groups']['-1004395661179']
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
    if len(original['bindings']) != 10:
        raise ValueError('Expected ten remaining source bindings required')
    updated = fenced(original)
    work = ROOT / 'workspace/scripts/relay-work'
    processes = subprocess.check_output(['/bin/ps', '-A', '-o', 'command='], text=True)
    sessions = subprocess.run(['/opt/homebrew/bin/tmux', 'list-sessions', '-F', '#{session_name}'],
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _, key, source_id in TOPICS.values():
        if source_id in processes or any(name in sessions.stdout.splitlines() for name in ('cr-' + key, 'crw-' + key)):
            raise ValueError('Source writer/watchers still active; do not transfer')
        if (work / ('claude-session-cr-' + key + '.txt')).read_text().strip() != source_id:
            raise ValueError('Source native pointer changed')
    recovery = Path(tempfile.mkdtemp(prefix='lab-topic-cutover.', dir=ROOT))
    (recovery / 'previous-openclaw.json').write_bytes(before)
    (recovery / 'previous-topics.json').write_text(json.dumps(original['channels']['telegram']['groups']['-1004395661179']))
    for _, key, _ in TOPICS.values():
        for source in work.glob('*' + key + '*'):
            if source.is_file() and not source.is_symlink():
                shutil.copy2(source, recovery / source.name)
    content = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.lab-cutover-', dir=ROOT)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(config.stat().st_mode))
            output.write(content);output.flush();os.fsync(output.fileno())
        if config.read_bytes() != before:
            raise ValueError('Source configuration changed during retirement')
        os.replace(temporary, config)
        environment = dict(os.environ, PATH='/opt/homebrew/bin:/usr/bin:/bin')
        check = subprocess.run(['/opt/homebrew/bin/openclaw', 'config', 'validate', '--json'],
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (recovery / 'validation.private.txt').write_bytes(check.stdout)
        if check.returncode:
            if config.read_bytes() != content:
                raise ValueError('Invalid candidate and concurrent config change; preserve for manual repair')
            rollback = recovery / 'rollback-openclaw.json'
            rollback.write_bytes(before);os.chmod(rollback, stat.S_IMODE(config.stat().st_mode))
            os.replace(rollback, config)
            raise ValueError('Source schema validation failed; exact configuration restored')
        for _, key, _ in TOPICS.values():
            source = work / ('claude-session-cr-' + key + '.txt')
            os.replace(source, recovery / ('retired-' + source.name))
        receipt = {'phase': 'source-topics-fenced', 'topics': [2697, 3315], 'remainingBindings': len(updated['bindings']),
                   'beforeSha256': hashlib.sha256(before).hexdigest(), 'afterSha256': hashlib.sha256(content).hexdigest(),
                   'recoveryDirectory': str(recovery), 'sharedDaemonRestarted': False, 'gatewayRestarted': False}
        (recovery / 'receipt.json').write_text(json.dumps(receipt))
        print(json.dumps(receipt))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Only the exact owned, unused temporary config.


if __name__ == '__main__':
    main()
