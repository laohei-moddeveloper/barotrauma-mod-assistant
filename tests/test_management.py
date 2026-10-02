import base64
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mod_assistant.core import AssistantError, Cancelled, Environment, Mod, atomic_json, inventory
from mod_assistant.mod_toggle import local_id
from mod_assistant.mod_order import read_order, save_order, suggest_order, validate_order, save_rules
from mod_assistant.mod_analysis import Features, inspect, evaluate, pair_evidence, pair_detail
from mod_assistant.analysis_cache import inspect_cached
from mod_assistant.profiles import SCHEMA, apply_profile, capture_profile, normalize_profile, resolve_profile
from mod_assistant.snapshots import SnapshotStore, safe_name
from mod_assistant.friends import apply_with_downloads
from mod_assistant.diagnostics import diagnose, lua_verification


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); root=Path(self.temp.name)
        self.env=Environment(root/'steam',root/'game',[root/'steam'],root/'player')
        vanilla=self.env.game/'Content/ContentPackages/Vanilla.xml'; vanilla.parent.mkdir(parents=True)
        vanilla.write_text('<contentpackage name="Vanilla" gameversion="1.13.4.0" />')
        self.config=self.env.game/'config_player.xml'
        self.make('101'); self.make('102'); self.make('103',core=True)
        self.configure(['101','102'])
        self.guard=lambda:False
        self.store=SnapshotStore(self.env,process_guard=self.guard)

    def tearDown(self): self.temp.cleanup()

    def make(self,item,core=False,version='1',name=None):
        folder=self.env.installed/item; folder.mkdir(parents=True,exist_ok=True)
        (folder/'filelist.xml').write_text(f'<contentpackage name="{name or "Mod "+item}" corepackage="{str(core).lower()}" modversion="{version}"><Item file="%ModDir%/items.xml" /></contentpackage>')
        (folder/'items.xml').write_text('<Items><Item identifier="shared" /></Items>')
        return Mod(item,name or 'Mod '+item,folder,enabled=item in ('101','102'),installed_version=version)

    def configure(self,ids,volume=77,core=None,bom=False):
        path=(self.env.installed/core/'filelist.xml').as_posix() if core else 'Content/ContentPackages/Vanilla.xml'
        packages=''.join(f'<!-- {item} --><package path="{(self.env.installed/item/"filelist.xml").as_posix()}" custom="keep" />' for item in ids)
        text=f'<config keep="yes"><contentpackages><corepackage path="{path}" /><regularpackages>{packages}</regularpackages></contentpackages><audio volume="{volume}" /></config>'
        self.config.write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.encode())

    def profile(self,ids,core=None):
        value=capture_profile(self.env)
        refs={x['id']:x for x in value['order']}
        value['order']=[refs.get(item,{'id':item,'name':'Mod '+item,'mod_version':'1'}) for item in ids]
        value['core']={'id':core,'name':'Mod '+core,'mod_version':'1'} if core else None
        return value


