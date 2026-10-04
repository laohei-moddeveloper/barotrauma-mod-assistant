import json
import tkinter as tk
from tkinter import ttk
import unittest

from mod_assistant.appearance import DEFAULTS, PALETTES, THEMES, contrast, normalize, palette
from mod_assistant.appearance import Appearance
from mod_assistant.management_ui import ManagementDialog
from mod_assistant.order_ui import OrderDialog
import test_ui


class AppearanceTests(unittest.TestCase):
    def test_invalid_preferences_fall_back_without_dropping_required_columns(self):
        for invalid in (None,[],{'theme':[],'accent':'red','font_size':100,'density':'unknown','show_logs':'yes'},
                        {'theme':{},'font_size':True,'columns':'name'}):
            self.assertEqual(normalize(invalid),DEFAULTS)
        prefs=normalize({'columns':['size','size','unknown']})
        self.assertEqual(prefs['columns'],['check','enable','name','size'])
        prefs['columns'].append('version'); self.assertNotIn('version',DEFAULTS['columns'])

    def test_custom_accent_is_preserved_but_foreground_is_readable(self):
        for theme in THEMES:
            for accent in ('#000000','#ffffff','#ffff00','#57dac4','#B9A3FF'):
                colours=palette({'theme':theme,'accent':accent})
                self.assertEqual(colours['accent'],accent.lower())
                self.assertGreaterEqual(contrast(colours['primary_text'],colours['accent']),4.5)
                self.assertGreaterEqual(contrast(colours['accent_text'],colours['panel']),4.5)
                self.assertGreaterEqual(contrast(colours['accent_text'],colours['bg']),4.5)

    def test_preset_body_text_is_readable(self):
        for colours in PALETTES.values():
            for foreground in ('text','muted'):
                for background in ('bg','panel'):
                    self.assertGreaterEqual(contrast(colours[foreground],colours[background]),4.5)


class AppearanceUiTests(test_ui.UiTests):
    # Reuse the fixture, without repeating the parent tests in discovery.
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def test_dropdown_selection_localizes_from_tcl_scope_and_preserves_game_config(self):
        app=self.app; before=self.config.read_bytes(); errors=[]
        self.root.report_callback_exception=lambda *error:errors.append(str(error[1]))
        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)
        def select(variable,index):
            picker=next(widget for widget in children(self.root)
                        if isinstance(widget,ttk.Combobox)
                        and str(widget.cget('textvariable'))==str(variable))
            # This is the same Tcl procedure used by the real dropdown, where
            # an unqualified getvar() resolves in Tcl's local callback scope.
            self.root.tk.call('ttk::combobox::SelectEntry',str(picker),index)
            self.root.update_idletasks()
        for language in ('en','zh'):
            app.set_language(language,persist=False)
            for index,theme in enumerate(THEMES):
                select(app.interface.theme,index)
                self.assertEqual(errors,[])
                self.assertEqual(app.appearance.prefs['theme'],theme)
                self.assertEqual(self.root.tk.globalgetvar(str(app.interface.language)),
                                 'English' if language=='en' else '中文')
            select(app.interface.font,2);select(app.interface.density,1)
            self.assertEqual(errors,[])
            self.assertEqual(app.appearance.prefs['font_size'],12)
            self.assertEqual(app.appearance.prefs['density'],'compact')
            self.assertEqual(self.config.read_bytes(),before)
            saved=json.loads(app.settings_file.read_text(encoding='utf-8'))
            self.assertEqual(saved['appearance']['theme'],'daylight')
            self.assertEqual(saved['appearance']['font_size'],12)

    def test_theme_updates_existing_dialogs_and_preserves_selection_and_game_configuration(self):
        app=self.app; before=self.config.read_bytes(); app.tree.selection_set('101'); app.selected={'101'}
        order=OrderDialog(app); manager=ManagementDialog(app)
        worker=object(); app.worker=worker
        for theme in THEMES:
            app.interface.apply({'theme':theme,'accent':'#ffff00','font_size':12,'show_logs':True})
            colours=app.appearance.colours
            self.assertEqual(app.root.cget('background'),colours['bg'])
            self.assertEqual(order.list.cget('background'),colours['panel'])
            self.assertEqual(manager.profile_preview.cget('foreground'),colours['muted'])
            self.assertEqual(app.tree.selection(),('101',)); self.assertEqual(app.selected,{'101'})
            self.assertIs(app.worker,worker); self.assertEqual(self.config.read_bytes(),before)
        app.worker=None; manager.window.destroy(); order.window.destroy()

    def test_font_density_columns_and_log_collapse_work_together(self):
        app=self.app; app.interface.apply({'font_size':12,'density':'compact','columns':['size'],'show_logs':True})
        self.assertEqual(app.tree['displaycolumns'],('check','enable','name','size'))
        self.assertEqual(app.logs.winfo_manager(),'pack')
        app.log('preserved while hidden'); app.interface.toggle_logs()
        self.assertEqual(app.logs.winfo_manager(),''); self.assertIn('preserved while hidden',app.logs.get('1.0','end'))
        app.interface.column_vars['compat'].set(True); app.interface.change_columns()
        self.assertIn('compat',app.tree['displaycolumns'])

    def test_saved_preferences_reopen_and_reset_only_appearance(self):
        app=self.app; app.settings['game_directory']='keep-directory'; app.settings['timeout']=200
        app.interface.apply({'theme':'daylight','font_size':11,'accent':'#b9a3ff'})
        saved=json.loads(app.settings_file.read_text(encoding='utf-8'))
        self.assertEqual(saved['appearance']['theme'],'daylight'); self.assertEqual(saved['timeout'],200)
        self.assertEqual(Appearance(saved['appearance']).prefs,app.appearance.prefs)
        reopened_root=tk.Toplevel(app.root); reopened_root.withdraw()
        reopened=test_ui.App(reopened_root,auto_scan=False)
        self.assertEqual(reopened.appearance.prefs,app.appearance.prefs)
        self.assertEqual(reopened.tree['displaycolumns'],app.tree['displaycolumns'])
        reopened.close()
        app.interface.apply(DEFAULTS)
        self.assertEqual(app.settings['game_directory'],'keep-directory'); self.assertEqual(app.settings['timeout'],200)
        self.assertEqual(app.appearance.prefs,DEFAULTS)

    def test_filters_search_and_readonly_theme_changes_do_not_enable_mods(self):
        app=self.app; before=self.config.read_bytes()
        app.filter.set('未启用'); self.assertEqual(app.tree.get_children(),('103',))
        app.filter.set('已启用'); self.assertEqual(set(app.tree.get_children()),{'101','102'})
        app.search.set('102'); self.assertEqual(app.tree.get_children(),('102',))
        app.interface.focus_search(); self.assertEqual(app.interface.notebook.select(),str(app.interface.mods_page))
        app.interface.apply({'theme':'graphite'}); self.assertEqual(app.tree.get_children(),('102',))
        self.assertEqual(app.interface.clear_search(),'break'); self.assertEqual(app.search.get(),'')
        app.mods['103']['stage']='未安装'; app.filter.set('需要处理')
        self.assertIn('103',app.tree.get_children())
        self.assertEqual(before,self.config.read_bytes())

    def test_small_window_and_large_font_keep_primary_actions_visible(self):
        app=self.app; app.root.deiconify(); app.root.geometry('1000x680')
        app.interface.apply({'font_size':12,'theme':'daylight'})
        app.root.update()
        for button in (app.update_button,app.refresh_button,app.stop_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),app.root.winfo_rootx()+app.root.winfo_width())
        self.assertGreater(app.tree.winfo_height(),180)
