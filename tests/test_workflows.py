"""Observable workflow regressions in isolated game folders, with no real network."""
import json
from pathlib import Path
from unittest.mock import patch
from mod_assistant.core import AssistantError, Mod, inventory
from mod_assistant.tasks import TaskCheckpoint
from mod_assistant.drafts import commit_draft
from mod_assistant.mod_order import read_order, save_rules
from mod_assistant.mod_analysis import Features, evaluate, pair_evidence, pair_detail
from mod_assistant.analysis_cache import inspect_cached
from mod_assistant.engine import UpdateEngine
from mod_assistant.order_ui import OrderDialog
from test_management import Fixture
from test_ui import UiTests
from test_assistant import Fixture as InstallFixture, FakeBridge


class CheckpointTests(InstallFixture):
    def test_finished_items_are_not_resumed_after_restart(self):
        self.package('102')
        engine=UpdateEngine(self.env,lambda event:None,bridge_factory=FakeBridge,process_guard=lambda:False)
        result=engine.run(['101','102'],online=False)
        self.assertEqual(set(result['completed']),{'101','102'})
        self.assertEqual(TaskCheckpoint(self.env).pending(),([],False))

    def test_interrupt_record_keeps_only_unfinished_ids_and_network_choice(self):
        task=TaskCheckpoint(self.env);task.begin(['101','102'],True);task.complete('101')
        self.assertEqual(TaskCheckpoint(self.env).pending(),(['102'],True))
        self.assertEqual(task.load()['state'],'running')
        task.finish('cancelled')
        self.assertEqual(TaskCheckpoint(self.env).pending(),(['102'],True))

    def test_corrupt_untrusted_records_are_kept_and_rejected(self):
        task=TaskCheckpoint(self.env);task.begin(['101'],False);valid=task.load()
        invalid=[[],None,{'schema':1}, {**valid,'ids':[['101']]}, {**valid,'ids':['../outside']},
                 {**valid,'ids':['١٠١']}, {**valid,'ids':['0']}, {**valid,'completed':['999']},
                 {**valid,'game':'other'}, {**valid,'online':'true'}, {**valid,'ids':['101','101']}]
        for value in invalid:
            content=json.dumps(value);task.path.write_text(content)
            with self.assertRaises(AssistantError):task.pending()
            self.assertEqual(task.path.read_text(),content)

    def test_cancelled_queue_can_resume_without_automatic_requests(self):
        engine=UpdateEngine(self.env,lambda event:None,bridge_factory=FakeBridge,process_guard=lambda:False)
        engine.cancel.set();result=engine.run(['101'],False)
        self.assertTrue(result['cancelled'])
        self.assertEqual(TaskCheckpoint(self.env).pending(),(['101'],False))


class DraftTests(Fixture):
    def test_batch_disable_and_reorder_preserve_core_and_other_settings(self):
        self.make('104');self.configure(['101','102'],core='103',bom=True)
        before=self.config.read_bytes();mods=inventory(self.env)
        backup=commit_draft(self.env,['104','101'],before,['101','102'],mods,self.guard)
        self.assertEqual(read_order(self.env),['104','101'])
        self.assertEqual(Path(backup).read_bytes(),before)
        content=self.config.read_bytes()
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'volume="77"',content);self.assertIn(b'custom="keep"',content)
        self.assertIn(b'103/filelist.xml',content)

    def test_changed_configuration_and_game_start_block_draft(self):
        before=self.config.read_bytes();mods=inventory(self.env)
        self.configure(['101'],volume=44);current=self.config.read_bytes()
        with self.assertRaises(AssistantError):commit_draft(self.env,['102'],before,['101','102'],mods,self.guard)
        self.assertEqual(self.config.read_bytes(),current)
        with self.assertRaises(AssistantError):commit_draft(self.env,['102'],current,['101'],mods,lambda:True)
        self.assertEqual(self.config.read_bytes(),current)

    def test_core_or_missing_files_cannot_enter_regular_draft(self):
        before=self.config.read_bytes();mods=inventory(self.env)
        for ids in [['103'],['999'],['101','101']]:
            with self.assertRaises(AssistantError):commit_draft(self.env,ids,before,['101','102'],mods,self.guard)
            self.assertEqual(self.config.read_bytes(),before)
        save_rules(self.env,{'before':[['101','102']]})
        with self.assertRaises(AssistantError):commit_draft(self.env,['102','101'],before,['101','102'],mods,self.guard)


