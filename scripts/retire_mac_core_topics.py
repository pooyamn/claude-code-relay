#!/usr/bin/env python3
"""Retire only the two already-idle ai-hil/supervisor source routes.

Retain private ingress, native-history and UI preimages. Fence ingress before
stopping these exact owned terminal generations; never restart a shared host.
An interrupted attempt stays fenced for inspection, never automatic replay.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path('/Users/pouya/.openclaw')
CHAT = '-1003550185469'
TOPICS = {
    '1876': ('claude-ai-hil-c9605e12ee', '8551d639a0', '37569e11-3bd5-4f3b-ac07-beecde706eb1', 'ai-hil'),
    '5786': ('claude-supervisor-fw-bf953d2e23', 'd4b8a06175', 'ef0ba453-d7f7-4c82-8838-01c6ad868d70', 'ai-hil/.worktrees/supervisor-fw'),
}
EXTRA_SUPERVISOR = '722583ef-f5e8-40b4-9c3e-9a75c8c9d2f6'
TMUX = '/opt/homebrew/bin/tmux'


def fenced(original):
    candidate = copy.deepcopy(original)
    selected = []
    for number, (agent, *_) in TOPICS.items():
        rows = [row for row in original['bindings'] if row.get('match', {}).get('peer', {}).get('id') ==
                CHAT + ':topic:' + number and row.get('match', {}).get('channel') == 'telegram']
        if len(rows) != 1 or rows[0].get('agentId') != agent:
            raise ValueError('Exact original source binding required; do not repeat retirement')
        selected.append(rows[0])
    candidate['bindings'] = [row for row in original['bindings'] if row not in selected]
    group = candidate['channels']['telegram']['groups'][CHAT]
    for number in TOPICS:
        group.setdefault('topics', {}).setdefault(number, {})['enabled'] = False
    restored = copy.deepcopy(candidate)
    restored['bindings'] = original['bindings']
    restored['channels']['telegram']['groups'][CHAT] = original['channels']['telegram']['groups'][CHAT]
    if restored != original:
        raise ValueError('Unrelated source settings changed')
    return candidate


def idle_view(pane, rows):
    tail = pane[-4500:]
    if not any(line.lstrip().startswith('❯') for line in tail.splitlines()[-10:]) or any(
            text in tail.lower() for text in ('esc to interrupt', 'do you want to proceed', 'allow once', 'permission request')):
        raise ValueError('Actual source terminal is not demonstrably idle')
    last = next((row for row in reversed(rows) if row.get('type') in ('assistant', 'user')), None)
    if not last or last.get('type') != 'assistant' or last.get('message', {}).get('stop_reason') != 'end_turn':
        raise ValueError('Source native turn/input is unfinished; do not stop it')


def processes():
    result = {}
    raw = subprocess.check_output(['/bin/ps', '-A', '-o', 'pid=,ppid=,state=,lstart=,command='], text=True)
    for line in raw.splitlines():
        fields = line.strip().split(None, 8)
        if len(fields) == 9 and not fields[2].startswith('Z'):
            result[int(fields[0])] = {'parent': int(fields[1]), 'generation': ' '.join(fields[3:8]),
                                     'command': fields[8]}
    return result


def history(relative, session):
    workspace = str(ROOT / 'workspace' / relative)
    return Path('/Users/pouya/.claude/projects') / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')


def checked_history(relative, session):
    path = history(relative, session)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
        raise ValueError('Literal source-owner native history required')
    body = path.read_bytes()
    rows = [json.loads(line) for line in body.splitlines()]
    after = path.lstat()
    if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
        raise ValueError('Source native history is still changing')
    return path, body, rows


def main():
    if os.uname().sysname != 'Darwin' or os.getuid() == 0:
        raise ValueError('Ordinary source Mac owner required')
    os.umask(0o077)
    config = ROOT / 'openclaw.json'
    if config.is_symlink() or config.stat().st_uid != os.getuid():
        raise ValueError('Literal owner source config required')
    before = config.read_bytes(); original = json.loads(before)
    if len(original['bindings']) != 5:
        raise ValueError('Exact five remaining source bindings required after controller cutover')
    updated = fenced(original); work = ROOT / 'workspace/scripts/relay-work'
    observed = processes(); selected = set(); views = {}; captures = {}
    for number, (_, key, session, relative) in TOPICS.items():
        if (work / ('claude-session-cr-' + key + '.txt')).read_text().strip() != session or \
                json.loads((work / ('backend-cr-' + key + '.json')).read_text()).get('backend') != 'claude' or \
                (work / ('default-model-cr-' + key + '.txt')).exists():
            raise ValueError('Selected source native pin/profile changed')
        pane = subprocess.check_output([TMUX, 'capture-pane', '-p', '-t', 'cr-' + key, '-S', '-80'], text=True)
        path, body, rows = checked_history(relative, session); idle_view(pane, rows)
        views[key] = pane; captures[session] = (relative, body)
        if number == '5786':
            _, extra, extra_rows = checked_history(relative, EXTRA_SUPERVISOR)
            idle_view(pane, extra_rows); captures[EXTRA_SUPERVISOR] = (relative, extra)
        for name in ('cr-' + key, 'crw-' + key):
            pid = int(subprocess.check_output([TMUX, 'display-message', '-p', '-t', name, '#{pane_pid}'], text=True))
            selected.add(pid)
    while True:
        added = {pid for pid, value in observed.items() if value['parent'] in selected} - selected
        if not added: break
        selected |= added
    if not selected or any(pid not in observed for pid in selected):
        raise ValueError('Exact source-owned terminal generations missing')
    recovery = Path(tempfile.mkdtemp(prefix='core-topic-cutover.', dir=ROOT))
    (recovery / 'previous-openclaw.json').write_bytes(before)
    (recovery / 'owned-generations.private.json').write_text(json.dumps({pid: observed[pid] for pid in selected}))
    for _, key, _, _ in TOPICS.values():
        (recovery / ('pane-' + key + '.private.txt')).write_text(views[key])
        for source in work.glob('*' + key + '*'):
            if source.is_file() and not source.is_symlink(): shutil.copy2(source, recovery / source.name)
    for session, (_, body) in captures.items(): (recovery / ('before-' + session + '.jsonl')).write_bytes(body)
    content = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.core-cutover-', dir=ROOT)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(config.stat().st_mode))
            output.write(content); output.flush(); os.fsync(output.fileno())
        if config.read_bytes() != before: raise ValueError('Concurrent source ingress edit; no replacement')
        os.replace(temporary, config)
        validation = subprocess.run(['/opt/homebrew/bin/openclaw', 'config', 'validate', '--json'],
            env=dict(os.environ, PATH='/opt/homebrew/bin:/usr/bin:/bin'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (recovery / 'validation.private.txt').write_bytes(validation.stdout)
        if validation.returncode:
            if config.read_bytes() != content: raise ValueError('Invalid candidate and concurrent edit; retain preimages')
            rollback = recovery / 'rollback-openclaw.json'; rollback.write_bytes(before)
            os.chmod(rollback, stat.S_IMODE(config.stat().st_mode)); os.replace(rollback, config)
            raise ValueError('Schema refused candidate; exact original restored')
        # Recheck after the ingress fence. A just-arrived old input stays held
        # for reconciliation rather than being terminated or replayed on PC.
        for number, (_, key, session, relative) in TOPICS.items():
            pane = subprocess.check_output([TMUX, 'capture-pane', '-p', '-t', 'cr-' + key, '-S', '-80'], text=True)
            _, _, rows = checked_history(relative, session); idle_view(pane, rows)
            if number == '5786': idle_view(pane, checked_history(relative, EXTRA_SUPERVISOR)[2])
        for _, key, _, _ in TOPICS.values():
            for name in ('crw-' + key, 'cr-' + key): subprocess.run([TMUX, 'kill-session', '-t', name], check=True)
        # A background PTY can outlive its terminal. Stop only an unchanged
        # captured owned generation, gracefully; never use broad pkill/SIGKILL.
        current = processes()
        for pid in selected:
            if pid in current:
                if any(current[pid][field] != observed[pid][field] for field in ('generation', 'command')):
                    raise ValueError('Owned PID generation changed; do not signal it')
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while selected.intersection(processes()):
            if time.monotonic() >= deadline: raise ValueError('Owned terminal shutdown incomplete; retain fence and inspect')
            time.sleep(0.2)
        histories = {}
        for session, (relative, _) in captures.items():
            path, body, _ = checked_history(relative, session)
            (recovery / ('final-' + session + '.jsonl')).write_bytes(body)
            histories[session] = {'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        for _, key, _, _ in TOPICS.values():
            source = work / ('claude-session-cr-' + key + '.txt'); os.replace(source, recovery / ('retired-' + source.name))
        receipt = {'phase': 'source-core-topics-fenced', 'topics': [1876, 5786], 'remainingBindings': 3,
            'beforeSha256': hashlib.sha256(before).hexdigest(), 'afterSha256': hashlib.sha256(content).hexdigest(),
            'recoveryDirectory': str(recovery), 'sourceHistories': histories, 'sharedDaemonRestarted': False,
            'gatewayRestarted': False, 'sourceSessionsStopped': 4}
        (recovery / 'receipt.json').write_text(json.dumps(receipt)); print(json.dumps(receipt))
    except BaseException:
        print(json.dumps({'phase': 'source-attempt-needs-inspection', 'recoveryDirectory': str(recovery)}), flush=True)
        raise
    finally:
        if os.path.exists(temporary): os.unlink(temporary)  # Exact unused owned staging file only.


def reconcile(directory):
    """Explicit read-before-finish reconciliation; never rerun shutdown/signals."""
    recovery = Path(directory)
    if os.uname().sysname != 'Darwin' or os.getuid() == 0 or recovery.parent != ROOT or \
            not re.fullmatch(r'core-topic-cutover\.[a-zA-Z0-9_]+', recovery.name) or \
            recovery.is_symlink() or recovery.stat().st_uid != os.getuid() or (recovery / 'receipt.json').exists():
        raise ValueError('Exact unreconciled source-owned recovery directory required')
    os.umask(0o077)
    before = (recovery / 'previous-openclaw.json').read_bytes()
    content = (ROOT / 'openclaw.json').read_bytes()
    original = json.loads(before)
    if len(original['bindings']) != 5 or json.loads(content) != fenced(original):
        raise ValueError('Exact source ingress fence changed; no reconciliation')
    for _, key, _, _ in TOPICS.values():
        for name in ('cr-' + key, 'crw-' + key):
            if subprocess.run([TMUX, 'has-session', '-t', name], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0:
                raise ValueError('Owned terminal still exists; no reconciliation')
    # This explicit path cannot send signals. Any remaining workspace process
    # or native file holder requires separate inspection rather than cleanup.
    cwd = subprocess.check_output(['/usr/sbin/lsof', '-nP', '-d', 'cwd', '-Fpcn'], text=True)
    for _, _, _, relative in TOPICS.values():
        if '\nn' + str(ROOT / 'workspace' / relative) + '\n' in '\n' + cwd:
            raise ValueError('Source workspace still has a producer')
    histories = {}
    selected = [(session, relative) for _, _, session, relative in TOPICS.values()]
    selected.append((EXTRA_SUPERVISOR, 'ai-hil/.worktrees/supervisor-fw'))
    for session, relative in selected:
        path, body, rows = checked_history(relative, session)
        old = [json.loads(line) for line in (recovery / ('before-' + session + '.jsonl')).read_bytes().splitlines()]
        conversation = lambda values: [row for row in values if row.get('type') in ('assistant', 'user')]
        if conversation(old) != conversation(rows):
            raise ValueError('New source conversation activity; do not infer delivery or replay')
        holders = subprocess.run(['/usr/sbin/lsof', '-t', str(path)], capture_output=True, text=True)
        if holders.returncode not in (0, 1) or holders.stdout.strip():
            raise ValueError('Native history still open or holder inspection failed')
        (recovery / ('final-' + session + '.jsonl')).write_bytes(body)
        histories[session] = {'path': str(path), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    for _, key, session, _ in TOPICS.values():
        source = ROOT / 'workspace/scripts/relay-work' / ('claude-session-cr-' + key + '.txt')
        target = recovery / ('retired-' + source.name)
        if not source.exists() or source.read_text().strip() != session or target.exists():
            raise ValueError('Exact original pin cannot be retired; preserve it')
    for _, key, _, _ in TOPICS.values():
        source = ROOT / 'workspace/scripts/relay-work' / ('claude-session-cr-' + key + '.txt')
        os.replace(source, recovery / ('retired-' + source.name))
    receipt = {'phase': 'source-core-topics-fenced', 'topics': [1876, 5786], 'remainingBindings': 3,
               'beforeSha256': hashlib.sha256(before).hexdigest(), 'afterSha256': hashlib.sha256(content).hexdigest(),
               'recoveryDirectory': str(recovery), 'sourceHistories': histories, 'sharedDaemonRestarted': False,
               'gatewayRestarted': False, 'sourceSessionsStopped': 4, 'explicitReconciliation': True,
               'signalsDuringReconciliation': 0, 'conversationUnchangedAfterShutdown': True}
    (recovery / 'receipt.json').write_text(json.dumps(receipt)); print(json.dumps(receipt))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--reconcile': reconcile(sys.argv[2])
    elif len(sys.argv) == 1: main()
    else: raise ValueError('Only initial retirement or explicit recovery-directory reconciliation is supported')
