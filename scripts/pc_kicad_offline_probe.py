"""Prepare an isolated PC KiCad research environment, without board/model work.

Reads the existing pinned Mac SSH identity and original environment metadata.
Never replaces the preserved Darwin .venv, installs editable vendor checkouts,
changes Telegram/configuration, starts KiCad, or instantiates an LLM client.
Private logs and the environment live in a fresh owner-only migration directory.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import venv


ROOT = Path('/Users/pouya/.openclaw/workspace/kicad-copilot-research')
PRIVATE = Path('/Users/pouya/.migration')
LOCAL_PROJECTS = {'kicad-tools': '0.14.0', 'kipilot-mcp': '0.1.1'}
EXCLUDED_TEST = 'test_live_routing_gnd_lowers_j'
PROVENANCE_FILES = (
    'copilot/test_scorer.py', 'copilot/scorer.py', 'copilot/executor.py',
    'copilot/state_bridge.py', 'copilot/live_editor.py', 'copilot/loop.py',
    'copilot/nudge.py', 'kicad-tools/pyproject.toml', 'kipilot-mcp/pyproject.toml',
)


def requirements(packages):
    if not isinstance(packages, dict) or not packages or len(packages) > 200:
        raise ValueError('Invalid source package inventory')
    for name, version in packages.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            raise ValueError('Unsafe package name')
        if not isinstance(version, str) or not re.fullmatch(r'[0-9][A-Za-z0-9_.+!-]*', version):
            raise ValueError('Unsafe package version')
    if any(packages.get(name) != version for name, version in LOCAL_PROJECTS.items()):
        raise ValueError('Unreviewed local project version')
    return [f'{name}=={version}' for name, version in sorted(packages.items())
            if name not in LOCAL_PROJECTS and name != 'pip']


def offline_nodes(code):
    tree = ast.parse(code)
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name.startswith('test_')]
    if len(names) != 13 or names.count(EXCLUDED_TEST) != 1 or len(set(names)) != len(names):
        raise ValueError('Scorer test set changed; review before running')
    return [f'copilot/test_scorer.py::{name}' for name in names if name != EXCLUDED_TEST]


def save(path, value):
    with open(path, 'x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def clean_environment():
    # No credential/API-key environment inheritance into package/probe commands.
    result = {name: os.environ[name] for name in ('PATH', 'LANG', 'LC_ALL') if name in os.environ}
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    return result


def main():
    if len(sys.argv) != 1 or sys.platform != 'linux' or os.getuid() != 1000:
        raise ValueError('Only the ordinary PC Linux owner is admitted')
    for path in (ROOT, PRIVATE):
        if path.is_symlink() or path.resolve() != path or not path.is_dir():
            raise ValueError('Expected literal PC paths are unavailable')
    os.umask(0o077)
    run = Path(tempfile.mkdtemp(prefix='kicad-portable-', dir=PRIVATE))
    report = {'schema': 'ccrelay.kicad_offline_environment.v1', 'startedAt': stamp(),
              'runDirectory': str(run), 'uid': os.getuid(), 'environment': str(run / 'venv'),
              'sourceEnvironmentReplaced': False, 'vendorCheckoutsInstalledEditable': False,
              'liveBoardTestExecuted': False, 'modelStarted': False,
              'topicBackendChanged': False, 'operationalAcceptance': False}
    save(run / 'started.json', report)
    try:
        remote = (
            'import hashlib,importlib.metadata as m,json,os,sys;'
            'from pathlib import Path;'
            f'r=Path({str(ROOT)!r});p={PROVENANCE_FILES!r};'
            'assert sys.platform=="darwin" and os.getuid()==501;'
            'print(json.dumps({"uid":os.getuid(),"python":sys.version,'
            '"packages":{d.metadata["Name"]:d.version for d in m.distributions()},'
            '"fileHashes":{n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in p}}))'
        )
        import shlex
        command = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                   'mac', str(ROOT / '.venv/bin/python'), '-c', shlex.quote(remote)]
        observation = subprocess.run(command, capture_output=True, timeout=45)
        if observation.returncode or observation.stderr:
            raise ValueError('Source environment observation failed; no package installation')
        source = json.loads(observation.stdout)
        pins = requirements(source['packages'])
        local_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                        for name in PROVENANCE_FILES}
        if source['fileHashes'] != local_hashes:
            raise ValueError('Source and PC probe-code versions differ; no package installation')
        nodes = offline_nodes((ROOT / 'copilot/test_scorer.py').read_text())
        save(run / 'source-environment.json', source)
        report['sourceInventorySha256'] = hashlib.sha256((run / 'source-environment.json').read_bytes()).hexdigest()
        report['codeHashes'] = local_hashes
        pin_file = run / 'requirements.txt'
        with open(pin_file, 'x', encoding='ascii') as stream:
            stream.write('\n'.join(pins) + '\n')
        venv.EnvBuilder(with_pip=True).create(run / 'venv')
        python = str(run / 'venv/bin/python')
        environment = clean_environment()
        with open(run / 'install.log', 'xb') as log:
            installed = subprocess.run([python, '-m', 'pip', '--isolated', 'install',
                '--index-url', 'https://pypi.org/simple', '--only-binary=:all:', '--no-cache-dir',
                '--no-input', '--disable-pip-version-check', '-r', str(pin_file)],
                stdout=log, stderr=subprocess.STDOUT, env=environment, timeout=300)
        report['installExit'] = installed.returncode
        if installed.returncode:
            raise ValueError('Exact source-version wheel installation failed; no version fallback')
        version_read = subprocess.run([python, '-c',
            'import importlib.metadata as m,json;print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))'],
            capture_output=True, env=environment, check=True, timeout=20)
        actual = json.loads(version_read.stdout)
        save(run / 'pc-environment.json', actual)
        report['exactExternalPackageVersions'] = all(actual.get(line.split('==')[0]) == line.split('==')[1] for line in pins)
        if not report['exactExternalPackageVersions']:
            raise ValueError('Installed package versions differ from source')
        environment['PYTHONPATH'] = os.pathsep.join((str(ROOT), str(ROOT / 'kicad-tools/src'), str(ROOT / 'kipilot-mcp/src')))
        environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        with open(run / 'offline-tests.log', 'xb') as log:
            checked = subprocess.run([python, '-m', 'pytest', '-p', 'no:cacheprovider',
                '--override-ini', 'addopts=', '-q', *nodes], cwd=ROOT, env=environment,
                stdout=log, stderr=subprocess.STDOUT, timeout=120)
        report['offlineTestExit'] = checked.returncode
        report['offlineTestNodes'] = nodes
        if checked.returncode:
            raise ValueError('Offline tests failed; environment retained for diagnosis')
        with open(run / 'imports.log', 'xb') as log:
            imported = subprocess.run([python, '-c',
                'import socket;'
                'socket.socket.connect=lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError("No network or IPC in this probe"));'
                'import kipy,pynng,kipilot_mcp,mcp,anthropic;'
                'import copilot.state_bridge,copilot.live_editor,copilot.executor,copilot.loop,copilot.nudge;'
                'print("PC IPC/MCP and copilot imports passed; no clients instantiated")'],
                env=environment, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=30)
        report['importsExit'] = imported.returncode
        if imported.returncode:
            raise ValueError('PC imports failed; no live acceptance claimed')
        report['successful'] = True
    except Exception as error:
        report['successful'] = False
        report['error'] = type(error).__name__ + ': ' + str(error)
    report['finishedAt'] = stamp()
    report['logHashes'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in run.glob('*.log')}
    save(run / 'result.json', report)
    print(json.dumps({key: report[key] for key in ('runDirectory', 'successful', 'finishedAt',
        'sourceEnvironmentReplaced', 'liveBoardTestExecuted', 'modelStarted', 'operationalAcceptance')
        if key in report} | {key: report[key] for key in ('error', 'installExit', 'offlineTestExit', 'importsExit') if key in report}))
    return 0 if report['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
