#!/usr/bin/env python3
"""One PC-controller request; no local creation or privilege changes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path('/Users/pouya/.openclaw/workspace/claude-code-relay')
BRIDGE = REPO / 'scripts/pc_ccrelay_mcp.py'


def build_request(catalog, args, thread_id):
    if catalog.get('registry') != 'pc-native':
        raise ValueError('Verified PC registry required')
    sources = [s for s in catalog['sessions'] if
               (s['threadId'] == thread_id if thread_id else s['name'] == catalog.get('you'))]
    if len(sources) != 1:
        raise ValueError('Exact originating native session required')
    source = sources[0]
    backend = source['tool'] if args.backend == 'auto' else args.backend
    if args.mode == 'existing' and not args.thread_id:
        raise ValueError('Existing enrollment requires its exact native ID')
    return {'operation': 'topic-create' if args.mode == 'fresh' else 'topic-enroll',
            'requestKey': args.intent_id, 'source': source, 'sourceUpdate': args.source_update,
            'name': args.name, 'backend': backend, 'mode': args.mode,
            'workspace': args.workspace, 'threadId': args.thread_id,
            'destination': 'same-original-forum', 'humanRequest': args.human_request or args.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--intent-id', required=True)
    parser.add_argument('--source-update', type=int)
    parser.add_argument('--source-thread')
    parser.add_argument('--human-request')
    parser.add_argument('--backend', choices=('auto', 'codex', 'claude'), default='auto')
    parser.add_argument('--workspace')
    parser.add_argument('--mode', choices=('fresh', 'existing'), default='fresh')
    parser.add_argument('--thread-id')
    args = parser.parse_args()
    if not 1 <= len(args.name) <= 128 or any(ord(c) < 32 for c in args.name):
        parser.error('Bounded plain topic name required')
    listed = subprocess.run([sys.executable, str(BRIDGE), 'list'], capture_output=True, text=True, timeout=15, check=True)
    catalog = json.loads(listed.stdout)
    request = build_request(catalog, args, args.source_thread or os.environ.get('CODEX_THREAD_ID') or os.environ.get('CLAUDE_SESSION_ID'))
    if catalog['you'] == 'claude-code-relay':
        print(json.dumps({'status': 'controller-use-protected-runner', 'settings': request}))
        return
    sent = subprocess.run([sys.executable, str(BRIDGE), 'send', '--to', 'claude-code-relay',
                           '--intent-id', args.intent_id, '--text', json.dumps(request, ensure_ascii=False)],
                          capture_output=True, text=True, timeout=40)
    print(sent.stdout, end='')
    if sent.returncode:
        print('Submission unconfirmed; retain intent ID and do not resend automatically.', file=sys.stderr)
        raise SystemExit(sent.returncode)


if __name__ == '__main__':
    main()
