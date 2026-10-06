"""Profiles, friend setup and full snapshots in one reviewable management window."""
import json
import re
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from .core import AssistantError, atomic_json, within, reject_link
from .friends import apply_with_downloads
from .profiles import capture_profile, normalize_profile, resolve_profile, save_profile
from .native_profiles import read_native, write_native
from .snapshots import SnapshotStore
from .i18n import Dialogs

class ManagementDialog:
    def __init__(self, app):
        self.prompts=Dialogs(app.locale, simpledialog)
        self.app=app; self.env=app.env; self.profiles={}; self.snapshots={}
        self.window=tk.Toplevel(app.root); self.window.title('配置、联机与快照')
        self.window.geometry('940x700'); self.window.minsize(850,640); self.window.configure(bg='#0b1422'); self.window.transient(app.root)
        app.label(self.window,'多套配置 · 联机配齐 · 更新前快照',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',padx=18,pady=12)
        description=app.label(self.window,'先检查清单与差异，再应用。导入清单也可选择战役存档；快照可恢复保存过的模组文件。',
                  fg='#8fa6bf',wraplength=800,justify='left')
        description.pack(anchor='w',padx=18)
        self.window.bind('<Configure>',lambda event:description.configure(wraplength=max(400,event.width-36))
                         if event.widget is self.window else None,add='+')
        notebook=ttk.Notebook(self.window); notebook.pack(fill='both',expand=True,padx=18,pady=12)
        profiles=tk.Frame(notebook,bg='#0b1422'); snapshots=tk.Frame(notebook,bg='#0b1422')
        notebook.add(profiles,text='模组配置与联机'); notebook.add(snapshots,text='整套快照')
        for page in (profiles,snapshots):
            page.columnconfigure(0,weight=1); page.rowconfigure(0,weight=1,minsize=80)
        self.profile_list=self.listbox(profiles); self.snapshot_list=self.listbox(snapshots)
        self.profile_preview=self.preview(profiles); self.snapshot_preview=self.preview(snapshots)
        self.allow=tk.BooleanVar(value=False)
        tk.Checkbutton(profiles,text='允许使用本机当前版本/文件（有差异时不保证与房主一致）',variable=self.allow,
                       bg='#0b1422',fg='#8fa6bf',selectcolor='#142237',activebackground='#0b1422').grid(row=2,column=0,sticky='w',pady=5)
        self.buttons(profiles,[('保存当前配置',self.save_current),('导入清单',self.import_file),('导出选中配置',self.export_file),
                              ('检查差异',self.compare),('应用配置',lambda:self.apply(False)),('下载并应用',lambda:self.apply(True))],row=3)
        self.buttons(snapshots,[('保存完整快照',self.capture_snapshot),('恢复选中快照',self.restore_snapshot),
                                ('打开选中备份',self.open_snapshot),('复制备份路径',self.copy_snapshot_path),
                                ('选择备份位置',self.choose_backup_root),('打开恢复记录',self.open_transactions)])
        app.label(snapshots,'快照独立复制文件，会占用磁盘空间。仅能恢复本机已保存的副本，游戏版本变化时会停止恢复。',
                  fg='#8fa6bf',wraplength=800).grid(row=3,column=0,sticky='w',pady=8)
        self.profile_list.bind('<<ListboxSelect>>',lambda event:self.describe_profile())
        self.snapshot_list.bind('<<ListboxSelect>>',lambda event:self.describe_snapshot())
        self.window._language_refresh = self.relocalize
        self.refresh()
        app.skin(self.window)

    def listbox(self,parent):
        panel=tk.Frame(parent,bg='#142237'); panel.grid(row=0,column=0,sticky='nsew',pady=8)
        bar=ttk.Scrollbar(panel); bar.pack(side='right',fill='y')
        listing=tk.Listbox(panel,bg='#142237',fg='#e8f0fa',font=('Microsoft YaHei UI',11),height=7,
                           exportselection=False,yscrollcommand=bar.set,selectbackground='#294866')
        listing.pack(fill='both',expand=True); bar.configure(command=listing.yview); return listing

    def preview(self,parent):
        text=tk.Text(parent,height=4,bg='#142237',fg='#8fa6bf',font=('Microsoft YaHei UI',10),wrap='word',relief='flat')
        text.grid(row=1,column=0,sticky='ew',pady=6); text.configure(state='disabled'); return text

    def set_preview(self,text,value):
        text.configure(state='normal'); text.delete('1.0','end'); self.app.locale.bind_text(text,value,[entry['mod'].name for entry in self.app.mods.values()]); text.configure(state='disabled')

    def buttons(self,parent,items,row=2):
        frame=tk.Frame(parent,bg='#0b1422'); frame.grid(row=row,column=0,sticky='ew',pady=6)
        for index,(title,command) in enumerate(items):
            button=self.app.button(frame,title,command,busy=False); button._language_wraplength=220
            button.grid(row=index//3,column=index%3,sticky='ew',padx=(0,7),pady=3)
        for column in range(3): frame.columnconfigure(column,weight=1)

    def busy(self): return bool(self.app.task_active or self.app.worker and self.app.worker.is_alive())

    def relocalize(self):
        profile=self.profile_keys[self.profile_list.curselection()[0]] if self.profile_list.curselection() else None
        snapshot=self.snapshot_keys[self.snapshot_list.curselection()[0]] if self.snapshot_list.curselection() else None
        self.refresh()
        if profile in self.profile_keys:
            self.profile_list.selection_set(self.profile_keys.index(profile)); self.describe_profile()
        if snapshot in self.snapshot_keys:
            self.snapshot_list.selection_set(self.snapshot_keys.index(snapshot)); self.describe_snapshot()

    def refresh(self):
        if not self.window.winfo_exists(): return
        self.profiles={}
        for path in sorted((self.env.work/'profiles').glob('*.json')):
            try:
                reject_link(path)
                if path.stat().st_size>2*1024*1024: raise AssistantError('模组清单文件过大')
                self.profiles[path.stem]=(path,normalize_profile(json.loads(path.read_text(encoding='utf-8'))))
            except (OSError,ValueError,AssistantError) as error:
                self.profiles[path.stem]=(path,{'name':path.stem,'order':[],'error':str(error)})
        for path in sorted((self.env.game/'ModLists').glob('*.xml')):
            try:
                reject_link(path)
                if path.stat().st_size>2*1024*1024: raise AssistantError('模组清单文件过大')
                raw=path.read_bytes(); data=read_native(self.env,raw,[x['mod'] for x in self.app.mods.values()])
                from .save_inspector import association_for
                association=association_for(self.env,raw)
                if association: data['save_reference']=association
                self.profiles['xml:'+path.name]=(path,data)
            except (OSError,ValueError,AssistantError) as error:
                self.profiles['xml:'+path.name]=(path,{'name':path.stem,'order':[],'error':str(error)})
        self.profile_keys=list(self.profiles); self.profile_list.delete(0,'end')
        for key in self.profile_keys:
            path,data=self.profiles[key]; label='游戏清单' if path.suffix.casefold()=='.xml' else '旧 JSON 配置'
            self.profile_list.insert('end',data['name']+' · '+self.app.tr('无法读取，原文件保留') if data.get('error') else self.app.tr(f"{data.get('name','未命名')} · {len(data['order'])} 个普通模组")+' · '+self.app.tr(label))
        self.set_preview(self.profile_preview,'选择上方配置查看清单。' if self.profile_keys else '还没有保存配置。点击“保存当前配置”记录你现在启用的组合，或导入朋友的清单。')
        store=SnapshotStore(self.env); values=store.list(); self.snapshots={v['id']:v for v in values}
        self.snapshot_keys=list(self.snapshots); self.snapshot_list.delete(0,'end')
        for key in self.snapshot_keys:
            data=self.snapshots[key]; state={'ready':'可恢复','capturing':'保存未完成','failed':'失败，副本保留'}[data['state']]
            self.snapshot_list.insert('end',f"{key} · {data['name']} · {data['bytes']/1048576:.1f} MB · "+self.app.tr(state))
        self.set_preview(self.snapshot_preview,'选择上方快照查看恢复范围。' if self.snapshot_keys else '还没有完整快照。点击“保存完整快照”，或开启主窗口“更新前快照”，在下次更新前生成恢复点。')
        if store.list_errors: self.set_preview(self.snapshot_preview,'部分备份位置无法读取：\n'+'\n'.join(store.list_errors))

    def selected_profile(self):
        selected=self.profile_list.curselection()
        if not selected: raise AssistantError('请先选择一套配置')
        data=self.profiles[self.profile_keys[selected[0]]][1]
        if data.get('error'): raise AssistantError('清单无法读取，原文件已保留：'+data['error'])
        return data

    def selected_snapshot(self):
        selected=self.snapshot_list.curselection()
        if not selected: raise AssistantError('请先选择一份快照')
        return self.snapshots[self.snapshot_keys[selected[0]]]

    def describe_profile(self):
        if not self.profile_list.curselection(): return
        path,selected=self.profiles[self.profile_keys[self.profile_list.curselection()[0]]]
        if selected.get('error'):
            self.set_preview(self.profile_preview,'无法读取，原文件保留'+'\n'+str(path)+'\n'+selected['error']); return
        data=self.selected_profile()
        lines=[data.get('name','未命名'),'核心：'+(data['core'].get('name','自定义') if data.get('core') else '原版'),
               '游戏版本：'+data.get('game_version','未记录'),'普通模组将按下列顺序启用，其他普通模组将禁用：']
        lines += [f"{i}. {x.get('name',x['id'])} · {x.get('mod_version','未记录版本')}" for i,x in enumerate(data['order'],1)]
        if 'native_entries' in data: lines.append('游戏清单不记录版本或指纹；缺失项目不会被静默忽略，应用前会检查。')
        if data.get('save_reference'): lines.append('来源存档（名称匹配）：'+data['save_reference']['filename'])
        self.set_preview(self.profile_preview,'\n'.join(lines))

    def describe_snapshot(self):
        if not self.snapshot_list.curselection(): return
        data=self.selected_snapshot()
        if data.get('state')!='ready':
            self.set_preview(self.snapshot_preview,'\n'.join([data['name'],'此备份未完成，不能恢复。已保存的文件仍可在备份文件夹中检查。',data.get('error',''),data['location']]))
            return
        self.set_preview(self.snapshot_preview,'\n'.join([data['name'],'游戏版本：'+data['game_version'],
                         f"将恢复 {len(data['records'])} 个模组目录及当时启用状态/顺序；其他游戏设置保留。",
                         '这些目录之后的手动修改将由快照副本替换，恢复前文件会保留在事务备份中。']+
                         [x.get('name',x['id']) for x in data['records']]+[data['location']]))

    def save_current(self):
        if self.busy(): return
        name=self.prompts.askstring('保存配置','给这套配置起一个名字：',parent=self.window)
        if not name: return
        def work():
            import uuid
            filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name).strip(' .')[:80] or 'ModList'
            write_native(self.env.game/'ModLists'/(filename+'-'+uuid.uuid4().hex[:8]+'.xml'),capture_profile(self.env,name))
            self.app.events.put({'kind':'ui_callback','callback':self.refresh})
            self.app.events.put({'kind':'log','message':'已保存模组配置：'+name})
        self.app.work(work)

    def import_file(self):
        if self.busy(): return
        path=self.app.files.askopenfilename(title='选择模组清单或战役存档',filetypes=[('清单或战役存档','*.xml *.json *.save'),('战役存档','*.save')],parent=self.window)
        if not path: return
        if Path(path).suffix.casefold()=='.save':
            from .save_ui import inspect_selected_save
            inspect_selected_save(self,path); return
        try:
            if Path(path).stat().st_size>2*1024*1024: raise AssistantError('配置文件过大')
            if Path(path).suffix.casefold()=='.xml':
                import uuid
                data=read_native(self.env,Path(path).read_bytes())
                result=write_native(self.env.game/'ModLists'/('Imported-'+uuid.uuid4().hex[:8]+'.xml'),data)
            else:
                data=normalize_profile(json.loads(Path(path).read_text(encoding='utf-8-sig')))
                result=save_profile(self.env,data)
            self.refresh()
            key=next(key for key,value in self.profiles.items() if value[0]==result)
            index=self.profile_keys.index(key); self.profile_list.selection_set(index); self.describe_profile()
        except Exception as error: self.app.report_error(error,'导入模组清单')

    def export_file(self):
        try: data=self.selected_profile()
        except AssistantError as error: self.app.dialogs.showinfo('选择配置',str(error),parent=self.window); return
        path=self.app.files.asksaveasfilename(title='导出选中配置',defaultextension='.xml',initialfile='Barotrauma-ModList.xml',
                                             filetypes=[('游戏清单','*.xml'),('旧 JSON 配置','*.json')],parent=self.window)
        if path:
            if Path(path).suffix.casefold()=='.json': atomic_json(Path(path),data)
            else: write_native(Path(path),data)

    def compare(self):
        if self.busy(): return
        try: data=self.selected_profile()
        except AssistantError as error: self.app.dialogs.showinfo('选择配置',str(error),parent=self.window); return
        def work():
            _,missing,differences=resolve_profile(self.env,data)
            current=capture_profile(self.env)
            lines=[]
            for entry in missing:
                lines.append('缺少：'+entry.get('name',entry['id'])+' ['+entry['id']+']')
                if entry['id'].isdecimal(): lines.append('https://steamcommunity.com/sharedfiles/filedetails/?id='+entry['id'])
            lines+=differences
            if [x['id'] for x in current['order']] != [x['id'] for x in data['order']]: lines.append('启用状态或加载顺序不同')
            if current.get('core') != data.get('core'): lines.append('核心内容包或其版本不同')
            text='\n'.join(lines) if lines else '已记录版本、已校验指纹和配置清单一致；未记录指纹的文件及游戏内兼容仍需核实。'
            self.app.events.put({'kind':'text_report','title':'配置差异','text':text})
        self.app.work(work)

    def apply(self,download):
        if self.busy(): return
        if download and not self.app.confirm_network(): return
        try: data=self.selected_profile()
        except AssistantError as error: self.app.dialogs.showinfo('选择配置',str(error),parent=self.window); return
        allow=self.allow.get()
        def work():
            result=apply_with_downloads(self.env,data,download,allow,self.app.events.put,self.app.cancel)
            self.app.events.put({'kind':'operation_done','result':result})
        self.window.destroy(); self.app.work(work)

    def capture_snapshot(self):
        if self.busy(): return
        name=self.prompts.askstring('保存快照','快照名称：',initialvalue='游玩验证后的组合',parent=self.window)
        if not name: return
        def work():
            result=SnapshotStore(self.env,lambda message:self.app.events.put({'kind':'scan_status','message':message}),cancel=self.app.cancel).capture(name,reuse=False)
            self.app.events.put({'kind':'ui_callback','callback':self.refresh})
            self.app.events.put({'kind':'log','message':'完整快照已保存：'+result['id']})
        self.app.work(work)

    def restore_snapshot(self):
        if self.busy(): return
        try: data=self.selected_snapshot()
        except AssistantError as error: self.app.dialogs.showinfo('选择快照',str(error),parent=self.window); return
        if data.get('state')!='ready':
            self.app.dialogs.showinfo('备份未完成','此备份未完成，不能恢复。已保存的文件仍可在备份文件夹中检查。',parent=self.window); return
        if not self.app.dialogs.askyesno('确认恢复范围',f"将替换 {len(data['records'])} 个模组目录，并恢复启用状态和顺序。恢复前文件会在各目标磁盘保留；其他游戏设置保留。",parent=self.window): return
        def work():
            result=SnapshotStore(self.env,lambda message:self.app.events.put({'kind':'scan_status','message':message}),cancel=self.app.cancel).restore(data['id'])
            result['message']=f"已恢复 {result['restored']} 个目录及启用顺序；下次启动游戏生效"
            self.app.events.put({'kind':'operation_done','result':result})
        self.window.destroy(); self.app.work(work)

    def open_folder(self,path):
        path=Path(path)
        if not path.is_dir(): raise AssistantError('文件夹尚不存在，请先保存备份')
        reject_link(path)
        subprocess.Popen(['explorer.exe',str(path)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def open_snapshot(self):
        try: self.open_folder(self.selected_snapshot()['location'])
        except AssistantError as error: self.app.dialogs.showinfo('备份位置',str(error),parent=self.window)

    def copy_snapshot_path(self):
        try: path=self.selected_snapshot()['location']
        except AssistantError as error: self.app.dialogs.showinfo('备份位置',str(error),parent=self.window); return
        self.window.clipboard_clear(); self.window.clipboard_append(path)

    def open_transactions(self):
        try: self.open_folder(SnapshotStore(self.env).root/'transactions')
        except AssistantError as error: self.app.dialogs.showinfo('恢复记录',str(error),parent=self.window)

    def choose_backup_root(self):
        if self.busy(): return
        path=self.app.files.askdirectory(title='选择备份位置',parent=self.window)
        if not path: return
        selected=Path(path)
        if any(within(selected,root) for root in (self.env.installed,self.env.game/'LocalMods',self.env.player/'LocalMods')):
            self.app.dialogs.showinfo('备份位置','备份不能放在模组目录内，请选择独立文件夹。',parent=self.window); return
        current=SnapshotStore(self.env).root
        if not self.app.dialogs.askyesno('选择备份位置',f'新备份将保存到：{selected}\n旧位置的文件保留在：{current}\n旧备份仍会列在此窗口中，不自动搬移。',parent=self.window): return
        history=list(dict.fromkeys((current,*self.env.snapshot_history)))[:10]
        self.env.snapshot_history=tuple(history); self.app.settings['snapshot_locations']=[str(path) for path in history]
        self.env.snapshot_root=selected; self.app.settings['snapshot_directory']=str(selected)
        self.app.save_settings(); self.refresh()
