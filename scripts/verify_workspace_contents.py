"""Read-only, batched content verification of formerly size-only workspace matches.

Private reports only; never import, overwrite, delete, restart, or infer a final
snapshot. Source programs execute in memory through pinned-host encrypted SSH.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from inventory_migration_dirty import observe
from inventory_migration_tree import MAX_ENTRIES, MAX_OUTPUT, ROOT, leaf_differences, private_directory, relative, save_private
from stream_owner_tools import safe_name

BATCH_SIZE = 50000


def selected_names(comparison):
    if comparison.get('schema') != 'ccrelay.workspace_metadata_comparison.v1' or \
            comparison.get('sourceProblems') != 0 or comparison.get('errors'):
        raise ValueError('Problem-free metadata comparison required')
    names = comparison.get('sameTypeAndSizeUnverified')
    if not isinstance(names, list) or not 0 < len(names) <= MAX_ENTRIES:
        raise ValueError('Bounded formerly size-only file selection required')
    names = [relative(name) for name in names]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate file selection')
    return sorted(names)


def source_program():
    program = "import json,sys,types,os; assert sys.platform=='darwin' and os.getuid()==501\n"
    for name in ('inventory_migration_git', 'inventory_migration_dirty'):
        code = Path(__file__).with_name(name + '.py').read_text()
        program += 'm=types.ModuleType(' + repr(name) + ');sys.modules[m.__name__]=m;exec(' + repr(code) + ',m.__dict__)\n'
    program += "names=json.loads(sys.stdin.buffer.read());json.dump(m.observe(m.ROOT,names),sys.stdout,separators=(',',':'))"
    return program


def verify_contents(directory):
    directory = private_directory(directory)
    metadata = json.loads((directory / 'capture-receipt.json').read_bytes())
    raw = (directory / 'comparison.private.json').read_bytes()
    if len(raw) > MAX_OUTPUT or hashlib.sha256(raw).hexdigest() != metadata['comparison']['sha256']:
        raise ValueError('Captured metadata comparison hash mismatch')
    names = selected_names(json.loads(raw))
    program = source_program()
    payload = base64.b64encode(program.encode()).decode()
    command = '/opt/homebrew/bin/python3.14 -I -B -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(payload) + '))')
    started = time.time()
    save_private(directory / 'content-phase-start.json', {'pid': os.getpid(), 'startedAt': started,
                 'filesSelected': len(names), 'producerSha256': hashlib.sha256(program.encode()).hexdigest()})
    counts = {key: 0 for key in ('differentOrMissing', 'sameContentsOrLink', 'sourceAbsent', 'errors')}
    source_bytes, pc_bytes, batches = 0, 0, []
    for index in range(0, len(names), BATCH_SIZE):
        batch = names[index:index + BATCH_SIZE]
        number = index // BATCH_SIZE + 1
        prefix = 'content-batch-' + str(number)
        save_private(directory / (prefix + '-attempt.json'), {'pid': os.getpid(), 'startedAt': time.time(), 'files': len(batch)})
        print(json.dumps({'stage': 'checking-source', 'batch': number, 'files': len(batch), 'observerPid': os.getpid()}), flush=True)
        result = subprocess.run(['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                 '-o', 'ConnectTimeout=10', '-T', 'mac', command], input=json.dumps(batch).encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
        if result.returncode or result.stderr or len(result.stdout) > MAX_OUTPUT:
            save_private(directory / (prefix + '-failure.private.json'), {'exit': result.returncode,
                         'stdoutBase64': base64.b64encode(result.stdout).decode(),
                         'stderrBase64': base64.b64encode(result.stderr).decode()})
            raise RuntimeError('Source verification failed; retained private receipt, never retry blindly')
        source = json.loads(result.stdout)
        if [row['name'] for row in source['entries']] != batch:
            raise ValueError('Source returned a different selection')
        print(json.dumps({'stage': 'checking-pc', 'batch': number, 'files': len(batch)}), flush=True)
        pc = observe(ROOT, batch)
        differences = leaf_differences(source, pc)
        receipt = {'batch': number, 'files': len(batch), 'finishedAt': time.time(),
                   'source': save_private(directory / (prefix + '-source.private.json'), source),
                   'pc': save_private(directory / (prefix + '-pc.private.json'), pc),
                   'comparison': save_private(directory / (prefix + '-differences.private.json'), differences),
                   'counts': {key: len(value) for key, value in differences.items()},
                   'sourceBytesHashed': source['fileBytesHashed'], 'pcBytesHashed': pc['fileBytesHashed']}
        save_private(directory / (prefix + '-receipt.json'), receipt)
        for key in counts:
            counts[key] += receipt['counts'][key]
        source_bytes += receipt['sourceBytesHashed']; pc_bytes += receipt['pcBytesHashed']
        batches.append(receipt)
        print(json.dumps({'stage': 'batch-verified', 'batch': number, 'counts': receipt['counts']}), flush=True)
    report = {'schema': 'ccrelay.workspace_content_comparison.v1', 'startedAt': started, 'finishedAt': time.time(),
              'filesSelected': len(names), 'counts': counts, 'sourceBytesHashed': source_bytes, 'pcBytesHashed': pc_bytes,
              'batches': batches, 'allSelectedContentsMatch': counts['sameContentsOrLink'] == len(names),
              'allWorkspaceContentsVerified': False, 'sourceWritersFrozen': False, 'consistentFinalSnapshot': False,
              'targetModified': False, 'sourceDeleted': False}
    save_private(directory / 'content-verification-receipt.json', report)
    print(json.dumps({key: value for key, value in report.items() if key != 'batches'}), flush=True)


def checked_report(directory, name, expected):
    if '/' in name or '\\' in name:
        raise ValueError('Literal report basename required')
    raw = (directory / name).read_bytes()
    if len(raw) > MAX_OUTPUT or len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
        raise ValueError('Private content report byte/hash mismatch')
    return json.loads(raw)


def preservation_rows(directory, report):
    if report.get('schema') != 'ccrelay.workspace_content_comparison.v1' or report['counts']['errors'] or report['counts']['sourceAbsent']:
        raise ValueError('Complete error-free content comparison required')
    source_rows, pc_rows, seen = [], [], set()
    for batch in report['batches']:
        number = batch['batch']
        if type(number) is not int or not 1 <= number <= 20:
            raise ValueError('Bounded literal content batch required')
        prefix = 'content-batch-' + str(number)
        differences = checked_report(directory, prefix + '-differences.private.json', batch['comparison'])
        if differences['errors'] or differences['sourceAbsent']:
            raise ValueError('Incomplete batch cannot become an archive selection')
        source = checked_report(directory, prefix + '-source.private.json', batch['source'])
        pc = checked_report(directory, prefix + '-pc.private.json', batch['pc'])
        source_by_name = {row['name']: row for row in source['entries']}
        pc_by_name = {row['name']: row for row in pc['entries']}
        for row in differences['differentOrMissing']:
            name = safe_name(relative(row['name']))
            if name in seen or row.get('kind') != 'file' or source_by_name.get(name) != row or name not in pc_by_name:
                raise ValueError('Unique independently hashed exact file selection required')
            seen.add(name); source_rows.append(row); pc_rows.append(pc_by_name[name])
    if not source_rows or len(source_rows) != report['counts']['differentOrMissing']:
        raise ValueError('Complete nonempty mismatch selection required')
    return source_rows, pc_rows


def make_selection(directory, destination):
    directory = private_directory(directory); destination = private_directory(destination)
    if any(destination.iterdir()):
        raise ValueError('Fresh empty private selection directory required')
    report = json.loads((directory / 'content-verification-receipt.json').read_bytes())
    source_rows, pc_rows = preservation_rows(directory, report)
    # Retain the unchanged metadata capture. This remains unfenced, not a final
    # backup; the archive producer rechecks every selected current file hash.
    for name in ('capture-receipt.json', 'mac-metadata.private.json', 'comparison.private.json'):
        source_fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW)
        output_fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(source_fd, 'rb') as source, os.fdopen(output_fd, 'wb') as output:
            count = 0
            while chunk := source.read(1 << 20):
                count += len(chunk)
                if count > MAX_OUTPUT:
                    raise ValueError('Metadata copy byte bound')
                output.write(chunk)
            output.flush(); os.fsync(output.fileno())
    source = {'entries': source_rows, 'fileBytesHashed': sum(row['bytes'] for row in source_rows)}
    pc = {'entries': pc_rows, 'fileBytesHashed': sum(row.get('bytes', 0) for row in pc_rows)}
    differences = leaf_differences(source, pc)
    proof = {'schema': 'ccrelay.workspace_candidate_content_capture.v1', 'startedAt': report['startedAt'], 'finishedAt': time.time(),
             'selectionScope': 'same-size-content-mismatches', 'source': save_private(destination / 'candidate-source.private.json', source),
             'pc': save_private(destination / 'candidate-pc.private.json', pc),
             'comparison': save_private(destination / 'candidate-content-differences.private.json', differences),
             'counts': {key: len(value) for key, value in differences.items()},
             'sourceBytesHashed': source['fileBytesHashed'], 'pcBytesHashed': pc['fileBytesHashed'],
             'incompatibleNames': 0, 'allWorkspaceContentsVerified': False, 'sourceWritersFrozen': False, 'targetModified': False,
             'verification': save_private(destination / 'content-verification-receipt.json', report), 'selections': []}
    for index in range(0, len(source_rows), 4000):
        rows = source_rows[index:index + 4000]; name = 'candidate-selection-' + str(index // 4000 + 1) + '.private.json'
        selection = {'schema': 'ccrelay.dirty_source_selection.v1', 'entries': rows}
        if len(json.dumps(selection).encode()) > 4 << 20:
            raise ValueError('Exact-leaf receiver selection byte bound')
        proof['selections'].append({'name': name, 'entries': len(rows), 'fileBytes': sum(row['bytes'] for row in rows),
                                   **save_private(destination / name, selection)})
    save_private(destination / 'candidate-content-receipt.json', proof)
    print(json.dumps({'stage': 'selection-prepared', 'files': len(source_rows), 'fileBytes': source['fileBytesHashed'],
                      'batches': len(proof['selections']), 'targetModified': False}), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--make-selection':
        make_selection(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2:
        verify_contents(sys.argv[1])
    else:
        raise SystemExit('Exact existing private tree-audit directory required')
