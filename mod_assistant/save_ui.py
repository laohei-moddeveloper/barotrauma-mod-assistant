"""Save matching ends in a reviewable preset, not an automatic game change."""
import tkinter as tk
from tkinter import ttk
from .core import AssistantError
from .save_inspector import read_save, candidates, build_profile, profile_matches,save_native_preset


def inspect_selected_save(manager,path=None):
    if manager.busy(): return
    app=manager.app
    path=path or app.files.askopenfilename(title='选择要核对的战役存档',filetypes=[('战役存档','*.save')],parent=manager.window)
    if not path: return
    mods=[entry['mod'] for entry in app.mods.values()]
    profiles=[data for _,data in manager.profiles.values() if 'error' not in data]
    def work():
        try:
            info=read_save(path,app.cancel); available,rows=candidates(manager.env,info,mods)
            matches=profile_matches(info,profiles)
            def show():
                if manager.window.winfo_exists(): SaveDialog(manager,info,available,rows,matches,mods)
            app.events.put({'kind':'ui_callback','callback':show})
        except Exception as error: app.events.put({'kind':'ui_callback','callback':lambda caught=error:app.report_error(caught,'读取战役存档')})
    app.work(work)


class SaveDialog:
    def __init__(self,manager,info,available,rows,matches,mods):
        self.manager=manager; self.app=manager.app; self.info=info; self.available=available; self.rows=rows; self.mods=mods
        self.choices={}; self.draft=None; self.extra=[]
        self.window=tk.Toplevel(manager.window); self.window.title('存档模组核对'); self.window.geometry('850x650'); self.window.minsize(800,580)
        self.window.transient(manager.window); self.window.grab_set()
        self.app.label(self.window,info.filename,font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w',padx=16,pady=10)
        self.app.label(self.window,'选择匹配项目后生成预览，再保存为待审核配置。不会修改存档、订阅或游戏启用列表。',wraplength=800,justify='left').pack(fill='x',padx=16)
        listing_frame=tk.Frame(self.window); listing_frame.pack(fill='both',expand=True,padx=16,pady=8)
        self.list=tk.Listbox(listing_frame,exportselection=False,height=6); self.list.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(listing_frame,command=self.list.yview); bar.pack(side='right',fill='y'); self.list.configure(yscrollcommand=bar.set)
        for index,row in enumerate(rows):
            values=row['candidates']
            label='唯一名称候选' if len(values)==1 else '同名候选，需确认' if values else '本机缺失，无法生成配置'
            self.list.insert('end',f"{index+1}. {row['name']} · {label}")
        self.picker=ttk.Combobox(self.window,state='readonly'); self.picker.pack(fill='x',padx=16)
        self.list.bind('<<ListboxSelect>>',lambda event:self.select())
        self.picker.bind('<<ComboboxSelected>>',lambda event:self.choose())
        self.keep=tk.BooleanVar(value=True)
        tk.Checkbutton(self.window,text='保留当前启用但存档未记录的额外项目，追加到草稿末尾',variable=self.keep,command=self.invalidate,wraplength=750,justify='left').pack(anchor='w',padx=16,pady=8)
        self.output=tk.Text(self.window,wrap='word',height=10,state='disabled'); self.output.pack(fill='both',expand=True,padx=16,pady=8)
        self.matches=matches; self.window._language_refresh=self.render; self.render()
        buttons=tk.Frame(self.window); buttons.pack(fill='x',padx=16,pady=(0,12))
        self.app.button(buttons,'生成待审核预览',self.preview,busy=False).pack(side='left',padx=(0,10))
        self.save_button=self.app.button(buttons,'保存为待审核配置',self.save,busy=False); self.save_button.pack(side='left'); self.save_button.configure(state='disabled')
        self.app.skin(self.window)
        if rows: self.list.selection_set(0); self.select()

    def description(self):
        lines=[self.app.tr(note) for note in self.info.notes]+[self.app.tr('记录游戏版本：')+(self.info.game_version or self.app.tr('未知'))]
        for row in self.matches:
            lines.append(row['name'])
            lines.append(self.app.tr('已记录名称顺序一致，文件和额外项目仍需核对' if row['order_matches'] else '记录名称缺失或顺序不同'))
            for name in row['missing']: lines.append(self.app.tr('缺少：')+name)
            for name in row['extra']: lines.append(self.app.tr('方案额外项：')+name)
        return '\n'.join(lines)

    def render(self):
        if not self.window.winfo_exists(): return
        text=self.description()
        if self.draft is not None:
            text+='\n\n'+self.app.tr('待审核顺序')+'\n'+'\n'.join(f"{index+1}. {entry['name']} [{entry['id']}]" for index,entry in enumerate(self.draft['order']))
            text+='\n'+self.app.tr('当前额外项：')+'、'.join(entry['name'] for entry in self.extra)
            text+='\n'+self.app.tr('核心：')+(self.draft['core']['name'] if self.draft.get('core') else 'Vanilla')
            text+='\n'+self.app.tr('模组版本取自当前本机文件，历史版本未知；应用前请核对原生清单与快照。')
        self.output.configure(state='normal'); self.output.delete('1.0','end')
        self.output.insert('end',text); self.output.configure(state='disabled')

    def select(self):
        if not self.list.curselection(): return
        index=self.list.curselection()[0]; values=self.rows[index]['candidates']
        self.picker.configure(values=[self.available[item]['name']+' ['+item+']' for item in values])
        chosen=self.choices.get(index,values[0] if len(values)==1 else None)
        self.picker.set('')
        if chosen in values: self.picker.current(values.index(chosen))

    def choose(self):
        if not self.list.curselection() or self.picker.current()<0: return
        index=self.list.curselection()[0]; self.choices[index]=self.rows[index]['candidates'][self.picker.current()]; self.invalidate()

    def invalidate(self):
        self.draft=None; self.save_button.configure(state='disabled'); self.render()

    def preview(self):
        if self.manager.busy(): return
        selections=dict(self.choices); keep=self.keep.get()
        def work():
            try:
                draft,extra=build_profile(self.manager.env,self.info,self.available,self.rows,selections,keep,self.mods)
                def show():
                    if not self.window.winfo_exists(): return
                    if selections!=self.choices or keep!=self.keep.get(): return
                    draft['name']=self.info.filename+self.app.tr(' · 待审核')
                    self.draft=draft; self.extra=extra; self.render(); self.save_button.configure(state='normal')
                self.app.events.put({'kind':'ui_callback','callback':show})
            except Exception as error: self.app.events.put({'kind':'ui_callback','callback':lambda caught=error:self.app.report_error(caught,'生成存档配置预览')})
        self.app.work(work)

    def save(self):
        if self.manager.busy() or self.draft is None: return
        try: save_native_preset(self.manager.env,self.draft)
        except Exception as error: self.app.report_error(error,'保存存档关联清单'); self.manager.refresh(); return
        self.manager.refresh(); self.window.destroy()