class AnalysisWorkflowTests(Fixture):
    def test_affliction_override_does_not_claim_generic_override_winner(self):
        key=('afflictions','affliction','injury')
        left=Features('101','Base',definitions={key})
        right=Features('102','Patch',definitions={key},overrides={key})
        detail=pair_detail(left,right,['102','101'])
        self.assertEqual(detail['expected_xml_winner'],'')
        self.assertIn('当前游戏版本',detail['advice'])

    def test_mixed_override_and_duplicate_keeps_duplicate_warning(self):
        special=('afflictions','affliction','injury')
        ordinary=('item','item','duplicate')
        left=Features('101','Base',definitions={special,ordinary})
        right=Features('102','Patch',definitions={special,ordinary},overrides={special})
        detail=pair_detail(left,right,['102','101'])
        self.assertEqual(detail['expected_xml_winner'],'')
        self.assertIn('普通定义',detail['advice'])

    def test_unrelated_mods_do_not_invoke_pair_comparison(self):
        mods=[Mod(str(1000+i),'Unique '+str(i),None) for i in range(500)]
        features={mod.item_id:Features(mod.item_id,mod.name,definitions={('item','item',mod.item_id)}) for mod in mods}
        features[mods[1].item_id].definitions=features[mods[0].item_id].definitions.copy()
        with patch('mod_assistant.mod_analysis.pair_evidence',wraps=pair_evidence) as compare:
            results=evaluate(mods,features)
        # One candidate, plus one evidence-detail call for each side of that pair.
        self.assertEqual(compare.call_count,3)
        self.assertEqual(results[mods[0].item_id].risky_pairs,1)
        self.assertEqual(results[mods[2].item_id].risky_pairs,0)
        self.assertEqual(results[mods[2].item_id].compared,499)

    def test_cache_delivers_per_mod_results_and_detects_changed_resource(self):
        mods=inventory(self.env);seen=[]
        _,first=inspect_cached(self.env,mods,on_feature=lambda item,f:seen.append(item))
        self.assertEqual(seen,[mod.item_id for mod in mods])
        _,second=inspect_cached(self.env,mods)
        self.assertEqual(second['reused'],len(mods))
        (self.env.installed/'101/items.xml').write_text('<Items><Item identifier="changed-id" /></Items>')
        features,third=inspect_cached(self.env,mods)
        self.assertEqual(third['scanned'],1)
        self.assertIn(('item','item','changed-id'),features['101'].definitions)


class InventorySpeedTests(InstallFixture):
    def test_each_steam_manifest_is_read_once_per_inventory(self):
        from mod_assistant.core import read_vdf
        self.package('102');self.package('103')
        with patch('mod_assistant.core.read_vdf',wraps=read_vdf) as read:
            mods=inventory(self.env,read_config=False)
        self.assertEqual(read.call_count,1)
        self.assertEqual(len(mods),3)
        self.assertEqual({m.size for m in mods},{100})


