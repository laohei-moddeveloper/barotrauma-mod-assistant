import time
import tkinter as tk
from unittest.mock import patch
import test_ui
from mod_assistant.mod_analysis import inspect
from mod_assistant.management_ui import ManagementDialog
from mod_assistant.save_ui import SaveDialog
from mod_assistant.save_inspector import SaveInfo,candidates
from mod_assistant.xml_compare_ui import XMLCompareDialog
from mod_assistant.xml_semantics import format_semantics
from mod_assistant.order_ui import OrderDialog


class EvidenceUiTests(test_ui.UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def finish(self):
        if self.app.worker: self.app.worker.join(5)
        self.app.drain(); self.root.update()

    def test_save_preview_native_export_and_language_switch_preserve_config(self):
        before=self.config.read_bytes(); manager=ManagementDialog(self.app)
        info=SaveInfo('战役.save','a'*64,'1.13.4.0','',['Vanilla','Mod 102','Mod 101'],[])
        mods=[data['mod'] for data in self.app.mods.values()]; available,rows=candidates(self.env,info,mods)
        dialog=SaveDialog(manager,info,available,rows,[],mods)
        self.app.set_language('en',persist=False); dialog.preview(); self.finish()
        self.assertIsNotNone(dialog.draft); self.assertEqual(str(dialog.save_button.cget('state')),'normal')
        self.assertIn('Mod 102',dialog.output.get('1.0','end'))
        self.assertIn('Order to review',dialog.output.get('1.0','end'))
        self.app.set_language('zh',persist=False); self.assertIn('待审核顺序',dialog.output.get('1.0','end'))
        self.assertNotIn('Order to review',dialog.output.get('1.0','end'))
        dialog.save(); self.assertTrue(list((self.env.game/'ModLists').glob('Save-review-*.xml')))
        self.assertEqual(self.config.read_bytes(),before); manager.window.destroy()

    def test_import_route_accepts_save_without_a_second_picker(self):
        manager=ManagementDialog(self.app); path=self.env.player/'test.save'
        with patch.object(self.app.files,'askopenfilename',return_value=str(path)),patch('mod_assistant.save_ui.inspect_selected_save') as inspect:
            manager.import_file(); inspect.assert_called_once_with(manager,str(path))
        manager.window.destroy()

    def test_semantic_report_preserves_literal_values_and_clears_on_selection(self):
        self.app.features={item:inspect(self.make(item)) for item in ('101','102')}
        dialog=XMLCompareDialog(self.app,'101')
        report={'loading':{'message':'所比较的声明字段没有差异。','winner':''},'chain':[],
                'changes':[{'path':'/item/@name','kind':'仅左方改变该字段','baseline':'低','left':'高','right':'未知'}],
                'notes':[],'source':'https://example.com'}
        dialog.semantic_result=report; self.app.set_language('en',persist=False); dialog.render_semantic()
        value=dialog.semantic.get('1.0','end'); self.assertIn('Left: 高',value); self.assertNotIn('Left: High',value)
        dialog.select_other(); self.assertEqual(dialog.semantic.get('1.0','end').strip(),''); dialog.window.destroy()

    def test_record_rule_dialog_buttons_fit_small_english_window(self):
        self.app.set_language('en',persist=False); self.app.interface.apply({'font_size':12},persist=False)
        self.root.deiconify(); self.root.update()
        dialog=OrderDialog(self.app); dialog.edit_rules(); editor=next(x for x in dialog.window.winfo_children() if isinstance(x,tk.Toplevel))
        def all_children(root):
            for child in root.winfo_children(): yield child; yield from all_children(child)
        pickers=[widget for widget in all_children(editor) if widget.winfo_class()=='TCombobox']
        for index,picker in enumerate(pickers): picker.current(index)
        buttons={button.cget('text'):button for button in all_children(editor) if isinstance(button,tk.Button)}
        buttons['Add rule'].invoke()
        listing=next(widget for widget in all_children(editor) if isinstance(widget,tk.Listbox)); listing.selection_set(0)
        buttons['Record rule evidence'].invoke(); popup=next(x for x in editor.winfo_children() if isinstance(x,tk.Toplevel))
        self.root.update(); bottom=popup.winfo_rooty()+popup.winfo_height()
        for button in [x for x in all_children(popup) if isinstance(x,tk.Button)]:
            self.assertTrue(button.winfo_ismapped()); self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),bottom)
        popup.destroy(); editor.destroy(); dialog.window.destroy()
