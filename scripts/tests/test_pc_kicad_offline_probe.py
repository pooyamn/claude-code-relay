import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('probe', Path(__file__).parents[1] / 'pc_kicad_offline_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PreparationTests(unittest.TestCase):
    def packages(self):
        return dict(probe.LOCAL_PROJECTS, pip='26.1.2', numpy='2.5.1', pytest='9.1.1')

    def test_exact_pins_exclude_only_local_sources_and_pip(self):
        self.assertEqual(probe.requirements(self.packages()), ['numpy==2.5.1', 'pytest==9.1.1'])

    def test_changed_local_project_version_is_rejected(self):
        packages = self.packages()
        packages['kicad-tools'] = '99.0'
        with self.assertRaises(ValueError):
            probe.requirements(packages)

    def test_requirement_option_injection_is_rejected(self):
        for key, value in (('--index-url https://example.invalid', '1'),
                           ('--index-url', '1'), ('numpy', '1\n--extra-index-url evil'),
                           ('numpy', '--no-index')):
            packages = self.packages()
            packages[key] = value
            with self.assertRaises(ValueError):
                probe.requirements(packages)

    def test_live_board_node_cannot_be_selected(self):
        code = '\n'.join(f'def test_case_{i}(): pass' for i in range(12))
        code += '\ndef test_live_routing_gnd_lowers_j(): pass'
        nodes = probe.offline_nodes(code)
        self.assertEqual(len(nodes), 12)
        self.assertTrue(all(probe.EXCLUDED_TEST not in node for node in nodes))

    def test_changed_test_set_is_rejected(self):
        with self.assertRaises(ValueError):
            probe.offline_nodes('def test_live_routing_gnd_lowers_j(): pass')

    def test_credential_environment_is_not_inherited(self):
        from unittest.mock import patch
        with patch.dict(probe.os.environ, {'ANTHROPIC_API_KEY': 'fixture', 'OPENAI_API_KEY': 'fixture'}):
            self.assertNotIn('ANTHROPIC_API_KEY', probe.clean_environment())
            self.assertNotIn('OPENAI_API_KEY', probe.clean_environment())


if __name__ == '__main__':
    unittest.main()
