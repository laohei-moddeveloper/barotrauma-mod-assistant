"""Explicit developer check using disposable fixtures, no Steam or real game."""
import gzip
import hashlib
from pathlib import Path
import struct
import tempfile
import time
import tkinter as tk
from tkinter import messagebox
from dataclasses import replace
from contextlib import contextmanager
from .core import Environment,atomic_json,inventory
from .mod_analysis import inspect
from .mod_order import suggest_order
from .rule_evidence import installed_context
from .save_inspector import read_save,candidates,association_for
from .save_ui import SaveDialog
from .xml_compare_ui import XMLCompareDialog
from .management_ui import ManagementDialog
from .diagnostics import diagnose
from . import VERSION


def run(report_path):
    from . import app as application
    result={'ok':False,'version':VERSION,'fixture_only':True,'Steam_connected':False,'game_launched':False}
    original_state=application.STATE; original_error=messagebox.showerror; errors=[]
    root=None; app=None
    @contextmanager
    def fixture_directory():
        with tempfile.TemporaryDirectory(prefix='BaroDock-evidence-') as temporary:
            try:yield temporary
            finally:
                if app:
                    for handler in list(app.logger.handlers):handler.close();app.logger.removeHandler(handler)
    try:
        with fixture_directory() as temporary:
            base=Path(temporary); env=Environment(base/'Steam',base/'game',[],base/'player')
            vanilla=env.game/'Content/ContentPackages/Vanilla.xml'; vanilla.parent.mkdir(parents=True)
            vanilla.write_text('<contentpackage name="Vanilla" gameversion="1.13.4.0"><Item file="Content/Items/base.xml" /></contentpackage>')
            items=env.game/'Content/Items'; items.mkdir()
            (items/'base.xml').write_text('<Items><Item identifier="shared" health="100"><Price baseprice="100"/></Item></Items>')
            for item,name,health,price in [('101','Condition Demo',300,100),('102','Price Demo',100,200)]:
                folder=env.installed/item; folder.mkdir(parents=True)
                (folder/'filelist.xml').write_text(f'<contentpackage name="{name}" modversion="1"><Item file="%ModDir%/items.xml"/></contentpackage>')
                (folder/'items.xml').write_text(f'<Items><Override><Item identifier="shared" health="{health}"><Price baseprice="{price}"/></Item></Override></Items>')
            config=env.game/'config_player.xml'
            config.write_text('<config><contentpackages><corepackage path="Content/ContentPackages/Vanilla.xml"/><regularpackages><package path="WorkshopMods/Installed/102/filelist.xml"/><package path="WorkshopMods/Installed/101/filelist.xml"/></regularpackages></contentpackages></config>')
            before=hashlib.sha256(config.read_bytes()).hexdigest()
            mods=[replace(mod,source=env.installed/mod.item_id) for mod in inventory(env)]
            application.STATE=base/'assistant-state'; root=tk.Tk(); root.withdraw(); app=application.App(root,auto_scan=False)
            app.env=env; app.config_ready=True
            app.mods={mod.item_id:{'mod':mod,'stage':mod.status,'progress':0,'detail':''} for mod in mods}
            app.features={mod.item_id:inspect(mod) for mod in mods}; app.assessments=app.evaluate_current(); app.render()
            messagebox.showerror=lambda title,message,**kwargs:errors.append(str(message))
            def idle():
                deadline=time.monotonic()+20
                while app.task_active or app.worker and app.worker.is_alive():
                    root.update()
                    if time.monotonic()>deadline: raise RuntimeError('Fixture task timed out')
                    time.sleep(.01)
                root.update()
                if errors: raise RuntimeError(str(errors))
            rules={'before':[['101','102']],'locks':[],'evidence':[{'before':'101','after':'102','method':'manual',
                    'reason':'fixture','game_version':'1.13.4.0','versions':{'101':'1','102':'1'}}]}
            proposed=suggest_order(['102','101'],{mod.item_id:mod for mod in mods},app.features,rules,game_version='1.13.4.0')
            assert proposed.ids==['101','102']
            package=env.installed/'101/filelist.xml'; saved=package.read_bytes(); package.write_bytes(saved.replace(b'modversion="1"',b'modversion="2"'))
            context=installed_context(env,{mod.item_id:mod for mod in mods},rules)
            suspended=suggest_order(['102','101'],context,app.features,rules,game_version='1.13.4.0')
            assert suspended.evidence[0]['status']=='stale'; package.write_bytes(saved)
            result['version_scope_checked']=True
            xml='<GameSession version="1.13.4.0" selectedcontentpackagenames="Vanilla|Condition Demo|Price Demo"/>'.encode()
            name='gamesession.xml'.encode('utf-16-le'); payload=struct.pack('<i',len(name)//2)+name+struct.pack('<i',len(xml))+xml
            save=base/'campaign.save'; save.write_bytes(gzip.compress(payload)); info=read_save(save)
            assert info.digest==hashlib.sha256(save.read_bytes()).hexdigest()
            available,rows=candidates(env,info,mods); manager=ManagementDialog(app)
            dialog=SaveDialog(manager,info,available,rows,[],mods); dialog.preview(); idle()
            assert dialog.draft is not None
            for language in ('en','zh'):
                app.set_language(language,persist=False)
                assert ('Order to review' if language=='en' else '待审核顺序') in dialog.output.get('1.0','end')
                assert 'Condition Demo' in dialog.output.get('1.0','end')
            dialog.save(); native=next((env.game/'ModLists').glob('Save-review-*.xml'))
            assert association_for(env,native.read_bytes())['sha256']==info.digest
            result['native_save_association_checked']=True; manager.window.destroy()
            comparison=XMLCompareDialog(app,'101'); comparison.compare(); idle()
            assert comparison.semantic_result['loading']['winner']=='102'
            assert any(row.get('meaning') for row in comparison.semantic_result['changes'])
            assert 'health' in comparison.semantic.get('1.0','end')
            app.set_language('en',persist=False); assert 'Base price' in comparison.semantic.get('1.0','end')
            result['XML_field_and_registration_check']=True; comparison.window.destroy()
            for mod in mods: (mod.source/'items.xml').write_text('<Items><Item identifier="shared"/></Items>')
            features={mod.item_id:inspect(mod) for mod in mods}
            log=env.game/'crash.log'; log.write_text('Failed to add the prefab "shared" (Barotrauma.ItemPrefab) from "Condition Demo": a prefab with the same identifier from "Price Demo" already exists\n')
            finding=diagnose(log,mods,env,features)['findings'][0]
            assert {'101','102','vanilla'} <= {row['mod_id'] for row in finding['locations'] if row.get('identifier')=='shared'}
            result['logged_error_file_link_checked']=True
            from .investigation import capture_scene,save_scene,read_scene,repair_candidates,compare_logs,compare_scenes
            from .native_profiles import write_native
            baseline_log=diagnose(log,mods,env,features)
            scene=capture_scene(env,mods,name='Frozen fixture',steps='Repeat inventory operation',log=baseline_log)
            assert read_scene(save_scene(env,scene))['name']=='Frozen fixture'
            repair_options=repair_candidates(baseline_log,scene['profile'],features)
            assert len(repair_options)==2
            write_native(env.game/'ModLists/Frozen-repair.xml',repair_options[0]['profile'])
            with log.open('a') as stream:stream.write('Test operation completed\n')
            after_log=diagnose(log,mods,env,features,baseline=baseline_log)
            assert compare_logs(baseline_log,after_log)['not_reproduced']
            after_scene=capture_scene(env,mods,phase='after',log=after_log)
            assert compare_scenes(scene,after_scene)['same_recorded_inputs']
            result['investigation_repair_and_append_recheck']=True
            from .runtime_capture import create_diagnostic,read_runtime_capture,compare_runtime
            folder=create_diagnostic(env,['shared'])
            assert not (folder/'Lua/ForcedAutorun').exists()
            atomic_json(base/'observation.json',{'schema':'barodock-runtime-v1','capture_id':'fixture','captured_unix':1791700000,
                'packages':[{'name':'Vanilla','version':'1','index':0,'manifest':'Content/ContentPackages/Vanilla.xml'}],
                'items':[{'requested':'shared','missing':True}]})
            observed=compare_runtime(env,read_runtime_capture(base/'observation.json'))
            assert len(observed['configured_but_not_observed'])==2
            result['optional_observer_export_import']=True
            assert hashlib.sha256(config.read_bytes()).hexdigest()==before
            result.update(ok=True,configuration_unchanged=True,languages=['en','zh'],frozen=bool(getattr(__import__('sys'),'frozen',False)))
            app.close(); root=None
            for handler in list(app.logger.handlers): handler.close(); app.logger.removeHandler(handler)
    except Exception as error:
        result['error']=repr(error)
        import traceback
        result['traceback']=traceback.format_exc()
    finally:
        if root is not None:
            if app and app.worker and app.worker.is_alive(): app.cancel.set(); app.worker.join(3)
            root.destroy()
        if app:
            for handler in list(app.logger.handlers): handler.close(); app.logger.removeHandler(handler)
        application.STATE=original_state; messagebox.showerror=original_error
        atomic_json(Path(report_path),result)
