#!/usr/bin/env python3
"""Observe one completed Claude input in native history, never send or resume."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


def verify(package, workspace, session, uuid, expected):
    if not re.fullmatch(r'/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-[a-f0-9]{32}', package):
        raise ValueError('Exact protected connector required')
    sys.path.insert(0, package)
    from pc_claude_stdio import (OWNER, acquire_lease, attest_workspaces, decode_frame,
                                no_session_writer, quiescent_history, require_owner, session_id)
    from pc_native_stdio import _file_identity
    require_owner(); session_id(session); session_id(uuid)
    gate = attest_workspaces([workspace]); gate()
    path = OWNER / '.claude/projects' / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')
    lease = acquire_lease(session)
    try:
        no_session_writer(session)
        for candidate in reversed([path, *path.parents]):
            m = candidate.lstat()
            uid = 1000 if candidate == OWNER or OWNER in candidate.parents else 0
            if m.st_uid != uid or m.st_mode & 0o022 or stat.S_ISLNK(m.st_mode) or candidate != path and not stat.S_ISDIR(m.st_mode):
                raise ValueError('Literal ordinary-owner history required')
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError('Single literal history file required')
            digest = hashlib.sha256(); matches = []
            for line in source:
                digest.update(line); row = decode_frame(line)
                if row.get('uuid') != uuid:
                    continue
                message = row.get('message', {}); content = message.get('content')
                if row.get('type') != 'user' or row.get('sessionId') != session or row.get('isSidechain') or message.get('role') != 'user' or \
                        type(content) is not list or len(content) != 1 or content[0].get('type') != 'text' or type(content[0].get('text')) is not str:
                    raise ValueError('Exact primary plain-text native input required')
                if hashlib.sha256(content[0]['text'].encode()).hexdigest() != expected:
                    raise ValueError('Native input content differs')
                matches.append(row.get('timestamp'))
            if len(matches) != 1:
                raise ValueError('Exactly one saved input required')
            source.seek(0); quiescent_history(source, session, workspace)
            if _file_identity(before) != _file_identity(os.fstat(source.fileno())) or _file_identity(before) != _file_identity(path.lstat()):
                raise ValueError('History changed during inspection')
        no_session_writer(session); gate()
        return dict(type='ccrelay_claude_delivery_evidence', session_id=session, uuid=uuid, workspace=workspace,
                    content_sha256=expected, history_sha256=digest.hexdigest(), history_bytes=before.st_size,
                    input_timestamp=matches[0], history_quiescent=True, native_writer=False, model_inference=False)
    finally:
        lease.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'workspace', 'session', 'uuid', 'content-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.package, args.workspace, args.session, args.uuid, args.content_sha256)), flush=True)
    except Exception as error:
        print('Native receipt verification failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
