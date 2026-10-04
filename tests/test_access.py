"""Security regressions: explicit network access and game-only file probes."""
import ctypes
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from mod_assistant.core import AssistantError, Environment, executable_in_use, game_running
from mod_assistant.steam import SteamBridge
from mod_assistant.access import access_report
from mod_assistant.friends import verify_workshop_items, apply_with_downloads
from test_management import Fixture
from test_ui import UiTests
from mod_assistant.order_ui import OrderDialog
from mod_assistant.mod_order import load_rules
from mod_assistant.mod_analysis import _resource_path
from mod_assistant.core import mod_files

class FileProbeTests(Fixture):
    def test_probe_targets_only_selected_game_files(self):
        for name in ('Barotrauma.exe','DedicatedServer.exe'):(self.env.game/name).write_bytes(b'fixture')
        with patch('mod_assistant.core.executable_in_use',return_value=False) as probe:
            self.assertFalse(game_running(self.env))
            self.assertEqual([call.args[0] for call in probe.call_args_list],
                             [self.env.game.resolve()/name for name in ('Barotrauma.exe','DedicatedServer.exe')])
        with patch('mod_assistant.core.executable_in_use',return_value=True):
            self.assertTrue(game_running(self.env))
        with patch('mod_assistant.core.executable_in_use',side_effect=AssistantError('unknown')):
            with self.assertRaises(AssistantError):game_running(self.env)

    @unittest.skipUnless(os.name=='nt','Windows loader file sharing')
    def test_native_running_executable_and_unloaded_file_without_modification(self):
        path=self.env.game/'unused.exe';path.write_bytes(b'unloaded executable fixture')
        before=path.read_bytes(),path.stat().st_mtime_ns
        self.assertFalse(executable_in_use(path))
        self.assertTrue(executable_in_use(Path(sys.executable)))
        self.assertEqual(before,(path.read_bytes(),path.stat().st_mtime_ns))

    def test_unsubscribed_profile_never_downloads_or_changes_config(self):
        before=self.config.read_bytes()
        class Bridge:
            def __init__(self,env):pass
            def connect(self):return self
            def close(self):pass
            def state(self,item):return 0
        with patch('mod_assistant.friends.UpdateEngine') as engine:
            with self.assertRaisesRegex(AssistantError,'手动订阅'):
                apply_with_downloads(self.env,self.profile(['999']),True,process_guard=self.guard,
                                     bridge_factory=Bridge,engine_factory=engine,verify_items=lambda ids:None)
            engine.assert_not_called()
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.store.list(),[])

    def test_runtime_has_no_subscription_operation(self):
        self.assertFalse(hasattr(SteamBridge,'subscribe'))
        names=[]
        bridge=SteamBridge(self.env)
        def binding(name,result,args):
            names.append(name)
            if name=='SteamAPI_InitFlat':return lambda *_:0
            if name=='SteamAPI_ISteamUtils_GetAppID':return lambda *_:602960
            return lambda *_:1
        with patch('mod_assistant.steam.C.CDLL'),patch.object(bridge,'bind',side_effect=binding):
            bridge.connect();bridge.close()
        self.assertFalse(any('SubscribeItem' in name or 'UnsubscribeItem' in name for name in names))

    def test_imported_ids_must_belong_to_barotrauma(self):
        response={'response':{'publishedfiledetails':[{'publishedfileid':'101','result':1,'consumer_app_id':123}]}}
        with patch('mod_assistant.friends.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaises(AssistantError):verify_workshop_items(['101'])

    def test_access_explanation_is_bilingual(self):
        report=access_report(language='en')
        self.assertIn('not an OS sandbox',report)
        self.assertIn('No process enumeration',report)
        self.assertFalse(any('\u4e00'<=char<='\u9fff' for char in report))

    def test_mod_traversal_rejects_links_before_reading_resources(self):
        folder=self.env.installed/'101'
        target=folder/'real';target.mkdir();(target/'items.xml').write_text('<items/>')
        linked=folder/'linked'
        if os.name=='nt':
            import _winapi
            _winapi.CreateJunction(str(target),str(linked))
        else: linked.symlink_to(target,target_is_directory=True)
        try:
            with self.assertRaises(AssistantError):list(mod_files(folder))
            with self.assertRaises(AssistantError):_resource_path(folder,'%ModDir%/linked/items.xml','Base')
        finally:
            # Remove only the link itself; never recurse through the target.
            if os.name=='nt': linked.rmdir()
            else: linked.unlink()

class LocalScanTests(UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def test_default_scan_does_not_connect_sdk_or_request_public_metadata(self):
        with patch('mod_assistant.app.discover',return_value=self.env), \
             patch('mod_assistant.app.game_running',return_value=False), \
             patch('mod_assistant.app.SteamBridge') as bridge, \
             patch('urllib.request.urlopen') as http, \
             patch.object(self.app,'work',side_effect=lambda fn:fn()):
            self.app.scan()
            bridge.assert_not_called();http.assert_not_called()

    def test_declining_online_action_leaves_worker_idle(self):
        self.app.selected={'101'}
        with patch.object(self.app.dialogs,'askyesno',return_value=False),patch.object(self.app,'work') as work:
            self.app.start_update(True);self.app.online_scan();self.app.install_luacs()
            work.assert_not_called()

    def test_import_rules_requires_confirmation_and_never_changes_game_order(self):
        dialog=OrderDialog(self.app)
        path=self.env.work/'import.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'schema':'baropy-order-rules-v1','before':[['101','102']],'locks':[]}))
        before=self.config.read_bytes()
        with patch.object(self.app.files,'askopenfilename',return_value=str(path)),patch.object(self.app.dialogs,'askyesno',return_value=False):
            dialog.import_rules()
        self.assertEqual(load_rules(self.env),{'before':[],'locks':[]})
        with patch.object(self.app.files,'askopenfilename',return_value=str(path)),patch.object(self.app.dialogs,'askyesno',return_value=True):
            dialog.import_rules()
        self.assertEqual(load_rules(self.env)['before'],[['101','102']])
        self.assertEqual(self.config.read_bytes(),before)
        exported=self.env.work/'export.json'
        with patch.object(self.app.files,'asksaveasfilename',return_value=str(exported)):dialog.export_rules()
        self.assertEqual(json.loads(exported.read_text())['before'],[['101','102']])

    def test_bad_or_cyclic_rule_import_preserves_rules_and_configuration(self):
        dialog=OrderDialog(self.app)
        path=self.env.work/'invalid.json';path.parent.mkdir(parents=True,exist_ok=True)
        before=self.config.read_bytes()
        values=[[],{'schema':'unknown'}, {'schema':'baropy-order-rules-v1','before':[['101','102'],['102','101']]}]
        for data in values:
            path.write_text(json.dumps(data))
            with patch.object(self.app.files,'askopenfilename',return_value=str(path)),patch.object(self.app.dialogs,'showerror') as error,patch.object(self.app.dialogs,'askyesno') as confirm:
                dialog.import_rules();error.assert_called_once();confirm.assert_not_called()
            self.assertEqual(load_rules(self.env),{'before':[],'locks':[]})
            self.assertEqual(self.config.read_bytes(),before)
