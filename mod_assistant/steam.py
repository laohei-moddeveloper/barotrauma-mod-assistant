from __future__ import annotations

import ctypes as C
import os
from pathlib import Path
import threading
import time
from .core import APP_ID, AssistantError, Cancelled, Environment, game_running

SUBSCRIBED, INSTALLED, NEEDS_UPDATE, DOWNLOADING, PENDING = 1, 4, 8, 16, 32
BUSY = NEEDS_UPDATE | DOWNLOADING | PENDING


class CallbackMessage(C.Structure):
    _fields_ = [("user", C.c_int), ("callback", C.c_int),
                ("data", C.c_void_p), ("size", C.c_int)]


class DownloadResult(C.Structure):
    _fields_ = [("appid", C.c_uint32), ("item", C.c_uint64), ("result", C.c_int)]


class SteamBridge:
    """Thin bindings to the user's installed Steamworks DLL; no credentials or Web API key."""
    def __init__(self, env: Environment):
        self.env = env
        self.lock = threading.RLock()
        self.dll = None
        self.ugc = None
        self.initialized = False

    def bind(self, name, result, arguments):
        function = getattr(self.dll, name)
        function.restype = result
        function.argtypes = arguments
        return function

    def connect(self):
        os.environ["SteamAppId"] = str(APP_ID)
        os.environ["SteamGameId"] = str(APP_ID)
        self.dll = C.CDLL(str(self.env.game / "steam_api64.dll"))
        self.shutdown_api = self.bind("SteamAPI_Shutdown", None, [])
        init = self.bind("SteamAPI_InitFlat", C.c_int, [C.c_char_p])
        error = C.create_string_buffer(1024)
        result = init(error)
        if result != 0:
            detail = error.value.decode("utf-8", errors="replace")
            raise AssistantError(f"Steam 连接失败，请先打开 Steam 并登录拥有游戏的账号。{detail}")
        self.initialized = True
        try:
            self.ugc = self.bind("SteamAPI_SteamUGC_v020", C.c_void_p, [])()
            if not self.ugc:
                raise AssistantError("Steam 工坊接口不可用，请更新 Steam 客户端")
            utils = self.bind("SteamAPI_SteamUtils_v010", C.c_void_p, [])()
            self.utils = utils
            self.subscribe_item = self.bind('SteamAPI_ISteamUGC_SubscribeItem', C.c_uint64, [C.c_void_p,C.c_uint64])
            self.call_completed = self.bind('SteamAPI_ISteamUtils_IsAPICallCompleted', C.c_bool,
                                           [C.c_void_p,C.c_uint64,C.POINTER(C.c_bool)])
            app = self.bind("SteamAPI_ISteamUtils_GetAppID", C.c_uint32, [C.c_void_p])(utils)
            if app != APP_ID:
                raise AssistantError("Steam 工坊连接的游戏编号不正确")
            self.get_state = self.bind("SteamAPI_ISteamUGC_GetItemState", C.c_uint32,
                                       [C.c_void_p, C.c_uint64])
            self.download_item = self.bind("SteamAPI_ISteamUGC_DownloadItem", C.c_bool,
                                           [C.c_void_p, C.c_uint64, C.c_bool])
            self.get_download = self.bind("SteamAPI_ISteamUGC_GetItemDownloadInfo", C.c_bool,
                                          [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64), C.POINTER(C.c_uint64)])
            self.get_install = self.bind("SteamAPI_ISteamUGC_GetItemInstallInfo", C.c_bool,
                                         [C.c_void_p, C.c_uint64, C.POINTER(C.c_uint64),
                                          C.c_char_p, C.c_uint32, C.POINTER(C.c_uint32)])
            self.count_subscribed = self.bind("SteamAPI_ISteamUGC_GetNumSubscribedItems", C.c_uint32,
                                              [C.c_void_p])
            self.get_subscribed = self.bind("SteamAPI_ISteamUGC_GetSubscribedItems", C.c_uint32,
                                            [C.c_void_p, C.POINTER(C.c_uint64), C.c_uint32])
            self.pipe = self.bind("SteamAPI_GetHSteamPipe", C.c_int, [])()
            self.bind("SteamAPI_ManualDispatch_Init", None, [])()
            self.run_frame = self.bind("SteamAPI_ManualDispatch_RunFrame", None, [C.c_int])
            self.next_callback = self.bind("SteamAPI_ManualDispatch_GetNextCallback", C.c_bool,
                                           [C.c_int, C.POINTER(CallbackMessage)])
            self.free_callback = self.bind("SteamAPI_ManualDispatch_FreeLastCallback", None, [C.c_int])
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        with self.lock:
            if self.initialized:
                self.shutdown_api()
                self.initialized = False

    def subscribed(self) -> list[str]:
        with self.lock:
            count = self.count_subscribed(self.ugc)
            array = (C.c_uint64 * max(1, count))()
            size = self.get_subscribed(self.ugc, array, count)
            return [str(array[i]) for i in range(min(size, count))]

    def state(self, item_id: str) -> int:
        with self.lock:
            return self.get_state(self.ugc, int(item_id))

    def ready(self, item_id: str) -> bool:
        state = self.state(item_id)
        return bool(state & INSTALLED) and not bool(state & BUSY)

    def request(self, item_id: str) -> bool:
        with self.lock:
            # Low priority avoids pausing Steam's other downloads. The coordinator submits
            # several requests without waiting on the previous item's completion.
            return self.download_item(self.ugc, int(item_id), False)

    def progress(self, item_id: str) -> tuple[int, int]:
        downloaded, total = C.c_uint64(), C.c_uint64()
        with self.lock:
            available = self.get_download(self.ugc, int(item_id), C.byref(downloaded), C.byref(total))
        return (downloaded.value, total.value) if available else (0, 0)

    def subscribe(self, item_id, cancel=None, timeout=60, process_guard=game_running):
        if not item_id.isdecimal() or not 0<int(item_id)<2**64: raise AssistantError('工坊编号无效')
        if process_guard(): raise AssistantError('请先关闭游戏，再订阅并配齐联机模组')
        if self.state(item_id) & SUBSCRIBED: return False
        with self.lock: call=self.subscribe_item(self.ugc,int(item_id))
        if not call: raise AssistantError('Steam 未接受模组订阅请求')
        started=time.monotonic()
        while time.monotonic()-started<timeout:
            if cancel and cancel.is_set(): raise Cancelled('订阅等待已停止，已接受的订阅可能继续')
            if process_guard(): raise AssistantError('游戏刚刚启动，已停止联机配置任务')
            self.pump(); failed=C.c_bool()
            with self.lock: completed=self.call_completed(self.utils,call,C.byref(failed))
            if completed:
                if failed.value: raise AssistantError('Steam 订阅请求失败，请检查登录和网络')
                if self.state(item_id)&SUBSCRIBED: return True
                raise AssistantError('Steam 未确认订阅，请核实此工坊项目属于潜渊症且有访问权限')
            time.sleep(0.1)
        raise AssistantError('等待 Steam 订阅超时；启用配置未切换')

    def installation(self, item_id: str) -> tuple[Path, int]:
        if not self.ready(item_id):
            raise AssistantError("Steam 尚未完成此模组下载")
        size, timestamp = C.c_uint64(), C.c_uint32()
        path = C.create_string_buffer(32768)
        with self.lock:
            success = self.get_install(self.ugc, int(item_id), C.byref(size), path,
                                        len(path), C.byref(timestamp))
        if not success:
            raise AssistantError("Steam 未提供已完成的安装信息")
        source = Path(path.value.decode("utf-8"))
        expected = self.env.cache(item_id)
        if expected is None or source.resolve() != expected.resolve():
            raise AssistantError("Steam 返回的缓存路径与此游戏的模组目录不匹配")
        record = self.env.record(item_id)
        # Use the actual downloaded revision's update time, never invent a newer time.
        return source, record.get("timeupdated") or timestamp.value

    def pump(self) -> dict[str, int]:
        results = {}
        with self.lock:
            self.run_frame(self.pipe)
            message = CallbackMessage()
            while self.next_callback(self.pipe, C.byref(message)):
                try:
                    if message.callback == 3406 and message.size >= C.sizeof(DownloadResult):
                        result = DownloadResult.from_buffer_copy(C.string_at(message.data, C.sizeof(DownloadResult)))
                        if result.appid == APP_ID:
                            results[str(result.item)] = result.result
                finally:
                    self.free_callback(self.pipe)
        return results


def result_text(code: int) -> str:
    names = {2: "Steam 服务暂时失败", 3: "Steam 网络连接中断", 8: "模组编号无效",
             9: "模组文件不存在", 10: "Steam 正忙", 15: "没有访问此模组的权限",
             16: "等待 Steam 超时", 20: "Steam 服务不可用", 21: "Steam 尚未登录",
             25: "Steam 请求超过限制", 27: "访问许可已过期", 35: "连接 Steam 失败",
             37: "文件读写失败", 42: "没有匹配的工坊内容", 43: "Steam 账号不可用",
             52: "Steam 下载已取消", 53: "下载数据损坏", 54: "磁盘空间不足",
             84: "请求过于频繁，请稍后重试", 86: "工坊内容已删除"}
    return names.get(code, f"Steam 错误码 {code}")