class WorkflowUiTests(UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def test_english_large_font_draft_actions_remain_inside_window(self):
        self.root.deiconify()
        self.app.set_language('en',persist=False)
        self.app.interface.apply({**self.app.appearance.prefs,'font_size':12},persist=False)
        dialog=OrderDialog(self.app);self.root.update()
        self.assertEqual(dialog.list.size(),len(dialog.ids))
        self.assertTrue(dialog.ids)
        def descendants(widget):
            for child in widget.winfo_children():
                yield child;yield from descendants(child)
        import tkinter as tk
        actions=[child for child in descendants(dialog.window) if isinstance(child,(tk.Button,tk.Menubutton))]
        self.assertGreaterEqual(len(actions),10)
        for action in actions:
            self.assertTrue(action.winfo_ismapped())
            self.assertLessEqual(action.winfo_rooty()+action.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
            self.assertLessEqual(action.winfo_rootx()+action.winfo_width(),dialog.window.winfo_rootx()+dialog.window.winfo_width())
        dialog.window.destroy()
        self.root.withdraw()

    def test_search_accepts_separated_keywords_and_copy_is_explicit(self):
        self.app.mods['101']['mod'].name='Demo Equipment Expansion Pack'
        self.app.search.set('Demo Pack')
        self.assertEqual(self.app.tree.get_children(),('101',))
        self.app.tree.selection_set('101')
        with patch.object(self.root,'clipboard_clear') as clear,patch.object(self.root,'clipboard_append') as copy:
            self.app.copy_selected();clear.assert_called_once();copy.assert_called_once_with('Demo Equipment Expansion Pack [101]')
        self.app.search.set('not-present');self.assertEqual(self.app.tree.get_children(),())

    def test_locked_auto_sort_preserves_added_and_disabled_draft_entries(self):
        import tkinter as tk
        mod=self.make('104')
        self.app.mods['104']={'mod':mod,'stage':mod.status,'progress':0,'detail':''}
        before=self.config.read_bytes();dialog=OrderDialog(self.app)
        dialog.list.selection_set(0);dialog.toggle_lock();dialog.add_installed()
        picker=next(child for child in dialog.window.winfo_children() if isinstance(child,tk.Toplevel))
        next(child for child in picker.winfo_children() if isinstance(child,tk.Button)).invoke()
        self.assertEqual(dialog.ids,['101','102','104'])
        dialog.automatic();self.app.worker.join(3);self.app.drain();self.assertEqual(dialog.ids,['101','102','104'])
        dialog.list.selection_clear(0,'end');dialog.list.selection_set(2);dialog.toggle_lock()
        self.assertNotIn('104',dialog.rules['locks'])
        dialog.list.selection_clear(0,'end');dialog.list.selection_set(1);dialog.remove_selected()
        dialog.automatic();self.app.worker.join(3);self.app.drain();self.assertEqual(dialog.ids,['101','104'])
        self.assertEqual(self.config.read_bytes(),before);dialog.window.destroy()

    def test_list_is_visible_before_deep_analysis_starts(self):
        self.app.set_language('en',persist=False)
        actual=inspect_cached;observed=[];before=self.config.read_bytes()
        def slow_analysis(*args,**kwargs):
            self.app.drain()
            observed.append(len(self.app.tree.get_children()))
            self.assertFalse(self.app.features)
            return actual(*args,**kwargs)
        with patch('mod_assistant.app.discover',return_value=self.env),patch('mod_assistant.app.game_running',return_value=False), \
             patch('mod_assistant.app.inspect_cached',side_effect=slow_analysis),patch.object(self.app,'work',side_effect=lambda fn:fn()), \
             patch('mod_assistant.app.SteamBridge') as bridge,patch('urllib.request.urlopen') as request:
            self.app.scan();self.app.drain()
        self.assertEqual(observed,[len(self.app.mods)])
        bridge.assert_not_called();request.assert_not_called()
        self.assertEqual(self.config.read_bytes(),before)
        self.assertGreaterEqual(self.app.scan_timings['complete_seconds'],self.app.scan_timings['first_list_seconds'])
        log=self.app.logs.get('1.0','end')
        self.assertFalse(any('\u4e00'<=char<='\u9fff' for char in log),log)

    def test_missing_or_invalid_config_is_browsable_and_blocks_changes(self):
        self.config.unlink()
        for malformed in (None,'<broken'):
            if malformed:self.config.write_text(malformed)
            with patch('mod_assistant.app.discover',return_value=self.env),patch('mod_assistant.app.game_running',return_value=False), \
                 patch.object(self.app,'work',side_effect=lambda fn:fn()),patch('urllib.request.urlopen') as request:
                self.app.scan();self.app.drain();self.app.set_busy(False)
            self.assertFalse(self.app.config_ready)
            self.assertTrue(self.app.tree.get_children())
            self.assertIn('未知',self.app.summary.get())
            self.app.filter.set('未启用');self.assertFalse(self.app.tree.get_children())
            self.app.filter.set('全部模组');self.assertTrue(self.app.tree.get_children())
            self.assertEqual(self.app.update_button.cget('state'),'disabled')
            self.assertEqual(self.app.refresh_button.cget('state'),'normal')
            request.assert_not_called()
            self.assertEqual(self.config.exists(),malformed is not None)

    def test_draft_disable_undo_redo_and_reset_never_write_game_config(self):
        before=self.config.read_bytes();dialog=OrderDialog(self.app)
        dialog.list.selection_set(1);dialog.remove_selected();self.assertEqual(dialog.ids,['101'])
        dialog.history();self.assertEqual(dialog.ids,['101','102'])
        dialog.history(True);self.assertEqual(dialog.ids,['101'])
        dialog.reset_draft();self.assertEqual(dialog.ids,['101','102'])
        self.assertEqual(self.config.read_bytes(),before)
        with patch.object(self.app.dialogs,'askyesno',return_value=False),patch.object(self.app,'work') as work:
            dialog.save();work.assert_not_called()
        dialog.window.destroy()

    def test_resuming_waits_for_explicit_online_confirmation(self):
        task=TaskCheckpoint(self.env);task.begin(['101','102'],True);task.complete('101')
        with patch.object(self.app.dialogs,'askyesno',return_value=False),patch.object(self.app,'work') as work:
            self.app.resume_update();work.assert_not_called()
        self.assertEqual(self.app.selected,{'102'})
        self.assertEqual(task.pending(),(['102'],True))
