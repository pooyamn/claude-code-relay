import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest

spec = importlib.util.spec_from_file_location('retire_kicad', Path(__file__).parents[1] / 'retire_mac_kicad_topic.py')
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class KiCadRetirementTests(unittest.TestCase):
    def test_exact_topic_only_and_no_replay(self):
        original = {'bindings': [{'agentId': retire.AGENT, 'match': {'channel': 'telegram', 'peer': {'id': retire.CHAT + ':topic:6004'}}},
                                {'agentId': 'excluded-qwen', 'match': {'channel': 'telegram', 'peer': {'id': retire.CHAT + ':topic:10656'}}}],
                    'channels': {'telegram': {'groups': {retire.CHAT: {'topics': {'816': {'enabled': False}}}}}}, 'privateOther': {'untouched': True}}
        before = copy.deepcopy(original); after = retire.fenced(original)
        self.assertEqual(original, before)
        self.assertEqual(after['bindings'], before['bindings'][1:])
        self.assertEqual(after['privateOther'], before['privateOther'])
        self.assertFalse(after['channels']['telegram']['groups'][retire.CHAT]['topics']['6004']['enabled'])
        self.assertEqual(after['channels']['telegram']['groups'][retire.CHAT]['topics']['816'], {'enabled': False})
        with self.assertRaises(ValueError):
            retire.fenced(after)

    def database(self):
        db = sqlite3.connect(':memory:')
        db.executescript('CREATE TABLE session(id,directory,time_updated,time_compacting,parent_id);'
                         'CREATE TABLE message(id,session_id,time_created,time_updated,data);'
                         'CREATE TABLE part(id,message_id,session_id,time_created,time_updated,data);'
                         'CREATE TABLE session_input(id,session_id); CREATE TABLE todo(session_id,body);')
        db.execute('INSERT INTO session VALUES(?,?,?,?,?)', (retire.SESSION, str(retire.WORKSPACE), 10, None, None))
        db.execute('INSERT INTO message VALUES(?,?,?,?,?)', ('message', retire.SESSION, 10, 10,
                   json.dumps({'role': 'assistant', 'finish': 'stop', 'time': {'completed': 10}})))
        self.addCleanup(db.close)
        return db

    def test_complete_history_allowed(self):
        self.assertEqual(retire.checked_history(self.database())['session'][0], retire.SESSION)

    def test_unfinished_turn_rejected(self):
        db = self.database(); db.execute('UPDATE message SET data=?', (json.dumps({'role': 'user'}),))
        with self.assertRaises(ValueError):
            retire.checked_history(db)

    def test_pending_inputs_children_and_tools_rejected(self):
        mutations = [('INSERT INTO session_input VALUES(?,?)', ('queued', retire.SESSION)),
                     ('INSERT INTO session VALUES(?,?,?,?,?)', ('child', str(retire.WORKSPACE), 10, None, retire.SESSION)),
                     ('INSERT INTO part VALUES(?,?,?,?,?,?)', ('part', 'message', retire.SESSION, 10, 10,
                      json.dumps({'type': 'tool', 'state': {'status': 'running'}})))]
        for sql, parameters in mutations:
            with self.subTest(sql=sql):
                db = self.database(); db.execute(sql, parameters)
                with self.assertRaises(ValueError):
                    retire.checked_history(db)


if __name__ == '__main__':
    unittest.main()
