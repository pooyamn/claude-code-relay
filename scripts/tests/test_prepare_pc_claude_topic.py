import importlib.util
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('topic_check', ROOT / 'prepare_pc_claude_topic.py')
topic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(topic)
retire_spec = importlib.util.spec_from_file_location('retire_topics', ROOT / 'retire_mac_lab_topics.py')
retire = importlib.util.module_from_spec(retire_spec)
retire_spec.loader.exec_module(retire)
additional_spec = importlib.util.spec_from_file_location('retire_additional', ROOT / 'retire_mac_additional_topics.py')
additional = importlib.util.module_from_spec(additional_spec)
additional_spec.loader.exec_module(additional)


class EvidenceTests(unittest.TestCase):
    def test_additional_projects_keep_exact_topic_addresses(self):
        self.assertEqual(topic.PROJECTS['hardware-lite'][:2], (-1003550185469, 6333))
        self.assertEqual(topic.PROJECTS['ai-hil/demos/fpga/mpu6000-i9'][:2], (-1003550185469, 8653))
        self.assertEqual(topic.PROJECTS['schematic-pipeline-lab'][:2], (-1004395661179, 2697))

    def evidence(self, continuity=False):
        return topic.Evidence('/workspace', 'session', 'digest', 'marker', 'first\nlast\n', continuity)

    def frame(self, name='Read', key='read', data=None):
        return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': key, 'name': name,
                 'input': data if data is not None else {'file_path': '/workspace/PC-MIGRATION-HANDOFF.md'}}]}}

    def result(self, key, body):
        return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': key, 'content': body}]}}

    def complete(self):
        return {'session_id': 'session', 'subtype': 'success', 'is_error': False, 'result': 'marker'}

    def test_fresh_requires_full_read_and_real_uid_hash(self):
        value = self.evidence(); value.observe(self.frame())
        value.observe(self.result('read', '1 first\n2 last'))
        value.observe(self.frame('Bash', 'bash', {'command': topic.COMMAND}))
        value.observe(self.result('bash', '1000\ndigest  PC-MIGRATION-HANDOFF.md\n'))
        value.complete(self.complete())

    def test_missing_tool_evidence_is_not_acceptance(self):
        with self.assertRaises(ValueError): self.evidence().complete(self.complete())

    def test_truncated_handoff_is_rejected(self):
        value = self.evidence(); value.observe(self.frame())
        with self.assertRaises(ValueError): value.observe(self.result('read', 'first'))

    def test_other_commands_and_offset_are_rejected(self):
        for frame in (self.frame('Bash', 'b', {'command': 'whoami'}),
                      self.frame(data={'file_path': '/workspace/PC-MIGRATION-HANDOFF.md', 'limit': 1}),
                      self.frame('Write')):
            with self.assertRaises(ValueError): self.evidence().observe(frame)

    def test_continuity_forbids_tools(self):
        with self.assertRaises(ValueError): self.evidence(True).observe(self.frame())
        self.evidence(True).complete(self.complete())

    def test_repeats_questions_and_other_sessions_are_rejected(self):
        value = self.evidence(); value.observe(self.frame())
        with self.assertRaises(ValueError): value.observe(self.frame())
        with self.assertRaises(ValueError): self.evidence().observe({'type': 'control_request'})
        result = self.complete(); result['session_id'] = 'other'
        with self.assertRaises(ValueError): self.evidence(True).complete(result)


class SourceFenceTests(unittest.TestCase):
    module = retire
    chat = '-1004395661179'

    def config(self):
        first = next(iter(self.module.TOPICS))
        bindings = [{'agentId': agent, 'match': {'channel': 'telegram',
                    'peer': {'id': self.chat + ':topic:' + number}}}
                    for number, (agent, *_) in self.module.TOPICS.items()]
        bindings.append({'agentId': 'unrelated', 'match': {'peer': {'id': 'other'}}})
        return {'bindings': bindings, 'private': {'preserve': True}, 'channels': {'telegram': {'groups': {
            self.chat: {'allowFrom': ['*'], 'topics': {'53': {'enabled': False},
                       first: {'custom': 'preserved'}}}, 'other': {'enabled': True}}}}}

    def test_only_exact_topics_change(self):
        original = self.config(); before = copy.deepcopy(original); result = self.module.fenced(original)
        self.assertEqual(original, before)
        self.assertEqual(len(result['bindings']), 1)
        group = result['channels']['telegram']['groups'][self.chat]
        first, second = self.module.TOPICS
        self.assertEqual(group['topics'][first], {'custom': 'preserved', 'enabled': False})
        self.assertEqual(group['topics'][second], {'enabled': False})
        self.assertEqual(result['private'], original['private'])
        self.assertEqual(result['channels']['telegram']['groups']['other'], {'enabled': True})

    def test_missing_or_duplicate_bindings_do_not_retire(self):
        for mutate in (lambda value: value['bindings'].pop(0),
                       lambda value: value['bindings'].append(copy.deepcopy(value['bindings'][0]))):
            config = self.config(); mutate(config)
            with self.assertRaises(ValueError): self.module.fenced(config)

    def test_changed_source_agent_is_not_retired(self):
        config = self.config(); config['bindings'][0]['agentId'] = 'new-agent'
        with self.assertRaises(ValueError): self.module.fenced(config)


class AdditionalSourceFenceTests(SourceFenceTests):
    module = additional
    chat = additional.CHAT


if __name__ == '__main__':
    unittest.main()
