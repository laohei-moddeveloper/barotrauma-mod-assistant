import json
from pathlib import Path
from unittest.mock import patch
from test_management import Fixture
from mod_assistant.core import AssistantError
from mod_assistant.runtime_capture import create_diagnostic,read_runtime_capture,compare_runtime


class RuntimeCaptureTests(Fixture):
    def test_fractional_moonsharp_timestamp_is_preserved_but_invalid_numbers_rejected(self):
        path=self.env.player/'runtime.json';record=self.capture();record['captured_unix']=1791721808.3550065
        path.write_text(json.dumps(record));self.assertEqual(read_runtime_capture(path)['captured_unix'],record['captured_unix'])
        for value in (True,float('nan'),float('inf'),-1):
            record['captured_unix']=value;path.write_text(json.dumps(record))
            with self.assertRaises(AssistantError):read_runtime_capture(path)
    def capture(self):
        return {'schema':'barodock-runtime-v1','capture_id':'example-1','captured_unix':1791700000,
            'packages':[{'name':'Vanilla','version':'1','index':0,'manifest':'Content/ContentPackages/Vanilla.xml'},
                        {'name':'Mod 101','version':'1','index':1,'manifest':str(self.env.installed/'101/filelist.xml')}],
            'items':[{'requested':'shared','identifier':'shared','provider_manifest':str(self.env.installed/'101/filelist.xml'),'health':200,'maxstacksize':1}]}

    def test_optional_helper_is_disabled_and_writes_only_a_new_local_folder(self):
        before=self.config.read_bytes();folder=create_diagnostic(self.env,['shared','special"identifier'])
        self.assertTrue((folder/'filelist.xml').is_file())
        script=(folder/'Lua/Autorun/barodock_diagnostics.lua').read_text()
        self.assertIn('Game.GetEnabledContentPackages()',script);self.assertIn('Game.GetItemPrefab(identifier)',script)
        self.assertFalse((folder/'Lua/ForcedAutorun').exists())
        self.assertEqual(before,self.config.read_bytes())

    def test_generated_lua_preserves_unicode_instead_of_encoding_as_byte_escapes(self):
        from mod_assistant.runtime_capture import lua_quote
        self.assertEqual(lua_quote('中文"\\\n'),'"中文\\034\\092\\010"')

    def test_observed_missing_package_and_actual_provider_are_shown(self):
        path=self.env.player/'runtime.json';path.write_text(json.dumps(self.capture()))
        record=read_runtime_capture(path);result=compare_runtime(self.env,record,{'shared':{'winner':'102'}})
        self.assertEqual(result['configured_but_not_observed'],['102'])
        self.assertEqual(result['items'][0]['observed_provider'],'101')
        self.assertFalse(result['items'][0]['provider_matches'])

    def test_imported_paths_are_never_opened_or_resolved_on_disk(self):
        record=self.capture();record['packages'][1]['manifest']='Z:/outside/not-a-game/filelist.xml'
        original=Path.resolve
        def resolve(path,*args,**kwargs):
            if str(path).lower().startswith('z:'):raise AssertionError('An imported path was accessed')
            return original(path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve):result=compare_runtime(self.env,record)
        self.assertEqual(result['unmapped_packages'],['Mod 101'])

    def test_observation_comparison_does_not_walk_installed_asset_receipts(self):
        folder=self.env.work/'receipts';folder.mkdir(parents=True)
        for item in ('101','102'):(folder/(item+'.json')).write_text('{"installed_snapshot":{},"fingerprint":"fixture"}')
        with patch('mod_assistant.profiles.files_snapshot',side_effect=AssertionError('Observation comparison walked asset files')):
            result=compare_runtime(self.env,self.capture())
        self.assertEqual(result['observed'],['vanilla','101'])

    def test_known_path_aliases_match_without_resolving_imported_labels(self):
        original=Path.resolve
        def expanded(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            return result.parent/'expanded-alias'/result.name
        with patch.object(Path,'resolve',expanded):
            result=compare_runtime(self.env,self.capture())
        self.assertEqual(result['observed'],['vanilla','101'])

    def test_invalid_numeric_or_duplicate_index_records_are_rejected(self):
        path=self.env.player/'runtime.json'
        for change in (lambda value:value['packages'][1].update(index=0),lambda value:value['items'][0].update(health=float('nan')),
                       lambda value:value['items'][0].update(missing='true'),lambda value:value.update(captured_unix=-1),
                       lambda value:value['items'].append(dict(value['items'][0]))):
            record=self.capture();change(record);path.write_text(json.dumps(record))
            with self.assertRaises(AssistantError):read_runtime_capture(path)

    def test_field_mismatch_is_explicit_and_missing_is_not_a_matching_provider(self):
        record=self.capture();model={'shared':{'status':'selected','winner':'101','expected_runtime_fields':{'health':100,'maxstacksize':1}}}
        item=compare_runtime(self.env,record,model)['items'][0]
        self.assertTrue(item['provider_matches'])
        self.assertEqual(item['field_comparisons'][0],{'field':'health','expected':100,'observed':200,'matches':False})
        record['items']=[{'requested':'shared','missing':True}]
        item=compare_runtime(self.env,record,{'shared':{'winner':None}})['items'][0]
        self.assertNotIn('provider_matches',item)

    def test_per_item_api_failure_is_preserved_without_claiming_missing(self):
        path=self.env.player/'runtime.json';record=self.capture();record['items']=[{'requested':'shared','error':'API unavailable'}]
        path.write_text(json.dumps(record));imported=read_runtime_capture(path)
        item=compare_runtime(self.env,imported,{'shared':{'winner':'101'}})['items'][0]
        self.assertEqual(item['observation_error'],'API unavailable');self.assertFalse(item['observed_missing']);self.assertNotIn('provider_matches',item)
