"""Ordinary-owner live acceptance: read PDFs, never credential contents."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path('/mnt/c/ProgramData/KhadangRouter')
FILES = (
    ('759325588-f941695071c14250bff79522b23fbda4/38744db5b05b4bcf8e8cf8c14de21330.bin',
     69523, 'e11868962d2e6f157492684b2a278f72b78c10b6b7aa74fcf9dbb4c4dd832ae4'),
    ('759325589-8e04b6057c214c1c8d6f05e78423ad3c/a98ac0b84a8045d1815e844447d26476.bin',
     179824, '1fc9f185d92ed0d7f2e85befaaa3fedfca5cfb1fb188aff2d099a1424de593a4'),
)


def main():
    if os.geteuid() != 1000:
        raise RuntimeError('Acceptance must run as the ordinary native agent UID, not root')
    checks = 1
    verified = []
    for relative, size, expected in FILES:
        path = ROOT / 'state/attachments' / relative
        with path.open('rb') as stream:
            data = stream.read(20_000_001)
        if len(data) != size or not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('PDF bytes differ from the retained download manifest')
        checks += 3
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CLOEXEC)  # No truncate/write.
        except PermissionError:
            checks += 1
        else:
            os.close(descriptor)
            raise RuntimeError('Attachment must remain read-only to the native owner')
        verified.append({'path': str(path), 'size': size, 'sha256': expected, 'pdfReadable': True})
    for path in (ROOT / 'khadang-token.dpapi', ROOT / 'config.json', ROOT / 'state/router.db',
                 Path('/mnt/c/ProgramData/KhadangClaudeHost/installed.json')):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        except PermissionError:
            checks += 1
        else:
            os.close(descriptor)  # Never read a credential/private-state byte.
            raise RuntimeError('Protected credentials/configuration/state must remain unreadable')
    for directory in (ROOT, ROOT / 'state'):
        try:
            os.listdir(directory)
        except PermissionError:
            checks += 1
        else:
            raise RuntimeError('Traversal must not allow listing private ancestor directories')
    print(json.dumps({'checksPassed': checks, 'nativeUid': os.geteuid(), 'files': verified,
                      'privateFilesDenied': 4, 'privateDirectoryListingsDenied': 2,
                      'attachmentWritesDenied': 2, 'credentialBytesRead': 0}))


if __name__ == '__main__':
    main()
