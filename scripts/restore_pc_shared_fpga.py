#!/usr/bin/env python3
"""Restore the exact preserved FPGA work files; never start a bridge or flash.

The protected archive/index are read only by the accepted administrator-origin
maintenance bootstrap as Linux UID1000. This is personal migration, not role
isolation. No archive links, hooks or source programs are executed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import time

ROOT = Path('/Users/pouya')
COHORT = 'Shared/fpga/'
ARCHIVE = Path('/mnt/c/ProgramData/OracovaMigration/2b2d3a5af5e74d1b9a470380aac0acb6/physical-shared.tar.gz')
INDEX = ARCHIVE.parent / 'shared-members.private.json'
ARCHIVE_SHA = 'a56382216e93d00ed0d283eeddc55181139df9a70c30ade1b58d8ac2ddba091f'
INDEX_SHA = 'c635b82b84b35e5fa035a0601d4448e0c3057c94d547211824ad4a58dbd30bc8'
DESTINATION = ROOT / 'fpga-bench'
MAX_BYTES = 128 << 20


def leaf(name):
    if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\0' in name:
        raise ValueError('Literal flat FPGA filename required')
    return name


def expected_files(index):
    if index.get('schema') != 'ccrelay.shared_archive_contents.v1' or not index.get('verified'):
        raise ValueError('Verified retained archive index required')
    files = {}
    for row in index['rows']:
        if not row['name'].startswith(COHORT):
            continue
        name = leaf(row['name'][len(COHORT):])
        if name in files or row['kind'] != '0' or not re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')):
            raise ValueError('Unique regular FPGA member required')
        size = row['size']
        if type(size) is not int or size < 0 or size > MAX_BYTES:
            raise ValueError('Bounded FPGA file required')
        files[name] = (size, row['sha256'])
    if len(files) != 61 or sum(size for size, _ in files.values()) > MAX_BYTES:
        raise ValueError('Complete observed 61-file FPGA cohort required')
    return files


def gather(source, expected):
    found = {}
    with tarfile.open(fileobj=source, mode='r|gz') as archive:
        for member in archive:
            if member.name == COHORT.rstrip('/'):
                if not member.isdir():
                    raise ValueError('FPGA root must be a directory')
                continue
            if not member.name.startswith(COHORT):
                continue
            name = leaf(member.name[len(COHORT):])
            if name not in expected or name in found or not member.isfile() or member.islnk() or member.issym():
                raise ValueError('Unexpected, duplicated or linked FPGA member')
            size, digest = expected[name]
            if member.size != size:
                raise ValueError('FPGA size differs from retained index')
            with archive.extractfile(member) as stream:
                body = stream.read(size + 1)
            if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
                raise ValueError('FPGA bytes differ from retained index')
            found[name] = body
    if found.keys() != expected.keys():
        raise ValueError('FPGA archive cohort is incomplete')
    return found


def private_directory(path):
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Literal owner-private directory required')


def durable(path, body):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())


def run(generation):
    if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000 or not re.fullmatch('[0-9a-f]{32}', generation):
        raise ValueError('Exact ordinary PC owner and migration generation required')
    os.umask(0o077)
    private_directory(ROOT); private_directory(ROOT / '.migration')
    attempt = ROOT / '.migration' / ('fpga-restore-' + generation)
    if attempt.exists() or attempt.is_symlink() or DESTINATION.exists() or DESTINATION.is_symlink():
        raise ValueError('Existing destination/attempt must be inspected, never overwritten')
    attempt.mkdir(mode=0o700)
    report = dict(schema='ccrelay.personal_fpga_work_restore.v1', generation=generation, complete=False,
                  archiveSha256=ARCHIVE_SHA, indexSha256=INDEX_SHA, destination=str(DESTINATION),
                  servicesStarted=False, hardwareAccessed=False, sourceChanged=False, modelInference=False,
                  administrativeWindowsReadBootstrap=True, companyRoleIsolation=False)
    durable(attempt / 'attempt.json', json.dumps(report).encode())
    index_bytes = INDEX.read_bytes()
    if hashlib.sha256(index_bytes).hexdigest() != INDEX_SHA:
        raise ValueError('Protected archive index changed')
    expected = expected_files(json.loads(index_bytes))
    before = ARCHIVE.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != 546447360:
        raise ValueError('Exact retained archive required')
    with ARCHIVE.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != ARCHIVE_SHA:
            raise ValueError('Protected archive content changed')
        source.seek(0); found = gather(source, expected)
    after = ARCHIVE.lstat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Archive changed during restore')
    payload = attempt / 'payload'; payload.mkdir(mode=0o700)
    for name, body in found.items():
        durable(payload / name, body)
    move = subprocess.run(['/usr/bin/mv', '-T', '-n', str(payload), str(DESTINATION)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    if move.returncode or payload.exists():
        raise ValueError('Destination appeared or owned move failed; retain both')
    private_directory(DESTINATION)
    for name, (size, digest) in expected.items():
        path = DESTINATION / name; info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o600 or \
                info.st_nlink != 1 or info.st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Restored owner/mode/content not verified')
    report.update(complete=True, files=len(found), bytes=sum(len(body) for body in found.values()),
                  originalFiles=expected, at=time.time(), finalSourceSnapshot=False,
                  bridgeActivationApproved=False, physicalHardwareAcceptance=False)
    durable(attempt / 'result.json', json.dumps(report, separators=(',', ':')).encode())
    print(json.dumps({k: v for k, v in report.items() if k != 'originalFiles'}, separators=(',', ':')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--generation', required=True)
    args = parser.parse_args()
    try:
        run(args.generation)
    except BaseException as error:
        print(json.dumps({'complete': False, 'failureType': type(error).__name__, 'replayAllowed': False}))
        raise SystemExit(1)
