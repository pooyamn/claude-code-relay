#!/usr/bin/env python3
"""Install the exact Linux counterpart of the preserved Mac OSS CAD suite.

No package upgrade, global PATH change, service, model, hardware connection or
privileged process. Download separately; verify the published release digest,
inspect all members, extract into a new private stage, and never replace an
existing installation. Failed/interrupted stages remain for reconciliation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat
import subprocess
import sys
import tarfile
import time

HOME_ROOT = Path('/Users/pouya')
ARCHIVE_NAME = 'oss-cad-suite-linux-x64-20260621.tgz'
ARCHIVE_BYTES = 717428552
ARCHIVE_SHA256 = '2bc1823e76b4bcae8750c5063cde4a8ae0d9143bf255f5a1b956e372be60f732'
SUITE = 'oss-cad-suite'
MAX_MEMBERS = 150000
MAX_UNPACKED = 8 * 1024 * 1024 * 1024


def validate_members(members):
    names = set(); size = 0
    if not 1 <= len(members) <= MAX_MEMBERS:
        raise ValueError('Invalid release member bound')
    for member in members:
        name = member.name.rstrip('/')
        parts = name.split('/')
        if not name or any(part in ('', '.', '..') for part in parts) or parts[0] != SUITE or \
                str(PurePosixPath(name)) != name or any(ord(char) < 32 for char in name):
            raise ValueError('Release member escapes the suite root')
        if name in names:
            raise ValueError('Duplicate release member')
        names.add(name)
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError('Special release member is not allowed')
        if member.issym() or member.islnk():
            target = member.linkname
            if not target or target.startswith('/') or any(ord(char) < 32 for char in target):
                raise ValueError('Unsafe release link')
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target) if member.issym() else target)
            if resolved != SUITE and not resolved.startswith(SUITE + '/'):
                raise ValueError('Release link escapes the suite root')
        if member.size < 0 or member.size > 512 * 1024 * 1024:
            raise ValueError('Oversized release member')
        size += member.size
        if size > MAX_UNPACKED:
            raise ValueError('Release exceeds unpacking bound')
    return {'members': len(members), 'unpackedFileBytes': size}


def private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Literal owner-private installation directory required')


def receipt(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as output:
        json.dump(value, output, separators=(',', ':')); output.flush(); os.fsync(output.fileno())


def run(directory):
    if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000:
        raise ValueError('Ordinary PC Linux owner required')
    if directory.parent != HOME_ROOT / '.migration' or not directory.name.startswith('bench-tools-'):
        raise ValueError('Literal private bench-tool generation required')
    private_directory(HOME_ROOT); private_directory(directory.parent); private_directory(directory)
    destination = HOME_ROOT / SUITE
    if destination.exists() or destination.is_symlink() or (directory / 'oss-cad-attempt.json').exists():
        raise ValueError('Existing installation or attempt retained; never replay or overwrite')
    archive_path = directory / ARCHIVE_NAME
    info = archive_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or info.st_size != ARCHIVE_BYTES:
        raise ValueError('Exact downloaded Linux release required')
    report = {'schema': 'ccrelay.personal_oss_cad_install.v1', 'complete': False,
              'archive': str(archive_path), 'archiveSha256': ARCHIVE_SHA256,
              'destination': str(destination), 'release': '20260621', 'uid': 1000,
              'hardwareOrSigningActions': False, 'servicesOrModelsStarted': False,
              'globalPathOrShellConfigChanged': False}
    receipt(directory / 'oss-cad-attempt.json', report)
    with archive_path.open('rb') as archive_file:
        if hashlib.file_digest(archive_file, 'sha256').hexdigest() != ARCHIVE_SHA256:
            raise ValueError('Published official release digest does not match')
        archive_file.seek(0)
        with tarfile.open(fileobj=archive_file, mode='r:gz') as archive:
            members = archive.getmembers(); counts = validate_members(members)
            stage = directory / 'oss-cad-stage'; stage.mkdir(mode=0o700)
            # Python's data filter rejects filesystem-resolved escaping links
            # as well as the lexical restrictions checked before any extraction.
            archive.extractall(stage, members=members, filter='data')
    after = archive_path.lstat()
    if (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Release archive changed during installation')
    payload = stage / SUITE
    if payload.is_symlink() or not payload.is_dir() or (payload / 'VERSION').read_text().strip() != '20260621':
        raise ValueError('Wrong extracted native suite')
    if (payload / 'libexec/openocd').read_bytes()[:4] != b'\x7fELF':
        raise ValueError('Linux OpenOCD image is not ELF')
    payload.chmod(0o700)
    move = subprocess.run(['/usr/bin/mv', '-T', '-n', str(payload), str(destination)], capture_output=True)
    if move.returncode or payload.exists():
        raise ValueError('Destination appeared or move failed; both copies retained')
    private_directory(destination)
    native = destination / 'libexec/openocd'
    report.update(complete=True, **counts, at=time.time(), publishedDigestVerified=True,
                  linuxOpenOcdSha256=hashlib.sha256(native.read_bytes()).hexdigest(),
                  existingDestinationReplaced=False)
    receipt(directory / 'oss-cad-result.json', report)
    print(json.dumps(report, separators=(',', ':')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        run(Path(args.directory))
    except Exception as error:
        print(json.dumps({'complete': False, 'failureType': type(error).__name__, 'replayAllowed': False}))
        raise SystemExit(1)
