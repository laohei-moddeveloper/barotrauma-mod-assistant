"""User-facing failures and independent format/permission regressions."""
import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from test_management import Fixture
from test_ui import UiTests
from mod_assistant.core import AssistantError, Cancelled, inventory
from mod_assistant.native_profiles import native_bytes, read_native
from mod_assistant.profiles import apply_profile
from mod_assistant.snapshots import SnapshotStore
from mod_assistant.steam import SteamBridge
from mod_assistant.diagnostics import redact
from mod_assistant.management_ui import ManagementDialog
from mod_assistant.order_ui import OrderDialog
from mod_assistant.xml_compare_ui import XMLCompareDialog


class ReliabilityTests(Fixture):
    def test_native_export_matches_game_reader_fields_and_keeps_core_first(self):
        # Independent traversal of the fields used by ModListPreset.cs, not
        # merely our own import/export round trip.
        root=ET.fromstring(native_bytes(self.profile(['102','101'],core='103')))
        self.assertEqual(root.tag,'mods'); self.assertIn('name',root.attrib)
        self.assertEqual([(x.tag,x.get('id')) for x in root],[('Workshop','103'),('Workshop','102'),('Workshop','101')])
        self.assertTrue(all(x.get('name') for x in root))
        self.assertEqual(ET.fromstring(native_bytes(self.profile([])))[0].tag,'Vanilla')

    def test_native_local_alias_and_blank_primary_name_match_game_name_rules(self):
        folder=self.env.game/'LocalMods/renamed'; folder.mkdir(parents=True)
        (folder/'filelist.xml').write_text('<contentpackage name="  New Name  " altnames="Old Name, Older Name"/>')
        mod=next(m for m in inventory(self.env) if m.source==folder)
        self.assertEqual(mod.name,'New Name'); self.assertEqual(mod.aliases,('Old Name','Older Name'))
        data=read_native(self.env,b'<mods><Vanilla/><Local name="old name"/></mods>')
        apply_profile(self.env,data,process_guard=self.guard)
        self.assertIn(b'LocalMods/renamed',self.config.read_bytes())
        (folder/'filelist.xml').write_text('<contentpackage name=" " altnames="Fallback Name, Other"/>')
        self.assertEqual(next(m for m in inventory(self.env) if m.source==folder).name,'Fallback Name')
        from mod_assistant.profiles import capture_profile
        exported=ET.fromstring(native_bytes(capture_profile(self.env)))
        self.assertEqual(next(node.get('name') for node in exported if node.tag=='Local'),'Fallback Name')

    def test_malformed_ready_manifest_stays_visible_but_is_not_restorable(self):
        snap=self.store.capture(reuse=False); path=self.store.snapshot_folder(snap['id'])/'snapshot.json'
        snap['records']=[17]; path.write_text(json.dumps(snap))
        before=self.config.read_bytes()
        row=self.store.list()[0]; self.assertEqual(row['state'],'failed'); self.assertIn('清单',row['error'])
        with self.assertRaises(AssistantError): self.store.restore(snap['id'])
        self.assertEqual(self.config.read_bytes(),before); self.assertTrue((path.parent/'payload').exists())

    def test_restore_disk_full_preflight_changes_no_live_files(self):
        snap=self.store.capture(reuse=False)
        before=self.config.read_bytes(),(self.env.installed/'101/items.xml').read_bytes()
        with patch('mod_assistant.snapshots.shutil.disk_usage',return_value=Mock(free=0)):
            with self.assertRaisesRegex(AssistantError,'空间不足'): self.store.restore(snap['id'])
        self.assertEqual(before,(self.config.read_bytes(),(self.env.installed/'101/items.xml').read_bytes()))
        self.assertFalse((self.store.root/'transactions').exists())

    def test_rejected_native_interfaces_never_touch_library(self):
        bridge=SteamBridge(self.env); library=Mock(); bridge.dll=library
        for name in ('SteamAPI_ISteamUGC_SubscribeItem','SteamAPI_ISteamUGC_UnsubscribeItem','SteamAPI_ISteamUGC_CreateItem','OpenProcess'):
            with self.assertRaises(AssistantError): bridge.bind(name,None,[])
        self.assertEqual(library.mock_calls,[])

    def test_traceback_escaped_personal_paths_are_redacted(self):
        raw=repr(str(self.env.player/'WorkshopMods/Installed/101'))
        result=redact(raw,self.env)
        self.assertNotIn(str(self.env.player).replace('\\','\\\\'),result)
        self.assertIn('[本机目录]',result)

    def test_snapshot_restore_only_interprets_content_package_regions(self):
        self.config.write_bytes(self.config.read_bytes().replace(b'</config>',b'<unrelated><package path="not-a-mod"/></unrelated></config>'))
        saved=self.store.capture(reuse=False)
        self.configure(['102'])
        self.config.write_bytes(self.config.read_bytes().replace(b'</config>',b'<unrelated><package path="keep-current"/></unrelated></config>'))
        self.store.restore(saved['id'])
        self.assertIn(b'path="keep-current"',self.config.read_bytes())


