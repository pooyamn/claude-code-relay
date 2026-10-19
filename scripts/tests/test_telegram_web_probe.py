"""Protocol serialization regression vectors from Telemt 3.5.14."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'pc-router/vpn/test_telegram_web.py'
SPEC = importlib.util.spec_from_file_location('telegram_web_probe', SOURCE)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class TelegramWebVectors(unittest.TestCase):
    def test_session_vectors(self):
        self.assertEqual(PROBE.frame(0x10, payload=b'\x01').hex(), '100000000000000101')
        self.assertEqual(PROBE.frame(0x11).hex(), '1100000000000000')

    def test_batch_round_trip(self):
        body = PROBE.frame(1, 17) + PROBE.frame(2, 17, b'round trip')
        self.assertEqual(list(PROBE.frames(body)), [(1, 17, b''), (2, 17, b'round trip')])
        self.assertEqual(PROBE.frame(1, 17).hex(), '0100001100000000')

    def test_truncation_rejected(self):
        for body in (b'\x01', PROBE.frame(2, 1, b'payload')[:-1]):
            with self.assertRaises(ValueError):
                list(PROBE.frames(body))


if __name__ == '__main__':
    unittest.main()
