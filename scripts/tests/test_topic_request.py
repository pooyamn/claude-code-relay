import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[2] / 'skills/khadang-topic-binding/scripts/request_topic.py'
spec = importlib.util.spec_from_file_location('topic_request', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TopicSettingsTests(unittest.TestCase):
    def catalog(self):
        return {'registry': 'pc-native', 'you': 'duts', 'sessions': [
            {'name': 'duts', 'threadId': 'dut-id', 'tool': 'claude', 'chat': -100123, 'topic': 53},
            {'name': 'claude-code-relay', 'threadId': 'controller-id', 'tool': 'codex', 'chat': -100999, 'topic': 816}]}

    def args(self, **changes):
        values = dict(name='DUT X', intent_id='request-1', source_update=123,
                      backend='auto', mode='fresh', workspace=None, thread_id=None,
                      human_request='Create DUT X')
        values.update(changes)
        return SimpleNamespace(**values)

    def test_original_forum_and_backend_not_controller_defaults(self):
        result = module.build_request(self.catalog(), self.args(), 'dut-id')
        self.assertEqual(result['source']['chat'], -100123)
        self.assertEqual(result['backend'], 'claude')
        self.assertEqual(result['destination'], 'same-original-forum')

    def test_explicit_backend_and_folder_preserved(self):
        result = module.build_request(self.catalog(), self.args(backend='codex', workspace='/exact/project'), 'dut-id')
        self.assertEqual(result['backend'], 'codex')
        self.assertEqual(result['workspace'], '/exact/project')

    def test_stable_intent_and_owner_reference_preserved(self):
        result = module.build_request(self.catalog(), self.args(), 'dut-id')
        self.assertEqual(result['requestKey'], 'request-1')
        self.assertEqual(result['sourceUpdate'], 123)
        self.assertEqual(result['humanRequest'], 'Create DUT X')

    def test_existing_never_falls_back_to_fresh(self):
        with self.assertRaises(ValueError):
            module.build_request(self.catalog(), self.args(mode='existing'), 'dut-id')
        result = module.build_request(self.catalog(), self.args(mode='existing', thread_id='keep-id'), 'dut-id')
        self.assertEqual(result['operation'], 'topic-enroll')
        self.assertEqual(result['threadId'], 'keep-id')

    def test_missing_or_ambiguous_source_rejected(self):
        with self.assertRaises(ValueError):
            module.build_request(self.catalog(), self.args(), 'unknown-id')
        catalog = self.catalog()
        catalog['sessions'].append(catalog['sessions'][0].copy())
        with self.assertRaises(ValueError):
            module.build_request(catalog, self.args(), 'dut-id')

    def test_legacy_registry_rejected(self):
        catalog = self.catalog()
        catalog['registry'] = 'legacy'
        with self.assertRaises(ValueError):
            module.build_request(catalog, self.args(), 'dut-id')

    def test_claude_without_session_environment_uses_verified_you(self):
        result = module.build_request(self.catalog(), self.args(), None)
        self.assertEqual(result['source']['threadId'], 'dut-id')


if __name__ == '__main__':
    unittest.main()
