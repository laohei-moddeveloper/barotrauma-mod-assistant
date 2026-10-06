"""A draggable preview of the actual enabled regular-package order."""
import tkinter as tk
import json
import copy
from pathlib import Path
from tkinter import messagebox, ttk

from .mod_order import read_order, suggest_order, load_rules, save_rules, validate_order, check_rules
from .core import atomic_json, AssistantError, Cancelled
from .drafts import commit_draft
from .profiles import installed_path, game_version
from .rule_evidence import SCHEMA, installed_context


class OrderDialog:
    def __init__(self, app):
        self.app = app
        self.baseline = (app.env.game/'config_player.xml').read_bytes()
        self.ids = read_order(app.env)
        if (app.env.game/'config_player.xml').read_bytes() != self.baseline:
            raise AssistantError('游戏配置已经被其他程序修改，请重新检测')
        self.original = list(self.ids)
        self.undo_stack, self.redo_stack = [], []
        self.rules = load_rules(app.env)
        self.last_reasons = []
        self.last_movements=[]; self.last_coverage=[]; self.last_evidence=[]; self.computing=False; self.controls=[]
        self.drag_index = None
        self.window = tk.Toplevel(app.root)
        self.window.title("模组加载顺序")
        self.window.geometry("850x640")
        self.window.minsize(850,560)
        self.window.configure(bg="#0b1422")
        self.window.transient(app.root)
        self.window.grab_set()
        app.label(self.window, "模组配置草稿 · 应用后生效", font=("Microsoft YaHei UI", 17, "bold")).pack(
            anchor="w", padx=20, pady=(16, 7))
        app.label(self.window, "拖动调整顺序；编辑草稿可添加或停用已安装模组，支持撤销和重做。统一应用前游戏配置不变，核心包保持原选择。",
                  fg="#8fa6bf", wraplength=800, justify="left").pack(anchor="w", padx=20)
        panel = tk.Frame(self.window, bg="#142237")
        panel.pack(fill="both", expand=True, padx=20, pady=12)
        scrollbar = ttk.Scrollbar(panel)
        scrollbar.pack(side="right", fill="y")
        self.list = tk.Listbox(panel, bg="#142237", fg="#e8f0fa", selectbackground="#294866",
                               selectforeground="#ffffff", relief="flat", bd=0, activestyle="none",
                               font=("Microsoft YaHei UI", 11), yscrollcommand=scrollbar.set)
        self.list.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.list.yview)
        self.list.bind("<ButtonPress-1>", self.drag_start)
        self.list.bind("<B1-Motion>", self.drag_move)
        self.list.bind("<ButtonRelease-1>", lambda event: setattr(self, "drag_index", None))
        self.note = app.locale.variable(app.root, value='自动排序依据作者声明、前后规则和锁定，保留现有覆盖选择；目录引用不生成顺序。请核对预览后保存。')
        note_label = app.label(self.window, textvariable=self.note, fg="#8fa6bf", wraplength=800,
                               justify="left", height=3, anchor="nw")
        note_label.pack(fill="x", padx=20)
        buttons = tk.Frame(self.window, bg="#0b1422")
        buttons.pack(fill="x", padx=20, pady=(8, 16))
        for index,(title, command) in enumerate([("自动排序（预览）", self.automatic), ("上移", lambda: self.move(-1)),
                               ("下移", lambda: self.move(1)), ("锁定/解锁", self.toggle_lock),
                               ("前后规则", self.edit_rules), ("应用草稿", self.save)]):
            button=app.button(buttons,title,command,primary=title in ('自动排序（预览）','应用草稿'),busy=False)
            button.grid(row=index//3,column=index%3,sticky='ew',padx=(0,8),pady=3); self.controls.append(button)
        for column in range(3): buttons.columnconfigure(column,weight=1)
        extra = tk.Frame(self.window, bg='#0b1422')
        extra.pack(fill='x', padx=20, pady=(0,10))
        for index,(title,command) in enumerate([('查看差异与依据',self.explain),('导入排序规则',self.import_rules),('导出排序规则',self.export_rules)]):
            button=app.button(extra,title,command,busy=False)
            button.grid(row=0,column=index,sticky='ew',padx=(0,8),pady=3); self.controls.append(button)
        for column in range(3): extra.columnconfigure(column,weight=1)
        edit = tk.Menubutton(extra,text='编辑草稿 ▾',relief='flat',padx=12,pady=6)
        menu = tk.Menu(edit,tearoff=False)
        for title,command in [('添加已安装模组',self.add_installed),('停用选中模组',self.remove_selected),
                              ('撤销',lambda:self.history(False)),('重做',lambda:self.history(True)),
                              ('放弃草稿修改',self.reset_draft)]:
            menu.add_command(label=title,command=command)
        edit.configure(menu=menu); edit.grid(row=1,column=0,sticky='ew',padx=(0,8),pady=3); self.controls.append(edit)
        self.cancel_button=app.button(extra,'取消计算',lambda:app.cancel.set(),busy=False)
        self.cancel_button.grid(row=1,column=1,sticky='ew',padx=(0,8),pady=3); self.cancel_button.configure(state='disabled')
        # Reserve actions before assigning the remaining space to the list.
        # Otherwise English at a larger font can push the draft menu offscreen.
        extra.pack_configure(side='bottom',before=panel)
        buttons.pack_configure(side='bottom',before=panel)
        note_label.pack_configure(side='bottom',before=panel)
        self.window.bind('<Control-z>',lambda event:self.history(False))
        self.window.bind('<Control-y>',lambda event:self.history(True))
        def close():
            if self.computing: app.cancel.set()
            self.window.destroy()
        self.window.protocol('WM_DELETE_WINDOW',close)
        self.window._language_refresh = lambda: self.render(self.list.curselection()[0] if self.list.curselection() else None)
        self.render()
        app.skin(self.window)

    def render(self, selected=None):
        self.list.delete(0, "end")
        for number, item in enumerate(self.ids, 1):
            data = self.app.mods.get(item)
            name = data["mod"].name if data else item
            locked = self.app.tr(' [锁定]') if item in self.rules['locks'] else ''
            self.list.insert("end", f"  {number:02d}    {name}{locked}")
        if selected is not None and self.ids:
            self.list.selection_set(selected)
            self.list.activate(selected)
            self.list.see(selected)

    def drag_start(self, event):
        if self.computing: return
        self.drag_index = self.list.nearest(event.y) if self.ids else None

    def drag_move(self, event):
        if self.computing: return
        if self.drag_index is None:
            return
        if event.y < 0:
            self.list.yview_scroll(-1, "units")
        elif event.y >= self.list.winfo_height():
            self.list.yview_scroll(1, "units")
        target = self.list.nearest(event.y)
        if target != self.drag_index:
            if self.try_move(self.drag_index,target): self.drag_index = target

    def move(self, offset):
        selected = self.list.curselection()
        if not selected:
            return
        index = selected[0]
        target = max(0, min(len(self.ids) - 1, index + offset))
        self.try_move(index,target)

    def try_move(self,index,target):
        if self.computing: return False
        candidate=list(self.ids); candidate.insert(target,candidate.pop(index))
        try: self.validate(candidate)
        except Exception as error:
            self.note.set(str(error)); return False
        self.remember(); self.ids=candidate; self.render(target); return True

    def remember(self):
        self.undo_stack.append(list(self.ids)); self.undo_stack=self.undo_stack[-50:]
        self.redo_stack.clear()
        self.last_reasons=[]; self.last_movements=[]; self.last_coverage=[]; self.last_evidence=[]

    def validate(self,ids):
        validate_order(ids,self.original,self.rules,{item:data['mod'] for item,data in self.app.mods.items()},game_version(self.app.env))

    def history(self, redo=False):
        if self.computing: return
        source,target = (self.redo_stack,self.undo_stack) if redo else (self.undo_stack,self.redo_stack)
        if not source:return
        try:self.validate(source[-1])
        except AssistantError as error:self.note.set(str(error));return
        target.append(list(self.ids));self.ids=source.pop();self.render()
        self.last_reasons=[]; self.last_movements=[]; self.last_coverage=[]; self.last_evidence=[]
        self.note.set('草稿已修改；游戏配置尚未改变。')

    def reset_draft(self):
        if self.computing: return
        self.remember();self.ids=list(self.original);self.render()
        self.note.set('已恢复打开窗口时的草稿；游戏配置尚未改变。')

    def remove_selected(self):
        if self.computing: return
        selection=self.list.curselection()
        if not selection:return
        item=self.ids[selection[0]]
        if item in self.rules['locks']:
            self.note.set('此模组已锁定，请先解锁再停用。');return
        candidate=[value for value in self.ids if value!=item]
        try:self.validate(candidate)
        except AssistantError as error:self.note.set(str(error));return
        self.remember();self.ids=candidate;self.render()
        self.note.set('草稿已修改；游戏配置尚未改变。')

    def add_installed(self):
        if self.computing: return
        from .core import load_package
        candidates=[]
        for item,data in self.app.mods.items():
            path=installed_path(self.app.env,data['mod'])
            if item in self.ids or path is None or not (path/'filelist.xml').is_file():continue
            try:
                if load_package(path).get('corepackage','false').casefold()!='true':candidates.append(item)
            except (AssistantError,OSError):continue
        if not candidates:
            self.note.set('没有可添加的已安装普通模组；请先更新缺失模组。');return
        window=tk.Toplevel(self.window);window.title('添加已安装模组');window.geometry('520x160')
        window.transient(self.window);window.grab_set()
        picker=ttk.Combobox(window,values=[self.app.mods[item]['mod'].name+' ['+item+']' for item in candidates],state='readonly',width=50)
        picker.pack(padx=15,pady=20);picker.current(0)
        def add():
            candidate=self.ids+[candidates[picker.current()]]
            try:self.validate(candidate)
            except AssistantError as error:self.note.set(str(error));return
            self.remember();self.ids=candidate;self.render(len(self.ids)-1)
            self.note.set('草稿已修改；游戏配置尚未改变。');close()
        def close():window.destroy();self.window.grab_set()
        self.app.button(window,'添加到草稿',add,busy=False).pack()
        window.protocol('WM_DELETE_WINDOW',close);self.app.skin(window)

    def toggle_lock(self):
        if self.computing: return
        selected=self.list.curselection()
        if not selected: return
        item=self.ids[selected[0]]
        if item in self.rules['locks']: self.rules['locks'].remove(item)
        else:
            if item not in self.original or self.ids.index(item)!=self.original.index(item):
                self.note.set('请先保存调整后的顺序，再锁定当前位置。'); return
            self.rules['locks'].append(item)
        save_rules(self.app.env,self.rules)
        self.render(selected[0]); self.note.set('锁定规则已保存；锁定项在本次排序中保持已保存的位置。')

    def edit_rules(self):
        if self.computing: return
        window=tk.Toplevel(self.window); window.title('自定义前后规则'); window.geometry('740x520')
        window.configure(bg='#0b1422'); window.transient(self.window); window.grab_set()
        rule_ids=list(self.ids)
        names=[f"{self.app.mods[item]['mod'].name} [{item}]" for item in rule_ids]
        pending=[list(pair) for pair in self.rules['before']]
        records={(row['before'],row['after']):copy.deepcopy(row) for row in self.rules.get('evidence',[])}
        self.app.label(window,'选择 A 和 B：A 必须排在 B 前面。相互矛盾的规则会阻止自动排序。',wraplength=700).pack(padx=15,pady=15)
        row=tk.Frame(window,bg='#0b1422'); row.pack(fill='x',padx=15)
        first=ttk.Combobox(row,values=names,state='readonly',width=30); first.pack(side='left')
        self.app.label(row,' 在 ').pack(side='left')
        second=ttk.Combobox(row,values=names,state='readonly',width=30); second.pack(side='left')
        self.app.label(row,' 前').pack(side='left')
        listing=tk.Listbox(window,bg='#142237',fg='#e8f0fa',selectbackground='#294866',font=('Microsoft YaHei UI',10))
        listing.pack(fill='both',expand=True,padx=15,pady=15)
        def refresh():
            listing.delete(0,'end')
            for before,after in pending:
                label=lambda item: self.app.mods[item]['mod'].name if item in self.app.mods else item+self.app.tr('（未启用）')
                listing.insert('end',label(before)+' → '+label(after))
        def add():
            a,b=first.current(),second.current()
            if min(a,b)<0 or a==b: return
            pair=[rule_ids[a],rule_ids[b]]
            if pair not in pending: pending.append(pair); refresh()
        def remove():
            if listing.curselection(): pending.pop(listing.curselection()[0]); refresh()
        def record():
            if not listing.curselection(): return
            pair=pending[listing.curselection()[0]]; a,b=pair
            entry=copy.deepcopy(records.get(tuple(pair),{'before':a,'after':b,'method':'manual'}))
            popup=tk.Toplevel(window); popup.title('记录排序依据'); popup.geometry('680x470'); popup.minsize(620,450); popup.transient(window); popup.grab_set()
            popup.columnconfigure(1,weight=1)
            fields={}
            for index,(label,key) in enumerate([('依据说明','reason'),('来源网址或出处','source'),('记录日期 YYYY-MM-DD','checked_at')]):
                self.app.label(popup,label).grid(row=index,column=0,padx=12,pady=8,sticky='w')
                field=tk.Entry(popup,width=45); field.insert(0,entry.get(key,'')); field.grid(row=index,column=1,padx=12,sticky='ew'); fields[key]=field
            labels=['手工判断','用户记录的作者说明','用户记录的实测']; methods=['manual','author','local_test']
            self.app.label(popup,'依据类型').grid(row=3,column=0,padx=12,pady=8,sticky='w')
            method=ttk.Combobox(popup,state='readonly',values=labels); method.current(methods.index(entry['method'])); method.grid(row=3,column=1,padx=12,sticky='ew')
            scoped=tk.BooleanVar(value=bool(entry.get('game_version') or entry.get('versions')))
            tk.Checkbutton(popup,text='限定为当前游戏与这两个模组的已安装版本',variable=scoped,wraplength=570,justify='left').grid(row=4,column=0,columnspan=2,padx=12,pady=12,sticky='w')
            self.app.label(popup,'记录是用户提供的依据，不是助手认证。版本变化后将停止沿用；版本号相同仍可能有文件变化。',wraplength=570,justify='left').grid(row=5,column=0,columnspan=2,padx=12,pady=8,sticky='w')
            def done():
                current=installed_context(self.app.env,{item:data['mod'] for item,data in self.app.mods.items()},
                                          {'evidence':[{'versions':dict.fromkeys(pair,'current')}]})
                if scoped.get() and (not game_version(self.app.env) or any(not current[item].installed_version for item in pair)):
                    self.app.dialogs.showerror('规则无法应用','游戏或模组版本缺失，不能建立完整版本范围。请取消限定并记录具体来源。',parent=popup); return
                value={**entry,**{key:field.get() for key,field in fields.items()},'method':methods[method.current()],
                       'game_version':game_version(self.app.env) if scoped.get() else '',
                       'versions':{item:current[item].installed_version for item in pair} if scoped.get() else {}}
                try: check_rules({'before':[pair],'evidence':[value]})
                except AssistantError as error: self.app.dialogs.showerror('规则无法应用',str(error),parent=popup); return
                records[tuple(pair)]=value; popup.destroy(); window.grab_set()
            self.app.button(popup,'保存依据',done,busy=False).grid(row=6,column=0,columnspan=2,pady=15)
            popup.protocol('WM_DELETE_WINDOW',lambda:(popup.destroy(),window.grab_set())); self.app.skin(popup)
        def commit():
            try:
                rules={'before':pending,'locks':list(self.rules['locks']),
                       'evidence':[records[tuple(pair)] for pair in pending if tuple(pair) in records]}
                suggest_order(rule_ids,{item:data['mod'] for item,data in self.app.mods.items()},self.app.features,rules,game_version=game_version(self.app.env))
                save_rules(self.app.env,rules); self.rules=rules
                self.last_reasons=[]; self.last_movements=[]; self.last_coverage=[]; self.last_evidence=[]
                self.note.set('前后规则已保存。点击自动排序应用规则；保存顺序后游戏才会使用新顺序。')
                window.destroy(); self.window.grab_set()
            except Exception as error: self.app.dialogs.showerror('规则无法应用',str(error),parent=window)
        buttons=tk.Frame(window,bg='#0b1422'); buttons.pack(fill='x',padx=15,pady=(0,15))
        for index,(title,command) in enumerate([('添加规则',add),('删除选中规则',remove),('记录排序依据',record),('保存规则',commit)]):
            self.app.button(buttons,title,command,busy=False).grid(row=index//2,column=index%2,sticky='ew',padx=(0,10),pady=3)
        for column in range(2): buttons.columnconfigure(column,weight=1)
        def close(): window.destroy(); self.window.grab_set()
        window.protocol('WM_DELETE_WINDOW',close); refresh(); self.app.skin(window)

    def automatic(self):
        if self.computing or self.app.task_active or self.app.worker and self.app.worker.is_alive(): return
        ids=list(self.ids); rules=copy.deepcopy(self.rules)
        mods={item:data['mod'] for item,data in self.app.mods.items()}; features=dict(self.app.features)
        self.computing=True
        for control in self.controls: control.configure(state='disabled')
        self.list.configure(state='disabled'); self.cancel_button.configure(state='normal')
        self.note.set('正在计算排序预览；可以取消，游戏配置尚未改变。')
        def finish(result,error):
            if not self.window.winfo_exists(): return
            self.computing=False
            for control in self.controls: control.configure(state='normal')
            self.list.configure(state='normal'); self.cancel_button.configure(state='disabled')
            if isinstance(error,Cancelled) or self.app.cancel.is_set():
                self.note.set('排序计算已取消，草稿和游戏配置未改动'); return
            if error:
                self.note.set(str(error)); self.app.report_error(error,'生成排序预览'); return
            if ids!=self.ids or rules!=self.rules or (self.app.env.game/'config_player.xml').read_bytes()!=self.baseline:
                self.note.set('计算期间配置或草稿变化，请重新打开预览；本次建议未应用。'); return
            self.remember(); self.ids=result.ids; self.last_reasons=result.reasons; self.last_movements=result.movements
            self.last_coverage=result.coverage; self.last_evidence=result.evidence
            self.note.set(f'已生成预览，{len(result.movements)} 个位置变化。点击“查看差异与依据”核对，游戏配置尚未改变。')
            self.render()
        def compute():
            result=None; error=None
            try:
                version=game_version(self.app.env)
                context=installed_context(self.app.env,mods,rules)
                result=suggest_order(ids,context,features,rules,self.app.cancel,version)
                validate_order(result.ids,self.original,rules,context,version)
            except Exception as caught: error=caught
            finally: self.app.events.put({'kind':'ui_callback','callback':lambda:finish(result,error)})
        self.app.work(compute)

    def explain(self):
        names=lambda ids: '\n'.join(f'{number}. {self.app.mods[item]["mod"].name} [{item}]' for number,item in enumerate(ids,1))
        text='\n\n'.join(['已保存的顺序',names(self.original),'当前预览（尚未保存）',names(self.ids),
                         '位置变化', '\n'.join(f"{self.app.mods[row['id']]['mod'].name} [{row['id']}]  {row['from']} → {row['to']}\n"+'\n'.join(row['reasons']) for row in self.last_movements) or '自动排序没有移动任何模组。',
                         '排序依据', '\n'.join(self.last_reasons) or '尚未生成自动排序建议。',
                         '证据覆盖与未验证项','\n'.join(self.last_coverage) or '尚未生成自动排序建议。',
                         '规则只描述模组之间的顺序，不执行代码；导入和导出均为本地文件，不自动上传。'])
        report=self.app.text_report('排序预览与依据',text)
        report.transient(self.window); report.grab_set()
        def close_report():
            report.destroy()
            if self.window.winfo_exists(): self.window.grab_set()
        report.protocol('WM_DELETE_WINDOW',close_report)

    def import_rules(self):
        if self.computing: return
        path=self.app.files.askopenfilename(title='导入排序规则',filetypes=[('JSON','*.json')],parent=self.window)
        if not path:return
        try:
            if Path(path).stat().st_size>2*1024*1024:raise AssistantError('排序规则文件过大')
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if data.get('schema') not in ('baropy-order-rules-v1',SCHEMA):raise AssistantError('排序规则格式不受支持')
            rules=check_rules(data)
            result=suggest_order(self.original,{item:d['mod'] for item,d in self.app.mods.items()},self.app.features,rules,game_version=game_version(self.app.env))
            detail=f'将替换本地规则：{len(rules["before"])} 条前后规则，{len(rules["locks"])} 个锁定。导入不会修改游戏顺序；请预览后另行保存。'
            if not self.app.dialogs.askyesno('确认导入排序规则',detail,parent=self.window):return
            save_rules(self.app.env,rules)
            self.rules=rules; self.last_reasons=result.reasons
            self.last_coverage=result.coverage; self.last_evidence=result.evidence; self.last_movements=[]
            self.note.set('规则已导入；请查看排序依据，生成预览后再保存顺序。')
            self.render()
        except (OSError,ValueError,TypeError,AttributeError,AssistantError) as error:
            self.app.dialogs.showerror('规则无法应用',str(error),parent=self.window)

    def export_rules(self):
        path=self.app.files.asksaveasfilename(title='导出排序规则',defaultextension='.json',initialfile='BaroDock-order-rules.json',parent=self.window)
        if not path:return
        try:
            atomic_json(Path(path),{'schema':SCHEMA,**check_rules(self.rules)})
        except OSError as error:
            self.app.dialogs.showerror('规则无法应用',str(error),parent=self.window)

    def save(self):
        if self.computing: return
        ids = list(self.ids)
        if not self.app.dialogs.askyesno('应用模组草稿',
                '将保存草稿中的启用列表和加载顺序，并备份原配置。核心内容包保持当前选择。是否应用？',parent=self.window):return
        def commit():
            backup = commit_draft(self.app.env,ids,self.baseline,self.original,[d['mod'] for d in self.app.mods.values()])
            self.app.events.put({"kind": "order_saved", "ids": ids, "backup": backup, 'draft':True})
        self.window.destroy()
        self.app.work(commit)
