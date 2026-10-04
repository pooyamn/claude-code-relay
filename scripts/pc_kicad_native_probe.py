"""One-shot native Windows KiCad qualification on disposable scratch copies.

No router/model/credential changes, production boards or editable vendor installs.
Existing KiCad settings are observed and cloned into an isolated profile. Only
the GUI process launched by this run is closed/terminated during cleanup.
"""
import ctypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid

from pc_kicad_offline_probe import requirements, save, stamp


PROJECT = Path(r'\\wsl.localhost\Ubuntu-24.04\Users\pouya\.openclaw\workspace\kicad-copilot-research')
SOURCE_INVENTORY = Path(r'\\wsl.localhost\Ubuntu-24.04\Users\pouya\.migration\kicad-portable-yjws1atg\source-environment.json')
SOURCE_INVENTORY_SHA = '7f9146225d4ac3584f7ec87b74b7c1b8d45362ac962a5ddba8dab6524d653dce'
BASE = Path(r'C:\Users\pou\.migration')
PYTHON = Path(r'C:\Users\pou\AppData\Local\Programs\Python\Python312\python.exe')
KICAD = Path(r'C:\Users\pou\AppData\Local\Programs\KiCad\10.0\bin')
CONFIG = Path(r'C:\Users\pou\AppData\Roaming\kicad\10.0')
FILES = ('test2.kicad_pcb', 'test2.kicad_pro')
SETTINGS = ('kicad_common.json', 'kicad.json', 'pcbnew.json', 'fp-lib-table',
            'sym-lib-table', 'design-block-lib-table')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_capture(value):
    if value.get('uid') != 503 or set(value.get('files', {})) != set(FILES):
        raise ValueError('Unexpected source identity or scratch cohort')
    import base64
    result = {}
    for name, row in value['files'].items():
        content = base64.b64decode(row['base64'], validate=True)
        if len(content) > 2 << 20 or len(content) != row['size'] or hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Scratch source content/digest mismatch')
        result[name] = content
    return result


def settings_hashes(root):
    result = {}
    for name in SETTINGS:
        path = root / name
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError('Unsupported existing KiCad setting')
            result[name] = digest(path)
    return result


def native_environment(run):
    # Native Windows needs these platform paths, but no API-key inheritance.
    names = ('PATH', 'SystemRoot', 'WINDIR', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
             'COMSPEC', 'USERNAME', 'COMPUTERNAME')
    result = {name: os.environ[name] for name in names if name in os.environ}
    result.update(TEMP=str(run / 'tmp'), TMP=str(run / 'tmp'),
        KICAD_CONFIG_HOME=str(run / 'config'), KICAD_DOCUMENTS_HOME=str(run / 'documents'),
        KICAD_API_SOCKET='ipc://' + str(run / 'tmp/kicad/api.sock'),
        PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
        PYTHONPATH=os.pathsep.join((str(PROJECT), str(PROJECT / 'kicad-tools/src'),
                                   str(PROJECT / 'kipilot-mcp/src'))))
    return result


def client(run):
    from kipy import KiCad
    from kipy.proto.common.types import DocumentType
    endpoint = os.environ['KICAD_API_SOCKET']
    deadline = time.monotonic() + 40
    board = None
    while time.monotonic() < deadline:
        try:
            connection = KiCad(endpoint, timeout_ms=1000)
            docs = connection.get_open_documents(DocumentType.DOCTYPE_PCB)
            if len(docs) != 1:
                raise ValueError('Scratch endpoint must expose exactly one PCB')
            board = connection.get_board()
            expected = run / 'scratch/test2.kicad_pcb'
            document_path = Path(board.document.project.path)
            if document_path.suffix == '.kicad_pro':
                document_path = document_path.parent
            actual = document_path / board.name
            if actual.resolve() != expected.resolve():
                raise ValueError('Endpoint is not the exact disposable scratch board')
            break
        except ValueError:
            raise
        except Exception:
            time.sleep(0.5)
    if board is None:
        raise TimeoutError('Own scratch KiCad IPC did not become ready')
    before = board.get_as_string()
    initial = {'footprints': len(board.get_footprints()), 'nets': len(board.get_nets()),
               'tracks': len(board.get_tracks()), 'vias': len(board.get_vias()),
               'layers': board.get_copper_layer_count()}
    if initial['footprints'] != 5 or initial['layers'] != 2 or initial['tracks'] != 0:
        raise ValueError('Unexpected scratch fixture; no mutation tests run')
    save(run / 'ipc-ready.json', {'at': stamp(), 'endpoint': endpoint,
        'board': str(expected), 'initial': initial,
        'serializationSha256': hashlib.sha256(before.encode()).hexdigest()})
    import pytest
    result = pytest.main(['-p', 'no:cacheprovider', '--override-ini', 'addopts=', '-q',
        'copilot/test_state_bridge.py', 'copilot/test_executor.py',
        'copilot/test_scorer.py', 'copilot/test_loop.py', 'copilot/test_nudge.py'])
    after = board.get_as_string()
    save(run / 'client-result.json', {'at': stamp(), 'testsExit': result,
        'serializationRestored': before == after,
        'finalSerializationSha256': hashlib.sha256(after.encode()).hexdigest(),
        'modelStarted': False, 'productionBoardTouched': False})
    return 0 if result == 0 and before == after else 1


