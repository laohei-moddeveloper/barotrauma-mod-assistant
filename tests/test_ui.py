import tkinter as tk
import gc
from unittest.mock import patch
from test_management import Fixture
from mod_assistant.app import App
from mod_assistant.mod_analysis import inspect_all
from mod_assistant.core import inventory
from mod_assistant.management_ui import ManagementDialog
from mod_assistant.order_ui import OrderDialog


class UiTests(Fixture):
    def setUp(self):
        super().setUp(); self.root=tk.Tk(); self.root.withdraw()
        self.state_patch=patch('mod_assistant.app.STATE',self.env.player/'AssistantState'); self.state_patch.start()
        self.app=App(self.root,auto_scan=False); self.app.env=self.env
        self.app.mods={mod.item_id:{'mod':mod,'stage':mod.status,'progress':0,'detail':''} for mod in inventory(self.env)}
        self.app.features=inspect_all([data['mod'] for data in self.app.mods.values()])
        self.app.runtime_luacs=self.app.runtime_csharp=True
        self.app.assessments=self.app.evaluate_current(); self.app.render()

    def tearDown(self):
        for callback in self.root.tk.call('after','info'):
            self.root.after_cancel(callback)
        self.root.update_idletasks()
        self.root.destroy()
        for handler in list(self.app.logger.handlers):
            handler.close(); self.app.logger.removeHandler(handler)
        self.app = None
        self.root = None
        # Collect closed Tk fixtures on the main thread before the next test
        # starts installer workers; Tk variables cannot be finalized on workers.
        gc.collect()
        self.state_patch.stop(); super().tearDown()

    def test_drag_preview_respects_lock_and_never_writes_live_order(self):
        before=self.config.read_bytes(); dialog=OrderDialog(self.app)
        dialog.list.selection_set(0); dialog.toggle_lock()
        self.assertFalse(dialog.try_move(0,1)); self.assertEqual(dialog.ids,['101','102'])
        dialog.toggle_lock(); self.assertTrue(dialog.try_move(0,1)); dialog.automatic()
        self.assertEqual(before,self.config.read_bytes()); dialog.window.destroy()

    def test_manager_callback_and_operation_result_are_handled(self):
        manager=ManagementDialog(self.app)
        self.app.events.put({'kind':'ui_callback','callback':manager.refresh})
        self.app.events.put({'kind':'operation_done','result':{'message':'fixture done','snapshot':'test'}})
        self.app.drain(); self.assertTrue(self.app.refresh_after_idle)
        self.assertIn('fixture done',self.app.logs.get('1.0','end'))
        manager.window.destroy()
        self.app.events.put({'kind':'ui_callback','callback':manager.refresh}); self.app.drain()

    def test_rule_editor_and_luacs_report_open(self):
        dialog=OrderDialog(self.app); dialog.edit_rules()
        editors=[x for x in dialog.window.winfo_children() if isinstance(x,tk.Toplevel)]
        self.assertEqual(len(editors),1); editors[0].destroy(); dialog.window.destroy()
        self.app.verify_luacs()
        reports=[x for x in self.root.winfo_children() if isinstance(x,tk.Toplevel)]
        self.assertEqual(len(reports),1); reports[0].destroy()
