from __future__ import annotations

from dataclasses import asdict, replace
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback
import webbrowser

from . import VERSION
from .core import AssistantError, Installer, Mod, atomic_json, discover, inventory, load_package
from .engine import UpdateEngine
from .mod_analysis import evaluate, inspect, inspect_all, luacs_runtime_detected, workshop_details
from .mod_toggle import enabled_ids, set_enabled
from .steam import BUSY, DOWNLOADING, NEEDS_UPDATE, PENDING, SteamBridge

STATE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BarotraumaModAssistant"
BG, PANEL, TEXT, MUTED, ACCENT = "#0b1422", "#142237", "#e8f0fa", "#8fa6bf", "#57dac4"


class App:
    def __init__(self, root, auto_scan=True):
        self.root = root
        self.root.title(f"潜渊症 · 模组更新助手 {VERSION}")
        self.root.geometry("1420x820")
        self.root.minsize(1000, 700)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.callback_error
        self.events = queue.Queue()
        self.worker = None
        self.engine = None
        self.cancel = threading.Event()
        self.mods = {}
        self.features = {}
        self.assessments = {}
        self.metadata = {}
        self.online = False
        self.runtime_luacs = None
        self.selected = set()
        self.env = None
        self.stage_log = {}
        self.last_summary = None
        STATE.mkdir(parents=True, exist_ok=True)
        self.settings_file = STATE / "settings.json"
        try:
            self.settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}
        self.logger = logging.getLogger("mod_assistant")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = RotatingFileHandler(STATE / "assistant.log", maxBytes=2_000_000,
                                           backupCount=3, encoding="utf-8")
            self.logger.addHandler(handler)
        self.status = tk.StringVar(value="正在准备本机检测…")
        self.summary = tk.StringVar(value="选择模组，然后开始并行更新")
        self.download_slots = tk.IntVar(value=self.settings.get("download_slots", 4))
        self.install_slots = tk.IntVar(value=self.settings.get("install_slots", 3))
        self.timeout = tk.IntVar(value=self.settings.get("timeout", 180))
        self.search = tk.StringVar()
        self.busy_buttons = []
        self.make_style()
        self.build()
        self.root.after(80, self.drain)
        if auto_scan:
            self.root.after(120, self.scan)

    def make_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=30, borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", background="#1c304a", foreground=MUTED,
                        padding=(8, 6), font=("Microsoft YaHei UI", 10))
        style.map("Treeview", background=[("selected", "#294866")],
                  foreground=[("selected", "#ffffff")])
        style.map("Treeview.Heading", background=[("active", "#294866")])
        style.configure("TScrollbar", background="#29405b", troughcolor=BG, borderwidth=0)
        style.configure("TProgressbar", background=ACCENT, troughcolor=PANEL, borderwidth=0)

    def label(self, parent, text="", **options):
        return tk.Label(parent, text=text, bg=options.pop("bg", BG),
                        fg=options.pop("fg", TEXT), font=options.pop("font", ("Microsoft YaHei UI", 10)), **options)

    def button(self, parent, text, command, primary=False, busy=True):
        button = tk.Button(parent, text=text, command=command, bg=ACCENT if primary else "#20354e",
                           fg=BG if primary else TEXT, activebackground="#78e8d5" if primary else "#2e4c6b",
                           activeforeground=BG if primary else TEXT, relief="flat", bd=0,
                           padx=12, pady=6, cursor="hand2", font=("Microsoft YaHei UI", 10),
                           disabledforeground="#627890")
        if busy:
            self.busy_buttons.append(button)
        return button

    def build(self):
        header = tk.Frame(self.root, bg=BG, padx=26, pady=9)
        header.pack(fill="x")
        self.label(header, "潜渊症  /  模组更新助手", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        self.label(header, textvariable=self.status, fg=ACCENT).pack(anchor="w", pady=(5, 0))

        toolbar = tk.Frame(self.root, bg=BG, padx=26)
        toolbar.pack(fill="x")
        for text, command, primary in [
            ("开始并行更新", lambda: self.start_update(True), True),
            ("仅同步本地缓存", lambda: self.start_update(False), False),
            ("重新检测", self.scan, False),
            ("启用/禁用选中模组", self.toggle_selected, False),
            ("启动游戏", self.launch, False),
        ]:
            self.button(toolbar, text, command, primary).pack(side="left", padx=(0, 10))
        self.stop_button = self.button(toolbar, "停止助手任务", self.stop, busy=False)
        self.stop_button.pack(side="right")
        self.stop_button.configure(state="disabled")

        settings = tk.Frame(self.root, bg=BG, padx=26, pady=6)
        settings.pack(fill="x")
        for title, variable, low, high in [("同时更新", self.download_slots, 1, 12),
                                           ("同时安装", self.install_slots, 1, 6),
                                           ("无进度超时（秒）", self.timeout, 30, 900)]:
            self.label(settings, title, fg=MUTED).pack(side="left", padx=(0, 7))
            spin = tk.Spinbox(settings, from_=low, to=high, textvariable=variable, width=5,
                             bg=PANEL, fg=TEXT, buttonbackground="#29405b", relief="flat",
                             insertbackground=TEXT, font=("Microsoft YaHei UI", 10))
            spin.pack(side="left", padx=(0, 20))
            self.busy_buttons.append(spin)
        self.button(settings, "选择游戏目录", self.choose_game).pack(side="right")

        self.label(self.root, "Steam 负责实际网络调度；停止助手不会强制取消 Steam 已提交的下载。",
                   fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="bottom", anchor="w", padx=26, pady=(4, 6))

        container = tk.Frame(self.root, bg=BG, padx=26)
        container.pack(fill="both", expand=True)
        controls = tk.Frame(container, bg=BG)
        controls.pack(fill="x", pady=(0, 5))
        for text, command in [("全选", self.select_all), ("只选已启用", self.select_enabled),
                              ("清空选择", self.select_none)]:
            self.button(controls, text, command).pack(side="left", padx=(0, 7))
        self.label(controls, "搜索", fg=MUTED).pack(side="left", padx=(14, 7))
        search = tk.Entry(controls, textvariable=self.search, bg=PANEL, fg=TEXT, relief="flat",
                          insertbackground=TEXT, font=("Microsoft YaHei UI", 10), width=27)
        search.pack(side="left", ipady=7)
        self.search.trace_add("write", lambda *_: self.render())
        self.label(controls, textvariable=self.summary, fg=MUTED).pack(side="right")

        table = tk.Frame(container, bg=PANEL)
        columns = ("check", "enable", "name", "kind", "importance", "compat",
                   "version", "installed", "size", "stage", "progress")
        self.tree = ttk.Treeview(table, columns=columns, show="headings",
                                 selectmode="extended", height=3)
        titles = ("更新", "启用", "模组", "类型", "重要程度", "兼容性", "缓存版本", "已安装版本", "大小", "状态", "进度")
        widths = (48, 64, 280, 175, 86, 120, 90, 96, 72, 160, 66)
        for name, title, width in zip(columns, titles, widths):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=width if name != "name" else 200,
                             stretch=name in ("name", "stage"),
                             anchor="w" if name in ("name", "kind", "stage") else "center")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("complete", foreground=ACCENT)
        self.tree.tag_configure("failed", foreground="#ff9f9f")
        self.tree.tag_configure("active", foreground="#8eceff")
        self.tree.tag_configure("warning", foreground="#f1c67b")
        self.tree.bind("<Button-1>", self.click_checkbox)
        self.tree.bind("<space>", self.toggle_highlight)
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)

        details = tk.Frame(container, bg=BG, pady=5)
        self.detail = tk.StringVar(value="更新勾选与启用开关分开；选中一行查看类型依据和兼容原因。")
        self.detail_label = self.label(details, textvariable=self.detail, fg=MUTED,
                                       anchor="nw", justify="left", wraplength=1080, height=2)
        self.detail_label.pack(fill="x")
        actions = tk.Frame(container, bg=BG)
        for text, command in [("重试失败项", self.retry_failed), ("恢复选中模组上一版", self.restore),
                              ("查看完整分析", self.show_full_analysis),
                              ("导出兼容分析", self.export_analysis),
                              ("导出联机清单", self.export_profile), ("对比联机清单", self.compare_profile),
                              ("导出更新报告", self.export_report)]:
            self.button(actions, text, command).pack(side="left", padx=(0, 8))

        self.logs = tk.Text(container, height=2, bg="#0e1b2d", fg=MUTED, relief="flat", bd=0,
                            padx=12, pady=5, font=("Microsoft YaHei UI", 9), state="disabled", wrap="word")
        self.logs.pack(side="bottom", fill="x")
        actions.pack(side="bottom", fill="x", pady=(0, 5))
        details.pack(side="bottom", fill="x")
        table.pack(side="top", fill="both", expand=True)

    def log(self, message):
        self.logger.info(message)
        self.logs.configure(state="normal")
        self.logs.insert("end", time.strftime("%H:%M:%S") + "  " + message + "\n")
        if int(self.logs.index("end-1c").split(".")[0]) > 250:
            self.logs.delete("1.0", "50.0")
        self.logs.see("end")
        self.logs.configure(state="disabled")

    def callback_error(self, error_type, error, trace):
        self.logger.error("界面操作失败", exc_info=(error_type, error, trace))
        messagebox.showerror("操作未完成", str(error), parent=self.root)

    def verified_fingerprint(self, item):
        receipt = self.env.work / "receipts" / (item + ".json")
        if not receipt.is_file():
            return ""
        data = json.loads(receipt.read_text(encoding="utf-8"))
        if data.get("manifest") != self.env.token(item):
            return ""
        return data.get("fingerprint", "")

    def set_busy(self, busy):
        for button in self.busy_buttons:
            button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def work(self, function):
        if self.worker is not None and self.worker.is_alive():
            return
        self.cancel.clear()
        self.set_busy(True)

        def run():
            try:
                function()
            except Exception as error:
                self.logger.error("%s\n%s", error, traceback.format_exc())
                self.events.put({"kind": "error", "message": str(error)})
            finally:
                self.events.put({"kind": "idle"})

        self.worker = threading.Thread(target=run, name="AssistantWorker", daemon=False)
        self.worker.start()

    def scan(self):
        self.status.set("正在检测游戏目录、模组缓存与 Steam 状态…")

        def detect():
            env = discover(self.settings.get("game_directory", ""))
            mods = inventory(env)
            online = False
            bridge = None
            try:
                bridge = SteamBridge(env).connect()
                bridge.pump()
                subscribed = bridge.subscribed()
                known = {mod.item_id for mod in mods}
                for item in subscribed:
                    if item not in known:
                        mods.append(Mod(item, f"尚未下载的订阅模组 {item}", env.cache(item), status="等待 Steam 下载"))
                for mod in mods:
                    if not mod.item_id.isdecimal():
                        continue
                    state = bridge.state(mod.item_id)
                    if state & DOWNLOADING:
                        mod.status = "Steam 正在下载"
                    elif state & PENDING:
                        mod.status = "Steam 等待下载"
                    elif state & NEEDS_UPDATE:
                        mod.status = "Steam 缓存待更新"
                    elif bridge.ready(mod.item_id) and mod.status == "已安装 / 待联网核对":
                        mod.status = "版本已同步"
                online = True
            except Exception as error:
                self.events.put({"kind": "log", "message": "本地检测完成；" + str(error)})
            finally:
                if bridge:
                    bridge.close()
            metadata, metadata_available = workshop_details(env, [mod.item_id for mod in mods])
            features = inspect_all(mods, metadata)
            runtime_luacs = luacs_runtime_detected(env)
            assessments = evaluate(mods, features, runtime_luacs)
            self.events.put({"kind": "inventory", "env": env, "mods": mods, "online": online,
                             "metadata": metadata, "features": features,
                             "assessments": assessments, "runtime_luacs": runtime_luacs,
                             "metadata_available": metadata_available})

        self.work(detect)

    def render(self):
        highlighted = self.tree.selection()
        existing = set(self.tree.get_children())
        search = self.search.get().casefold()
        for item, data in self.mods.items():
            mod = data["mod"]
            assessment = self.assessments.get(item)
            if search and search not in (mod.name + " " + item).casefold():
                if item in existing:
                    self.tree.delete(item)
                continue
            type_labels = assessment.kinds if assessment else ()
            shown_type = "、".join(type_labels[:2]) + (f" +{len(type_labels) - 2}" if len(type_labels) > 2 else "")
            values = ("✓" if item in self.selected else "", "已启用" if mod.enabled else "关闭",
                      mod.name, shown_type or "待分析",
                      assessment.importance if assessment else "待分析",
                      assessment.compatibility if assessment else "待分析",
                      mod.mod_version or "—", mod.installed_version or "未安装",
                      f"{mod.size / 1048576:.1f} MB" if mod.size else "—", data["stage"],
                      f'{data["progress"]:.0f}%' if data["progress"] else "—")
            stage = data["stage"]
            tag = "complete" if stage in ("已完成", "版本已同步") else (
                "failed" if stage in ("失败", "等待超时") or stage.startswith("需要检查") else
                "active" if stage in ("下载中", "安装准备", "校验缓存") else
                "warning" if assessment and assessment.compatibility.startswith(("低", "中")) else "")
            if self.tree.exists(item):
                self.tree.item(item, values=values, tags=(tag,))
            else:
                self.tree.insert("", "end", iid=item, values=values, tags=(tag,))
        self.tree.selection_set([i for i in highlighted if self.tree.exists(i)])
        self.summary.set(f"{len(self.mods)} 个模组 · 启用 {sum(x['mod'].enabled for x in self.mods.values())} 个 · 已选更新 {len(self.selected)} 个")

    def click_checkbox(self, event):
        item = self.tree.identify_row(event.y)
        if item and self.tree.identify_column(event.x) == "#2":
            if not (self.worker and self.worker.is_alive()):
                self.toggle_item(item)
            return "break"
        if item and self.tree.identify_column(event.x) == "#1":
            if self.worker and self.worker.is_alive():
                return "break"
            if not item.isdecimal():
                return "break"
            if item in self.selected:
                self.selected.remove(item)
            else:
                self.selected.add(item)
            self.render()
            return "break"

    def toggle_highlight(self, event=None):
        if self.worker and self.worker.is_alive():
            return "break"
        for item in self.tree.selection():
            if item in self.selected:
                self.selected.remove(item)
            else:
                self.selected.add(item)
        self.render()
        return "break"

    def select_all(self):
        self.selected = {item for item in self.mods if item.isdecimal()}
        self.render()

    def select_none(self):
        self.selected.clear()
        self.render()

    def select_enabled(self):
        self.selected = {item for item, data in self.mods.items()
                         if item.isdecimal() and data["mod"].enabled}
        self.render()

    def show_detail(self, event=None):
        highlighted = self.tree.selection()
        if highlighted:
            data = self.mods[highlighted[0]]
            mod = data["mod"]
            assessment = self.assessments.get(mod.item_id)
            if assessment:
                self.detail.set(mod.name + "  ·  类型：" + "、".join(assessment.kinds) +
                                "  ·  重要程度（影响范围估计）：" + assessment.importance +
                                "  ·  兼容性：" + assessment.compatibility +
                                f"（已比对 {assessment.compared} 个其他模组）\n" +
                                "；".join(assessment.reasons[:2]) +
                                ("\n" + data["detail"] if data["detail"] else ""))
            else:
                self.detail.set(mod.name + "  ·  " + data["stage"])

    def show_full_analysis(self):
        highlighted = self.tree.selection()
        if len(highlighted) != 1:
            messagebox.showinfo("选择一行", "请先选中一个模组查看分析。", parent=self.root)
            return
        item = highlighted[0]
        mod = self.mods[item]["mod"]
        assessment = self.assessments.get(item)
        feature = self.features.get(item)
        if not assessment or not feature:
            return
        lines = [mod.name, "模组编号：" + item,
                 "类型：" + "、".join(assessment.kinds),
                 "重要程度（内容影响范围）：" + assessment.importance,
                 "兼容等级：" + assessment.compatibility,
                 f"已比对 {assessment.compared} 个其他模组，其中 {assessment.risky_pairs} 对存在可解释的重叠信号。",
                 f"资源定义：{len(feature.definitions)} 个；Lua/C# 源文件：{feature.code_files} 个；"
                 f"识别到的方法补丁：{len(feature.patches)} 个；Hook.Add：{len(feature.hook_names)} 个。",
                 ""]
        lines += [f"{number}. {reason}" for number, reason in enumerate(assessment.reasons, 1)]
        lines += ["", "这是静态风险筛查。相同标识或方法补丁也可能是作者有意配合；最终仍需按作者说明设置顺序并在游戏内测试。"]
        dialog = tk.Toplevel(self.root)
        dialog.title("模组分析 · " + mod.name)
        dialog.geometry("800x600")
        dialog.configure(bg=BG)
        panel = tk.Frame(dialog, bg=BG, padx=15, pady=15)
        panel.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(panel)
        scrollbar.pack(side="right", fill="y")
        content = tk.Text(panel, bg=PANEL, fg=TEXT, relief="flat", wrap="word",
                          padx=15, pady=15, font=("Microsoft YaHei UI", 10),
                          yscrollcommand=scrollbar.set)
        content.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=content.yview)
        content.insert("1.0", "\n".join(lines))
        content.configure(state="disabled")

    def export_analysis(self):
        if not self.assessments:
            return
        path = filedialog.asksaveasfilename(title="导出兼容分析", defaultextension=".json",
                                            initialfile="潜渊症模组兼容分析.json", parent=self.root)
        if not path:
            return
        rows = []
        for item, data in self.mods.items():
            assessment = self.assessments.get(item)
            feature = self.features.get(item)
            if not assessment or not feature:
                continue
            rows.append({"id": item, "name": data["mod"].name, "enabled": data["mod"].enabled,
                         "types": assessment.kinds, "importance": assessment.importance,
                         "compatibility": assessment.compatibility, "reasons": assessment.reasons,
                         "compared": assessment.compared, "overlapping_pairs": assessment.risky_pairs,
                         "xml_definitions": len(feature.definitions), "code_files": feature.code_files,
                         "method_patches": len(feature.patches), "hook_registrations": len(feature.hook_names),
                         "unreadable_libraries": feature.opaque_code, "partial": feature.partial})
        atomic_json(Path(path), {"schema": "barotrauma-mod-analysis-v1",
                                 "note": "静态风险筛查；需要结合模组作者说明、加载顺序和游戏内测试。",
                                 "runtime_luacs_detected": self.runtime_luacs, "mods": rows})
        self.log("已导出全部模组的兼容分析。")

    def toggle_selected(self):
        highlighted = self.tree.selection()
        if len(highlighted) != 1:
            messagebox.showinfo("选择一行", "请先选中一个模组，或直接点击表格中的启用状态。", parent=self.root)
            return
        self.toggle_item(highlighted[0])

    def toggle_item(self, item):
        if self.env is None or item not in self.mods:
            return
        desired = not self.mods[item]["mod"].enabled
        self.status.set(("正在启用：" if desired else "正在禁用：") + self.mods[item]["mod"].name)

        def change():
            if desired and item.isdecimal() and not (self.env.installed / item / "filelist.xml").is_file():
                engine = UpdateEngine(self.env, self.events.put,
                                      self.download_slots.get(), self.install_slots.get(), self.timeout.get())
                self.engine = engine
                engine.cancel = self.cancel
                summary = engine.run([item], online=self.online)
                if item in summary["errors"]:
                    raise AssistantError(summary["errors"][item])
            changed = set_enabled(self.env, item, desired, source=self.mods[item]["mod"].source)
            source = self.env.cache(item) if item.isdecimal() else self.mods[item]["mod"].source
            feature = inspect(replace(self.mods[item]["mod"], source=source),
                              self.metadata.get(item))
            self.events.put({"kind": "enabled", "id": item, "enabled": desired,
                             "changed": changed.changed, "feature": feature})

        self.work(change)

    def start_update(self, online=True):
        if self.env is None:
            messagebox.showinfo("先检测目录", "请先完成本机检测。", parent=self.root)
            return
        if not self.selected:
            messagebox.showinfo("选择模组", "请勾选需要更新的模组，或点击全选。", parent=self.root)
            return
        try:
            downloads = max(1, min(12, self.download_slots.get()))
            installs = max(1, min(6, self.install_slots.get()))
            timeout = max(30, min(900, self.timeout.get()))
        except tk.TclError:
            messagebox.showerror("设置无效", "并行数量和超时必须是数字。", parent=self.root)
            return
        self.settings.update(download_slots=downloads, install_slots=installs, timeout=timeout)
        atomic_json(self.settings_file, self.settings)
        ids = list(self.selected)
        self.stage_log.clear()
        self.status.set(f"正在处理 {len(ids)} 个模组 · 同时更新 {downloads} · 同时安装 {installs}")
        self.log("开始并行更新" if online else "开始安装完整本地缓存，不联网检查新版本")

        def update():
            self.engine = UpdateEngine(self.env, self.events.put, downloads, installs, timeout)
            self.engine.cancel = self.cancel
            summary = self.engine.run(ids, online)
            refreshed = {}
            for item in summary["completed"]:
                mod = self.mods[item]["mod"]
                refreshed[item] = inspect(replace(mod, source=self.env.cache(item)),
                                          self.metadata.get(item))
            if refreshed:
                self.events.put({"kind": "analyses", "features": refreshed})
            self.events.put({"kind": "summary", "summary": summary})

        self.work(update)

    def retry_failed(self):
        failures = {item for item, data in self.mods.items() if data["stage"] in ("失败", "等待超时", "已停止")}
        if not failures:
            messagebox.showinfo("没有失败项", "当前没有需要重试的任务。", parent=self.root)
            return
        self.selected = failures
        self.render()
        self.start_update(True)

    def stop(self):
        self.cancel.set()
        self.status.set("正在停止助手任务，原有模组会保留…")
        self.stop_button.configure(state="disabled")

    def restore(self):
        highlighted = self.tree.selection()
        if self.env is None or len(highlighted) != 1:
            messagebox.showinfo("选择一行", "请选中一行模组，再恢复上一版。", parent=self.root)
            return
        item = highlighted[0]

        def rollback():
            installer = Installer(self.env, lambda _: True)
            for message in installer.recover():
                self.events.put({"kind": "log", "message": message})
            backup = installer.restore(item)
            self.events.put({"kind": "item", "id": item, "stage": "已恢复上一版",
                             "progress": 100, "detail": "可重新检测或再次更新"})
            self.events.put({"kind": "log", "message": "已恢复备份：" + backup})

        self.work(rollback)

    def choose_game(self):
        directory = filedialog.askdirectory(title="选择包含 Barotrauma.exe 的游戏目录", parent=self.root)
        if directory:
            self.settings["game_directory"] = directory
            atomic_json(self.settings_file, self.settings)
            self.scan()

    def launch(self):
        if self.env is not None:
            webbrowser.open("steam://run/602960")

    def export_profile(self):
        if self.env is None or not self.mods:
            return
        path = filedialog.asksaveasfilename(title="导出联机清单", defaultextension=".json",
                                           initialfile="潜渊症联机模组清单.json", parent=self.root)
        if path:
            entries = []
            for item in self.selected:
                mod = self.mods[item]["mod"]
                fingerprint = self.verified_fingerprint(item)
                entries.append({"id": item, "name": mod.name, "mod_version": mod.mod_version,
                                "cache_manifest": self.env.record(item).get("manifest", ""),
                                "assistant_fingerprint": fingerprint})
            atomic_json(Path(path), {"schema": "barotrauma-mod-assistant-profile-v1", "appid": 602960,
                                     "note": "助手文件指纹不是游戏联机内容哈希；游戏仍会验证完整内容。",
                                     "mods": entries})
            self.log("已导出所选模组的联机清单。")

    def compare_profile(self):
        path = filedialog.askopenfilename(title="选择房主导出的联机清单", filetypes=[("模组清单", "*.json")], parent=self.root)
        if not path or self.env is None:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if data.get("schema") != "barotrauma-mod-assistant-profile-v1" or data.get("appid") != 602960:
                raise AssistantError("这不是助手支持的潜渊症联机清单")
            lines = []
            for entry in data["mods"]:
                item = str(entry["id"])
                local = self.mods.get(item)
                if local is None:
                    lines.append(f'缺少：{entry.get("name", item)}')
                    continue
                if local["mod"].mod_version != entry.get("mod_version"):
                    lines.append(f'版本不同：{local["mod"].name}')
                if self.env.record(item).get("manifest") != entry.get("cache_manifest"):
                    lines.append(f'缓存修订不同：{local["mod"].name}')
                if entry.get("assistant_fingerprint"):
                    value = self.verified_fingerprint(item)
                    if value != entry["assistant_fingerprint"]:
                        lines.append(f'文件指纹不同或未校验：{local["mod"].name}')
            text = "\n".join(lines) if lines else "缓存版本与清单一致；游戏仍会检查内容哈希、依赖和加载顺序。"
            self.log(text)
            messagebox.showinfo("联机清单对比", text[:3500], parent=self.root)
        except Exception as error:
            messagebox.showerror("无法读取清单", str(error), parent=self.root)

    def export_report(self):
        path = filedialog.asksaveasfilename(title="导出更新报告", defaultextension=".json",
                                           initialfile="模组更新报告.json", parent=self.root)
        if path:
            atomic_json(Path(path), self.last_summary or {
                "mods": [{"id": item, "name": data["mod"].name, "status": data["stage"],
                          "detail": data["detail"]} for item, data in self.mods.items()]})
            self.log("已保存更新报告。")

    def drain(self):
        changed = False
        for _ in range(350):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event["kind"]
            if kind == "inventory":
                self.env = event["env"]
                previous_selection = set(self.selected) if self.mods else None
                self.mods = {mod.item_id: {"mod": mod, "stage": mod.status, "progress": 0, "detail": ""}
                             for mod in event["mods"]}
                self.features = event["features"]
                self.assessments = event["assessments"]
                self.metadata = event["metadata"]
                self.online = event["online"]
                self.runtime_luacs = event["runtime_luacs"]
                self.selected = ((previous_selection & set(self.mods)) if previous_selection is not None
                                 else {item for item in self.mods if item.isdecimal()})
                self.tree.delete(*self.tree.get_children())
                self.status.set(f'{len(self.mods)} 个订阅 / 缓存模组 · ' +
                                ("Steam 已连接" if event["online"] else "本地检测模式") +
                                f" · 游戏：{self.env.game}")
                self.log("本机检测完成。完整缓存可以直接安装，不需要先删除重下。")
                if not event["metadata_available"]:
                    self.log("工坊公开资料暂不可用；类型和兼容性主要根据本地资源分析。")
                changed = True
            elif kind == "enabled":
                item = event["id"]
                mod = self.mods[item]["mod"]
                enabled = enabled_ids(self.env)
                for data in self.mods.values():
                    data["mod"].enabled = data["mod"].item_id in enabled
                mod.source = self.env.cache(item) if item.isdecimal() else mod.source
                self.features[item] = event["feature"]
                self.assessments = evaluate([data["mod"] for data in self.mods.values()],
                                            self.features, self.runtime_luacs)
                action = "启用" if event["enabled"] else "禁用"
                self.status.set(f"{mod.name} 已{action}；下次启动游戏后生效")
                self.log(self.status.get())
                changed = True
            elif kind == "analyses":
                self.features.update(event["features"])
                self.assessments = evaluate([data["mod"] for data in self.mods.values()],
                                            self.features, self.runtime_luacs)
                changed = True
            elif kind == "item":
                item = event["id"]
                if item in self.mods:
                    self.mods[item].update(stage=event["stage"], progress=event["progress"], detail=event["detail"])
                    if event["stage"] != self.stage_log.get(item):
                        self.log(self.mods[item]["mod"].name + "：" + event["stage"] +
                                 (" · " + event["detail"] if event["detail"] else ""))
                        self.stage_log[item] = event["stage"]
                    if event["stage"] == "已完成":
                        mod = self.mods[item]["mod"]
                        package = load_package(self.env.installed / item)
                        mod.mod_version = package.get("modversion", "")
                        mod.installed_version = mod.mod_version
                        mod.name = package.get("name", mod.name)
                        mod.size = self.env.record(item).get("size", mod.size)
                    changed = True
            elif kind == "log":
                self.log(event["message"])
            elif kind == "error":
                self.status.set("任务未完成：" + event["message"])
                self.log(event["message"])
                messagebox.showerror("任务未完成", event["message"], parent=self.root)
            elif kind == "summary":
                self.last_summary = event["summary"]
                summary = self.last_summary
                self.status.set(f'完成 {len(summary["completed"])} 个 · 未完成 {len(summary["errors"])} 个 · '
                                f'耗时 {summary["seconds"]:.1f} 秒' + (" · 已停止" if summary["cancelled"] else ""))
                self.log(self.status.get())
            elif kind == "idle":
                self.set_busy(False)
                self.engine = None
        if changed:
            self.render()
            self.show_detail()
        self.root.after(80, self.drain)

    def close(self):
        if self.worker and self.worker.is_alive():
            self.stop()
            self.root.after(120, self.finish_close)
        else:
            self.root.destroy()

    def finish_close(self):
        if self.worker and self.worker.is_alive():
            self.root.after(120, self.finish_close)
        else:
            self.root.destroy()


