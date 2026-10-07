import hashlib
import hmac
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('health', Path(__file__).parents[2] / 'pc-router/mtproto/health_probe.py')
HEALTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HEALTH)


class Socket:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def recv(self, size):
        return next(self.chunks, b'')


class HealthTests(unittest.TestCase):
    def test_generated_hello_has_fresh_authenticated_timestamp(self):
        secret = bytes(range(16))
        with patch.object(HEALTH.time, 'time', return_value=1800000000):
            hello, digest = HEALTH.client_hello('www.bing.com', secret)
        self.assertGreaterEqual(len(hello), 517)
        self.assertEqual(hello[11:43], digest)
        expected = hmac.digest(secret, hello[:11] + bytes(32) + hello[43:], 'sha256')
        self.assertEqual(bytes(a ^ b for a, b in zip(expected, digest)), bytes(28) + (1800000000).to_bytes(4, 'little'))
        second, _ = HEALTH.client_hello('www.bing.com', secret)
        self.assertNotEqual(hello, second)

    def test_authenticates_all_three_server_records(self):
        key, digest = bytes(range(16)), bytes(range(32))
        server = bytearray(b'\x16\x03\x03\x00\x40' + bytes(64))
        ccs, app = b'\x14\x03\x03\x00\x01\x01', b'\x17\x03\x03\x00\x04abcd'
        server[11:43] = hmac.digest(key, digest + server + ccs + app, 'sha256')
        HEALTH.verify_server([server, ccs, app], key, digest)
        with self.assertRaises(ValueError):
            HEALTH.verify_server([server, ccs, app[:-1] + b'e'], key, digest)
        with self.assertRaises(ValueError):
            HEALTH.verify_server([server, ccs, app], bytes(16), digest)

    def test_rejects_bad_shape_and_large_record(self):
        for records in ([], [bytes(48)] * 3, [b'\x16' + bytes(47), b'bad', b'\x17']):
            with self.assertRaises(ValueError):
                HEALTH.verify_server(records, bytes(16), bytes(32))
        with self.assertRaises(ValueError):
            HEALTH.record(Socket([b'\x17\x03\x03\xff\xff']))

    def test_exact_read_handles_fragmentation_and_closed_socket(self):
        self.assertEqual(HEALTH.exact(Socket([b'a', b'bc']), 3), b'abc')
        with self.assertRaises(OSError):
            HEALTH.exact(Socket([b'a']), 2)

    def test_res_pq_nonce_and_envelope_are_checked(self):
        # No AES dependency/network needed: exercise the response-validation
        # path with a deterministic transport and unrelated nonce rejection.
        nonce = bytes(range(16))
        packet = bytes(8) + struct.pack('<QI', 123, 20) + struct.pack('<I', 0x05162463) + nonce
        transport = HEALTH.Transport.__new__(HEALTH.Transport)
        transport.write = lambda data: None
        transport.encrypt = type('Cipher', (), {'encrypt': lambda self, data: data})()
        for suffix in (nonce, bytes(16)):
            response = packet[:24] + suffix
            reads = iter([struct.pack('<I', len(response)), response])
            transport.read = lambda size: next(reads)
            with patch.object(HEALTH.secrets, 'token_bytes', side_effect=lambda n: nonce if n == 16 else bytes(n)):
                if suffix == nonce:
                    transport.request_pq()
                else:
                    with self.assertRaises(ValueError):
                        transport.request_pq()

    def test_fixed_scope_and_no_secret_arguments(self):
        self.assertEqual(set(HEALTH.SERVICES), {'OracovaMTProto', 'OracovaMTProto8443'})
        self.assertEqual(HEALTH.DC, ('149.154.167.51', 443))


if __name__ == '__main__':
    unittest.main()
