"""No network or credentials: checks public-address screening bounds."""
import importlib.util
import pathlib
import unittest
from unittest import mock
import contextlib

spec = importlib.util.spec_from_file_location('scanner', pathlib.Path(__file__).resolve().parents[1] / 'scan-public-vpn.py')
scanner = importlib.util.module_from_spec(spec); spec.loader.exec_module(scanner)


class ScreeningTests(unittest.TestCase):
    def node(self, host='public.example'):
        return {'server': host, 'server_port': 443}

    def test_local_names_rejected(self):
        for host in ('localhost', 'LOCALHOST', '1'):
            with self.assertRaises(ValueError): scanner.endpoint(self.node(host))

    def test_private_or_mixed_resolution_rejected(self):
        for addresses in (['127.0.0.1'], ['192.168.0.1'], ['::1'], ['8.8.8.8', '10.0.0.1']):
            rows = [(None, None, None, None, (ip, 443)) for ip in addresses]
            with mock.patch.object(scanner.socket, 'getaddrinfo', return_value=rows), \
                 mock.patch.object(scanner.socket, 'create_connection') as dial:
                with self.assertRaises(ValueError): scanner.endpoint(self.node())
                dial.assert_not_called()

    def test_public_tcp_requires_both_trials(self):
        rows = [(None, None, None, None, ('8.8.8.8', 443))]
        with mock.patch.object(scanner.socket, 'getaddrinfo', return_value=rows), \
             mock.patch.object(scanner.socket, 'create_connection', side_effect=[contextlib.nullcontext(), OSError()]):
            self.assertIsNone(scanner.endpoint(self.node()))

    def test_no_tcp_result_if_dns_fails(self):
        with mock.patch.object(scanner.socket, 'getaddrinfo', side_effect=OSError()):
            self.assertIsNone(scanner.endpoint(self.node()))


if __name__ == '__main__': unittest.main()