class ProfileTests(Fixture):
    def test_atomic_switch_core_regular_comments_bom_preserves_other_settings(self):
        self.configure(['101','102'],bom=True); before=self.config.read_bytes()
        backup=apply_profile(self.env,self.profile(['102'],core='103'),process_guard=self.guard)
        self.assertEqual(Path(backup).read_bytes(),before)
        self.assertEqual(read_order(self.env),['102'])
        value=self.config.read_bytes()
        self.assertTrue(value.startswith(b'\xef\xbb\xbf')); self.assertIn(b'<audio volume="77" />',value)
        self.assertIn(b'<!-- 102 -->',value); self.assertIn(b'custom="keep"',value); self.assertIn(b'Installed/103',value)

    def test_core_in_regular_and_missing_item_leave_config_unchanged(self):
        before=self.config.read_bytes()
        for profile in (self.profile(['103']),self.profile(['999']),self.profile(['101'],core='102')):
            with self.assertRaises(AssistantError): apply_profile(self.env,profile,process_guard=self.guard)
            self.assertEqual(self.config.read_bytes(),before)

    def test_game_start_during_commit_and_concurrent_config_edit(self):
        before=self.config.read_bytes(); checks=iter([False,False,True])
        with self.assertRaisesRegex(AssistantError,'刚刚启动'):
            apply_profile(self.env,self.profile(['102']),process_guard=lambda:next(checks))
        self.assertEqual(self.config.read_bytes(),before)
        calls=[0]
        def guard():
            calls[0]+=1
            if calls[0]==3: self.config.write_bytes(before.replace(b'77',b'99'))
            return False
        with self.assertRaisesRegex(AssistantError,'刚被其他程序'):
            apply_profile(self.env,self.profile(['102']),process_guard=guard)
        self.assertIn(b'99',self.config.read_bytes())

    def test_installed_only_mods_are_not_lost_if_steam_cache_absent(self):
        mods=inventory(self.env); self.assertEqual({m.item_id for m in mods},{'101','102','103'})
        self.assertTrue(all(m.source is None for m in mods))
        self.assertEqual([x['id'] for x in capture_profile(self.env)['order']],['101','102'])

    def test_cross_computer_local_resolution_requires_unique_name(self):
        folder=self.env.game/'LocalMods'/'Chinese'; folder.mkdir(parents=True)
        (folder/'filelist.xml').write_text('<contentpackage name="Chinese" modversion="2" />')
        data=self.profile([]); data['order']=[{'id':'local:0123456789abcdef','name':'Chinese','mod_version':'2'}]
        resolved,missing,differences=resolve_profile(self.env,data)
        self.assertFalse(missing); self.assertFalse(differences)
        self.assertEqual(resolved[data['order'][0]['id']].item_id,local_id(folder))
        apply_profile(self.env,data,process_guard=self.guard)
        self.assertEqual(read_order(self.env),[local_id(folder)])
        other=self.env.player/'LocalMods'/'Chinese2'; other.mkdir(parents=True)
        (other/'filelist.xml').write_text('<contentpackage name="Chinese" />')
        self.assertTrue(resolve_profile(self.env,data)[1])

    def test_profile_validation_and_legacy_import(self):
        for value in ({}, {'schema':SCHEMA,'appid':602960,'order':[{'id':'../101'}]},
                      self.profile(['101','101']), {'schema':'barotrauma-mod-assistant-profile-v1','appid':602960,'mods':None}):
            with self.assertRaises(AssistantError): normalize_profile(value)
        data=normalize_profile({'schema':'barotrauma-mod-assistant-profile-v1','appid':602960,'mods':[{'id':'101','name':'A'}],'load_order':['101']})
        self.assertEqual(data['schema'],SCHEMA); self.assertEqual(data['order'][0]['id'],'101')


