"""A draggable preview of the actual enabled regular-package order."""
import tkinter as tk
import json
from pathlib import Path
from tkinter import messagebox, ttk

from .mod_order import read_order, save_order, suggest_order, load_rules, save_rules, validate_order, check_rules
from .core import atomic_json, AssistantError


class OrderDialog:
    def __init__(self, app):
        self.app = app
        self.ids = read_order(app.env)
        self.original = list(self.ids)
        self.rules = load_rules(app.env)
        self.last_reasons = []
        self.drag_index = None
        self.window = tk.Toplevel(app.root)
        self.window.title("模组加载顺序")
        self.window.geometry("850x640")
        self.window.configure(bg="#0b1422")
        self.window.transient(app.root)
        self.window.grab_set()
        app.label(self.window, "已启用模组 · 实际加载顺序", font=("Microsoft YaHei UI", 17, "bold")).pack(
            anchor="w", padx=20, pady=(16, 7))
        app.label(self.window, "拖动一行或用上下移按钮调整。核心内容包固定在最前面；同标识 Override 通常上方优先。保存后重启游戏生效。",
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
        self.note = app.locale.variable(app.root, value="自动排序依据资源依赖和前后规则，保留现有覆盖优先级；不按类型猜顺序。请核对作者说明，再保存。")
        app.label(self.window, textvariable=self.note, fg="#8fa6bf", wraplength=800,
                  justify="left", height=3, anchor="nw").pack(fill="x", padx=20)
        buttons = tk.Frame(self.window, bg="#0b1422")
        buttons.pack(fill="x", padx=20, pady=(8, 16))
        for title, command in [("自动排序", self.automatic), ("上移", lambda: self.move(-1)),
                               ("下移", lambda: self.move(1)), ("锁定/解锁", self.toggle_lock),
                               ("前后规则", self.edit_rules), ("保存加载顺序", self.save)]:
            app.button(buttons, title, command, primary=title.startswith("保存"), busy=False).pack(
                side="left", padx=(0, 10))
        extra = tk.Frame(self.window, bg='#0b1422')
        extra.pack(fill='x', padx=20, pady=(0,10))
        for title,command in [('查看排序依据',self.explain),('导入排序规则',self.import_rules),('导出排序规则',self.export_rules)]:
            app.button(extra,title,command,busy=False).pack(side='left',padx=(0,10))
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
        self.drag_index = self.list.nearest(event.y) if self.ids else None

    def drag_move(self, event):
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
        candidate=list(self.ids); candidate.insert(target,candidate.pop(index))
        try: validate_order(candidate,self.original,self.rules)
        except Exception as error:
            self.note.set(str(error)); return False
        self.ids=candidate; self.render(target); return True

    def toggle_lock(self):
        selected=self.list.curselection()
        if not selected: return
        item=self.ids[selected[0]]
        if item in self.rules['locks']: self.rules['locks'].remove(item)
        else:
            if self.ids.index(item)!=self.original.index(item):
                self.note.set('请先保存调整后的顺序，再锁定当前位置。'); return
            self.rules['locks'].append(item)
        save_rules(self.app.env,self.rules)
        self.render(selected[0]); self.note.set('锁定规则已保存；锁定项在本次排序中保持已保存的位置。')

    def edit_rules(self):
        window=tk.Toplevel(self.window); window.title('自定义前后规则'); window.geometry('740x490')
        window.configure(bg='#0b1422'); window.transient(self.window); window.grab_set()
        names=[f"{self.app.mods[item]['mod'].name} [{item}]" for item in self.original]
        pending=[list(pair) for pair in self.rules['before']]
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
            pair=[self.original[a],self.original[b]]
            if pair not in pending: pending.append(pair); refresh()
        def remove():
            if listing.curselection(): pending.pop(listing.curselection()[0]); refresh()
        def commit():
            try:
                rules={'before':pending,'locks':list(self.rules['locks'])}
                suggest_order(self.original,{item:data['mod'] for item,data in self.app.mods.items()},self.app.features,rules)
                save_rules(self.app.env,rules); self.rules=rules
                self.note.set('前后规则已保存。点击自动排序应用规则；保存顺序后游戏才会使用新顺序。')
                window.destroy(); self.window.grab_set()
            except Exception as error: self.app.dialogs.showerror('规则无法应用',str(error),parent=window)
        buttons=tk.Frame(window,bg='#0b1422'); buttons.pack(fill='x',padx=15,pady=(0,15))
        for title,command in [('添加规则',add),('删除选中规则',remove),('保存规则',commit)]:
            self.app.button(buttons,title,command,busy=False).pack(side='left',padx=(0,10))
        def close(): window.destroy(); self.window.grab_set()
        window.protocol('WM_DELETE_WINDOW',close); refresh(); self.app.skin(window)

    def automatic(self):
        try:
            # Locks refer to the saved configuration; starting from it prevents
            # an unsaved preview from moving a locked package indirectly.
            baseline=self.original if self.rules['locks'] else self.ids
            result = suggest_order(baseline, {item: data["mod"] for item, data in self.app.mods.items()},
                                   self.app.features,self.rules)
            validate_order(result.ids,self.original,self.rules)
            self.ids = result.ids
            self.last_reasons = result.reasons
            self.note.set("；".join(result.reasons[:2]) + "。全部依据已记入主窗口日志，可继续拖动调整。")
            for reason in result.reasons:
                self.app.log("排序建议：" + reason)
            self.render()
        except Exception as error:
            self.app.dialogs.showerror("无法自动排序", str(error), parent=self.window)

    def explain(self):
        names=lambda ids: '\n'.join(f'{number}. {self.app.mods[item]["mod"].name} [{item}]' for number,item in enumerate(ids,1))
        text='\n\n'.join(['已保存的顺序',names(self.original),'当前预览（尚未保存）',names(self.ids),
                         '排序依据', '\n'.join(self.last_reasons) or '尚未生成自动排序建议。',
                         '规则只描述模组之间的顺序，不执行代码；导入和导出均为本地文件，不自动上传。'])
        self.app.text_report('排序预览与依据',text)

    def import_rules(self):
        path=self.app.files.askopenfilename(title='导入排序规则',filetypes=[('JSON','*.json')],parent=self.window)
        if not path:return
        try:
            if Path(path).stat().st_size>256*1024:raise AssistantError('排序规则文件过大')
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if data.get('schema')!='baropy-order-rules-v1':raise AssistantError('排序规则格式不受支持')
            rules=check_rules(data)
            result=suggest_order(self.original,{item:d['mod'] for item,d in self.app.mods.items()},self.app.features,rules)
            detail=f'将替换本地规则：{len(rules["before"])} 条前后规则，{len(rules["locks"])} 个锁定。导入不会修改游戏顺序；请预览后另行保存。'
            if not self.app.dialogs.askyesno('确认导入排序规则',detail,parent=self.window):return
            save_rules(self.app.env,rules)
            self.rules=rules; self.last_reasons=result.reasons
            self.note.set('规则已导入；请查看排序依据，生成预览后再保存顺序。')
            self.render()
        except (OSError,ValueError,TypeError,AttributeError,AssistantError) as error:
            self.app.dialogs.showerror('规则无法应用',str(error),parent=self.window)

    def export_rules(self):
        path=self.app.files.asksaveasfilename(title='导出排序规则',defaultextension='.json',initialfile='BaroPy-order-rules.json',parent=self.window)
        if not path:return
        try:
            atomic_json(Path(path),{'schema':'baropy-order-rules-v1',**check_rules(self.rules)})
        except OSError as error:
            self.app.dialogs.showerror('规则无法应用',str(error),parent=self.window)

    def save(self):
        ids = list(self.ids)
        def commit():
            backup = save_order(self.app.env, ids)
            self.app.events.put({"kind": "order_saved", "ids": ids, "backup": backup})
        self.window.destroy()
        self.app.work(commit)
