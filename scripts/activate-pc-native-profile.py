#!/usr/bin/env python3
"""Activate the PC owner's current file logins; never resume imported sessions.

Run only from migration-native-profile.ps1's verified limited interactive token.
Windows sources stay untouched. Receipts and raw native output stay private.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import tomllib

OWNER = Path('/Users/pouya')
WINDOWS_OWNER = Path('/mnt/c/Users/pou')
CLAUDE_SHA = '0298068b686e7fdbaf9402a7a587bb7f49c0b0e084de09f69145a0719207640c'
ROOT_SETTINGS = {'sandbox_mode': 'danger-full-access', 'approval_policy': 'never',
                 'cli_auth_credentials_store': 'file', 'check_for_update_on_startup': False}


def regular(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Redirected input or destination refused')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Regular source required')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def exclusive(path, data):
    """An existing or partially-created profile is evidence, never overwritten."""
    for part in path.parents:
        if part.is_symlink():
            raise ValueError('Redirected destination refused')
    with path.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def codex_settings(source):
    original = tomllib.loads(source)
    lines = [f'{key} = {json.dumps(value)}' for key, value in ROOT_SETTINGS.items()]
    in_root = True
    for line in source.splitlines():
        if re.match(r'^\s*\[', line):
            in_root = False
        if in_root and re.match(r'^\s*(' + '|'.join(ROOT_SETTINGS) + r')\s*=', line):
            continue
        lines.append(line)
    result = '\n'.join(lines) + '\n'
    expected = {**original, **ROOT_SETTINGS}
    if tomllib.loads(result) != expected:
        raise ValueError('Unrelated Codex configuration changed')
    return result.encode()


def claude_settings(source):
    result = copy.deepcopy(source)
    result.setdefault('permissions', {})['defaultMode'] = 'bypassPermissions'
    result.setdefault('env', {})['DISABLE_AUTOUPDATER'] = '1'
    # Do not persist diagnostic traffic-disabling flags: they break Remote Control.
    return (json.dumps(result, indent=2) + '\n').encode()


def claude_account_settings(source, account):
    result = copy.deepcopy(source)
    result['oauthAccount'] = copy.deepcopy(account)
    result['autoUpdates'] = False
    return (json.dumps(result, indent=2) + '\n').encode()


def login_documents(codex_bytes, claude_bytes):
    codex, claude = json.loads(codex_bytes), json.loads(claude_bytes)
    tokens = codex.get('tokens') or {}
    if codex.get('auth_mode') != 'chatgpt' or codex.get('OPENAI_API_KEY') or \
            not all(tokens.get(key) for key in ('access_token', 'refresh_token', 'account_id')):
        raise ValueError('Current owner ChatGPT login required; no API substitution')
    oauth = claude.get('claudeAiOauth') or {}
    if not all(oauth.get(key) for key in ('accessToken', 'refreshToken')) or \
            oauth.get('expiresAt', 0) <= time.time() * 1000:
        raise ValueError('Current unexpired owner Claude login required')
    return codex, claude


def captured_command(arguments, state, label, environment):
    with (state / (label + '-stdout.private.txt')).open('xb') as output, \
            (state / (label + '-stderr.private.txt')).open('xb') as error:
        child = subprocess.Popen(arguments, cwd=state, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=error, start_new_session=True)
        try:
            code = child.wait(timeout=45)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
    if code != 0:
        raise ValueError('Native login check failed; raw private output retained')
    return (state / (label + '-stdout.private.txt')).read_text()


def account_checks(native, codex_binary, claude_binary, state, windows_account):
    environment = {'HOME': str(OWNER), 'CODEX_HOME': str(OWNER / '.codex'),
                   'PATH': str(OWNER / '.local/bin') + ':/usr/bin:/bin', 'LANG': 'C.UTF-8',
                   'DISABLE_AUTOUPDATER': '1', 'DISABLE_UPDATES': '1',
                   'CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL': '1'}
    text = captured_command([str(codex_binary), 'login', 'status'], state, 'codex-login', environment)
    # Codex prints this status on stderr, not stdout, in this pinned release.
    text += (state / 'codex-login-stderr.private.txt').read_text()
    if 'Logged in using ChatGPT' not in text:
        raise ValueError('Native Codex did not select the ChatGPT cache')
    status = json.loads(captured_command([str(claude_binary), 'auth', 'status'],
                                       state, 'claude-auth', environment))
    if status.get('authMethod') != 'claude.ai' or not status.get('loggedIn'):
        raise ValueError('Native Claude did not select the subscription login')
    if windows_account.get('emailAddress') and status.get('email') != windows_account['emailAddress']:
        raise ValueError('Native Claude account differs from current Windows owner')
    native.READ_METHODS = {'initialize', 'account/read', 'account/rateLimits/read',
                           'config/read', 'thread/loaded/list'}
    child = rpc = None
    with (state / 'codex-account-stderr.private.txt').open('xb') as error:
        try:
            child = subprocess.Popen([str(codex_binary), '-c', 'analytics.enabled=false',
                                      '-c', 'feedback.enabled=false', 'app-server'],
                                     cwd=state, env=environment, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=error, start_new_session=True)
            rpc = native.ReadOnlyRPC(child, state)
            rpc.call('initialize', {'clientInfo': {'name': 'oracova-migration-account', 'version': '1'}})
            rpc.initialized()
            account = rpc.call('account/read', {'refreshToken': False})
            config = rpc.call('config/read', {'includeLayers': False})
            limits = rpc.call('account/rateLimits/read', {})
            loaded = rpc.call('thread/loaded/list', {})
            for label, value in (('account', account), ('config', config), ('limits', limits)):
                exclusive(state / (label + '.private.json'), json.dumps(value).encode())
            if (account.get('account') or {}).get('type') != 'chatgpt' or loaded.get('data'):
                raise ValueError('Wrong Codex account or unexpectedly loaded conversation')
            if not limits.get('rateLimits') and not limits.get('rateLimitsByLimitId'):
                raise ValueError('Authenticated Codex quota evidence missing')
            result = {'codexAuthMethod': 'chatgpt', 'claudeAuthMethod': status['authMethod'],
                      'claudeLoggedIn': True, 'claudeAccountMatchesWindows': True,
                      'rateLimitsRead': True, 'loadedThreads': 0,
                      'codexConfigurationKeys': sorted(config.get('config', {}))}
        finally:
            if rpc:
                rpc.close()
            if child:
                child.stdin.close()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                child.stdout.close()
    return {**result, 'nativeStopped': True}


def main(migration_run, run):
    os.umask(0o077)
    if not all(re.fullmatch('[0-9a-f]{32}', x) for x in (migration_run, run)):
        raise ValueError('Exact migration/profile runs required')
    if os.getuid() != 1000 or OWNER.is_symlink() or OWNER.stat().st_uid != 1000 or \
            stat.S_IMODE(OWNER.stat().st_mode) != 0o700:
        raise ValueError('Private ordinary PC owner home required')
    seeds = OWNER / '.migration' / migration_run / 'native-seeds'
    state = seeds.parent / ('native-profile-' + run)
    state.mkdir(mode=0o700)
    report = {'schema': 'ccrelay.migration.native_profile.v1', 'complete': False,
              'uid': os.getuid(), 'routingChanged': False, 'sessionsResumed': False,
              'modelPromptsSent': 0, 'windowsFilesChanged': False, 'installed': []}
    try:
        spec = importlib.util.spec_from_file_location('native_restore', Path(__file__).with_name('restore-pc-native-histories.py'))
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        codex_binary = native.pinned_executable(OWNER / '.local/share/pc-migration-native/codex-0.160.0')
        claude_binary = regular(OWNER / '.local/share/pc-migration-native/claude-2.1.288/claude')
        if digest(claude_binary.read_bytes()) != CLAUDE_SHA:
            raise ValueError('Pinned Claude executable required')
        for process in Path('/proc').glob('[0-9]*/exe'):
            try:
                if process.resolve() in (codex_binary.resolve(), claude_binary.resolve()):
                    raise ValueError('Existing native Linux writer preserved')
            except (OSError, RuntimeError):
                continue
        paths = {'codexAuth': WINDOWS_OWNER / '.codex/auth.json',
                 'claudeAuth': WINDOWS_OWNER / '.claude/.credentials.json',
                 'windowsAccount': WINDOWS_OWNER / '.claude.json',
                 'linuxAccountSettings': OWNER / '.claude.json',
                 'codexSettings': seeds / 'codex-home-file/config.toml',
                 'claudeSettings': seeds / 'claude-home-file/settings.json'}
        captured = {key: regular(path).read_bytes() for key, path in paths.items()}
        codex_auth, _ = login_documents(captured['codexAuth'], captured['claudeAuth'])
        old_codex = json.loads(regular(seeds / 'codex-home-file/auth.json').read_bytes())
        if old_codex.get('tokens', {}).get('account_id') != codex_auth['tokens']['account_id']:
            raise ValueError('Current Windows Codex account differs from preserved source account')
        account = json.loads(captured['windowsAccount']).get('oauthAccount')
        if not isinstance(account, dict) or not account.get('emailAddress'):
            raise ValueError('Current Windows Claude account metadata required')
        install = [(OWNER / '.codex/auth.json', captured['codexAuth']),
                   (OWNER / '.claude/.credentials.json', captured['claudeAuth']),
                   (OWNER / '.codex/config.toml', codex_settings(captured['codexSettings'].decode())),
                   (OWNER / '.claude/settings.json', claude_settings(json.loads(captured['claudeSettings'])))]
        new_account_settings = claude_account_settings(json.loads(captured['linuxAccountSettings']), account)
        for target, _ in install:
            if target.exists() or target.is_symlink():
                raise ValueError('Existing profile preserved; inspect before another activation')
            if target.parent.is_symlink() or target.parent.stat().st_uid != 1000 or \
                    stat.S_IMODE(target.parent.stat().st_mode) != 0o700:
                raise ValueError('Private native home required')
        bin_dir = OWNER / '.local/bin'
        if bin_dir.exists() or bin_dir.is_symlink():
            raise ValueError('Existing launcher directory preserved; inspect before merging')
        for key, data in captured.items():
            exclusive(state / (key + '.private'), data)
        for key, path in paths.items():
            if regular(path).read_bytes() != captured[key]:
                raise ValueError('Source profile changed during inspection; no overwrite')
        for target, data in install:
            exclusive(target, data)
            if regular(target).read_bytes() != data:
                raise ValueError('Installed profile readback differs')
            report['installed'].append(str(target.relative_to(OWNER)))
        if regular(paths['linuxAccountSettings']).read_bytes() != captured['linuxAccountSettings']:
            raise ValueError('Linux account settings changed; original retained')
        account_staging = state / 'linux-account-settings.new.private.json'
        exclusive(account_staging, new_account_settings)
        os.replace(account_staging, paths['linuxAccountSettings'])
        report['installed'].append('.claude.json:oauthAccount,autoUpdates')
        bin_dir.mkdir(mode=0o700)
        (bin_dir / 'codex').symlink_to(codex_binary)
        (bin_dir / 'claude').symlink_to(claude_binary)
        report['checks'] = account_checks(native, codex_binary, claude_binary, state, account)
        report['complete'] = True
    except Exception as error:
        report['failureType'] = type(error).__name__
        exclusive(state / 'failure.private.txt', str(error).encode())
    finally:
        exclusive(state / 'result.json', json.dumps(report).encode())
    print(json.dumps(report))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ValueError('Migration and activation runs required')
        sys.exit(main(*sys.argv[1:]))
    except Exception as error:
        print(json.dumps({'failureType': type(error).__name__, 'modelPromptsSent': 0}))
        sys.exit(2)
