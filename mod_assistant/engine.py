from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import threading
import time
from .core import AssistantError, Cancelled, Environment, Installer, atomic_json, game_running, scoped_game_guard
from .steam import DOWNLOADING, PENDING, SUBSCRIBED, SteamBridge, result_text


class UpdateEngine:
    def __init__(self, env: Environment, emit, download_slots=4, install_slots=3,
                 stall_timeout=180, retries=2, bridge_factory=SteamBridge,
                 installer_factory=Installer, process_guard=game_running):
        self.env, self.emit = env, emit
        self.download_slots = max(1, min(12, int(download_slots)))
        self.install_slots = max(1, min(6, int(install_slots)))
        self.stall_timeout = stall_timeout
        self.retries = retries
        self.bridge_factory = bridge_factory
        self.installer_factory = installer_factory
        self.process_guard = scoped_game_guard(env, process_guard)
        self.cancel = threading.Event()

    def event(self, item, stage, progress=0, detail=""):
        self.emit({"kind": "item", "id": item, "stage": stage,
                   "progress": progress, "detail": detail})

    def run(self, ids: list[str], online=True) -> dict:
        if self.process_guard():
            raise AssistantError("请先关闭《潜渊症》和服务器，再更新模组")
        ids = list(dict.fromkeys(ids))
        if any(not item.isdecimal() for item in ids):
            raise AssistantError("模组编号格式无效")
        bridge = None
        results, errors = {}, {}
        started = time.monotonic()
        if online:
            bridge = self.bridge_factory(self.env).connect()
            try:
                subscribed = set(bridge.subscribed())
            except Exception:
                bridge.close()
                raise
            missing = [item for item in ids if item not in subscribed]
            for item in missing:
                errors[item] = "当前账号未订阅此模组，请先在工坊订阅"
                self.event(item, "失败", detail=errors[item])
            ids = [item for item in ids if item in subscribed]

        def cache_ready(item):
            if bridge:
                return bridge.ready(item)
            record = self.env.record(item)
            return bool(record and not record.get("global_busy")
                        and record.get("manifest") == record.get("latest_manifest"))

        installer = self.installer_factory(self.env, cache_ready, process_guard=self.process_guard)
        try:
            for message in installer.recover():
                self.emit({"kind": "log", "message": message})
            pending = deque(ids)
            active = {}
            install_pending = deque()
            futures = {}
            late_results = {}
            with ThreadPoolExecutor(max_workers=self.install_slots, thread_name_prefix="ModInstall") as pool:
                while pending or active or install_pending or futures:
                    if self.cancel.is_set():
                        for item in list(pending) + list(active) + list(install_pending):
                            errors[item] = "任务已停止；已提交的 Steam 下载可能继续"
                            self.event(item, "已停止", detail="Steam 已提交的下载可能继续，可下次复用")
                        pending.clear()
                        active.clear()
                        install_pending.clear()
                    # Fill all available request slots before waiting for any one completion.
                    while pending and len(active) < self.download_slots and not self.cancel.is_set():
                        item = pending.popleft()
                        if bridge:
                            now = time.monotonic()
                            if not bridge.request(item):
                                errors[item] = "Steam 没有接受更新请求，请检查网络与登录状态"
                                self.event(item, "失败", detail=errors[item])
                            else:
                                active[item] = {"last_progress": now, "started": now,
                                                "bytes": -1, "attempt": 0, "retry_at": 0}
                                self.event(item, "已提交 / 等待 Steam")
                        elif cache_ready(item):
                            install_pending.append(item)
                            self.event(item, "等待安装", detail="使用已下载缓存；未联网检查新版本")
                        else:
                            errors[item] = "Steam 缓存尚未完成，不能执行本地安装"
                            self.event(item, "失败", detail=errors[item])
                    if bridge and active:
                        late_results.update(bridge.pump())
                        for item in list(active):
                            state = active[item]
                            code = late_results.pop(item, None)
                            now = time.monotonic()
                            if code == 1:
                                state["callback_ok"] = True
                            if state.get("callback_ok") and bridge.ready(item):
                                install_pending.append(item)
                                del active[item]
                                self.event(item, "等待安装")
                                continue
                            if code is not None and code != 1:
                                state.pop("callback_ok", None)
                                if state["attempt"] < self.retries and code not in (8, 9, 15, 25, 42, 43, 52, 54, 86):
                                    state["attempt"] += 1
                                    state["retry_at"] = now + min(20, 2 ** state["attempt"])
                                    self.event(item, "准备重试", detail=result_text(code))
                                else:
                                    errors[item] = result_text(code)
                                    del active[item]
                                    self.event(item, "失败", detail=errors[item])
                                    continue
                            if state["retry_at"]:
                                if now >= state["retry_at"]:
                                    if bridge.request(item):
                                        state.update(retry_at=0, last_progress=now, bytes=-1)
                                        self.event(item, "已重试", detail=f'第 {state["attempt"]} 次重试')
                                    else:
                                        errors[item] = "Steam 拒绝重试请求"
                                        del active[item]
                                        self.event(item, "失败", detail=errors[item])
                                continue
                            done, total = bridge.progress(item)
                            if done != state["bytes"]:
                                state["bytes"] = done
                                state["last_progress"] = now
                            native_state = bridge.state(item)
                            label = "下载中" if native_state & DOWNLOADING else "Steam 排队 / 等待完成"
                            self.event(item, label, done / total * 100 if total else 0,
                                       f"{done / 1048576:.1f} / {total / 1048576:.1f} MB" if total else "")
                            if now - state["last_progress"] > self.stall_timeout or now - state["started"] > 1800:
                                # Do not delete or resubmit a still active native download.
                                if native_state & (DOWNLOADING | PENDING):
                                    errors[item] = "长时间没有进度，已让出助手槽位；Steam 下载仍可继续，完成后重试"
                                    del active[item]
                                    self.event(item, "等待超时", detail=errors[item])
                                elif state["attempt"] < self.retries:
                                    state["attempt"] += 1
                                    state["retry_at"] = now + 2 ** state["attempt"]
                                else:
                                    errors[item] = "未收到 Steam 完成通知，请稍后重试"
                                    del active[item]
                                    self.event(item, "等待超时", detail=errors[item])
                    while install_pending and len(futures) < self.install_slots and not self.cancel.is_set():
                        item = install_pending.popleft()
                        try:
                            if bridge:
                                source, timestamp = bridge.installation(item)
                            else:
                                source = self.env.cache(item)
                                timestamp = self.env.record(item).get("timeupdated", 0)
                            throttle = [0.0]

                            def progress(stage, percent, item_id=item, clock=throttle):
                                now = time.monotonic()
                                if now - clock[0] >= 0.12 or percent == 100:
                                    self.event(item_id, stage, percent)
                                    clock[0] = now

                            future = pool.submit(installer.install, item, source, timestamp, self.cancel, progress)
                            futures[future] = item
                        except Exception as error:
                            errors[item] = str(error)
                            self.event(item, "失败", detail=str(error))
                    for future in list(futures):
                        if future.done():
                            item = futures.pop(future)
                            try:
                                results[item] = asdict(future.result())
                                self.event(item, "已完成", 100,
                                           "文件状态未变化，沿用上次完整校验的安装" if results[item].get("unchanged") else
                                           f'复制 {results[item]["copied"]} 个，复用 {results[item]["reused"]} 个文件')
                            except Cancelled as error:
                                errors[item] = str(error)
                                self.event(item, "已停止", detail=str(error))
                            except Exception as error:
                                errors[item] = str(error)
                                self.event(item, "失败", detail=str(error))
                    # The callback pump must run frequently; a short wait stays cancellable.
                    time.sleep(0.08)
            summary = {"completed": results, "errors": errors, "cancelled": self.cancel.is_set(),
                       "seconds": round(time.monotonic() - started, 2),
                       "download_slots": self.download_slots, "install_slots": self.install_slots,
                       "online": online}
            atomic_json(self.env.work / "last-run.json", summary)
            return summary
        finally:
            if bridge:
                bridge.close()
