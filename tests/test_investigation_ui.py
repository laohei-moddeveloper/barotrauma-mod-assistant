import time
from unittest.mock import patch
import test_ui
from mod_assistant.diagnostics import diagnose
from mod_assistant.investigation_ui import InvestigationDialog
from mod_assistant.investigation import read_scene


class InvestigationUiTests(test_ui.UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def settle(self):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            self.root.update();self.app.drain()
            if not (self.app.worker and self.app.worker.is_alive()) and self.app.events.empty():return
            time.sleep(.01)
        self.fail('Investigation background operation did not complete')

    def dialog(self):
        path=self.env.game/'test.log';path.write_text('Failed to add the prefab "shared" (Barotrauma.ItemPrefab) from "Mod 101": a prefab with the same identifier already exists\n')
        mods=[row['mod'] for row in self.app.mods.values()]
        return InvestigationDialog(self.app,path,diagnose(path,mods,self.env,self.app.features))

    def test_before_record_repair_preset_and_recheck_keep_live_configuration_unchanged(self):
        before=self.config.read_bytes();dialog=self.dialog();errors=[]
        self.app.report_error=lambda error,*args:errors.append(str(error))
        def guard(environment):
            self.assertIs(environment,self.env);return False
        with patch('mod_assistant.core.game_running',side_effect=guard),patch('tkinter.simpledialog.askstring',return_value='Repeat the same inventory operation'):
            dialog.capture_before();self.settle()
            self.assertIsNotNone(dialog.before)
            saved=list((self.env.work/'investigations').glob('*.json'))
            self.assertEqual(len(saved),1);self.assertEqual(read_scene(saved[0])['phase'],'before')
            dialog.prepare_repair();self.settle();self.assertEqual(len(dialog.candidates),2)
            dialog.picker.current(0)
            with patch.object(self.app.dialogs,'showinfo'):
                dialog.save_repair();self.settle()
            self.assertEqual(len(list((self.env.game/'ModLists').glob('BaroDock-Repair-*.xml'))),1)
            path=self.env.game/'new.log';path.write_text('Barotrauma Client 1.13.4.0\nOperation completed\n')
            with patch.object(self.app.dialogs,'askyesno',return_value=True),patch.object(self.app.files,'askopenfilename',return_value=str(path)):
                dialog.recheck_log();self.settle()
            self.assertTrue(dialog.recheck['fresh_log']);self.assertTrue(dialog.recheck['not_reproduced'])
        self.assertFalse(errors);self.assertEqual(self.config.read_bytes(),before)
        dialog.window.destroy()

    def test_running_game_blocks_deep_record_but_log_view_is_available(self):
        dialog=self.dialog();errors=[];self.app.report_error=lambda error,*args:errors.append(str(error))
        with patch('mod_assistant.core.game_running',return_value=True),patch('tkinter.simpledialog.askstring',return_value='test'):
            dialog.capture_before()
        self.assertFalse(dialog.before);self.assertTrue(errors);self.assertTrue(dialog.views['log'].get('1.0','end').strip())
        dialog.window.destroy()

    def test_local_labels_filter_and_language_change_preserve_user_text(self):
        before=self.config.read_bytes()
        self.app.tree.selection_set('101')
        with patch('tkinter.simpledialog.askstring',return_value='高 priority crew'):
            self.app.set_mod_label()
        self.app.filter.set('有本地标记');self.app.render()
        self.assertEqual(self.app.tree.get_children(),('101',))
        self.app.set_language('en',persist=False)
        self.assertEqual(self.app.settings['mod_labels']['101'],'高 priority crew')
        self.assertIn('高 priority crew',self.app.detail.get())
        self.assertEqual(self.config.read_bytes(),before)

    def test_reverse_query_shows_disabled_relation_and_small_english_controls_remain_visible(self):
        self.root.deiconify()
        before=self.config.read_bytes();feature=self.app.features['102']
        feature.declared_rules=[{'type':'requiredAnyOrder','id':'101','name':'','condition':'','source':'metadata.xml'}]
        self.app.mods['102']['mod'].enabled=False;self.app.tree.selection_set('101')
        self.app.set_language('en',persist=False);self.app.show_dependents();self.root.update()
        reports=[widget for widget in self.root.winfo_children() if widget.winfo_class()=='Toplevel']
        self.assertTrue(any(widget.title()=='Mods that require or reference this mod' for widget in reports))
        dialog=self.dialog();self.app.interface.apply({'font_size':12},persist=False)
        dialog.window.geometry('850x640');self.root.update()
        self.assertTrue(all(button.winfo_ismapped() for button in dialog.controls))
        self.assertEqual(self.config.read_bytes(),before);dialog.window.destroy()
