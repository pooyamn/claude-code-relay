import importlib.util
from pathlib import Path
import sys
import hashlib
import json
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('workspace_contents', Path(__file__).parents[1] / 'verify_workspace_contents.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContentSelectionTests(unittest.TestCase):
    def comparison(self, names=None):
        return {'schema': 'ccrelay.workspace_metadata_comparison.v1', 'sourceProblems': 0,
                'errors': [], 'sameTypeAndSizeUnverified': names or ['z.bin', '.ignored/a.bin']}

    def test_only_exact_unique_formerly_size_only_paths(self):
        self.assertEqual(module.selected_names(self.comparison()), ['.ignored/a.bin', 'z.bin'])
        for names in (['a', 'a'], ['/etc/passwd'], ['a/../secret'], ['a//b'], [42]):
            with self.assertRaises(ValueError):
                module.selected_names(self.comparison(names))

    def test_incomplete_observation_is_never_a_verified_selection(self):
        for field, value in (('schema', 'other'), ('sourceProblems', 1), ('errors', [{'error': 'denied'}]),
                             ('sameTypeAndSizeUnverified', [])):
            comparison = self.comparison(); comparison[field] = value
            with self.assertRaises(ValueError):
                module.selected_names(comparison)

    def test_source_code_is_read_only_and_account_scoped(self):
        code = module.source_program()
        self.assertIn("sys.platform=='darwin' and os.getuid()==501", code)
        self.assertIn('m.observe(m.ROOT,names)', code)
        compile(code, '<in-memory-source-observer>', 'exec')

    def test_selection_rejects_tampered_report_and_incomplete_comparison(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            raw = b'{"entries":[]}'
            (root / 'fixture.json').write_bytes(raw)
            proof = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            self.assertEqual(module.checked_report(root, 'fixture.json', proof), {'entries': []})
            (root / 'fixture.json').write_bytes(b'{"entries":[]} ')
            with self.assertRaises(ValueError): module.checked_report(root, 'fixture.json', proof)
            with self.assertRaises(ValueError): module.checked_report(root, '../fixture.json', proof)
            with self.assertRaises(ValueError):
                module.preservation_rows(root, {'schema': 'ccrelay.workspace_content_comparison.v1', 'counts': {'errors': 1}})


if __name__ == '__main__':
    unittest.main()
