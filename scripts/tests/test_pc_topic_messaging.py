import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pc_messages', Path(__file__).parents[1] / 'pc_ccrelay_mcp.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def binding(name, cwd='/work', backend='codex'):
    return {'Alias': name, 'Workspace': cwd, 'Backend': backend, 'Runtime': 'linux',
            'ThreadId': '11111111-1111-1111-1111-111111111111', 'Chat': -1001, 'Topic': 1}


class Rpc:
    def __init__(self, status='active', turns=None, cwd='/work'):
        self.status, self.turns, self.cwd = status, turns, cwd
        self.calls = []

    def call(self, method, args):
        self.calls.append((method, args))
        if method == 'thread/read': return {'thread': {'id': args['threadId'], 'cwd': self.cwd, 'status': {'type': self.status}}}
        if method == 'thread/turns/list': return {'data': self.turns or [{'id': 'active-one', 'status': 'inProgress'}]}
        if method == 'turn/steer': return {'turnId': args['expectedTurnId']}
        if method == 'turn/start': return {'turn': {'id': 'new-turn'}}
        raise AssertionError(method)


class DeliveryTests(unittest.TestCase):
    def test_active_codex_steers_exact_turn_not_queue_or_start(self):
        rpc = Rpc()
        r = m.codex_delivery(binding('target'), 'hello', rpc)
        self.assertEqual('steer', r['mode'])
        self.assertEqual('active-one', rpc.calls[-1][1]['expectedTurnId'])
        self.assertEqual(['thread/read', 'thread/turns/list', 'turn/steer'], [p[0] for p in rpc.calls])

    def test_idle_codex_starts_without_resume(self):
        rpc = Rpc(status='idle')
        self.assertEqual('start', m.codex_delivery(binding('target'), 'hello', rpc)['mode'])
        self.assertEqual(['thread/read', 'turn/start'], [p[0] for p in rpc.calls])

    def test_unloaded_and_wrong_workspace_refuse_without_input(self):
        for rpc in (Rpc(status='notLoaded'), Rpc(cwd='/another')):
            with self.assertRaises(ValueError): m.codex_delivery(binding('target'), 'hello', rpc)
            self.assertEqual(['thread/read'], [p[0] for p in rpc.calls])

    def test_ambiguous_active_turn_refuses(self):
        rpc = Rpc(turns=[{'id': 'one', 'status': 'inProgress'}, {'id': 'two', 'status': 'inProgress'}])
        with self.assertRaises(ValueError): m.codex_delivery(binding('target'), 'hello', rpc)
        self.assertFalse(any(p[0].startswith('turn/') for p in rpc.calls))

    def test_most_specific_project_scope(self):
        bs = {'root': binding('root', '/work'), 'child': binding('child', '/work/dut-x')}
        self.assertEqual('child', m.caller(bs, '/work/dut-x/src'))
        with self.assertRaises(ValueError): m.caller(bs, '/work-not-this')

    def test_claude_is_a_requester_not_an_unverified_inbox_target(self):
        with patch.object(m, 'Codex') as rpc:
            with self.assertRaises(ValueError): m.deliver(binding('target', backend='claude'), 'hello')
            rpc.assert_not_called()

    def test_public_adapter_cannot_dispatch_arbitrary_peer_input(self):
        with patch.object(m.Messages, 'send') as send:
            with self.assertRaises(ValueError):
                m.invoke('send_message', {'to': 'another-topic', 'text': 'hi'}, {}, 'duts', m.Messages.__new__(m.Messages))
            send.assert_not_called()

    def test_claude_requester_can_resolve_the_cross_provider_controller(self):
        routes = {'duts': binding('duts', '/work/dut', 'claude'),
                  'claude-code-relay': binding('claude-code-relay', '/work/relay')}
        sender = m.caller(routes, '/work/dut')
        listed = m.invoke('list_sessions', {}, routes, sender, None)
        self.assertEqual('duts', listed['you'])
        self.assertEqual('pc-native', listed['registry'])
        self.assertEqual(['claude-code-relay'], [p['name'] for p in listed['sessions'] if p['reachable']])


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'messages.db'
        self.bs = {'sender': binding('sender'), 'target': binding('target')}
        self.s = m.Messages(self.bs, 'sender', self.db); self.addCleanup(self.s.db.close)

    @patch.object(m, 'deliver', return_value={'state': 'accepted', 'mode': 'steer'})
    def test_stable_intent_delivers_once_after_reopen(self, deliver):
        first = self.s.send('target', 'topic request', intent_id='request_123')
        fresh = m.Messages(self.bs, 'sender', self.db)
        try: self.assertEqual(first, fresh.send('target', 'topic request', intent_id='request_123'))
        finally: fresh.db.close()
        self.assertEqual(1, deliver.call_count)

    @patch.object(m, 'deliver', side_effect=TimeoutError('Lost response'))
    def test_ambiguous_timeout_never_replayed(self, deliver):
        first = self.s.send('target', 'topic request')
        self.assertEqual('unconfirmed', first['state'])
        self.assertEqual(first, self.s.send('target', 'topic request'))
        self.assertEqual(1, deliver.call_count)

    @patch.object(m, 'deliver', return_value={'state': 'accepted', 'mode': 'steer'})
    def test_reply_requires_actual_inbound_and_hop_limit(self, deliver):
        first = self.s.send('target', 'one')
        peer = m.Messages(self.bs, 'target', self.db)
        try:
            with self.assertRaises(ValueError): peer.send('sender', 'bad', reply_to='missing')
            second = peer.send('sender', 'two', reply_to=first['id'])
            third = self.s.send('target', 'three', reply_to=second['id'])
            with self.assertRaises(ValueError): peer.send('sender', 'four', reply_to=third['id'])
        finally: peer.db.close()
        self.assertEqual(3, deliver.call_count)

    @patch.object(m, 'deliver', return_value={'state': 'accepted'})
    def test_changed_claim_cannot_reuse_intent(self, deliver):
        self.s.send('target', 'one', intent_id='request_123')
        with self.assertRaises(ValueError): self.s.send('target', 'different', intent_id='request_123')
        self.assertEqual(1, deliver.call_count)

    def test_crashed_attempt_retained_not_replayed(self):
        self.s.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,NULL)', ('request_123', 'sender', 'target', 'one', None, 1, 'attempting'))
        self.s.db.commit()
        with patch.object(m, 'deliver') as deliver:
            self.assertEqual('attempting', self.s.send('target', 'one', intent_id='request_123')['state'])
            deliver.assert_not_called()

    def test_log_is_participant_scoped(self):
        self.s.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,NULL)', ('request_123', 'someone', 'other', 'private', None, 1, 'attempting')); self.s.db.commit()
        self.assertEqual([], self.s.log())


if __name__ == '__main__': unittest.main()