class ReliabilityUiTests(UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def test_cancel_sort_keeps_window_responsive_and_draft_unchanged(self):
        dialog=OrderDialog(self.app); before=self.config.read_bytes(); draft=list(dialog.ids)
        started=threading.Event()
        def compute(*args):
            started.set(); self.app.cancel.wait(2); raise Cancelled('fixture canceled')
        with patch('mod_assistant.order_ui.suggest_order',side_effect=compute):
            dialog.automatic(); self.assertTrue(started.wait(1))
            self.root.update_idletasks(); self.assertTrue(dialog.computing)
            dialog.cancel_button.invoke(); self.app.worker.join(3); self.app.drain()
        self.assertFalse(dialog.computing); self.assertEqual(dialog.ids,draft)
        self.assertEqual(self.config.read_bytes(),before); self.assertIn('取消',dialog.note.get())
        dialog.window.destroy()

    def test_preview_rejects_configuration_changed_during_computation(self):
        dialog=OrderDialog(self.app); started=threading.Event(); proceed=threading.Event()
        from mod_assistant.mod_order import suggest_order
        def compute(*args): started.set(); proceed.wait(2); return suggest_order(*args)
        with patch('mod_assistant.order_ui.suggest_order',side_effect=compute):
            dialog.automatic(); self.assertTrue(started.wait(1)); self.configure(['102','101'])
            proceed.set(); self.app.worker.join(3); self.app.drain()
        self.assertEqual(dialog.ids,['101','102']); self.assertIn('未应用',dialog.note.get())
        self.assertIn(b'<!-- 102 -->',self.config.read_bytes()); dialog.window.destroy()

    def test_bad_profile_is_visible_with_filename_and_reason(self):
        path=self.env.game/'ModLists/Broken.xml'; path.parent.mkdir(); path.write_text('<mods>')
        dialog=ManagementDialog(self.app)
        self.assertIn('xml:Broken.xml',dialog.profile_keys)
        dialog.profile_list.selection_set(dialog.profile_keys.index('xml:Broken.xml')); dialog.describe_profile()
        self.assertIn(str(path),dialog.profile_preview.get('1.0','end'))
        with self.assertRaises(AssistantError): dialog.selected_profile()
        dialog.window.destroy()

    def test_both_management_tabs_keep_all_six_actions_visible_in_small_english_window(self):
        import tkinter as tk
        from tkinter import ttk
        self.app.set_language('en',persist=False)
        self.app.interface.apply({'font_size':12},persist=False)
        self.root.deiconify(); self.root.update()
        dialog=ManagementDialog(self.app); dialog.window.geometry('850x640')
        notebook=next(child for child in dialog.window.winfo_children() if isinstance(child,ttk.Notebook))
        def descendants(widget):
            for child in widget.winfo_children(): yield child; yield from descendants(child)
        for tab in notebook.tabs():
            notebook.select(tab); self.root.update()
            page=dialog.window.nametowidget(tab)
            listing=dialog.profile_list if tab==notebook.tabs()[0] else dialog.snapshot_list
            self.assertGreaterEqual(listing.winfo_height(),70,'The mod list must remain usable too.')
            buttons=[widget for widget in descendants(page) if isinstance(widget,tk.Button)]
            self.assertEqual(len(buttons),6)
            bottom=dialog.window.winfo_rooty()+dialog.window.winfo_height()
            right=dialog.window.winfo_rootx()+dialog.window.winfo_width()
            for button in buttons:
                self.assertTrue(button.winfo_ismapped(),button.cget('text'))
                self.assertGreaterEqual(button.winfo_height(),button.winfo_reqheight()-2,button.cget('text'))
                self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth()-2,button.cget('text'))
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),bottom)
                self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),right)
        dialog.window.destroy()

    def test_comparison_blocks_selection_changes_until_read_finishes(self):
        from mod_assistant.mod_analysis import inspect
        self.app.features={item:inspect(self.make(item)) for item in ('101','102')}
        dialog=XMLCompareDialog(self.app,'101'); before=self.config.read_bytes()
        from mod_assistant.xml_compare import compare_definition
        start=threading.Event(); proceed=threading.Event()
        def compare(*args): start.set(); proceed.wait(2); return compare_definition(*args)
        with patch('mod_assistant.xml_compare_ui.compare_definition',side_effect=compare):
            dialog.compare(); self.assertTrue(start.wait(1)); self.assertEqual(str(dialog.other.cget('state')),'disabled')
            proceed.set(); self.app.worker.join(3); self.app.drain()
        self.assertEqual(str(dialog.other.cget('state')),'readonly')
        self.assertIn('identifier="shared"',dialog.a.get('1.0','end'))
        self.assertEqual(before,self.config.read_bytes()); dialog.window.destroy()

    def test_sort_reasons_window_accepts_input_and_restores_modal_parent(self):
        dialog=OrderDialog(self.app); dialog.explain()
        report=self.root.grab_current(); self.assertNotEqual(report,dialog.window)
        self.assertEqual(str(report.transient()),str(dialog.window))
        self.root.tk.call(report.protocol('WM_DELETE_WINDOW'))
        self.assertEqual(self.root.grab_current(),dialog.window); dialog.window.destroy()

    def test_per_item_update_errors_are_accessible_in_recent_error_details(self):
        from mod_assistant.operation_errors import describe_error
        report=describe_error(PermissionError('fixture'),'','更新模组')
        self.app.events.put({'kind':'summary','summary':{'completed':[],'errors':{'101':'denied'},'error_details':{'101':report},'seconds':0,'cancelled':False}})
        self.app.drain(); self.assertEqual(self.app.last_error_report['id'],report['id'])

    def test_finished_worker_cannot_start_another_task_before_results_are_processed(self):
        self.app.work(lambda:None); self.app.worker.join(3)
        self.assertTrue(self.app.task_active)
        next_task=Mock(); self.app.work(next_task); next_task.assert_not_called()
        self.assertFalse(self.app.changes_allowed())
        self.app.drain(); self.assertFalse(self.app.task_active)
        self.app.work(next_task); self.app.worker.join(3); self.app.drain(); next_task.assert_called_once()

    def test_missing_workshop_links_only_open_on_click_and_survive_language_change(self):
        import tkinter as tk
        from mod_assistant.i18n import Localizer
        url='https://steamcommunity.com/sharedfiles/filedetails/?id=101'
        with patch('mod_assistant.app.webbrowser.open') as opened:
            report=self.app.text_report('配置差异','缺少：Example\n'+url+'\nhttps://example.com/not-a-workshop-link')
            content=next(child for panel in report.winfo_children() for child in panel.winfo_children() if isinstance(child,tk.Text))
            tags=[tag for tag in content.tag_names() if tag.startswith('workshop-link-')]
            self.assertEqual(len(tags),1); opened.assert_not_called()
            self.app.set_language('en',persist=False)
            self.assertTrue(content.tag_ranges(tags[0]))
            command=content.tk.call(str(content),'tag','bind',tags[0],'<Button-1>')
            callback=command.split('[',1)[1].split()[0]; self.root.tk.call(callback,*(0 for _ in range(19)))
            opened.assert_called_once_with(url)
            report.destroy()