def main():
    if sys.platform != 'win32' or getpass.getuser().lower() != 'pou' or os.environ.get('COMPUTERNAME') != 'DESKTOP-8SO9HDK':
        raise ValueError('Exact native Windows PC owner required')
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError('Never run GUI/package qualification elevated')
    if len(sys.argv) == 3 and sys.argv[1] == '--client':
        run = Path(sys.argv[2])
        if run.parent != BASE or not run.name.startswith('kicad-native-') or run.is_symlink():
            raise ValueError('Exact private run directory required')
        os.chdir(PROJECT)
        return client(run)
    if len(sys.argv) != 1 or Path(sys.executable).resolve() != PYTHON.resolve():
        raise ValueError('Use the installed native Python3.12 for preparation')
    run = BASE / ('kicad-native-' + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'ccrelay.kicad_native_scratch_probe.v1', 'startedAt': stamp(),
        'runDirectory': str(run), 'modelStarted': False, 'productionBoardTouched': False,
        'routerChanged': False, 'sourceFilesChanged': False, 'operationalAcceptance': False}
    save(run / 'started.json', report)
    gui = None
    gui_log = None
    original = None
    try:
        original = settings_hashes(CONFIG)
        save(run / 'existing-settings-hashes.json', original)
        current = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-Command',
            '@(Get-Process pcbnew,kicad,eeschema -ErrorAction SilentlyContinue | Select-Object Id,ProcessName) | ConvertTo-Json -Compress'],
            capture_output=True, timeout=15)
        if current.returncode or current.stderr:
            raise ValueError('Could not verify absence of another KiCad GUI')
        if current.stdout.strip() and json.loads(current.stdout) not in (None, []):
            raise ValueError('An existing KiCad GUI is present; do not interact with it')
        if digest(SOURCE_INVENTORY) != SOURCE_INVENTORY_SHA:
            raise ValueError('Source package inventory hash changed')
        source = json.loads(SOURCE_INVENTORY.read_bytes())
        pins = requirements(source['packages'])
        if any(digest(PROJECT / name) != value for name, value in source['fileHashes'].items()):
            raise ValueError('PC project code differs from the observed source')
        save(run / 'source-environment.json', source)
        (run / 'requirements.txt').write_text('\n'.join(pins) + '\n', encoding='ascii')
        import base64
        remote_program = '''import base64,hashlib,json,os,stat,sys
from pathlib import Path
assert sys.platform == "darwin" and os.getuid() == 503
r = Path("/Users/Shared/kicad-scratch")
assert r.resolve() == r
assert set(os.listdir(r)) == {"test2.kicad_pcb", "test2.kicad_pro"}
rows = {}
for n in ("test2.kicad_pcb", "test2.kicad_pro"):
    p = r / n
    a = p.lstat()
    assert stat.S_ISREG(a.st_mode) and a.st_size < 2097152
    d = p.read_bytes()
    b = p.lstat()
    assert (a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns) == (b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
    rows[n] = {"size":len(d),"sha256":hashlib.sha256(d).hexdigest(),
        "base64":base64.b64encode(d).decode(),"mode":a.st_mode,"mtimeNs":a.st_mtime_ns}
print(json.dumps({"uid":os.getuid(),"files":rows}))
'''
        remote = 'import base64;exec(base64.b64decode("' + base64.b64encode(remote_program.encode()).decode() + '"))'
        capture = subprocess.run(['wsl.exe', '-d', 'Ubuntu-24.04', '-u', 'pou', '--exec',
            '/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', 'bench-mac',
            '/usr/bin/python3', '-c', shlex.quote(remote)], capture_output=True, timeout=45)
        if capture.returncode or capture.stderr:
            (run / 'capture-error.log').write_bytes(capture.stderr)
            raise ValueError('Source scratch capture failed; no GUI/test launched')
        captured = json.loads(capture.stdout)
        content = validate_capture(captured)
        save(run / 'source-scratch.private.json', captured)
        for folder in ('source', 'scratch', 'tmp', 'config/10.0', 'documents'):
            (run / folder).mkdir(parents=True, exist_ok=True)
        for name, data in content.items():
            for folder in ('source', 'scratch'):
                with open(run / folder / name, 'xb') as stream:
                    stream.write(data)
        report['sourceFiles'] = {name: row['sha256'] for name, row in captured['files'].items()}
        for name in original:
            shutil.copyfile(CONFIG / name, run / 'config/10.0' / name)
        common = json.loads((run / 'config/10.0/kicad_common.json').read_bytes())
        common.setdefault('api', {})['enable_server'] = True
        (run / 'config/10.0/kicad_common.json').write_text(json.dumps(common), encoding='utf-8')
        environment = native_environment(run)
        subprocess.run([str(PYTHON), '-m', 'venv', str(run / 'venv')], env=environment, check=True, timeout=45)
        python = str(run / 'venv/Scripts/python.exe')
        with open(run / 'install.log', 'xb') as log:
            installed = subprocess.run([python, '-m', 'pip', '--isolated', 'install', '--index-url',
                'https://pypi.org/simple', '--only-binary=:all:', '--no-input', '--no-cache-dir',
                '--disable-pip-version-check', '-r', str(run / 'requirements.txt')],
                env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        report['installExit'] = installed.returncode
        if installed.returncode:
            raise ValueError('Exact Windows wheels unavailable; no version substitution')
        inventory = subprocess.run([python, '-c',
            'import importlib.metadata as m,json;print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))'],
            env=environment, capture_output=True, check=True, timeout=20)
        actual = json.loads(inventory.stdout)
        save(run / 'pc-environment.json', actual)
        report['exactExternalPackageVersions'] = all(actual.get(line.split('==')[0]) == line.split('==')[1] for line in pins)
        if not report['exactExternalPackageVersions']:
            raise ValueError('Windows package versions differ from source')
        gui_log = open(run / 'gui.log', 'xb')
        gui = subprocess.Popen([str(KICAD / 'pcbnew.exe'), str(run / 'scratch/test2.kicad_pcb')],
            cwd=run / 'scratch', env=environment, stdout=gui_log, stderr=gui_log)
        save(run / 'gui-started.json', {'at': stamp(), 'pid': gui.pid, 'exe': str(KICAD / 'pcbnew.exe'),
            'exeSha256': digest(KICAD / 'pcbnew.exe'), 'scratchDirectory': str(run / 'scratch')})
        with open(run / 'live-tests.log', 'xb') as log:
            tested = subprocess.run([python, str(Path(__file__).resolve()), '--client', str(run)],
                cwd=PROJECT, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        report['clientExit'] = tested.returncode
        report['successful'] = tested.returncode == 0
    except Exception as error:
        report['successful'] = False
        report['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        if gui is not None:
            # Popen's retained process handle targets only our disposable GUI,
            # not an unrelated process or a potentially reused PID.
            if gui.poll() is None:
                gui.terminate()
            try:
                report['guiExit'] = gui.wait(timeout=10)
            except subprocess.TimeoutExpired:
                report['guiStillLive'] = True
            report['guiStillLive'] = gui.poll() is None
        if gui_log is not None:
            gui_log.close()
        report['existingSettingsUnchanged'] = original is not None and original == settings_hashes(CONFIG)
        if not report['existingSettingsUnchanged']:
            report['successful'] = False
        report['finishedAt'] = stamp()
        report['logHashes'] = {p.name: digest(p) for p in run.glob('*.log')}
        save(run / 'result.json', report)
    print(json.dumps(report))
    return 0 if report['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
