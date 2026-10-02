"""A draggable preview of the actual enabled regular-package order."""
import tkinter as tk
from tkinter import messagebox, ttk

from .mod_order import read_order, save_order, suggest_order


class OrderDialog:
    def __init__(self, app):
        self.app = app
        self.ids = read_order(app.env)
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
        self.note = tk.StringVar(value="自动排序考虑资源依赖，保留重复定义的现有覆盖顺序，再建议框架、汉化、补丁、内容分组。请优先遵循作者说明。")
        app.label(self.window, textvariable=self.note, fg="#8fa6bf", wraplength=800,
                  justify="left", height=3, anchor="nw").pack(fill="x", padx=20)
        buttons = tk.Frame(self.window, bg="#0b1422")
        buttons.pack(fill="x", padx=20, pady=(8, 16))
        for title, command in [("自动排序", self.automatic), ("上移", lambda: self.move(-1)),
                               ("下移", lambda: self.move(1)), ("保存加载顺序", self.save)]:
            app.button(buttons, title, command, primary=title.startswith("保存"), busy=False).pack(
                side="left", padx=(0, 10))
        self.render()

    def render(self, selected=None):
        self.list.delete(0, "end")
        for number, item in enumerate(self.ids, 1):
            data = self.app.mods.get(item)
            name = data["mod"].name if data else item
            self.list.insert("end", f"  {number:02d}    {name}")
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
            self.ids.insert(target, self.ids.pop(self.drag_index))
            self.drag_index = target
            self.render(target)

    def move(self, offset):
        selected = self.list.curselection()
        if not selected:
            return
        index = selected[0]
        target = max(0, min(len(self.ids) - 1, index + offset))
        self.ids.insert(target, self.ids.pop(index))
        self.render(target)

    def automatic(self):
        try:
            result = suggest_order(self.ids, {item: data["mod"] for item, data in self.app.mods.items()},
                                   self.app.features)
            self.ids = result.ids
            self.note.set("；".join(result.reasons[:2]) + "。全部依据已记入主窗口日志，可继续拖动调整。")
            for reason in result.reasons:
                self.app.log("排序建议：" + reason)
            self.render()
        except Exception as error:
            messagebox.showerror("无法自动排序", str(error), parent=self.window)

    def save(self):
        ids = list(self.ids)
        def commit():
            backup = save_order(self.app.env, ids)
            self.app.events.put({"kind": "order_saved", "ids": ids, "backup": backup})
        self.window.destroy()
        self.app.work(commit)