class SnapshotTests(Fixture):
    def test_independent_copy_restore_order_and_current_audio(self):
        saved=self.store.capture(); first=self.env.installed/'101/items.xml'
        first.write_text('user-changed'); self.configure(['102'],volume=12)
        snapshot=self.store.root/saved['id']/'payload/0/items.xml'
        self.assertNotEqual(first.read_bytes(),snapshot.read_bytes())
        result=self.store.restore(saved['id'])
        self.assertEqual(read_order(self.env),['101','102']); self.assertIn(b'volume="12"',self.config.read_bytes())
        self.assertEqual(first.read_bytes(),snapshot.read_bytes())
        self.assertEqual((Path(result['backup'])/'0/items.xml').read_text(),'user-changed')

    def test_reuses_unchanged_snapshot_and_detects_later_edits(self):
        first=self.store.capture(); second=self.store.capture()
        self.assertEqual(first['id'],second['id'])
        (self.env.installed/'101/items.xml').write_text('changed')
        self.assertNotEqual(first['id'],self.store.capture()['id'])

    def test_corrupt_payload_and_game_version_rejected_before_live_mutations(self):
        saved=self.store.capture(); before=self.config.read_bytes()
        (self.store.root/saved['id']/'payload/0/items.xml').write_text('bad')
        with self.assertRaisesRegex(AssistantError,'校验失败'): self.store.restore(saved['id'])
        self.assertEqual(before,self.config.read_bytes()); self.assertIn('shared',(self.env.installed/'101/items.xml').read_text())
        (self.env.game/'Content/ContentPackages/Vanilla.xml').write_text('<contentpackage name="Vanilla" gameversion="changed"/>')
        with self.assertRaisesRegex(AssistantError,'游戏版本'): self.store.restore(saved['id'])

    def test_failure_after_directory_or_config_commit_rolls_back_everything(self):
        saved=self.store.capture()
        (self.env.installed/'101/items.xml').write_text('new-live'); self.configure(['102'])
        before=self.config.read_bytes()
        for phase in ('replaced','config_replaced'):
            def fault(current):
                if current==phase: raise OSError('injected failure')
            failing=SnapshotStore(self.env,process_guard=self.guard,fault=fault)
            with self.assertRaises(OSError): failing.restore(saved['id'])
            self.assertEqual(self.config.read_bytes(),before)
            self.assertEqual((self.env.installed/'101/items.xml').read_text(),'new-live')

    def test_crash_after_config_commit_recovered_on_next_run(self):
        saved=self.store.capture(); (self.env.installed/'101/items.xml').write_text('new-live')
        self.configure(['102']); before=self.config.read_bytes()
        def crash(phase):
            if phase=='config_replaced': raise SystemExit('crash')
        with self.assertRaises(SystemExit): SnapshotStore(self.env,process_guard=self.guard,fault=crash).restore(saved['id'])
        self.assertEqual(read_order(self.env),['101','102'])
        self.store.recover(); self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual((self.env.installed/'101/items.xml').read_text(),'new-live')
        self.store.recover()  # Idempotent after recovery.

    def test_absent_target_restored_to_absent_without_destroying_new_copy(self):
        saved=self.store.capture(targets=['999']); self.make('999')
        result=self.store.restore(saved['id'])
        self.assertFalse((self.env.installed/'999').exists())
        self.assertTrue(any(Path(result['backup']).glob('*/filelist.xml')))

    def test_running_game_cancel_space_and_unsafe_paths_stop_before_write(self):
        with self.assertRaises(AssistantError): SnapshotStore(self.env,process_guard=lambda:True).capture()
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): SnapshotStore(self.env,process_guard=self.guard,cancel=cancel).capture()
        with patch('mod_assistant.snapshots.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
            with self.assertRaisesRegex(AssistantError,'空间不足'): self.store.capture()
        for value in ('.','../outside','a//b','a/./b','C:/outside','/outside','a\\b',None):
            with self.assertRaises(AssistantError): safe_name(value)
        with self.assertRaises(AssistantError): self.store.target({'kind':'game_local','folder':'../escape'})

    def test_invalid_recovery_index_is_rejected(self):
        journal={'entries':[{'index':'../escape'}],'written':['../escape'],'config_before':base64.b64encode(self.config.read_bytes()).decode(),'config_after':''}
        transaction=self.store.root/'transactions'/'bad'; transaction.mkdir(parents=True)
        with self.assertRaisesRegex(AssistantError,'索引'): self.store.rollback(transaction,journal)


class CacheAndEvidenceTests(Fixture):
    def test_cache_reuse_script_change_and_metadata_change(self):
        mod=self.make('101'); metadata={'101':{'children':[]}}
        first,stats=inspect_cached(self.env,[mod],metadata); self.assertEqual(stats['scanned'],1)
        with patch('mod_assistant.analysis_cache.inspect',side_effect=AssertionError('must reuse')):
            second,stats=inspect_cached(self.env,[mod],metadata)
        self.assertEqual(stats['reused'],1); self.assertEqual(first['101'].definitions,second['101'].definitions)
        (mod.source/'a.lua').write_text('Hook.Add("test", "same", function() end)')
        features,stats=inspect_cached(self.env,[mod],metadata); self.assertEqual(stats['scanned'],1)
        self.assertTrue(features['101'].hook_names)
        features,stats=inspect_cached(self.env,[mod],{'101':{'children':['102']}})
        self.assertEqual(stats['scanned'],1); self.assertEqual(features['101'].workshop_dependencies,{'102'})

    def test_light_mode_does_not_walk_or_read_code_and_marks_cache_stale(self):
        mod=self.make('101'); inspect_cached(self.env,[mod])
        with patch.object(Path,'rglob',side_effect=AssertionError('no tree walk')), patch('mod_assistant.analysis_cache.inspect',side_effect=AssertionError('no code reads')):
            features,stats=inspect_cached(self.env,[mod],light=True)
        self.assertEqual(stats['deferred'],1)
        report=evaluate([mod],features,True)['101']; self.assertEqual(report.evidence,'缓存待刷新')
        self.assertEqual(report.compatibility,'待刷新·缓存结论')

    def test_corrupt_cache_and_no_prior_cache_light_scan(self):
        mod=self.make('101'); inspect_cached(self.env,[mod])
        path=next((self.env.work/'analysis/features-v2').glob('*.json')); path.write_text('[]')
        _,stats=inspect_cached(self.env,[mod]); self.assertEqual(stats['scanned'],1)
        path.write_text('{')
        with patch.object(Path,'rglob',side_effect=AssertionError('no tree walk')):
            features,_=inspect_cached(self.env,[mod],light=True)
        self.assertTrue(features['101'].partial)

    def test_xml_override_winner_paths_and_unmarked_duplicate_risk(self):
        left=self.make('101'); right=self.make('102')
        a,b=inspect(left),inspect(right)
        self.assertEqual(pair_evidence(a,b)[0],3)
        (right.source/'items.xml').write_text('<Items><Override><Item identifier="shared" /></Override></Items>')
        b=inspect(right); self.assertEqual(pair_evidence(a,b)[0],1)
        detail=pair_detail(a,b,['101','102']); self.assertEqual(detail['expected_xml_winner'],right.name)
        self.assertEqual(detail['locations'][0]['right_files'],['items.xml'])
        (left.source/'items.xml').write_text('<Override><Item identifier="shared" /></Override>')
        a=inspect(left)
        self.assertEqual(pair_detail(a,b,['102','101'])['expected_xml_winner'],right.name)
        self.assertEqual(pair_detail(a,b,['101','102'])['expected_xml_winner'],left.name)

    def test_csharp_disabled_and_compiled_code_are_not_claimed_compatible(self):
        mod=self.make('101'); (mod.source/'script.cs').write_text('class Example {}')
        feature=inspect(mod); result=evaluate([mod],{'101':feature},True,csharp=False)
        self.assertEqual(result['101'].compatibility,'低·运行条件')
        result=evaluate([mod],{'101':Features('101','A',opaque_code=1)},True)
        self.assertEqual(result['101'].compatibility,'未知·资料不足')


class RuleTests(Fixture):
    def test_rules_reverse_existing_overlap_and_keep_locked_position(self):
        ids=['101','102']; mods={m.item_id:m for m in inventory(self.env)}
        definition={('item','item','shared')}; features={item:Features(item,item,definitions=definition) for item in ids}
        result=suggest_order(ids,mods,features,{'before':[['102','101']]})
        self.assertEqual(result.ids,['102','101'])
        result=suggest_order(ids,mods,{}, {'locks':['101']}); self.assertEqual(result.ids[0],'101')
        with self.assertRaisesRegex(AssistantError,'循环'):
            suggest_order(ids,mods,{}, {'locks':['101'],'before':[['102','101']]})

    def test_drag_and_save_cannot_bypass_rules_or_locks(self):
        rules={'before':[['101','102']],'locks':['101']}; save_rules(self.env,rules)
        before=self.config.read_bytes()
        with self.assertRaises(AssistantError): validate_order(['102','101'],['101','102'],rules)
        with self.assertRaises(AssistantError): save_order(self.env,['102','101'],process_guard=self.guard)
        self.assertEqual(self.config.read_bytes(),before)


class FriendAndLogTests(Fixture):
    def test_missing_local_and_version_mismatch_keep_configuration(self):
        before=self.config.read_bytes(); data=self.profile(['101']); data['order'][0]['mod_version']='old'
        with self.assertRaisesRegex(AssistantError,'版本'): apply_with_downloads(self.env,data,process_guard=self.guard)
        self.assertFalse(self.store.list()); self.assertEqual(self.config.read_bytes(),before)
        data['order']=[{'id':'local:0123456789abcdef','name':'missing'}]
        with self.assertRaisesRegex(AssistantError,'本地模组'): apply_with_downloads(self.env,data,download=True,process_guard=self.guard)

    def test_download_missing_then_apply_together_and_restore_point_exists(self):
        data=self.profile(['999','101']); subscribed=[]; fixture=self
        class Bridge:
            def __init__(self,env): pass
            def connect(self): return self
            def subscribe(self,item,**kwargs): subscribed.append(item)
            def close(self): pass
        class Engine:
            def __init__(self,*args,**kwargs): pass
            def run(self,ids,online):
                for item in ids: fixture.make(item)
                return {'errors':{},'completed':ids,'cancelled':False}
        result=apply_with_downloads(self.env,data,True,process_guard=self.guard,bridge_factory=Bridge,engine_factory=Engine,verify_items=lambda ids:None)
        self.assertEqual(subscribed,['999']); self.assertEqual(read_order(self.env),['999','101'])
        self.assertEqual(len(self.store.list()),1)
        self.store.restore(result['snapshot']); self.assertFalse((self.env.installed/'999').exists())
        self.assertEqual(read_order(self.env),['101','102'])

    def test_partial_download_failure_keeps_enabled_state(self):
        data=self.profile(['999']); before=self.config.read_bytes()
        class Bridge:
            def __init__(self,env): pass
            def connect(self): return self
            def subscribe(self,*args,**kwargs): pass
            def close(self): pass
        class Engine:
            def __init__(self,*args,**kwargs): pass
            def run(self,*args,**kwargs): return {'errors':{'999':'failed'}}
        with self.assertRaisesRegex(AssistantError,'未切换'):
            apply_with_downloads(self.env,data,True,process_guard=self.guard,bridge_factory=Bridge,engine_factory=Engine,verify_items=lambda ids:None)
        self.assertEqual(before,self.config.read_bytes()); self.assertEqual(len(self.store.list()),1)

    def test_explicit_allow_differences_records_warning(self):
        data=self.profile(['101']); data['order'][0]['mod_version']='old'
        result=apply_with_downloads(self.env,data,allow_differences=True,process_guard=self.guard)
        self.assertTrue(result['differences']); self.assertIn('未确认',result['message'])
        self.assertEqual(read_order(self.env),['101'])

    def test_log_triage_redaction_and_luacs_guidance_not_runtime_claim(self):
        path=self.env.game/'test.log'; path.write_text(f'password=secret\nException {self.env.installed}/101 Mod 101\nstack traceback\n',encoding='utf-8')
        result=diagnose(path,[self.make('101')],self.env)
        self.assertEqual(result['findings'][0]['possible_mods'],['Mod 101'])
        self.assertNotIn('secret',result['findings'][0]['text']); self.assertNotIn(str(self.env.player),result['findings'][0]['text'])
        self.assertFalse(lua_verification(self.env)['runtime_verified'])

    def test_large_utf16_log_tail_is_bounded_and_decoded(self):
        path=self.env.game/'large.log'; path.write_text('x'*2300000+'\nException Mod 101\n',encoding='utf-16')
        result=diagnose(path,[self.make('101')],self.env)
        self.assertTrue(result['tail_only']); self.assertEqual(result['findings'][0]['possible_mods'],['Mod 101'])


if __name__=='__main__': unittest.main()
