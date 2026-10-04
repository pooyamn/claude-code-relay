#!/usr/bin/env python3
"""Read-only final-history evidence for the exact three PC Claude topics."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

PROJECTS = {
    '7dc840b0-402f-451e-bc79-dadfb706d363': ('ai-hil/hardware/duts', 53),
    '6159472a-7878-42e4-b497-ffbb64a7e2d6': ('schematic-pipeline-lab', 2697),
    '10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2': ('mimic-fast-pcb', 3315),
}
if sys.platform != 'linux' or os.getuid() != 1000 or os.geteuid() != 1000:
    raise ValueError('Exact ordinary PC Linux owner required')
results = []
for session, (relative, topic) in PROJECTS.items():
    workspace = '/Users/pouya/.openclaw/workspace/' + relative
    path = Path('/Users/pouya/.claude/projects') / re.sub(r'[/\.]', '-', workspace) / (session + '.jsonl')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != 1000 or before.st_mode & 0o077:
        raise ValueError('Private literal native history required')
    sessions = set()
    with path.open('rb') as source:
        sha = hashlib.file_digest(source, 'sha256').hexdigest()
        source.seek(0)
        for line in source:
            row = json.loads(line)
            if row.get('sessionId'):
                sessions.add(row['sessionId'])
    after = path.lstat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns) or sessions != {session}:
        raise ValueError('History changed or belongs to another native conversation')
    producers = []
    for process in Path('/proc').glob('[0-9]*'):
        try:
            arguments = (process / 'cmdline').read_bytes().split(b'\0')
            if any(value in (('--resume=' + session).encode(), ('--session-id=' + session).encode(), session.encode())
                   for value in arguments):
                producers.append(int(process.name))
        except (OSError, ProcessLookupError):
            pass
    results.append({'session': session, 'workspace': workspace, 'chat': -1004395661179, 'topic': topic,
                    'path': str(path), 'bytes': before.st_size, 'sha256': sha, 'uid': 1000, 'liveProducers': producers})
print(json.dumps(results, separators=(',', ':')))
