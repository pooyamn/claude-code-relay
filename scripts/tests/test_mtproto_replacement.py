import importlib.util
from pathlib import Path
import re
import unittest

SPEC = importlib.util.spec_from_file_location('mtproto_adapter', Path(__file__).parents[2] / 'pc-router/mtproto/server.py')
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class ReplacementConfig(unittest.TestCase):
    def document(self, bind='127.0.0.1:10990'):
        return {'bind-to': bind, 'secret': 'ee' + '0123456789abcdef' * 2 + b'www.cloudflare.com'.hex()}

    def test_keeps_existing_secret_and_domain(self):
        result = ADAPTER.configuration(self.document(), '127.0.0.1:10990')
        self.assertEqual(result['USERS']['owner'], '0123456789abcdef' * 2)
        self.assertEqual(result['TLS_DOMAIN'], 'www.cloudflare.com')
        self.assertEqual(result['PORT'], 10990)
        self.assertEqual(result['LISTEN_ADDR_IPV4'], '127.0.0.1')
        self.assertEqual(result['MODES'], {'classic': False, 'secure': False, 'tls': True})
        self.assertFalse(result['FAST_MODE'])
        self.assertFalse(result['METRICS_EXPORT_LINKS'])
        self.assertEqual(result['METRICS_LISTEN_ADDR_IPV4'], '127.0.0.1')

    def test_direct_listener_preserved(self):
        result = ADAPTER.configuration(self.document('0.0.0.0:8443'), '0.0.0.0:8443')
        self.assertEqual(result['PORT'], 8443)
        self.assertEqual(result['METRICS_PORT'], 11091)

    def test_installer_uses_exact_official_dependency_digest(self):
        installer = (Path(__file__).parents[2] / 'pc-router/replace-mtproto.ps1').read_text()
        digests = re.findall(r"'([A-F0-9]{60,})'", installer)
        self.assertEqual(digests, ['C75B52AACC6C0C260F204CBDD834F76EDC9FB0D8E0DA9FBF8352EF58202564E2'])
        self.assertTrue(all(len(value) == 64 for value in digests))

    def test_refuses_unexpected_bind_and_bad_secret(self):
        with self.assertRaises(ValueError):
            ADAPTER.configuration(self.document('0.0.0.0:443'), '0.0.0.0:8443')
        for secret in ('', 'dd' + '0' * 32, 'eeff', 'ee' + '0' * 32 + b'bad\nvalue'.hex()):
            document = self.document()
            document['secret'] = secret
            with self.assertRaises(ValueError):
                ADAPTER.configuration(document, '127.0.0.1:10990')


if __name__ == '__main__':
    unittest.main()
