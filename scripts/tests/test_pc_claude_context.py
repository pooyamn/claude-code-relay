import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('claude_context', Path(__file__).parents[1] / 'check-pc-claude-context.py')
CONTEXT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTEXT)


class IdleControlChecks(unittest.TestCase):
    def control(self, messages):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        reader, writer = os.pipe()
        stream = os.fdopen(reader, 'rb')
        self.addCleanup(stream.close)
        os.write(writer, b''.join(json.dumps(message).encode() + b'\n' for message in messages))
        os.close(writer)
        child = SimpleNamespace(stdout=stream, stdin=io.BytesIO())
        control = CONTEXT.IdleControl(child, Path(temporary.name), 'exact-id')
        self.addCleanup(control.selector.close)
        return control

    def test_cannot_issue_action_or_send_prompt(self):
        control = CONTEXT.IdleControl.__new__(CONTEXT.IdleControl)
        for subtype in ('interrupt', 'set_model', 'set_permission_mode', 'rewind_files', 'mcp_message', 'user'):
            with self.assertRaises(ValueError):
                control.call(subtype)

    def test_exact_initialization_reply(self):
        control = self.control([{'type': 'control_response', 'response': {'request_id': 'migration-read-1',
                                 'subtype': 'success', 'response': {'commands': []}}}])
        self.assertEqual(control.call('initialize'), {'commands': []})
        written = json.loads(control.child.stdin.getvalue())
        self.assertEqual(written['request'], {'subtype': 'initialize', 'hooks': None})

    def test_unexpected_action_or_reply_is_rejected(self):
        for message in ({'type': 'assistant'}, {'type': 'control_request'},
                        {'type': 'system', 'subtype': 'session_state_changed', 'state': 'running'},
                        {'type': 'system', 'subtype': 'session_title_changed', 'session_id': 'other'},
                        {'type': 'system', 'subtype': 'session_title_changed'},
                        {'type': 'control_response', 'response': {'subtype': 'success', 'request_id': 'other'}},
                        {'type': 'control_response', 'response': {'subtype': 'error', 'request_id': 'migration-read-1'}}):
            with self.assertRaises(ValueError):
                self.control([message]).call('initialize')

    def test_stored_native_title_is_scoped_and_never_disclosed(self):
        control = self.control([{'type': 'system', 'subtype': 'session_title_changed', 'session_id': 'exact-id', 'title': 'private'},
                               {'type': 'control_response', 'response': {'request_id': 'migration-read-1',
                                'subtype': 'success', 'response': {'commands': []}}}])
        self.assertEqual(control.call('initialize'), {'commands': []})
        self.assertEqual(control.events[0]['session_id'], 'exact-id')
        self.assertNotIn('private', json.dumps(control.events))

    def test_native_cost_state_append_keeps_every_preserved_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'history.jsonl'
            original = b'{"type":"assistant","message":"private"}\n'
            path.write_bytes(original)
            before = {'bytes': len(original), 'sha256': CONTEXT.digest(path)}
            row = {key: 0 for key in CONTEXT.COST_FIELDS}
            row.update(type='cost-state', sessionId='exact-id', hasUnknownModelCost=False, modelUsage={})
            path.write_bytes(original + json.dumps(row).encode() + b'\n')
            result = CONTEXT.inspect_native_append(path, before, 'exact-id')
            self.assertTrue(result['preservedPrefixIdentical'])
            self.assertFalse(result['historyUnchanged'])
            self.assertEqual(result['observedSessionIds'], ['exact-id'])
            self.assertNotIn('private', json.dumps(result))
            for bad in ({**row, 'type': 'assistant'}, {**row, 'sessionId': 'other'},
                        {**row, 'unexpected': 1}, {**row, 'totalDuration': 'command'}):
                path.write_bytes(original + json.dumps(bad).encode() + b'\n')
                with self.assertRaises(ValueError):
                    CONTEXT.inspect_native_append(path, before, 'exact-id')
            path.write_bytes(original.replace(b'private', b'mutated'))
            with self.assertRaises(ValueError):
                CONTEXT.inspect_native_append(path, before, 'exact-id')
            path.write_bytes(original[:-1])
            with self.assertRaises(ValueError):
                CONTEXT.inspect_native_append(path, before, 'exact-id')

    def test_nonempty_native_message_context_required(self):
        response = {'totalTokens': 1234, 'categories': [{'name': 'Messages', 'tokens': 1000}]}
        self.assertEqual(CONTEXT.summarize_context(response)['messageTokens'], 1000)
        for bad in ({'categories': []}, {'categories': [{'name': 'Messages', 'tokens': 0}]},
                    {'categories': [{'name': 'Messages', 'tokens': 'unknown'}]}):
            with self.assertRaises(ValueError):
                CONTEXT.summarize_context(bad)

    def test_retained_failure_stays_held_and_changed_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner = Path(temporary)
            prior = owner / '.migration' / ('a' * 32) / ('claude-idle-context-' + 'b' * 32)
            prior.mkdir(parents=True)
            workspace = owner / 'workspace' / 'fixture'
            project = owner / '.claude/projects' / CONTEXT.re.sub(r'[/\.]', '-', str(workspace))
            project.mkdir(parents=True)
            transcript = project / 'exact-id.jsonl'
            transcript.write_text('preserved')
            result = {'requestedSessionId': 'exact-id', 'workspace': str(workspace), 'uid': 1000,
                      'modelPromptsSent': 0, 'nativeStopped': True, 'complete': False,
                      'afterHistorySha256': CONTEXT.digest(transcript)}
            (prior / 'result.json').write_text(json.dumps({'checks': [result]}))
            state = owner / 'new-state'
            state.mkdir()
            history = SimpleNamespace(WORKSPACE=owner / 'workspace', PROJECTS=[('fixture', 1, 1)], pin=lambda path: 'exact-id')
            with patch.object(CONTEXT, 'OWNER', owner):
                retained = CONTEXT.retained_evidence(state, history, 'a' * 32, 'b' * 32)
                self.assertTrue(retained[str(workspace)]['heldForReconciliation'])
                self.assertFalse(retained[str(workspace)]['complete'])
                transcript.write_text('different')
                with self.assertRaises(ValueError):
                    CONTEXT.retained_evidence(state, history, 'a' * 32, 'b' * 32)


if __name__ == '__main__':
    unittest.main()
