"""Inert diagnostic guards only; not native or subscription acceptance."""
import importlib.util
import json
from pathlib import Path
import unittest
import uuid

spec = importlib.util.spec_from_file_location('claude_wire_probe', Path(__file__).parents[1] / 'check-pc-claude-wire.py')
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


class WireGuards(unittest.TestCase):
    def setUp(self):
        self.session = str(uuid.uuid4())
        self.init = {'type': 'control_request', 'request_id': 'khadang-claude-1',
                     'request': {'subtype': 'initialize', 'hooks': None}}
        self.user = {'type': 'user', 'message': {'role': 'user', 'content': wire.PROMPT},
                     'parent_tool_use_id': None, 'session_id': self.session,
                     'uuid': str(uuid.uuid4()), 'priority': 'now'}

    def test_one_initialization(self):
        self.assertEqual(wire.validate_input(self.init, self.session, False, False), 'initialize')
        with self.assertRaises(ValueError):
            wire.validate_input(self.init, self.session, True, False)

    def test_exact_one_inert_input(self):
        self.assertEqual(wire.validate_input(self.user, self.session, True, False), 'user')
        for initialized, sent in ((False, False), (True, True)):
            with self.assertRaises(ValueError):
                wire.validate_input(self.user, self.session, initialized, sent)

    def test_foreign_pin_queue_and_changed_prompt_refused(self):
        for key, value in (('session_id', str(uuid.uuid4())), ('priority', 'next'),
                           ('parent_tool_use_id', 'foreign'), ('uuid', 'invalid'),
                           ('message', {'role': 'user', 'content': 'Run tools'})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                wire.validate_input({**self.user, key: value}, self.session, True, False)

    def test_other_control_or_answer_refused(self):
        for frame in ({**self.init, 'request': {'subtype': 'remote_control', 'enabled': True}},
                      {'type': 'control_response', 'response': {'behavior': 'allow'}},
                      {**self.init, 'extra': True}, None, []):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                wire.validate_input(frame, self.session, False, False)

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"type":"user","type":"control_request"}', object_pairs_hook=wire.unique_object)


if __name__ == '__main__':
    unittest.main()