def self_check(report_path):
    """Read-only packaged UI/Steam smoke test, without starting an update."""
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    errors = []
    messagebox.showerror = lambda title, message, **kwargs: errors.append(str(message))
    started = time.monotonic()

    def finish():
        if app.env is not None and not (app.worker and app.worker.is_alive()):
            try:
                assert len(app.tree.get_children()) == len(app.mods)
                assert len(app.features) == len(app.mods)
                assert len(app.assessments) == len(app.mods)
                assert all(assessment.compared == len(app.mods) - 1
                           for assessment in app.assessments.values())
                assert any(item.startswith("local:") for item in app.mods)
                app.select_none()
                assert not app.selected
                app.select_all()
                assert len(app.selected) == sum(item.isdecimal() for item in app.mods)
                first = next(iter(app.mods), "")
                app.search.set(first)
                assert not first or app.tree.exists(first)
                app.search.set("")
                assert len(app.tree.get_children()) == len(app.mods)
            except Exception as error:
                errors.append(repr(error))
            atomic_json(Path(report_path), {"ok": not errors, "errors": errors,
                        "mods": len(app.mods), "status": app.status.get(), "version": VERSION,
                        "analyzed": len(app.assessments),
                        "enabled": sum(data["mod"].enabled for data in app.mods.values()),
                        "frozen": bool(getattr(sys, "frozen", False))})
            app.close()
        elif errors or time.monotonic() - started > 30:
            atomic_json(Path(report_path), {"ok": False, "errors": errors or ["检测超时"]})
            app.close()
        else:
            root.after(100, finish)

    root.after(300, finish)
    root.mainloop()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        self_check(sys.argv[2])
        return
    mutex = None
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        mutex = kernel.CreateMutexW(None, False, "Local\\BarotraumaModAssistant-602960")
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(mutex)
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("助手已打开", "模组更新助手已经在运行，请使用已打开的窗口。", parent=root)
            root.destroy()
            return
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    finally:
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
