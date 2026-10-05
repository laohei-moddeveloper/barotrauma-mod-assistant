import io
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from mod_assistant.core import discover, AssistantError, Cancelled
from mod_assistant.preferences import load_preferences, normalize_preferences
from mod_assistant.mod_analysis import workshop_details
from mod_assistant.analysis_cache import inspect_cached, signature
from mod_assistant.steam import SteamBridge
from mod_assistant.i18n import Localizer
from mod_assistant.app import App
import test_ui
from test_management import Fixture


class FirstInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='new user 中文 ')
        self.root = Path(self.temp.name)
        self.steam = self.root / 'Steam'
        (self.steam / 'steamapps').mkdir(parents=True)
        (self.steam / 'steam.exe').write_bytes(b'fixture')
        self.roots = patch('mod_assistant.core.steam_locations', return_value=[self.root/'removed', self.steam])
        self.roots.start()

    def tearDown(self):
        self.roots.stop()
        self.temp.cleanup()

    def test_moved_game_and_legacy_secondary_library(self):
        library = self.root / 'Games 移动盘'
        game = library / 'steamapps/common/CustomName'
        game.mkdir(parents=True)
        (game/'Barotrauma.exe').touch()
        (library/'steamapps/appmanifest_602960.acf').write_text('"AppState" { "installdir" "CustomName" }')
        path = library.as_posix()
        (self.steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" "'+path+'" }',encoding='utf-8')
        found = discover(str(self.root/'old game'))
        self.assertEqual(found.game, game)
        self.assertIn(library, found.libraries)

    def test_no_manifest_fallback_and_missing_localappdata(self):
        game = self.steam/'steamapps/common/Barotrauma'
        game.mkdir(parents=True)
        (game/'Barotrauma.exe').touch()
        with patch.dict(os.environ, {'LOCALAPPDATA':''}):
            found = discover()
        self.assertEqual(found.game, game)
        self.assertEqual(found.player, Path.home()/'AppData/Local/Daedalic Entertainment GmbH/Barotrauma')

    def test_no_steam_or_game_has_actionable_message(self):
        with patch('mod_assistant.core.steam_locations', return_value=[]):
            with self.assertRaisesRegex(AssistantError, 'Steam'): discover()
        with self.assertRaisesRegex(AssistantError, '选择游戏目录'): discover()

    def test_preferences_invalid_types_limits_and_boolean_strings(self):
        value=normalize_preferences({'download_slots':[], 'install_slots':'999', 'timeout':-1,
                                    'auto_snapshot':'false', 'light_detection':None, 'game_directory':{},
                                    'custom':'preserved'})
        self.assertEqual((value['download_slots'],value['install_slots'],value['timeout']), (4,6,30))
        self.assertFalse(value['auto_snapshot']); self.assertTrue(value['light_detection'])
        self.assertEqual(value['game_directory'],''); self.assertEqual(value['custom'],'preserved')

    def test_invalid_settings_preserved_and_unreadable_settings_not_overwritten(self):
        path=self.root/'settings.json'; original=b'{invalid settings'
        path.write_bytes(original)
        settings,warnings,writable=load_preferences(path)
        self.assertTrue(writable); self.assertTrue(warnings)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(next(self.root.glob('settings.invalid-*.json')).read_bytes(),original)
        with patch.object(Path, 'read_text', side_effect=PermissionError('ACL')):
            _,warnings,writable=load_preferences(path)
        self.assertFalse(writable); self.assertTrue(warnings)
        self.assertEqual(path.read_bytes(),original)


class NetworkAndCacheTests(Fixture):
    def test_malformed_metadata_cache_and_response_do_not_abort_scan(self):
        path=self.env.work/'analysis/workshop-details.json';path.parent.mkdir(parents=True)
        for malformed in [[], {'entries':[]}, {'entries':{'101':None},'fetched_at':{}},
                          {'entries':{'101':{'tags':'bad','children':[]}},'fetched_at':'bad'}]:
            path.write_text(json.dumps(malformed))
            with patch('mod_assistant.mod_analysis.urllib.request.urlopen',return_value=io.BytesIO(b'[]')):
                data,available=workshop_details(self.env,['101'])
            self.assertEqual(data,{});self.assertFalse(available)

    def test_metadata_backoff_preserves_old_data_then_recovers(self):
        path=self.env.work/'analysis/workshop-details.json';path.parent.mkdir(parents=True)
        original={'101':{'tags':['Items'],'children':['102']}}
        path.write_text(json.dumps({'entries':original,'fetched_at':0}))
        with patch('mod_assistant.mod_analysis.time.time',return_value=100000), \
             patch('mod_assistant.mod_analysis.urllib.request.urlopen',side_effect=OSError('429')) as request:
            self.assertEqual(workshop_details(self.env,['101'])[0],original)
            self.assertEqual(workshop_details(self.env,['101'])[0],original)
            self.assertEqual(request.call_count,1)
        response={'response':{'publishedfiledetails':[{'publishedfileid':'101','result':1,
                  'consumer_app_id':602960,'tags':[],'children':[]}]}}
        with patch('mod_assistant.mod_analysis.time.time',return_value=100061), \
             patch('mod_assistant.mod_analysis.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as request:
            data,available=workshop_details(self.env,['101'])
            self.assertTrue(available);self.assertEqual(data['101']['children'],[])
            self.assertEqual(request.call_count,1)

    def test_cancelled_metadata_does_not_start_network(self):
        cancel=threading.Event();cancel.set()
        with patch('mod_assistant.mod_analysis.urllib.request.urlopen') as request:
            with self.assertRaises(Cancelled):workshop_details(self.env,['101'],cancel=cancel)
            request.assert_not_called()

    def test_unwritable_analysis_cache_keeps_results(self):
        mods=[self.make('201')]; notices=[]
        with patch('mod_assistant.analysis_cache.atomic_json',side_effect=PermissionError('ACL')):
            features,stats=inspect_cached(self.env,mods,emit=notices.append)
        self.assertIn('201',features);self.assertEqual(stats['scanned'],1)
        self.assertTrue(any('无法保存' in message for message in notices))

    def test_signature_ignores_texture_stats_but_not_changed_code(self):
        mod=self.make('201');texture=mod.source/'image.png';texture.write_bytes(b'image')
        before=signature(mod,{})
        texture.write_bytes(b'image changed')
        self.assertEqual(signature(mod,{}),before)
        resource=mod.source/'items.xml'
        resource.write_text('<Items><Item identifier="changed"/></Items>',encoding='utf-8')
        # Model an observable file-state change without relying on write timing
        # or the host filesystem's timestamp resolution.
        state=resource.stat()
        os.utime(resource,ns=(state.st_atime_ns,state.st_mtime_ns+1_000_000_000))
        self.assertNotEqual(signature(mod,{}),before)
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):signature(mod,{},cancel)

    def test_missing_native_steam_library_is_actionable(self):
        with patch('mod_assistant.steam.C.CDLL',side_effect=OSError('WinError 126')):
            with self.assertRaisesRegex(AssistantError,'验证游戏文件完整性'):SteamBridge(self.env).connect()

    def test_force_refresh_updates_recent_dependencies(self):
        path=self.env.work/'analysis/workshop-details.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'entries':{'101':{'tags':[],'children':['old']}},'fetched_at':100000}))
        response={'response':{'publishedfiledetails':[{'publishedfileid':'101','result':1,
                  'consumer_app_id':602960,'tags':[],'children':[{'publishedfileid':'102'}]}]}}
        with patch('mod_assistant.mod_analysis.time.time',return_value=100001), \
             patch('mod_assistant.mod_analysis.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as request:
            workshop_details(self.env,['101']);request.assert_not_called()
            data,_=workshop_details(self.env,['101'],force=True)
        self.assertEqual(data['101']['children'],['102'])

    def test_current_mixed_case_analysis_cache_is_reused(self):
        import hashlib
        from mod_assistant.analysis_cache import encode, SCHEMA
        from mod_assistant.mod_analysis import inspect
        mod=self.make('201')
        (mod.source/'Z.lua').write_text('-- fixture')
        (mod.source/'a.lua').write_text('-- fixture')
        rows=[]
        for file in sorted(mod.source.rglob('*')):
            if file.is_file() and file.suffix.casefold() in ('.xml','.lua','.cs','.dll'):
                stat=file.stat();rows.append((file.relative_to(mod.source).as_posix(),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
        legacy=hashlib.sha256(json.dumps([str(mod.source),mod.name,list(mod.aliases),rows,{}],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        path=self.env.work/'analysis/features-v3'/ (hashlib.sha256(mod.item_id.encode()).hexdigest()+'.json')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'schema':SCHEMA,'source':str(mod.source),'signature':legacy,'feature':encode(inspect(mod))}))
        with patch('mod_assistant.analysis_cache.inspect',side_effect=AssertionError('unchanged cache should be reused')):
            _,stats=inspect_cached(self.env,[mod])
        self.assertEqual(stats['reused'],1)


class OnboardingUiTests(test_ui.UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def test_no_game_controls_and_bilingual_help(self):
        app=self.app;app.env=None;app.set_busy(False)
        self.assertEqual(app.update_button.cget('state'),'disabled')
        self.assertEqual(app.refresh_button.cget('state'),'normal')
        self.assertEqual(app.interface.restore_button.cget('state'),'disabled')
        app.set_language('en');app.environment_help()
        content=next(iter(app.locale.documents))
        self.assertIn('Install the Steam edition', content.get('1.0','end'))
        self.assertIn('Not located yet', content.get('1.0','end'))

    def test_no_backup_shows_help_without_task_or_game_changes(self):
        app=self.app;before=self.config.read_bytes()
        app.set_language('en')
        with patch.object(app, 'work') as work:app.restore_luacs()
        work.assert_not_called()
        self.assertEqual(self.config.read_bytes(),before)
        content=next(iter(app.locale.documents))
        self.assertIn('No assistant installation backup',content.get('1.0','end'))
        self.assertIn('Steam Launch Options',content.get('1.0','end'))

    def test_invalid_selected_folder_keeps_previous_choice(self):
        app=self.app;app.settings['game_directory']=str(self.env.game)
        with patch.object(app.files,'askdirectory',return_value=str(self.env.player)), \
             patch.object(app.dialogs,'showinfo') as dialog, patch.object(app,'scan') as scan:
            app.choose_game()
        self.assertEqual(app.settings['game_directory'],str(self.env.game))
        dialog.assert_called_once();scan.assert_not_called()

    def test_preference_write_failure_allows_switch_and_close(self):
        app=self.app
        with patch('mod_assistant.app.atomic_json',side_effect=PermissionError('ACL')):
            app.set_language('en')
        self.assertEqual(app.locale.language,'en');self.assertFalse(app.settings_writable)
        self.assertFalse(app.save_settings())
        root=tk.Toplevel(app.root);root.withdraw()
        with patch('mod_assistant.app.STATE', self.env.player/'blocked-state'):
            (self.env.player/'blocked-state').write_bytes(b'file blocks directory')
            reopened=App(root,auto_scan=False)
        self.assertFalse(reopened.settings_writable)
        reopened.close()

    def test_unchanged_rows_not_rewritten_during_progress(self):
        app=self.app;app.render()
        with patch.object(app.tree,'item',wraps=app.tree.item) as update:
            app.render();self.assertEqual(update.call_count,0)
            app.mods['101']['progress']=50;app.mods['101']['stage']='下载中'
            app.render();self.assertEqual(update.call_count,1)
        app.tree.selection_set('102');app.render()
        self.assertEqual(app.tree.selection(),('102',))

    def test_language_translation_cache_is_bounded_and_changes_language(self):
        localizer=Localizer('en')
        self.assertEqual(localizer.text('游戏目录：'), 'Game folder: ')
        localizer.language='zh';self.assertEqual(localizer.text('游戏目录：'),'游戏目录：')
        for i in range(1500):localizer.text(str(i))
        self.assertLessEqual(len(localizer.translations),1024)

    def test_game_never_launched_reports_next_step_before_network(self):
        app=self.app;app.env=None;self.config.unlink()
        with patch('mod_assistant.app.discover',return_value=self.env), \
             patch('mod_assistant.app.SteamBridge') as bridge, patch.object(app.dialogs,'showerror') as dialog:
            app.scan();app.worker.join(3)
            self.assertFalse(app.worker.is_alive());app.drain()
        bridge.assert_not_called()
        dialog.assert_not_called()
        self.assertFalse(app.config_ready)
        self.assertIn('主菜单',app.logs.get('1.0','end'))
        self.assertTrue(app.mods)
        self.assertEqual(app.update_button.cget('state'),'disabled')

    def test_empty_new_user_inventory_is_successful_offline(self):
        app=self.app;app.env=None
        with patch('mod_assistant.app.discover',return_value=self.env), \
             patch('mod_assistant.app.game_running',return_value=False), \
             patch('mod_assistant.app.inventory',return_value=[]), \
             patch('mod_assistant.app.SteamBridge') as bridge, \
             patch('mod_assistant.app.workshop_details',return_value=({},False)), \
             patch.object(app.dialogs,'showerror') as dialog:
            bridge.return_value.connect.side_effect=AssistantError('Steam unavailable')
            app.scan();app.worker.join(3);self.assertFalse(app.worker.is_alive());app.drain()
        dialog.assert_not_called();self.assertEqual(app.mods,{})
        self.assertFalse(app.online);self.assertIn('空列表',app.logs.get('1.0','end'))

    def test_corrupt_operation_preferences_do_not_break_startup(self):
        path=self.app.settings_file
        path.write_text(json.dumps({'download_slots':None,'install_slots':{},'timeout':'not a number',
                                    'auto_snapshot':{},'light_detection':'false'}))
        root=tk.Toplevel(self.root);root.withdraw();app=App(root,auto_scan=False)
        self.assertEqual((app.download_slots.get(),app.install_slots.get(),app.timeout.get()),(4,3,180))
        self.assertFalse(app.light_detection.get());app.close()

    def test_english_small_window_keeps_list_and_column_control_visible(self):
        app=self.app;app.root.deiconify();app.root.geometry('1000x680')
        app.set_language('en');app.interface.apply({'font_size':12});app.root.update()
        self.assertGreater(app.tree.winfo_height(),180)
        for widget in app.search_entry.master.winfo_children():
            self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),widget.master.winfo_width())
