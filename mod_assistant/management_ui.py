"""Profiles, friend setup and full snapshots in one reviewable management window."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from .core import AssistantError, atomic_json
from .friends import apply_with_downloads
from .profiles import capture_profile, normalize_profile, resolve_profile, save_profile
from .snapshots import SnapshotStore

class ManagementDialog:
    def __init__(self, app):
        self.app=app; self.env=app.env; self.profiles={}; self.snapshots={}
        self.window=tk.Toplevel(app.root); self.window.title('配置、联机与快照')
        self.window.geometry('940x700'); self.window.configure(bg='#0b1422'); self.window.transient(app.root)
        app.label(self.window,'多套配置 · 联机配齐 · 更新前快照',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',padx=18,pady=12)
        app.label(self.window,'先检查清单与差异，再应用。配置只切换启用状态和顺序；快照可恢复保存过的模组文件。',
                  fg='#8fa6bf',wraplength=890).pack(anchor='w',padx=18)
        notebook=ttk.Notebook(self.window); notebook.pack(fill='both',expand=True,padx=18,pady=12)
        profiles=tk.Frame(notebook,bg='#0b1422'); snapshots=tk.Frame(notebook,bg='#0b1422')
        notebook.add(profiles,text='模组配置与联机'); notebook.add(snapshots,text='整套快照')
        self.profile_list=self.listbox(profiles); self.snapshot_list=self.listbox(snapshots)
        self.profile_preview=self.preview(profiles); self.snapshot_preview=self.preview(snapshots)
        self.allow=tk.BooleanVar(value=False)
        tk.Checkbutton(profiles,text='允许使用本机当前版本/文件（有差异时不保证与房主一致）',variable=self.allow,
                       bg='#0b1422',fg='#8fa6bf',selectcolor='#142237',activebackground='#0b1422').pack(anchor='w',pady=5)
        self.buttons(profiles,[('保存当前配置',self.save_current),('导入清单',self.import_file),('导出选中配置',self.export_file),
                              ('检查差异',self.compare),('应用配置',lambda:self.apply(False)),('订阅下载并应用',lambda:self.apply(True))])
        self.buttons(snapshots,[('保存完整快照',self.capture_snapshot),('恢复选中快照',self.restore_snapshot)])
        app.label(snapshots,'快照独立复制文件，会占用磁盘空间。仅能恢复本机已保存的副本，游戏版本变化时会停止恢复。',
                  fg='#8fa6bf',wraplength=880).pack(anchor='w',pady=8)
        self.profile_list.bind('<<ListboxSelect>>',lambda event:self.describe_profile())
        self.snapshot_list.bind('<<ListboxSelect>>',lambda event:self.describe_snapshot())
        self.refresh()

    def listbox(self,parent):
        panel=tk.Frame(parent,bg='#142237'); panel.pack(fill='both',expand=True,pady=8)
        bar=ttk.Scrollbar(panel); bar.pack(side='right',fill='y')
        listing=tk.Listbox(panel,bg='#142237',fg='#e8f0fa',font=('Microsoft YaHei UI',11),height=7,
                           exportselection=False,yscrollcommand=bar.set,selectbackground='#294866')
        listing.pack(fill='both',expand=True); bar.configure(command=listing.yview); return listing

    def preview(self,parent):
        text=tk.Text(parent,height=8,bg='#142237',fg='#8fa6bf',font=('Microsoft YaHei UI',10),wrap='word',relief='flat')
        text.pack(fill='x',pady=6); text.configure(state='disabled'); return text

    def set_preview(self,text,value):
        text.configure(state='normal'); text.delete('1.0','end'); text.insert('1.0',value); text.configure(state='disabled')

    def buttons(self,parent,items):
        frame=tk.Frame(parent,bg='#0b1422'); frame.pack(fill='x',pady=6)
        for title,command in items: self.app.button(frame,title,command,busy=False).pack(side='left',padx=(0,7))

    def busy(self): return bool(self.app.worker and self.app.worker.is_alive())

    def refresh(self):
        if not self.window.winfo_exists(): return
        self.profiles={}
        for path in sorted((self.env.work/'profiles').glob('*.json')):
            try: self.profiles[path.stem]=(path,normalize_profile(json.loads(path.read_text(encoding='utf-8'))))
            except (OSError,ValueError,AssistantError): continue
        self.profile_keys=list(self.profiles); self.profile_list.delete(0,'end')
        for key in self.profile_keys:
            data=self.profiles[key][1]; self.profile_list.insert('end',f"{data.get('name','未命名')} · {len(data['order'])} 个普通模组")
        self.set_preview(self.profile_preview,'选择上方配置查看清单。' if self.profile_keys else '还没有保存配置。点击“保存当前配置”记录你现在启用的组合，或导入朋友的清单。')
        values=SnapshotStore(self.env).list(); self.snapshots={v['id']:v for v in values}
        self.snapshot_keys=list(self.snapshots); self.snapshot_list.delete(0,'end')
        for key in self.snapshot_keys:
            data=self.snapshots[key]; self.snapshot_list.insert('end',f"{key} · {data['name']} · {data['bytes']/1048576:.1f} MB")
        self.set_preview(self.snapshot_preview,'选择上方快照查看恢复范围。' if self.snapshot_keys else '还没有完整快照。点击“保存完整快照”，或开启主窗口“更新前快照”，在下次更新前生成恢复点。')

    def selected_profile(self):
        selected=self.profile_list.curselection()
        if not selected: raise AssistantError('请先选择一套配置')
        return self.profiles[self.profile_keys[selected[0]]][1]

    def selected_snapshot(self):
        selected=self.snapshot_list.curselection()
        if not selected: raise AssistantError('请先选择一份快照')
        return self.snapshots[self.snapshot_keys[selected[0]]]

    def describe_profile(self):
        if not self.profile_list.curselection(): return
        data=self.selected_profile()
        lines=[data.get('name','未命名'),'核心：'+(data['core'].get('name','自定义') if data.get('core') else '原版'),
               '游戏版本：'+data.get('game_version','未记录'),'普通模组将按下列顺序启用，其他普通模组将禁用：']
        lines += [f"{i}. {x.get('name',x['id'])} · {x.get('mod_version','未记录版本')}" for i,x in enumerate(data['order'],1)]
        self.set_preview(self.profile_preview,'\n'.join(lines))

    def describe_snapshot(self):
        if not self.snapshot_list.curselection(): return
        data=self.selected_snapshot()
        self.set_preview(self.snapshot_preview,'\n'.join([data['name'],'游戏版本：'+data['game_version'],
                         f"将恢复 {len(data['records'])} 个模组目录及当时启用状态/顺序；其他游戏设置保留。",
                         '这些目录之后的手动修改将由快照副本替换，恢复前文件会保留在事务备份中。']+
                         [x.get('name',x['id']) for x in data['records']]))

    def save_current(self):
        if self.busy(): return
        name=simpledialog.askstring('保存配置','给这套配置起一个名字：',parent=self.window)
        if not name: return
        def work():
            save_profile(self.env,capture_profile(self.env,name))
            self.app.events.put({'kind':'ui_callback','callback':self.refresh})
            self.app.events.put({'kind':'log','message':'已保存模组配置：'+name})
        self.app.work(work)

    def import_file(self):
        if self.busy(): return
        path=filedialog.askopenfilename(title='选择朋友或自己导出的配置',filetypes=[('模组配置','*.json')],parent=self.window)
        if not path: return
        try:
            if Path(path).stat().st_size>2*1024*1024: raise AssistantError('配置文件过大')
            data=normalize_profile(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            result=save_profile(self.env,data); self.refresh()
            index=self.profile_keys.index(result.stem); self.profile_list.selection_set(index); self.describe_profile()
        except Exception as error: messagebox.showerror('导入失败',str(error),parent=self.window)

    def export_file(self):
        try: data=self.selected_profile()
        except AssistantError as error: messagebox.showinfo('选择配置',str(error),parent=self.window); return
        path=filedialog.asksaveasfilename(title='导出选中配置',defaultextension='.json',initialfile='潜渊症模组配置.json',parent=self.window)
        if path: atomic_json(Path(path),data)

    def compare(self):
        if self.busy(): return
        try: data=self.selected_profile()
        except AssistantError as error: messagebox.showinfo('选择配置',str(error),parent=self.window); return
        def work():
            _,missing,differences=resolve_profile(self.env,data)
            current=capture_profile(self.env)
            lines=['缺少：'+x.get('name',x['id']) for x in missing]+differences
            if [x['id'] for x in current['order']] != [x['id'] for x in data['order']]: lines.append('启用状态或加载顺序不同')
            if current.get('core') != data.get('core'): lines.append('核心内容包或其版本不同')
            text='\n'.join(lines) if lines else '已记录版本、已校验指纹和配置清单一致；未记录指纹的文件及游戏内兼容仍需核实。'
            self.app.events.put({'kind':'text_report','title':'配置差异','text':text})
        self.app.work(work)

    def apply(self,download):
        if self.busy(): return
        try: data=self.selected_profile()
        except AssistantError as error: messagebox.showinfo('选择配置',str(error),parent=self.window); return
        allow=self.allow.get()
        def work():
            result=apply_with_downloads(self.env,data,download,allow,self.app.events.put,self.app.cancel)
            self.app.events.put({'kind':'operation_done','result':result})
        self.window.destroy(); self.app.work(work)

    def capture_snapshot(self):
        if self.busy(): return
        name=simpledialog.askstring('保存快照','快照名称：',initialvalue='游玩验证后的组合',parent=self.window)
        if not name: return
        def work():
            result=SnapshotStore(self.env,lambda message:self.app.events.put({'kind':'scan_status','message':message}),cancel=self.app.cancel).capture(name,reuse=False)
            self.app.events.put({'kind':'ui_callback','callback':self.refresh})
            self.app.events.put({'kind':'log','message':'完整快照已保存：'+result['id']})
        self.app.work(work)

    def restore_snapshot(self):
        if self.busy(): return
        try: data=self.selected_snapshot()
        except AssistantError as error: messagebox.showinfo('选择快照',str(error),parent=self.window); return
        def work():
            result=SnapshotStore(self.env,lambda message:self.app.events.put({'kind':'scan_status','message':message}),cancel=self.app.cancel).restore(data['id'])
            result['message']=f"已恢复 {result['restored']} 个目录及启用顺序；下次启动游戏生效"
            self.app.events.put({'kind':'operation_done','result':result})
        self.window.destroy(); self.app.work(work)
