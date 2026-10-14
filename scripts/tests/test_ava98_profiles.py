"""No credentials/network: preserve Home-only cascades and untouched routes."""
import contextlib
import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest

source=pathlib.Path(__file__).resolve().parents[2]/'pc-router/vpn/ava98_profiles.py'
spec=importlib.util.spec_from_file_location('ava_profiles',source)
profiles=importlib.util.module_from_spec(spec);spec.loader.exec_module(profiles)


class HomeProfilesTests(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self, overrides=None):
        with tempfile.TemporaryDirectory(prefix='home-profile-fixture-') as temp:
            root=pathlib.Path(temp)
            original=[{'type':'vless','tag':f'Original {rank}','server':'original.example.test','server_port':443,'uuid':'fixture'} for rank in range(9)]
            extras=[{'type':'trojan','tag':f'Free tested {rank} - fixture','server':'entry.example.test','server_port':443,
                     'password':'fixture','tls':{'enabled':True,'server_name':'entry.example.test'}} for rank in range(1,6)]
            (root/'ava98-source.json').write_text(json.dumps({'outbounds':original}))
            (root/'free-tested-extras.json').write_text(json.dumps({'outbounds':extras}))
            if overrides is not None:(root/'ava98-home-overrides.json').write_text(json.dumps(overrides))
            home={'outbounds':[
                {'type':'vless','tag':'Cloudflare - kk.fidior.com','server':'cf.example.test','server_port':443,'uuid':'home-fixture',
                 'transport':{'type':'ws','path':'/home'},'tls':{'enabled':True,'server_name':'cf.example.test'}},
                {'type':'vless','tag':'Home Reality','server':'192.0.2.10','server_port':443,'uuid':'home-fixture',
                 'flow':'xtls-rprx-vision','tls':{'enabled':True,'reality':{'enabled':True,'public_key':'fixture'}}}]}
            yield root,original,extras,home

    def build(self,root,home):return profiles.build_profile(root,'ava98-home.json',lambda:copy.deepcopy(home))

    def test_default_preserves_fourteen_cloudflare_home_chains(self):
        with self.fixture() as (root,original,extras,home):
            result=self.build(root,home);self.assertEqual(set(result),{'outbounds'})
            self.assertEqual(len(result['outbounds']),28)
            self.assertTrue(all(n['server']=='cf.example.test' for n in result['outbounds'][:14]))

    def test_only_selected_new_routes_use_exact_existing_reality_template(self):
        overrides={'Free tested 3 - fixture':'Reality','Free tested 4 - fixture':'Reality'}
        with self.fixture(overrides) as (root,original,extras,home):
            outbounds=self.build(root,home)['outbounds'];by_tag={n['tag']:n for n in outbounds}
            for rank,node in enumerate(outbounds[:14]):
                template=home['outbounds'][1 if rank in (11,12) else 0]
                expected=copy.deepcopy(template);expected.update(tag=node['tag'],detour=node['detour'])
                self.assertEqual(node,expected);self.assertIn(profiles.HIDE,node['detour'])
                self.assertIn(node['detour'],by_tag);self.assertNotIn('detour',by_tag[node['detour']])
            self.assertEqual(outbounds[10]['server'],'cf.example.test') # working Free tested 2

    def test_standalone_profile_and_original_nine_not_changed_by_override(self):
        with self.fixture() as (root,original,extras,home):
            standalone=profiles.build_profile(root,'ava98.json',lambda:home)
            before=self.build(root,home)
            (root/'ava98-home-overrides.json').write_text(json.dumps({'Free tested 3 - fixture':'Reality'}))
            self.assertEqual(profiles.build_profile(root,'ava98.json',lambda:home),standalone)
            self.assertEqual(self.build(root,home)['outbounds'][:9],before['outbounds'][:9])

    def test_unknown_original_or_unsupported_overrides_are_rejected(self):
        for overrides in ({'missing':'Reality'},{'Original 0':'Reality'},{'Free tested 3 - fixture':'Direct'},[]):
            with self.fixture(overrides) as (root,original,extras,home):
                with self.assertRaises(ValueError):self.build(root,home)

    def test_missing_or_ambiguous_home_reality_fails_closed(self):
        with self.fixture({'Free tested 3 - fixture':'Reality'}) as (root,original,extras,home):
            for outbounds in ([home['outbounds'][0]],home['outbounds']+[home['outbounds'][1]]):
                with self.assertRaises(ValueError):self.build(root,{'outbounds':outbounds})


if __name__=='__main__':unittest.main()
