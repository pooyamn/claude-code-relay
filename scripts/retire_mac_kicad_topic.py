#!/usr/bin/env python3
"""Fixed KiCad ingress retirement; preserve unrelated source routes and history."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile

ROOT = Path('/Users/pouya/.openclaw')
CHAT = '-1003550185469'
TOPIC = '6004'
AGENT = 'claude-kicad-copilot-research-2899cad3bb'
KEY = 'a445c68b44'
SESSION = 'ses_fda86bd86ffeX9tdQh70Q6uZoX'
WORKSPACE = ROOT / 'workspace/kicad-copilot-research'
HEAD = '3b4213fb0a66b707a06f5749adfd1a14651fdc3e'


def fenced(original):
    candidate = copy.deepcopy(original)
    selected = [r for r in original['bindings'] if
                r.get('match', {}).get('channel') == 'telegram' and
                r.get('match', {}).get('peer', {}).get('id') == CHAT + ':topic:' + TOPIC]
    if len(selected) != 1 or selected[0].get('agentId') != AGENT:
        raise ValueError('Exact source KiCad binding required; no retirement replay')
    candidate['bindings'] = [r for r in original['bindings'] if r not in selected]
    candidate['channels']['telegram']['groups'][CHAT].setdefault('topics', {}).setdefault(TOPIC, {})['enabled'] = False
    restored = copy.deepcopy(candidate)
    restored['bindings'] = original['bindings']
    restored['channels']['telegram']['groups'][CHAT] = original['channels']['telegram']['groups'][CHAT]
    if restored != original:
        raise ValueError('Unrelated source settings changed')
    return candidate


def checked_history(db):
    session = db.execute('SELECT id,directory,time_updated,time_compacting FROM session WHERE id=?', (SESSION,)).fetchone()
    messages = list(db.execute('SELECT id,time_created,time_updated,data FROM message WHERE session_id=? ORDER BY time_created,id', (SESSION,)))
    parts = list(db.execute('SELECT id,message_id,time_created,time_updated,data FROM part WHERE session_id=? ORDER BY time_created,id', (SESSION,)))
    if not session or session[1] != str(WORKSPACE) or session[3] is not None or not messages:
        raise ValueError('Exact non-compacting source session required')
    last = json.loads(messages[-1][3])
    if last.get('role') != 'assistant' or last.get('finish') != 'stop' or not last.get('time', {}).get('completed') or last.get('error'):
        raise ValueError('Source turn is unfinished or failed; retain source ingress')
    if list(db.execute('SELECT id FROM session_input WHERE session_id=?', (SESSION,))) or list(db.execute('SELECT id FROM session WHERE parent_id=?', (SESSION,))):
        raise ValueError('Source input/child work requires reconciliation')
    for row in parts:
        part = json.loads(row[4])
        if part.get('type') == 'tool' and part.get('state', {}).get('status') not in ('completed', 'error'):
            raise ValueError('Source tool effect unfinished; do not transfer')
    return {'session': session, 'messages': messages, 'parts': parts,
            'todo': list(db.execute('SELECT * FROM todo WHERE session_id=?', (SESSION,)))}


def no_writer():
    panes = subprocess.run(['/opt/homebrew/bin/tmux', 'list-sessions', '-F', '#{session_name}'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.splitlines()
    if any(name in panes for name in ('cr-' + KEY, 'crw-' + KEY)):
        raise ValueError('Source terminal/watcher still exists')
    cwd = subprocess.check_output(['/usr/sbin/lsof', '-nP', '-d', 'cwd', '-Fpcn'], text=True)
    if '\nn' + str(WORKSPACE) + '\n' in '\n' + cwd:
        raise ValueError('Source workspace has a producer')
    port = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:4536', '-sTCP:LISTEN'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if port.returncode == 0 or port.returncode != 1:
        raise ValueError('Old OpenCode ingress exists or cannot be observed')


def main():
    if os.uname().sysname != 'Darwin' or os.getuid() == 0:
        raise ValueError('Ordinary source Mac owner required')
    os.umask(0o077)
    config = ROOT / 'openclaw.json'
    if config.is_symlink() or config.stat().st_uid != os.getuid():
        raise ValueError('Literal source-owner config required')
    before = config.read_bytes(); original = json.loads(before)
    if len(original['bindings']) != 3:
        raise ValueError('Exact three remaining source bindings required')
    candidate = fenced(original)
    work = ROOT / 'workspace/scripts/relay-work'
    pointer = work / ('opencode-session-cr-' + KEY + '.txt')
    if pointer.is_symlink() or pointer.read_text().strip() != SESSION or (work / ('backend-cr-' + KEY + '.json')).exists():
        raise ValueError('Source native pin/backend changed')
    no_writer()
    if subprocess.check_output(['/usr/bin/git', '-C', str(WORKSPACE), 'rev-parse', 'HEAD'], text=True).strip() != HEAD or \
            subprocess.check_output(['/usr/bin/git', '-C', str(WORKSPACE), 'status', '--porcelain=v1'], text=True):
        raise ValueError('Source worktree changed; review final delta first')
    db = sqlite3.connect('file:/Users/pouya/.local/share/opencode/opencode.db?mode=ro', uri=True)
    history = checked_history(db)
    manifest = {}
    for path in sorted(WORKSPACE.rglob('*')):
        if path.is_symlink():
            manifest[str(path.relative_to(WORKSPACE))] = {'symlink': os.readlink(path)}
        elif path.is_file():
            before_stat = path.stat(); body = path.read_bytes(); after_stat = path.stat()
            if (before_stat.st_ino, before_stat.st_mtime_ns, before_stat.st_size) != (after_stat.st_ino, after_stat.st_mtime_ns, after_stat.st_size):
                raise ValueError('Source file changed during final manifest')
            manifest[str(path.relative_to(WORKSPACE))] = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    recovery = Path(tempfile.mkdtemp(prefix='kicad-topic-cutover.', dir=ROOT))
    # Persist attempt ownership before changing ingress. A later invocation must not replay.
    claim = ROOT / 'kicad-topic-cutover.claim'
    with claim.open('x') as output:
        output.write(str(recovery)); output.flush(); os.fsync(output.fileno())
    (recovery / 'previous-openclaw.json').write_bytes(before)
    (recovery / 'source-history.private.json').write_text(json.dumps(history))
    (recovery / 'source-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
    for source in work.glob('*' + KEY + '*'):
        if source.is_file() and not source.is_symlink():
            shutil.copy2(source, recovery / source.name)
    content = (json.dumps(candidate, ensure_ascii=False, indent=2) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.kicad-cutover-', dir=ROOT)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(config.stat().st_mode)); output.write(content); output.flush(); os.fsync(output.fileno())
        if config.read_bytes() != before or checked_history(db) != history:
            raise ValueError('Concurrent source ingress/native history change')
        no_writer(); os.replace(temporary, config)
        validation = subprocess.run(['/opt/homebrew/bin/openclaw', 'config', 'validate', '--json'],
                                    env=dict(os.environ, PATH='/opt/homebrew/bin:/usr/bin:/bin'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (recovery / 'validation.private.txt').write_bytes(validation.stdout)
        if validation.returncode:
            if config.read_bytes() != content:
                raise ValueError('Invalid config plus concurrent edit; retain preimages')
            rollback = recovery / 'rollback-openclaw.json'; rollback.write_bytes(before)
            os.chmod(rollback, stat.S_IMODE(config.stat().st_mode)); os.replace(rollback, config)
            raise ValueError('Invalid source candidate; prior config restored')
        no_writer()
        if checked_history(db) != history:
            raise ValueError('Source history changed after ingress fence; inspect without replay')
        os.replace(pointer, recovery / ('retired-' + pointer.name))
        receipt = {'phase': 'source-kicad-topic-fenced', 'topic': 6004, 'chat': int(CHAT), 'sourceSession': SESSION,
                   'remainingBindings': 2, 'historySha256': hashlib.sha256((recovery / 'source-history.private.json').read_bytes()).hexdigest(),
                   'manifestSha256': hashlib.sha256((recovery / 'source-manifest.json').read_bytes()).hexdigest(),
                   'beforeSha256': hashlib.sha256(before).hexdigest(), 'afterSha256': hashlib.sha256(content).hexdigest(),
                   'recoveryDirectory': str(recovery), 'modelsStarted': False, 'sharedDaemonRestarted': False, 'gatewayRestarted': False}
        (recovery / 'receipt.json').write_text(json.dumps(receipt)); print(json.dumps(receipt))
    except BaseException:
        print(json.dumps({'phase': 'source-attempt-needs-inspection', 'recoveryDirectory': str(recovery)}), flush=True)
        raise
    finally:
        db.close()
        if os.path.exists(temporary):
            os.unlink(temporary)  # Exact unused owned staging file only.


if __name__ == '__main__':
    main()
