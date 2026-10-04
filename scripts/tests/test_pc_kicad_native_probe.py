import base64
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('native_probe', Path(__file__).parents[1] / 'pc_kicad_native_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class NativePreparationTests(unittest.TestCase):
    def capture(self):
        import hashlib
        return {'uid': 503, 'files': {name: {'base64': base64.b64encode(b'fixture').decode(),
            'size': 7, 'sha256': hashlib.sha256(b'fixture').hexdigest()} for name in probe.FILES}}

    def test_exact_two_source_files(self):
        self.assertEqual(set(probe.validate_capture(self.capture())), set(probe.FILES))

    def test_missing_extra_or_wrong_identity_rejected(self):
        for kind in ('missing', 'extra', 'identity'):
            value = self.capture()
            if kind == 'missing':
                value['files'].pop(probe.FILES[0])
            elif kind == 'extra':
                value['files']['other.kicad_pcb'] = value['files'][probe.FILES[0]]
            else:
                value['uid'] = 0
            with self.assertRaises(ValueError):
                probe.validate_capture(value)

    def test_content_corruption_rejected(self):
        value = self.capture()
        value['files'][probe.FILES[0]]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            probe.validate_capture(value)

    def test_no_api_credentials_and_isolated_profile(self):
        from unittest.mock import patch
        with patch.dict(probe.os.environ, {'ANTHROPIC_API_KEY': 'fixture', 'OPENAI_API_KEY': 'fixture',
                                         'USERNAME': 'pou', 'COMPUTERNAME': 'DESKTOP-8SO9HDK'}):
            environment = probe.native_environment(Path('fixture-run'))
            self.assertNotIn('ANTHROPIC_API_KEY', environment)
            self.assertNotIn('OPENAI_API_KEY', environment)
            self.assertEqual(environment['KICAD_CONFIG_HOME'], str(Path('fixture-run/config')))
            self.assertIn('fixture-run', environment['KICAD_API_SOCKET'])
            self.assertEqual(environment['USERNAME'], 'pou')
            self.assertEqual(environment['COMPUTERNAME'], 'DESKTOP-8SO9HDK')


if __name__ == '__main__':
    unittest.main()
