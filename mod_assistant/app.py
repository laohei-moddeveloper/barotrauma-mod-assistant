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
from .core import AssistantError, Installer, Mod, atomic_json, discover, game_running, inventory, load_package
from .engine import UpdateEngine
from .mod_analysis import evaluate, inspect, inspect_all, luacs_runtime_detected, workshop_details
from .mod_toggle import enabled_ids, set_enabled
from .mod_order import read_order
from .order_ui import OrderDialog
from .luacs import LuaCsInstaller, status as luacs_status
from .analysis_cache import inspect_cached
from .management_ui import ManagementDialog
from .profiles import capture_profile, normalize_profile, resolve_profile
from .snapshots import SnapshotStore
from .diagnostics import diagnose, recent_logs, lua_verification
from .steam import BUSY, DOWNLOADING, NEEDS_UPDATE, PENDING, SteamBridge
from .appearance import Appearance
from .main_ui import MainInterface

STATE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BarotraumaModAssistant"
BG, PANEL, TEXT, MUTED, ACCENT = "#0b1422", "#142237", "#e8f0fa", "#8fa6bf", "#57dac4"


class App:
    def __init__(self, root, auto_scan=True):
        self.root = root
        self.root.title(f"潜渊症 · 模组更新助手 {VERSION}")
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
        self.runtime_csharp = None
        self.luacs_text = tk.StringVar(value="LuaCs 状态待检测")
        self.selected = set()
        self.env = None
        self.stage_log = {}
        self.last_summary = None
        self.refresh_after_idle = False
        STATE.mkdir(parents=True, exist_ok=True)
        self.settings_file = STATE / "settings.json"
        try:
            self.settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}
        if not isinstance(self.settings,dict): self.settings = {}
        self.appearance=Appearance(self.settings.get('appearance'))
        screen_width,screen_height=self.root.winfo_screenwidth(),self.root.winfo_screenheight()
        size=self.settings.get('window_size',[1360,800])
        if not isinstance(size,list) or len(size)!=2 or any(type(value) is not int for value in size): size=[1360,800]
        available_width,available_height=max(1,screen_width-50),max(1,screen_height-80)
        minimum_width,minimum_height=min(1000,available_width),min(680,available_height)
        self.root.minsize(minimum_width,minimum_height)
        self.root.geometry(f'{max(minimum_width,min(size[0],available_width))}x{max(minimum_height,min(size[1],available_height))}')
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
        self.auto_snapshot = tk.BooleanVar(value=self.settings.get('auto_snapshot', True))
        self.light_detection = tk.BooleanVar(value=self.settings.get('light_detection', True))
        self.search = tk.StringVar()
        self.busy_buttons = []
        self.make_style()
        self.build()
        self.root.after(80, self.drain)
        if auto_scan:
            self.root.after(120, self.scan)

    def make_style(self):
        self.appearance.configure_style(self.root)

    def skin(self, window):
        self.appearance.skin(window)
        if hasattr(self, 'tree'):
            colours = self.appearance.colours
            for tag, role in [('complete', 'accent_text'), ('failed', 'error'),
                              ('active', 'active'), ('warning', 'warning')]:
                self.tree.tag_configure(tag, foreground=colours[role])

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
        button._appearance_primary=primary
        return button

    def build(self):
        self.interface = MainInterface(self)

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
        self.busy_buttons = [button for button in self.busy_buttons if button.winfo_exists()]
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

    def scan(self, force=False):
        lightweight = self.light_detection.get()
        self.status.set("正在检测游戏目录、模组缓存与 Steam 状态…")

        def detect():
            env = discover(self.settings.get("game_directory", ""))
            try:
                running = game_running()
            except AssistantError as error:
                running = None
                self.events.put({"kind": "log", "message": "无法确认游戏进程：" + str(error)})
            self.events.put({"kind": "scan_status", "message":
                             "游戏正在运行：只读检测模组；更新和启用切换需关闭游戏" if running else
                             "正在读取本地模组与启用状态…"})
            mods = inventory(env)
            light = bool(running is not False and lightweight)
            if force and running is not False:
                raise AssistantError('请先关闭游戏和服务器，再完整重新分析')
            self.events.put({"kind": "scan_status", "message": "正在读取 Steam 工坊状态…"})
            online = False
            bridge = None
            try:
                if light:
                    raise AssistantError('游戏运行中：轻量模式暂不查询 Steam 工坊')
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
            self.events.put({"kind": "scan_status", "message": "正在读取模组公开资料…"})
            metadata, metadata_available = workshop_details(env, [mod.item_id for mod in mods], allow_network=not light)
            self.events.put({"kind": "scan_status", "message":
                             f"正在比对 {len(mods)} 个模组的资源和代码…"})
            analysis_mods = [replace(mod,source=env.installed/mod.item_id)
                             if mod.item_id.isdecimal() and (env.installed/mod.item_id/'filelist.xml').is_file() else mod for mod in mods]
            features,stats = inspect_cached(env,analysis_mods,metadata,light,force,self.cancel,
                                            lambda message:self.events.put({'kind':'scan_status','message':message}))
            detected = luacs_status(env)
            runtime_luacs = detected.runtime
            assessments = evaluate(mods, features, runtime_luacs, read_order(env,strict=False), detected.csharp)
            self.events.put({"kind": "inventory", "env": env, "mods": mods, "online": online,
                             "metadata": metadata, "features": features,
                             "assessments": assessments, "runtime_luacs": runtime_luacs,
                             "game_running": running,
                             "luacs_status": detected.text, 'runtime_csharp':detected.csharp,
                             'analysis_stats':stats, 'light':light,
                             "metadata_available": metadata_available})

        self.work(detect)

    def evaluate_current(self):
        return evaluate([data['mod'] for data in self.mods.values()],self.features,self.runtime_luacs,
                        read_order(self.env,strict=False),self.runtime_csharp)

    def show_management(self):
        if self.env: ManagementDialog(self)

    def text_report(self,title,text):
        dialog=tk.Toplevel(self.root); dialog.title(title); dialog.geometry('900x650'); dialog.configure(bg=BG)
        panel=tk.Frame(dialog,bg=BG,padx=15,pady=15); panel.pack(fill='both',expand=True)
        scrollbar=ttk.Scrollbar(panel); scrollbar.pack(side='right',fill='y')
        content=tk.Text(panel,bg=PANEL,fg=TEXT,wrap='word',relief='flat',padx=12,pady=12,
                        font=('Microsoft YaHei UI',10),yscrollcommand=scrollbar.set)
        content.pack(fill='both',expand=True); scrollbar.configure(command=content.yview)
        content.insert('1.0',text); content.configure(state='disabled')
        self.skin(dialog)

    def diagnose_logs(self,choose=False):
        if not self.env: return
        logs=recent_logs(self.env)
        path=filedialog.askopenfilename(title='选择游戏、LuaCs 或服务器日志',filetypes=[('日志','*.log *.txt'),('所有文件','*.*')],parent=self.root) if choose or not logs else logs[0]
        if not path: return
        mods=[data['mod'] for data in self.mods.values()]
        summary=self.last_summary
        def work():
            report=diagnose(path,mods,self.env)
            lines=[report['file'],report['note'],'']
            if summary and summary.get('errors'):
                lines+=['最近助手更新未完成项：']+[f'{item}：{error}' for item,error in summary['errors'].items()]+['']
            for finding in report['findings']:
                lines += [f"[{finding['category']}] 片段行 {finding['line_in_tail']}",finding['evidence'],
                          '可能相关模组：'+('、'.join(finding['possible_mods']) or '未确定'),finding['text'],
                          '建议：'+finding['advice'],'']
            if not report['findings']: lines.append('读取片段未发现已识别的错误关键词；这不代表游戏运行无错误。')
            self.events.put({'kind':'text_report','title':'游戏 / LuaCs 日志诊断','text':'\n'.join(lines)})
        self.work(work)

    def verify_luacs(self):
        if not self.env: return
        report=lua_verification(self.env)
        self.text_report('LuaCs 安装后验证', '\n'.join([report['disk_status']['text'],
                         '当前为磁盘检测；尚未由助手确认游戏内脚本运行成功。','']+
                         [f'{i}. {line}' for i,line in enumerate(report['instructions'],1)]+['',report['official_guide']]))

    def render(self):
        highlighted = self.tree.selection()
        existing = set(self.tree.get_children())
        search = self.search.get().casefold()
        for item, data in self.mods.items():
            mod = data["mod"]
            assessment = self.assessments.get(item)
            filter_value = self.filter.get()
            filtered = (filter_value == '已启用' and not mod.enabled
                        or filter_value == '未启用' and mod.enabled
                        or filter_value == '需要处理' and not (
                            any(word in data['stage'] for word in ('待更新', '待同步', '失败', '需要检查', '超时',
                                                                 '未安装', '等待 Steam', '等待下载', '已停止'))
                            or assessment and assessment.compatibility.startswith('低')))
            if filtered or search and search not in (mod.name + " " + item).casefold():
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
                 '证据状态：'+assessment.evidence,
                 f"已比对 {assessment.compared} 个其他模组，其中 {assessment.risky_pairs} 对存在可解释的重叠信号。",
                 f"资源定义：{len(feature.definitions)} 个；Lua/C# 源文件：{feature.code_files} 个；"
                 f"识别到的方法补丁：{len(feature.patches)} 个；Hook.Add：{len(feature.hook_names)} 个。",
                 ""]
        lines += [f"{number}. {reason}" for number, reason in enumerate(assessment.reasons, 1)]
        for pair in assessment.pairs:
            lines += ['', '与 '+pair['other_name']+'：'+pair['reason'], '依据：'+pair['evidence'], '处理建议：'+pair['advice']]
            for location in pair['locations']:
                lines.append(f"  {location['category']}/{location['identifier']} · 本模组 {', '.join(location['left_files']) or '未知路径'} · 对方 {', '.join(location['right_files']) or '未知路径'}")
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
        self.skin(dialog)

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
                         'evidence':assessment.evidence, 'pair_details':assessment.pairs,
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

    def show_order(self):
        if self.env is None:
            return
        OrderDialog(self)

    def install_luacs(self):
        if self.env is None:
            return
        self.status.set("正在准备 LuaCs 安装与 C# 设置…")
        def install():
            installer = LuaCsInstaller(self.env, lambda message: self.events.put(
                {"kind": "scan_status", "message": message}))
            installer.cancel = self.cancel
            result = installer.install()
            detected = luacs_status(self.env)
            self.events.put({"kind": "luacs_ready", "result": result,
                             "status": detected.text, "runtime": detected.runtime, 'csharp':detected.csharp})
        self.work(install)

    def restore_luacs(self):
        if self.env is None:
            return
        def restore():
            LuaCsInstaller(self.env).restore()
            detected = luacs_status(self.env)
            self.events.put({"kind": "luacs_ready", "runtime": detected.runtime,
                             'csharp':detected.csharp,
                             "status": detected.text, "result": {
                                 "message": "已恢复 LuaCs 安装前的文件与设置", "backup": ""}})
        self.work(restore)

    def arrange_mods(self, ids):
        positions = {item: number for number, item in enumerate(ids)}
        self.mods = dict(sorted(self.mods.items(), key=lambda value: (
            not value[1]["mod"].enabled,
            positions.get(value[0], -1 if value[1]["mod"].enabled else len(positions)),
            value[1]["mod"].name.casefold())))
        self.tree.delete(*self.tree.get_children())

    def toggle_item(self, item):
        if self.env is None or item not in self.mods:
            return
        desired = not self.mods[item]["mod"].enabled
        downloads,installs,timeout = self.download_slots.get(),self.install_slots.get(),self.timeout.get()
        self.status.set(("正在启用：" if desired else "正在禁用：") + self.mods[item]["mod"].name)

        def change():
            if desired and item.isdecimal() and not (self.env.installed / item / "filelist.xml").is_file():
                engine = UpdateEngine(self.env, self.events.put,
                                      downloads, installs, timeout)
                self.engine = engine
                engine.cancel = self.cancel
                summary = engine.run([item], online=self.online)
                if item in summary["errors"]:
                    raise AssistantError(summary["errors"][item])
            changed = set_enabled(self.env, item, desired, source=self.mods[item]["mod"].source)
            source = self.env.installed/item if item.isdecimal() else self.mods[item]["mod"].source
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
        automatic_snapshot=self.auto_snapshot.get()
        self.settings.update(auto_snapshot=automatic_snapshot,light_detection=self.light_detection.get())
        atomic_json(self.settings_file, self.settings)
        ids = list(self.selected)
        self.stage_log.clear()
        self.status.set(f"正在处理 {len(ids)} 个模组 · 同时更新 {downloads} · 同时安装 {installs}")
        self.log("开始并行更新" if online else "开始安装完整本地缓存，不联网检查新版本")

        def update():
            store=SnapshotStore(self.env,lambda message:self.events.put({'kind':'scan_status','message':message}),cancel=self.cancel)
            if automatic_snapshot:
                snapshot=store.capture('更新前',targets=ids)
                self.events.put({'kind':'log','message':'更新前快照已就绪：'+snapshot['id']})
            else: store.recover()
            self.engine = UpdateEngine(self.env, self.events.put, downloads, installs, timeout)
            self.engine.cancel = self.cancel
            summary = self.engine.run(ids, online)
            refreshed = {}
            for item in summary["completed"]:
                mod = self.mods[item]["mod"]
                refreshed[item] = inspect(replace(mod, source=self.env.installed/item),
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
            def export():
                atomic_json(Path(path), capture_profile(self.env, '当前联机配置'))
                self.events.put({'kind':'log','message':'已导出当前启用配置，包含核心包、实际顺序和已安装版本。'})
            self.work(export)

    def compare_profile(self):
        path = filedialog.askopenfilename(title="选择房主导出的联机清单", filetypes=[("模组清单", "*.json")], parent=self.root)
        if not path or self.env is None:
            return
        try:
            if Path(path).stat().st_size > 2*1024*1024: raise AssistantError('配置文件过大')
            data = normalize_profile(json.loads(Path(path).read_text(encoding="utf-8-sig")))
            def compare():
                resolved,missing,lines=resolve_profile(self.env,data)
                lines=[f'缺少：{entry.get("name",entry["id"])}' for entry in missing]+lines
                current=capture_profile(self.env)
                proposed=[resolved[x['id']].item_id for x in data['order'] if x['id'] in resolved]
                if proposed != [x['id'] for x in current['order']]: lines.append('启用清单或加载顺序不同')
                core=resolved[data['core']['id']].item_id if data.get('core') and data['core']['id'] in resolved else None
                if core != (current['core']['id'] if current.get('core') else None): lines.append('核心内容包不同')
                text='\n'.join(lines) if lines else '已安装版本、启用配置与清单一致；游戏仍需校验实际内容哈希。'
                self.events.put({'kind':'text_report','title':'联机清单对比','text':text})
            self.work(compare)
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
            if kind == "scan_status":
                self.status.set(event["message"])
            elif kind == "inventory":
                self.env = event["env"]
                previous_selection = set(self.selected) if self.mods else None
                self.mods = {mod.item_id: {"mod": mod, "stage": mod.status, "progress": 0, "detail": ""}
                             for mod in event["mods"]}
                self.features = event["features"]
                self.assessments = event["assessments"]
                self.metadata = event["metadata"]
                self.online = event["online"]
                self.runtime_luacs = event["runtime_luacs"]
                self.runtime_csharp = event['runtime_csharp']
                self.analysis_stats=event['analysis_stats']
                self.luacs_text.set(event["luacs_status"])
                self.selected = ((previous_selection & set(self.mods)) if previous_selection is not None
                                 else {item for item in self.mods if item.isdecimal()})
                self.tree.delete(*self.tree.get_children())
                self.status.set(f'{len(self.mods)} 个订阅 / 缓存模组 · ' +
                                ("Steam 已连接" if event["online"] else "本地检测模式") +
                                (" · 游戏运行中（仅检测）" if event["game_running"] else "") +
                                f" · 游戏：{self.env.game}")
                self.log("本机检测完成。完整缓存可以直接安装，不需要先删除重下。")
                stats=event['analysis_stats']
                self.log(f"分析缓存：复用 {stats['reused']} 个，分析变化 {stats['scanned']} 个，待完整检测 {stats['deferred']} 个。")
                if event['light']:
                    self.status.set(self.status.get()+' · 轻量检测，兼容资料待刷新')
                    self.log('游戏运行中没有遍历模组资源或读取脚本；已有分析仅作参考，关闭游戏后重新检测更新结论。')
                if not event["metadata_available"]:
                    self.log("工坊公开资料暂不可用；类型和兼容性主要根据本地资源分析。")
                changed = True
            elif kind == "enabled":
                item = event["id"]
                mod = self.mods[item]["mod"]
                enabled = enabled_ids(self.env)
                for data in self.mods.values():
                    data["mod"].enabled = data["mod"].item_id in enabled
                self.arrange_mods(read_order(self.env, strict=False))
                mod.source = self.env.cache(item) if item.isdecimal() else mod.source
                self.features[item] = event["feature"]
                self.assessments = self.evaluate_current()
                action = "启用" if event["enabled"] else "禁用"
                self.status.set(f"{mod.name} 已{action}；下次启动游戏后生效")
                self.log(self.status.get())
                changed = True
            elif kind == "order_saved":
                self.arrange_mods(event["ids"])
                self.assessments = self.evaluate_current()
                self.status.set("模组加载顺序已保存；下次启动游戏生效")
                self.log(self.status.get() + (" · 原配置已备份" if event["backup"] else " · 顺序未变化"))
                changed = True
            elif kind == "luacs_ready":
                self.runtime_luacs = event["runtime"]
                self.runtime_csharp = event['csharp']
                self.luacs_text.set(event["status"])
                self.assessments = self.evaluate_current()
                self.status.set(event["result"]["message"])
                self.log(self.status.get())
                if event["result"]["backup"]:
                    self.log("LuaCs 安装前文件已备份：" + event["result"]["backup"])
                self.refresh_after_idle = True
                changed = True
            elif kind == "analyses":
                self.features.update(event["features"])
                self.assessments = self.evaluate_current()
                changed = True
            elif kind == 'text_report':
                self.text_report(event['title'],event['text'])
            elif kind == 'ui_callback':
                event['callback']()
            elif kind == 'operation_done':
                result=event['result']; self.log(result.get('message','快照恢复完成；下次启动游戏生效'))
                if result.get('snapshot'): self.log('恢复点：'+result['snapshot'])
                if result.get('backup'): self.log('原文件已备份：'+result['backup'])
                self.refresh_after_idle=True
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
                if self.refresh_after_idle:
                    self.refresh_after_idle = False
                    self.root.after(150, self.scan)
        if changed:
            self.render()
            self.show_detail()
        self.root.after(80, self.drain)

    def close(self):
        self.settings.update(auto_snapshot=self.auto_snapshot.get(),light_detection=self.light_detection.get())
        self.settings['appearance']=self.appearance.prefs
        if self.root.winfo_viewable():
            self.settings['window_size']=[self.root.winfo_width(),self.root.winfo_height()]
            self.settings['column_widths']={key:self.tree.column(key,'width') for key in self.tree['columns']}
        atomic_json(self.settings_file,self.settings)
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
            appearance_checks = []
            try:
                assert len(app.interface.notebook.tabs()) == 3
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
                order = read_order(app.env)
                assert all(item in app.mods for item in order)
                dialog = OrderDialog(app)
                assert dialog.ids == order
                manager=ManagementDialog(app)
                assert manager.profile_list.winfo_exists() and manager.snapshot_list.winfo_exists()
                original = app.appearance.prefs
                try:
                    for theme in ('ocean','graphite','daylight'):
                        app.interface.apply({**original,'theme':theme},persist=False)
                        assert app.root.cget('background') == app.appearance.colours['bg']
                        assert dialog.list.cget('background') == app.appearance.colours['panel']
                        assert manager.profile_preview.cget('foreground') == app.appearance.colours['muted']
                        assert app.tree['displaycolumns'][:3] == ('check','enable','name')
                        appearance_checks.append(theme)
                finally:
                    app.interface.apply(original,persist=False)
                    dialog.window.destroy(); manager.window.destroy()
                assert all(value.evidence for value in app.assessments.values())
            except Exception as error:
                errors.append(repr(error))
            atomic_json(Path(report_path), {"ok": not errors, "errors": errors,
                        "mods": len(app.mods), "status": app.status.get(), "version": VERSION,
                        "analyzed": len(app.assessments),
                        'seconds':round(time.monotonic()-started,3),
                        'analysis_cache':app.analysis_stats,
                        'appearance_checks':appearance_checks,
                        "load_order": read_order(app.env, strict=False),
                        "luacs": asdict(luacs_status(app.env)),
                        "enabled": sum(data["mod"].enabled for data in app.mods.values()),
                        "frozen": bool(getattr(sys, "frozen", False))})
            app.close()
        elif errors or time.monotonic() - started > 180:
            atomic_json(Path(report_path), {"ok": False, "errors": errors or ["检测超时"],
                                           'last_status':app.status.get()})
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
