#!/usr/bin/env python3
"""Verify the physical bench's preserved working payload without executing it.

Source reads use the existing pinned SSH host. No credentials, signing,
hardware operations, services or model requests. Darwin OpenOCD is retained in
the protected operational archive, not admitted as a Linux tool installation.
Generated inventories and receipts belong in the owner's private .migration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import sys
import time

ROOT = Path('/Users/pouya/oracova-bench')
SOURCE_ROOTS = {'bench': '/Users/oracova/oracova-bench', 'supervisor-tools': '/Users/oracova/supervisor-tools'}
EXCLUDED = 'xpack-openocd-0.12.0-7'
MAX_FILES = 3000
MAX_BYTES = 128 * 1024 * 1024
SOURCE = r'''
require 'etc'
root = '/Users/oracova/oracova-bench'
raise 'Source owner/root mismatch' unless Etc.getpwuid(Process.uid).name == 'oracova' &&
  File.realpath(root) == root && File.stat(root).uid == Process.uid
files = {}; directories = ['']
Dir.glob(root + '/**/*', File::FNM_DOTMATCH).sort.each do |path|
  next if ['.', '..'].include?(File.basename(path))
  relative = path[(root.length + 1)..-1]
  next if relative.split('/').first == 'xpack-openocd-0.12.0-7'
  info = File.lstat(path)
  raise 'Unexpected source member' unless info.file? || info.directory?
  if info.directory?
    directories << relative
  else
    files[relative] = {'bytes' => info.size, 'sha256' => Digest::SHA256.file(path).hexdigest}
  end
end
puts JSON.generate({'schema' => 'ccrelay.personal_bench_payload.v1',
  'source' => root, 'excludedDarwinTool' => 'xpack-openocd-0.12.0-7',
  'files' => files, 'directories' => directories})
'''


def relative_path(value, allow_root=False):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise ValueError('Invalid inventory path')
    if allow_root and value == '':
        return value
    parts = value.split('/')
    if not value or value.startswith('/') or any(part in ('', '.', '..') for part in parts) or \
            str(PurePosixPath(value)) != value or parts[0] == EXCLUDED:
        raise ValueError('Inventory escapes the selected payload')
    return value


def inventory(value):
    if value.get('schema') != 'ccrelay.personal_bench_payload.v1' or \
            value.get('source') not in SOURCE_ROOTS.values() or value.get('excludedDarwinTool') != EXCLUDED:
        raise ValueError('Wrong physical bench inventory')
    files = value['files']; directories = value['directories']
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES or not isinstance(directories, list) or \
            not 1 <= len(directories) <= MAX_FILES or '' not in directories or len(set(directories)) != len(directories):
        raise ValueError('Invalid bounded inventory')
    for path in directories:
        relative_path(path, allow_root=True)
        if path:
            parent = str(PurePosixPath(path).parent)
            if ('' if parent == '.' else parent) not in directories or path in files:
                raise ValueError('Incomplete directory ancestry')
    for path, entry in files.items():
        relative_path(path)
        if not isinstance(entry, dict) or type(entry.get('bytes')) is not int or not 0 <= entry['bytes'] <= MAX_BYTES or \
                not isinstance(entry.get('sha256'), str) or len(entry['sha256']) != 64 or \
                any(char not in '0123456789abcdef' for char in entry['sha256']):
            raise ValueError('Invalid pinned file metadata')
        parent = str(PurePosixPath(path).parent)
        if ('' if parent == '.' else parent) not in directories or path in directories:
            raise ValueError('Incomplete directory inventory')
    if sum(entry['bytes'] for entry in files.values()) > MAX_BYTES:
        raise ValueError('Payload exceeds inspection bound')
    return value


def private(path, directory):
    info = path.lstat()
    if info.st_uid != 1000 or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode)):
        raise ValueError('Literal PC-owner object required')
    expected = 0o700 if directory else 0o600
    if stat.S_IMODE(info.st_mode) != expected:
        raise ValueError('Owner-private permissions required')


def write_private(path, value):
    if not path.is_absolute() or '..' in path.parts or not str(path).startswith('/Users/pouya/.migration/'):
        raise ValueError('Private migration receipt path required')
    parent = path.parent
    while parent != Path('/Users/pouya'):
        private(parent, True); parent = parent.parent
    private(parent, True)
    body = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as output:
        output.write(body); output.flush(); os.fsync(output.fileno())
    return hashlib.sha256(body).hexdigest()


def verify(value, root=ROOT):
    inventory(value)
    for directory in value['directories']:
        private(root / directory, True)
    for relative, entry in value['files'].items():
        path = root / relative; info = path.lstat()
        mode = 0o700 if relative == 'keys/oimgkey.py' else 0o600
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != mode or \
                info.st_size != entry['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('PC file identity, content or permissions differ')
    return {'schema': 'ccrelay.personal_bench_payload_check.v1', 'complete': True,
            'files': len(value['files']), 'bytes': sum(entry['bytes'] for entry in value['files'].values()),
            'directories': len(value['directories']), 'originalFilesMatched': True, 'uid': 1000,
            'ownerPrivateModesVerified': True, 'destination': str(root), 'at': time.time(),
            'excludedDarwinTool': EXCLUDED, 'darwinToolLinuxAcceptance': False,
            'hardwareOrSigningActions': False, 'servicesOrModelsStarted': False}


def run(args):
    if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000:
        raise ValueError('Ordinary PC Linux owner required')
    if args.snapshot_source:
        selected = SOURCE.replace('/Users/oracova/oracova-bench', SOURCE_ROOTS[args.source_kind])
        command = '/usr/bin/ruby -rjson -rdigest -retc -e ' + shlex.quote(selected)
        result = subprocess.run(['/usr/bin/ssh', '-o', 'BatchMode=yes', 'bench-mac', command],
                                capture_output=True, timeout=60, check=True)
        if len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError('Source inventory exceeds bounds')
        value = inventory(json.loads(result.stdout))
        digest = write_private(Path(args.snapshot_source), value)
        print(json.dumps({'sourceInventorySha256': digest, 'files': len(value['files']),
                          'bytes': sum(entry['bytes'] for entry in value['files'].values())}))
    else:
        path = Path(args.verify); private(path, False)
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != args.expected_sha256:
            raise ValueError('Source inventory digest changed')
        value = inventory(json.loads(body))
        destination = Path('/Users/pouya') / value['source'].rsplit('/', 1)[-1]
        result = verify(value, root=destination)
        result['sourceInventorySha256'] = args.expected_sha256
        if args.result:
            write_private(Path(args.result), result)
        print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--snapshot-source')
    choice.add_argument('--verify')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--result')
    parser.add_argument('--source-kind', choices=SOURCE_ROOTS, default='bench')
    arguments = parser.parse_args()
    try:
        run(arguments)
    except Exception as error:
        print(json.dumps({'complete': False, 'failureType': type(error).__name__}))
        raise SystemExit(1)
