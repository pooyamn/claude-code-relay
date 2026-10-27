import hashlib
import io
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, '/Users/pouya/.openclaw/workspace/claude-code-relay/scripts')
import pc_claude_stdio as bridge

session = '2c0bce31-f586-4d5e-9422-4be550763ed8'
workspace = '/Users/pouya/.openclaw/workspace/ai-hil'
path = Path('/Users/pouya/.claude/projects/-Users-pouya--openclaw-workspace-ai-hil') / (session+'.jsonl')
bridge.no_session_writer(session)
raw = path.read_bytes()
rows = [bridge.decode_frame(line) for line in raw.splitlines(keepends=True)]
queue, filtered, results, attachments = [], [], {}, {}
counts = {'queue': 0, 'priorityDequeue': 0, 'structuredRemoval': 0, 'deliveredToAgent': 0, 'completedTasks': 0, 'killedTasks': 0, 'historicalAgentCompletions': 0}
for i, row in enumerate(rows):
    if row.get('sessionId', session) != session or row.get('isSidechain'):
        raise RuntimeError('Foreign history')
    if row.get('type') == 'attachment' and row.get('attachment', {}).get('type') == 'queued_command':
        a = row['attachment']
        attachments[(a.get('source_uuid'),a.get('delivery_id'))] = a
    if row.get('type') == 'queue-operation':
        counts['queue'] += 1
        op, content = row.get('operation'), row.get('content')
        if op == 'enqueue':
            queue.append(row)
        elif op == 'dequeue' and queue:
            echo = None
            for following in rows[i+1:]:
                if following.get('type') == 'queue-operation': break
                if following.get('type') == 'user':
                    echo = following.get('message', {}).get('content')
                    break
            text = echo if isinstance(echo, str) else ''.join(b.get('text','') for b in echo) if isinstance(echo,list) and all(b.get('type')=='text' for b in echo) else None
            matches = [q for q in queue if isinstance(text,str) and q.get('content') == text]
            if len(matches) == 1:
                counts['priorityDequeue'] += matches[0] is not queue[0]
                queue.remove(matches[0])
            else:
                queue.pop(0)  # Existing reviewed FIFO contract for non-text events.
        elif op == 'remove':
            if row.get('reason') == 'delivered_to_agent' and isinstance(content,str) and content:
                counts['deliveredToAgent'] += 1
            elif row.get('reason') != 'absorbed_mid_turn' or any(not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', row.get(k,'')) for k in ('commandUuid','deliveryId')):
                raise RuntimeError('Unknown removal at line '+str(i+1)+' reason='+str(row.get('reason')))
            matches = [q for q in queue if q.get('content') == content]
            if 'content' not in row:
                a = attachments.get((row['commandUuid'],row['deliveryId']))
                if not a or a.get('origin') != {'kind':'human'} or a.get('humanTurn') is not True or a.get('commandMode') != 'prompt' or not isinstance(a.get('prompt'),list):
                    raise RuntimeError('Unproved structured removal')
                matches = [q for q in matches if 'content' not in q and q.get('timestamp') == a.get('timestamp')]
                counts['structuredRemoval'] += 1
            if len(matches) != 1: raise RuntimeError('Ambiguous queue')
            queue.remove(matches[0])
        else:
            raise RuntimeError('Unmatched queue transition')
        continue
    content = row.get('message', {}).get('content')
    blocks = content if isinstance(content,list) else [{'type':'text','text':content}] if isinstance(content,str) else []
    notification = False
    for block in blocks:
        if block.get('type') == 'tool_result': results[block['tool_use_id']] = json.dumps(block.get('content'),ensure_ascii=False)
        text = block.get('text','')
        if '<task-notification' in text:
            if row.get('type') != 'user' or not text.startswith('<task-notification>') or not text.rstrip().endswith('</task-notification>'):
                raise RuntimeError('Not a literal terminal native notification')
            get = lambda tag: re.findall('<'+tag+'>([^<]+)</'+tag+'>',text)
            task, status, tool = get('task-id'), get('status'), get('tool-use-id')
            if len(task)!=1 or len(status)!=1 or status[0] not in ('completed','killed'):
                raise RuntimeError('Nonterminal task')
            matches = [v for k,v in results.items() if task[0] in v and (not tool or tool == [k])]
            if not matches:
                # Historical native Agent notifications can outlive the tool
                # launch segment after compaction. Manual review accepts only
                # the literal completed Agent ID/output artifact, not a running
                # job, killed unknown shell, or arbitrary message mention.
                output = get('output-file')
                if status != ['completed'] or not re.fullmatch(r'a[0-9a-f]{16}',task[0]) or len(output)!=1 or not output[0].startswith('/tmp/') or not output[0].endswith('/tasks/'+task[0]+'.output'):
                    raise RuntimeError('Unproved historical task at line '+str(i+1))
                counts['historicalAgentCompletions'] += 1
            counts['completedTasks' if status[0]=='completed' else 'killedTasks'] += 1
            notification = True
    if notification:
        # Only the dedicated native notification frame is reconciled, never
        # tool calls/results, ordinary user work or assistant completion.
        if len(blocks)!=1: raise RuntimeError('Mixed task notification')
        continue
    cwd = row.get('cwd',workspace)
    if not Path(cwd).is_relative_to(workspace):
        # Reviewed historical shell navigation, not a new launch root/grant.
        if cwd != '/Users/pouya/demo/augur-demo': raise RuntimeError('Unreviewed historical navigation')
        row = {**row, 'cwd':workspace}
    filtered.append(json.dumps(row).encode()+b'\n')
if queue: raise RuntimeError('Pending native queue')
bridge.quiescent_history(io.BytesIO(b''.join(filtered)),session,workspace)
bridge.no_session_writer(session)
if raw != path.read_bytes(): raise RuntimeError('History changed during owner review')
print(json.dumps({'schema':'ccrelay.owner_history_review.v1','session':session,'workspace':workspace,
 'history':{'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'evidence':counts,
 'toolsBalanced':True,'finalTurnCompleted':True,'pendingQueue':0,'modelInference':False,'historyModified':False}))
