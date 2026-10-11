import copy
import json
from pathlib import Path
from unittest.mock import patch

from test_management import Fixture
from mod_assistant.core import AssistantError
from mod_assistant.diagnostics import diagnose
from mod_assistant.file_evidence import package_evidence
from mod_assistant.investigation import capture_scene, compare_scenes, compare_logs, read_scene, save_scene, repair_candidates
from mod_assistant.mod_analysis import inspect
from mod_assistant.mod_order import suggest_order
from mod_assistant.rule_evidence import installed_context


class InvestigationTests(Fixture):
    def test_same_version_file_change_is_visible_and_rule_expires(self):
        mods={item:self.make(item) for item in ('101','102')}
        before=capture_scene(self.env,list(mods.values()),steps='Open the same inventory')
        evidence=before['mods']['101']['evidence']
        rules={'before':[['102','101']],'evidence':[{'before':'102','after':'101','fingerprints':{'101':{'scope':evidence['scope'],'digest':evidence['digest']}}}]}
        valid=installed_context(self.env,mods,rules)
        self.assertEqual(suggest_order(['101','102'],valid,{},rules).ids,['102','101'])
        path=mods['101'].source/'items.xml';path.write_text('<Items><Item identifier="different"/></Items>')
        after=capture_scene(self.env,list(mods.values()),phase='after')
        differences=compare_scenes(before,after)['differences']
        self.assertTrue(any(row.get('file')=='items.xml' and row.get('id')=='101' for row in differences))
        self.assertFalse(any(row['kind']=='模组版本变化' for row in differences))
        stale=installed_context(self.env,mods,rules)
        result=suggest_order(['101','102'],stale,{},rules)
        self.assertEqual(result.ids,['101','102']);self.assertEqual(result.evidence[0]['status'],'changed')

    def test_record_is_local_and_cannot_smuggle_a_path(self):
        original=self.config.read_bytes();scene=capture_scene(self.env)
        path=save_scene(self.env,scene);self.assertEqual(read_scene(path)['id'],scene['id'])
        forged=copy.deepcopy(scene);files=forged['mods']['101']['evidence']['files']
        files['../outside.xml']=files.pop('items.xml');path.write_text(json.dumps(forged))
        with self.assertRaises(AssistantError):read_scene(path)
        self.assertEqual(self.config.read_bytes(),original)

    def test_capture_retains_user_record_name_and_rejects_outside_reads(self):
        from mod_assistant.file_evidence import read_stable
        scene=capture_scene(self.env,name='我的测试 Example',steps='Repeat operation')
        self.assertEqual(scene['name'],'我的测试 Example')
        outside=self.env.game.parent/'outside.xml';outside.write_text('<Example/>')
        with self.assertRaises(AssistantError):read_stable(outside,self.env.game)

    def test_duplicate_log_storm_keeps_the_first_distinct_failure(self):
        path=self.env.game/'test.log'
        path.write_text('Exception first failure\n    at First()\n'+'Exception repeated failure\n    at Repeated()\n'*150)
        report=diagnose(path,[],self.env)
        self.assertEqual(len(report['findings']),2)
        self.assertIn('first failure',report['findings'][0]['text'])
        self.assertEqual(report['findings'][1]['occurrences'],150)
        self.assertFalse(report['findings_truncated'])

    def test_equal_headlines_with_different_stacks_are_separate_message_blocks(self):
        path=self.env.game/'test.log'
        path.write_text('Exception failure\n    at First() in ExceptionTool.cs\nException failure\n    at Second()\nException failure\n    at First() in ExceptionTool.cs\n')
        report=diagnose(path,[],self.env)
        self.assertEqual(len(report['findings']),2)
        self.assertEqual(report['total_occurrences'],3)
        self.assertEqual([row['occurrences'] for row in report['findings']],[2,1])
        legacy=copy.deepcopy(report);legacy.pop('signature_scope')
        other=copy.deepcopy(report);other['sha256']='f'*64
        self.assertFalse(compare_logs(legacy,other)['complete_comparison'])
        self.assertFalse(compare_logs(legacy,other)['not_reproduced'])

    def test_log_comparison_requires_new_bytes_and_complete_coverage(self):
        path=self.env.game/'test.log';path.write_text('Exception broken\n')
        old=diagnose(path,[],self.env)
        self.assertFalse(compare_logs(old,old)['fresh_log'])
        path.write_text('Barotrauma Client 1.13.4.0\nTest operation completed\n')
        new=diagnose(path,[],self.env,baseline=old)
        result=compare_logs(old,new);self.assertTrue(result['fresh_log'])
        self.assertEqual(len(result['not_reproduced']),1)
        new['tail_only']=True
        self.assertFalse(compare_logs(old,new)['not_reproduced'])

    def test_append_recheck_ignores_old_errors_and_counts_new_occurrences(self):
        path=self.env.game/'test.log';path.write_text('Exception old failure\nException shared failure\n',encoding='utf-8')
        before=diagnose(path,[],self.env)
        with path.open('a',encoding='utf-8') as stream:stream.write('Test operation\nException shared failure\nException new failure\n')
        after=diagnose(path,[],self.env,baseline=before);result=compare_logs(before,after)
        self.assertEqual(after['comparison_window']['kind'],'append')
        self.assertTrue(result['complete_comparison'])
        self.assertEqual([row['text'] for row in result['not_reproduced']],['Exception old failure'])
        self.assertEqual([row['text'] for row in result['still_present']],['Exception shared failure'])
        self.assertEqual([row['text'] for row in result['new_errors']],['Exception new failure'])
        self.assertEqual(after['findings'][0]['occurrences'],1)

    def test_partial_line_and_unverified_appended_report_cannot_confirm_repair(self):
        path=self.env.game/'test.log';path.write_bytes(b'Exception unfinished')
        before=diagnose(path,[],self.env)
        with path.open('ab') as stream:stream.write(b' line\nOperation complete\n')
        after=diagnose(path,[],self.env,baseline=before)
        self.assertFalse(compare_logs(before,after)['complete_comparison'])
        self.assertFalse(compare_logs(before,diagnose(path,[],self.env))['complete_comparison'])

    def test_utf16_append_and_record_validation(self):
        path=self.env.game/'test.log';path.write_bytes('Exception 旧错误\n'.encode('utf-16'))
        before=diagnose(path,[],self.env)
        with path.open('ab') as stream:stream.write('Operation complete\n'.encode('utf-16-le'))
        after=diagnose(path,[],self.env,baseline=before)
        self.assertTrue(compare_logs(before,after)['not_reproduced'])
        scene=capture_scene(self.env,log=after);record=save_scene(self.env,scene)
        self.assertEqual(read_scene(record)['log']['comparison_window']['start'],before['log_size'])
        for mutate in (lambda value:value['log'].update(tail_only='false'),lambda value:value['log']['comparison_window'].update(start=-1),lambda value:value['runtime'].update(disk_luacs_trace='true')):
            forged=copy.deepcopy(scene);mutate(forged);record.write_text(json.dumps(forged))
            with self.assertRaises(AssistantError):read_scene(record)

    def test_partial_file_read_does_not_become_matching_evidence(self):
        mod=self.make('101')
        with patch('mod_assistant.file_evidence.MAX_FILES',1):
            report=package_evidence(mod.source)
        self.assertFalse(report['complete']);self.assertFalse(report['digest'])

    def test_context_rules_expire_on_core_or_script_policy_not_ui_or_order(self):
        from mod_assistant.file_evidence import game_context_evidence
        from mod_assistant.rule_evidence import scope_status
        mods={item:self.make(item) for item in ('101','102')}
        context=game_context_evidence(self.env,mods.values())
        record={'before':'102','after':'101','context':{'scope':context['scope'],'digest':context['digest']}}
        rules={'before':[['102','101']],'evidence':[record]}
        def state():return scope_status(record,installed_context(self.env,mods,rules),'1.13.4.0')
        self.assertEqual(state(),'applicable')
        self.configure(['102','101'])
        self.config.write_text(self.config.read_text().replace('<config>','<config soundvolume="0.1">'))
        self.assertEqual(state(),'applicable')
        core=self.env.game/'Content/changed.xml';core.write_text('<Content/>')
        self.assertEqual(state(),'changed');core.unlink()
        self.assertEqual(state(),'applicable')
        (self.env.game/'LuaCsSetupConfig.xml').write_text('<LuaCsSetupConfig EnableCsScripting="true"/>')
        self.assertEqual(state(),'changed')

    def test_scene_comparison_includes_runtime_assemblies_not_only_client_dll(self):
        path=self.env.game/'BarotraumaCore.dll';path.write_bytes(b'old fixture assembly')
        before=capture_scene(self.env)
        path.write_bytes(b'new fixture assembly')
        after=capture_scene(self.env,phase='after')
        changes=compare_scenes(before,after)
        self.assertFalse(changes['same_recorded_inputs'])
        self.assertTrue(any(row.get('file')=='BarotraumaCore.dll' for row in changes['differences']))

    def test_core_change_after_context_capture_is_rejected(self):
        import mod_assistant.investigation as investigation
        path=self.env.game/'BarotraumaCore.dll';path.write_bytes(b'original fixture assembly')
        original=investigation.read_stable;reads=0
        def change(file,*args,**kwargs):
            nonlocal reads
            result=original(file,*args,**kwargs)
            if Path(file).name=='config_player.xml':
                reads+=1
                if reads==2:path.write_bytes(b'changed fixture assembly')
            return result
        with patch.object(investigation,'read_stable',side_effect=change):
            with self.assertRaises(AssistantError):capture_scene(self.env)

    def test_package_metadata_changing_before_hash_is_not_bound_to_old_version(self):
        import mod_assistant.investigation as investigation
        original=investigation.capture_profile;first=True
        def change(*args,**kwargs):
            nonlocal first
            profile=original(*args,**kwargs)
            if first:
                first=False;path=self.env.installed/'101/filelist.xml'
                path.write_text(path.read_text().replace('modversion="1"','modversion="2"'))
            return profile
        with patch.object(investigation,'capture_profile',side_effect=change):
            with self.assertRaises(AssistantError):capture_scene(self.env)

    def test_repair_preview_removes_declared_dependents_without_writing_config(self):
        mods=[self.make('101'),self.make('102'),self.make('104')]
        self.configure(['101','102','104']);profile=capture_scene(self.env,mods)['profile']
        features={mod.item_id:inspect(mod) for mod in mods}
        features['104'].declared_rules=[{'type':'requiredAnyOrder','id':'101','name':'','condition':'','source':'metadata.xml'}]
        report={'findings':[{'locations':[{'mod_id':mod.item_id,'mod_name':mod.name,'identifier':'shared','override':False} for mod in mods[:2]]}]}
        baseline=self.config.read_bytes();candidates=repair_candidates(report,profile,features)
        candidate=next(row for row in candidates if row['target']=='101')
        self.assertEqual(candidate['removed'],['101','104'])
        self.assertEqual([entry['id'] for entry in candidate['profile']['order']],['102'])
        self.assertEqual(self.config.read_bytes(),baseline)
