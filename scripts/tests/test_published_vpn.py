"""Credential-free regression tests for isolated published-route validation."""
import contextlib
import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

source=pathlib.Path(__file__).resolve().parents[1]/'test-published-vpn.py'
spec=importlib.util.spec_from_file_location('published_vpn',source)
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)


class Child:
    def poll(self): return None
    def terminate(self): pass
    def wait(self, timeout=None): pass


class PublishedVPNTests(unittest.TestCase):
    def node(self, rank=1):
        return {'type':'trojan','tag':f'Free tested {rank} - fixture','server':'example.test',
                'server_port':443,'password':'fixture-only',
                'tls':{'enabled':True,'server_name':'Example.Test.','alpn':['http/1.1']},
                'transport':{'type':'ws','path':'/assignment?ed','headers':{'Host':'Example.Test.'}}}

    def test_working_second_node_never_changed(self):
        self.assertEqual(checks.variants(self.node(2)), [])

    def test_variants_do_not_mutate_source(self):
        node=self.node();before=copy.deepcopy(node);checks.variants(node);self.assertEqual(node,before)

    def test_every_variant_preserves_endpoint_credentials_and_verified_tls(self):
        node=self.node()
        for _,candidate in checks.variants(node):
            for key in ('server','server_port','password','tag','type'):
                self.assertEqual(candidate[key],node[key])
            self.assertTrue(candidate['tls']['enabled']);self.assertFalse(candidate['tls'].get('insecure'))

    def test_alpn_correction_and_canonical_spelling(self):
        variants=dict(checks.variants(self.node()))
        self.assertNotIn('alpn',variants['no-alpn']['tls'])
        self.assertEqual(variants['canonical']['tls']['server_name'],'example.test')
        self.assertEqual(variants['canonical']['transport']['headers']['Host'],'example.test')
        self.assertEqual(variants['canonical']['transport']['path'],'/assignment')

    def probe(self, returned_ip):
        chain={'type':'vless','tag':'Home','server':'home.example.test','server_port':443,'detour':'Entry §hide§'}
        entry=self.node();entry['tag']='Entry §hide§'
        success={'ok':True,'http':'204','exit':0,'https_ttfb_ms':400.0}
        with tempfile.TemporaryDirectory(prefix='vpn-regression-') as temp:
            root=pathlib.Path(temp)
            with mock.patch.object(checks.socket,'create_connection',return_value=contextlib.nullcontext()), \
                 mock.patch.object(checks.subprocess,'Popen',return_value=Child()) as launch, \
                 mock.patch.object(checks,'request',side_effect=[(success,''),(success,''),(success,'ip='+returned_ip+'\n')]):
                result=checks.probe(root/'core',root,'case',chain,entry,'192.0.2.100',True)
            config=json.loads((root/'case.json').read_text())
            self.assertEqual(config['inbounds'][0]['listen'],'127.0.0.1')
            self.assertEqual(config['route']['final'],'Home')
            self.assertEqual(config['outbounds'],[chain,entry])
            self.assertIn('srun',launch.call_args.args[0])
            self.assertEqual((root/'case.json').stat().st_mode & 0o777,0o600)
            return result

    def test_exact_hidden_hop_and_home_exit(self):
        self.assertTrue(self.probe('192.0.2.100')['passed'])

    def test_successful_https_wrong_exit_must_fail(self):
        self.assertFalse(self.probe('192.0.2.101')['passed'])


if __name__=='__main__':unittest.main()
