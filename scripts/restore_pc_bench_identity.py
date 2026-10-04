#!/usr/bin/env python3
"""Restore exact existing bench identities; no signing, enrollment or services.

The protected Windows archive is read through a reviewed administrator bootstrap
as Linux UID 1000. This is personal-owner migration, NOT company-role isolation.
Only individually pinned regular files are copied, never tar.extractall().
Existing targets and interrupted attempts are retained, never overwritten.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import time

ROOT = Path('/Users/pouya')
ARCHIVE = Path('/mnt/c/ProgramData/OracovaMigration/38258191bb20aac6fae35f6f964cefd8/physical-bench-operational-sftp.tar.gz')
ARCHIVE_BYTES = 2629314560
ARCHIVE_SHA = '48542d3b8f5ecbd74537ea3be82234667f1d6a42366473172ccab8398f44da2a'
DESTINATION = ROOT / 'oracova-bench'
# Fresh physical-bench owner observation. File bodies never appear in output.
FILES = {
    'keys/dev.pem': (119, 'b17e2ef4fe43a070b93c5f36262dfc8e6a62eb095257818b81c75a523e5ba34d'),
    'keys/operator.pem': (119, 'ddb3039cf34cbb1c2e9709e8f72e782d7b873a96df601e473d564cf0017d712e'),
    'keys/policy.pem': (119, 'ebe798e272d5295a78ac8672e680df09d782bc0eea94466b578212e9d576ba2a'),
    'keys/alice.pem': (119, '7c0771befe967deb12e2d311c2dcaaa588b39f3ff055b1b09a05b98a6cbbd90c'),
    'keys/bob.pem': (119, '5a9c35837cb5bdbd51720499cbb0d78046dae6d9647cdf90f39cf1d89358a1ef'),
    'keys/oimgkey.py': (3065, 'ba718c58846c008b0d9b582ab64e880a57814383d2dfc551275e94726e3c890c'),
    'keys/opk_v1.hex': (449, '226d63189e458e98f69fd43702052cc6920a2cc3c28b89ba592611db8bf57fe8'),
    'keys/opk_v2.hex': (449, 'e3c8b59c0d9d4d94f3ea3365951f3f58714cd5617b224493439a67d449e730fe'),
    'keys/opk_v3.hex': (449, '9154b3eaa89540d0d5b6c5064c23d80f0c1317eed8ea8e6a6bf1cb2bcad87634'),
    'keys/opk_v4.hex': (449, 'd585b868d3850822944c2a420e839665361eba7dcdd291dcf496e66b35d04d6d'),
    'keys/opk_v5.hex': (449, 'c5dc9fb6983e5d2f96ead4666ff7dca95347d8814f2deb9daa4b20f18a3ee6a5'),
    'keys/opk_v6.hex': (449, '2e7218eb8381b04017ceb3fadc4335f8a39de515eaddda10b0f99a069f788c11'),
    'pki/nucleo1/operator_roots.der': (420, 'cc3b704f62eb4b1c176e30d8dc45e2d1346012e82cc047fdcf83c8bf1134f553'),
    'pki/nucleo1/pouya.p12': (1611, '73a6d8cbb70986a8229ef645d62755a35d7a34cbe7b87494573341cb48c234ac'),
    'pki/nucleo1/device_ca_key.pem': (241, '2314cb77de509a3735ed5e334d8b9f843b634d11185de9afe23700e612eb4e8c'),
    'pki/nucleo1/issued_leaf.der': (483, '92fd43b3b2d7d9533424eb08d94c45c3a2a151aea92b7f4a604a9aab44761482'),
    'pki/nucleo1/device_chain.der': (435, 'b4d23789194a0d6fdad4dd33049e45965c5342eb7541ee23de565235c372d7ea'),
    'pki/nucleo1/operator_ca.pem': (623, '8f104b2596d7fca6630c825e75d0e37c6e5856af756217c21de5d589ff49e9c9'),
    'pki/nucleo1/device_ca.pem': (635, '9f5fad913687bb8dc61a8156c3bdb790b1f50da13f3dcb50f50433f45d641aa2'),
    'pki/nucleo1/pouya.pem': (1959, '466b45d2d4b23d1d89ceb6022a73c88edfc4433c182d098e56d159cf7d62998d'),
    'pki/nucleo1/device_key.der': (138, 'a063d579378dc6b2fab883d8f27fe69cc1382d8cad43966297a50efe9751616d'),
}


def gather(source, expected=FILES):
    """Bounded regular-file reads; arbitrary archive siblings cannot extract."""
    found = {}
    with tarfile.open(fileobj=source, mode='r|gz') as archive:
        for member in archive:
            prefix = 'oracova-bench/'
            relative = member.name[len(prefix):] if member.name.startswith(prefix) else None
            if relative not in expected:
                continue
            size, digest = expected[relative]
            if relative in found or not member.isfile() or member.islnk() or member.issym() or member.size != size:
                raise ValueError('Selected bench identity is duplicated, non-regular or incorrectly sized')
            with archive.extractfile(member) as entry:
                body = entry.read(size + 1)
            if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
                raise ValueError('Selected identity does not match the original bench file')
            found[relative] = body
    if found.keys() != expected.keys():
        raise ValueError('Original bench identities are missing from the archive')
    return found


def private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Literal private PC owner directory required')


def durable(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as output:
        output.write(json.dumps(value, separators=(',', ':')))
        output.flush(); os.fsync(output.fileno())


def run(generation, restore):
    if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000:
        raise ValueError('Ordinary PC Linux owner required')
    if not re.fullmatch('[0-9a-f]{32}', generation):
        raise ValueError('Literal migration generation required')
    os.umask(0o077)
    private_directory(ROOT); private_directory(ROOT / '.migration')
    attempt = ROOT / '.migration' / ('bench-identity-' + generation)
    if attempt.exists() or attempt.is_symlink():
        raise ValueError('Existing attempt must be inspected, never replayed')
    if restore and (DESTINATION.exists() or DESTINATION.is_symlink()):
        raise ValueError('Existing bench destination preserved')
    attempt.mkdir(mode=0o700)
    report = {'schema': 'ccrelay.personal_bench_identity_restore.v1', 'complete': False,
              'uid': 1000, 'generation': generation, 'restore': restore,
              'archive': str(ARCHIVE), 'archiveSha256': ARCHIVE_SHA,
              'destination': str(DESTINATION), 'modelInference': False, 'servicesStarted': False,
              'keysGenerated': False, 'signaturesOrEnrollmentPerformed': False,
              'bootstrapUsedAdministrativeWindowsToken': True, 'companyRoleIsolation': False}
    durable(attempt / 'attempt.json', report)
    before = ARCHIVE.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != ARCHIVE_BYTES:
        raise ValueError('Exact retained protected archive required')
    with ARCHIVE.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != ARCHIVE_SHA:
            raise ValueError('Protected source archive digest changed')
        source.seek(0)
        found = gather(source)
    after = ARCHIVE.lstat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Source archive changed during inspection')
    if restore:
        payload = attempt / 'payload'; payload.mkdir(mode=0o700)
        for directory in ['keys', 'pki', 'pki/nucleo1']:
            (payload / directory).mkdir(mode=0o700)
        for relative, body in found.items():
            path = payload / relative
            mode = 0o700 if relative == 'keys/oimgkey.py' else 0o600
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode), 'wb') as output:
                output.write(body); output.flush(); os.fsync(output.fileno())
        # renameat2 NOREPLACE is supplied by GNU mv -T -n; do not let a target
        # that appeared after preflight be overwritten by directory rename.
        import subprocess
        move = subprocess.run(['/usr/bin/mv', '-T', '-n', str(payload), str(DESTINATION)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if move.returncode or payload.exists():
            raise ValueError('Destination appeared or move failed; both copies preserved')
        for directory in [DESTINATION, DESTINATION / 'keys', DESTINATION / 'pki', DESTINATION / 'pki/nucleo1']:
            private_directory(directory)
        for relative, (size, digest) in FILES.items():
            path = DESTINATION / relative; info = path.lstat()
            mode = 0o700 if relative == 'keys/oimgkey.py' else 0o600
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != mode or \
                    info.st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Restored identity owner/mode/content not verified')
    report.update(complete=True, files=len(found), bytes=sum(len(body) for body in found.values()),
                  archiveVerified=True, originalIdentityHashesMatched=True,
                  privateRestoredModesVerified=restore, originalFiles=FILES, at=time.time())
    durable(attempt / 'result.json', report)
    print(json.dumps({key: value for key, value in report.items() if key != 'originalFiles'}, separators=(',', ':')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generation', required=True)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    try:
        run(args.generation, args.restore)
    except BaseException as error:
        # No parser/file contents or native exceptions can leak key material.
        print(json.dumps({'complete': False, 'failureType': type(error).__name__, 'replayAllowed': False}))
        raise SystemExit(1)
