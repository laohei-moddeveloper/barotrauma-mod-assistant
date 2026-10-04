from __future__ import annotations

import concurrent.futures
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

APP_ID = 602960
GAME_EXECUTABLES = ("Barotrauma.exe", "DedicatedServer.exe")


class AssistantError(Exception):
    pass


class Cancelled(AssistantError):
    pass


def parse_vdf(text: str) -> dict:
    # Valve KeyValues uses quoted keys/values and braces. Do not interpret it as code.
    tokens = re.finditer(r'"((?:\\.|[^"\\])*)"|([{}])|//[^\r\n]*', text)
    values = [(re.sub(r'\\([\\"])', r'\1', token.group(1) or ""), token.group(2) or "")
              for token in tokens if not token.group(0).startswith("//")]
    position = 0

    def object_body(nested=False):
        nonlocal position
        result = {}
        while position < len(values):
            key, brace = values[position]
            position += 1
            if brace == "}":
                if not nested:
                    raise AssistantError("Steam 清单括号不完整")
                return result
            if brace or position >= len(values):
                raise AssistantError("Steam 清单格式不完整，请稍后重新检测")
            value, brace = values[position]
            position += 1
            if brace == "{":
                result[key] = object_body(True)
            elif brace:
                raise AssistantError("Steam 清单值不完整")
            else:
                result[key] = value
        if nested:
            raise AssistantError("Steam 正在写入清单，请稍后重试")
        return result

    return object_body()


def read_vdf(path: Path) -> dict:
    # Steam briefly replaces or exclusively locks its manifests while committing
    # an update. Treat these transient reads as contention, rather than a bad mod.
    for attempt in range(8):
        try:
            return parse_vdf(path.read_text(encoding="utf-8-sig"))
        except (PermissionError, FileNotFoundError, AssistantError) as error:
            if attempt == 7:
                raise AssistantError(f"Steam 清单暂时无法读取，请稍后重试：{path.name}") from error
            time.sleep(min(0.4, 0.05 * (attempt + 1)))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def reject_link(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise AssistantError(f"不处理符号链接或目录联接：{path.name}")


def remove_owned_tree(path: Path, root: Path):
    if not within(path, root) or path.resolve() == root.resolve():
        raise AssistantError("清理路径超出助手临时目录")
    if path.exists():
        reject_link(path)
        shutil.rmtree(path)


def digest(path: Path, cancel: threading.Event | None = None) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled("已停止，原有模组保留")
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            checksum.update(chunk)
    return checksum.hexdigest()


def files_snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    reject_link(folder)
    files = {}
    for directory, directories, names in os.walk(folder, followlinks=False):
        base = Path(directory)
        for child in list(directories):
            if child.startswith("."):
                directories.remove(child)
                continue
            reject_link(base / child)
        for name in names:
            if name.startswith("."):
                continue
            path = base / name
            reject_link(path)
            info = path.stat()
            files[path.relative_to(folder).as_posix()] = (info.st_size, info.st_mtime_ns)
    return dict(sorted(files.items()))


def executable_in_use(path: Path) -> bool:
    """Probe one existing game executable; never enumerate or open processes.

    OPEN_EXISTING requests a temporary write-access handle without writing any
    bytes. Windows refuses that handle for an executable mapped by its loader.
    Other file-sharing conflicts also block changes conservatively. Access
    errors are unknown, not evidence that the game is closed.
    """
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                          ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # No WriteFile, truncation, file creation, PID queries, or process handles.
    handle = open_file(str(path), 0x40000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        if code in (32, 33):
            return True
        raise AssistantError("无法确认游戏文件占用状态；保持只读，请检查游戏目录权限和文件占用。")
    kernel.CloseHandle(handle)
    return False


def game_running(env=None) -> bool:
    if os.name != "nt":
        return False
    env = env or discover()
    root = env.game.resolve()
    client = root / GAME_EXECUTABLES[0]
    if not client.is_file():
        raise AssistantError("没有找到游戏程序，无法确认文件占用状态。")
    for name in GAME_EXECUTABLES:
        path = root / name
        if path.is_file():
            reject_link(path)
            if not within(path, root):
                raise AssistantError("游戏程序路径超出所选游戏目录。")
            if executable_in_use(path):
                return True
    return False


def scoped_game_guard(env, guard=game_running):
    """Default safety check belongs to this chosen game, not a system scan."""
    return (lambda: game_running(env)) if guard is game_running else guard


@dataclass
class Environment:
    steam: Path
    game: Path
    libraries: list[Path]
    player: Path

    @property
    def installed(self):
        return self.player / "WorkshopMods" / "Installed"

    @property
    def work(self):
        return self.player / "WorkshopMods" / ".mod-assistant"

    def cache(self, item_id: str) -> Path | None:
        for library in self.libraries:
            candidate = library / "steamapps" / "workshop" / "content" / str(APP_ID) / item_id
            if candidate.is_dir():
                return candidate
        return None

    def record(self, item_id: str) -> dict:
        for library in self.libraries:
            path = library / "steamapps" / "workshop" / f"appworkshop_{APP_ID}.acf"
            if not path.is_file():
                continue
            data = read_vdf(path).get("AppWorkshop", {})
            installed = data.get("WorkshopItemsInstalled", {}).get(item_id)
            details = data.get("WorkshopItemDetails", {}).get(item_id, {})
            if installed:
                return {"manifest": installed.get("manifest", ""),
                        "timeupdated": int(installed.get("timeupdated", 0)),
                        "size": int(installed.get("size", 0)),
                        "latest_manifest": details.get("latest_manifest", installed.get("manifest", "")),
                        "global_busy": data.get("NeedsUpdate") == "1" or data.get("NeedsDownload") == "1"}
        return {}

    def token(self, item_id: str) -> str:
        record = self.record(item_id)
        return f'{record.get("manifest", "")}:{record.get("timeupdated", 0)}'


def steam_locations():
    import winreg
    roots = []
    for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")]:
        try:
            with winreg.OpenKey(hive, key) as handle:
                for value in ("SteamPath", "InstallPath"):
                    try:
                        raw = winreg.QueryValueEx(handle, value)[0]
                        if isinstance(raw, str) and raw.strip():
                            path = Path(raw)
                            if path not in roots:
                                roots.append(path)
                    except (OSError, ValueError):
                        continue
        except OSError:
            continue
    for key in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'ProgramW6432'):
        if os.environ.get(key):
            path = Path(os.environ[key]) / 'Steam'
            if path not in roots:
                roots.append(path)
    return roots


def discover(game_override: str = "") -> Environment:
    steam = next((path for path in steam_locations() if (path / 'steam.exe').is_file()), None)
    if steam is None:
        raise AssistantError("没有找到 Steam，请先安装并登录 Steam")
    libraries = [steam]
    library_file = steam / "steamapps" / "libraryfolders.vdf"
    if library_file.is_file():
        for value in read_vdf(library_file).get("libraryfolders", {}).values():
            raw = value.get('path') if isinstance(value, dict) else value if isinstance(value, str) else None
            if isinstance(raw, str) and raw and (isinstance(value, dict) or raw != '0' and ('/' in raw or '\\' in raw)):
                path = Path(raw)
                if path not in libraries:
                    libraries.append(path)
    game = Path(game_override) if isinstance(game_override, str) and game_override and (Path(game_override) / 'Barotrauma.exe').is_file() else None
    if game is None:
        for library in libraries:
            path = library / "steamapps" / f"appmanifest_{APP_ID}.acf"
            if path.is_file():
                name = read_vdf(path).get("AppState", {}).get("installdir", "Barotrauma")
                if isinstance(name, str):
                    candidate = library / "steamapps" / "common" / name
                    if (candidate / 'Barotrauma.exe').is_file():
                        game = candidate
                        break
            candidate = library / 'steamapps/common/Barotrauma'
            if (candidate / 'Barotrauma.exe').is_file():
                game = candidate
                break
    if game is None or not (game / "Barotrauma.exe").is_file():
        raise AssistantError("没有找到《潜渊症》，请在设置中选择游戏目录")
    player = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / "Daedalic Entertainment GmbH" / "Barotrauma"
    return Environment(steam, game, libraries, player)


def load_package(folder: Path) -> ET.Element:
    try:
        reject_link(folder)
        reject_link(folder / 'filelist.xml')
        root = ET.parse(folder / "filelist.xml").getroot()
    except (OSError, ET.ParseError) as error:
        raise AssistantError(f"模组清单损坏或缺失：{error}") from error
    if root.tag.lower() != "contentpackage" or not root.get("name", "").strip():
        raise AssistantError("模组清单缺少 contentpackage 或名称")
    return root


def mod_files(folder: Path):
    """Walk an approved mod folder without following links or junctions."""
    reject_link(folder)
    for directory, directories, names in os.walk(folder, followlinks=False):
        base = Path(directory)
        for child in directories:
            reject_link(base / child)
        for name in names:
            path = base / name
            reject_link(path)
            # os.walk names are single directory entries. All parents above
            # were checked before descent, so lexical containment is enough;
            # resolving every texture file would repeat expensive I/O.
            if not path.is_relative_to(folder):
                raise AssistantError('模组文件超出自身目录，不读取。')
            yield path


@dataclass
class Mod:
    item_id: str
    name: str
    source: Path | None
    mod_version: str = ""
    game_version: str = ""
    size: int = 0
    status: str = "待检测"
    enabled: bool = False
    installed_version: str = ""
    claimed_hash: str = ""


def inventory(env: Environment) -> list[Mod]:
    # Import here to keep the read-only discovery module separate from config edits.
    from .mod_toggle import enabled_ids
    enabled = enabled_ids(env)
    ids = set()
    for library in env.libraries:
        folder = library / "steamapps" / "workshop" / "content" / str(APP_ID)
        if folder.is_dir():
            ids.update(p.name for p in folder.iterdir() if p.is_dir() and p.name.isdecimal())
    mods = []
    if env.installed.is_dir():
        ids.update(p.name for p in env.installed.iterdir() if p.is_dir() and p.name.isdecimal())
    for item_id in sorted(ids, key=int):
        source = env.cache(item_id)
        mod = Mod(item_id, item_id, source, enabled=item_id in enabled)
        try:
            root = load_package(source or env.installed/item_id)
            mod.name = root.get("name", item_id)
            mod.mod_version = root.get("modversion", "")
            mod.game_version = root.get("gameversion", "")
            mod.claimed_hash = root.get("expectedhash", "")
            record = env.record(item_id)
            mod.size = record.get("size", 0)
            target = env.installed / item_id
            if target.is_dir():
                destination = load_package(target)
                mod.name = destination.get('name',mod.name)
                mod.installed_version = destination.get("modversion", "")
                current_time = int(destination.get("installtime", 0))
                mod.status = "已安装 / 无 Steam 缓存" if source is None else "已安装 / 待联网核对" if (
                    current_time >= record.get("timeupdated", 0)
                    and mod.installed_version == mod.mod_version) else "本地副本待同步"
            else:
                mod.status = "缓存可用 / 未安装"
            if record.get("latest_manifest") != record.get("manifest"):
                mod.status = "Steam 缓存待更新"
        except (AssistantError, ValueError, OSError) as error:
            mod.status = f"需要检查：{error}"
        mods.append(mod)
    from .mod_toggle import local_id
    for root in (env.game / "LocalMods", env.player / "LocalMods"):
        if root.is_dir():
            for folder in root.iterdir():
                if not folder.is_dir() or not (folder / "filelist.xml").is_file():
                    continue
                item = local_id(folder)
                mod = Mod(item, folder.name, folder, enabled=item in enabled)
                try:
                    package = load_package(folder)
                    mod.name = package.get("name", folder.name)
                    mod.mod_version = package.get("modversion", "")
                    mod.installed_version = mod.mod_version
                    mod.game_version = package.get("gameversion", "")
                    mod.status = "本地模组 / 已启用" if mod.enabled else "本地模组 / 未启用"
                except (AssistantError, OSError) as error:
                    mod.status = f"需要检查：{error}"
                mods.append(mod)
    from .mod_order import read_order
    order = {item: index for index, item in enumerate(read_order(env, strict=False))}
    return sorted(mods, key=lambda m: (not m.enabled,
                                      order.get(m.item_id, -1 if m.enabled else len(order)),
                                      m.name.lower()))


def validate_manifest(folder: Path, env: Environment) -> list[str]:
    root = load_package(folder)
    version = tuple(int(n) for n in re.findall(r"\d+", root.get("gameversion", "1.0")))
    if version and version < (0, 18, 3, 0):
        raise AssistantError("此模组使用旧版路径格式，请用游戏内安装转换")
    warnings = []
    for element in root:
        value = element.get("file")
        if not value:
            raise AssistantError(f"清单中的 {element.tag} 缺少文件路径")
        normalized = value.replace("\\", "/")
        named = re.search(r"%ModDir:([^%]+)%", normalized, re.IGNORECASE)
        if named and named.group(1).casefold() == root.get("name", "").casefold():
            normalized = normalized.replace(named.group(0), "%ModDir%")
        elif named or "%OtherModDir:" in normalized:
            warnings.append(f"外部依赖由游戏检查：{normalized}")
            continue
        if "%ModDir%" in normalized:
            path = Path(normalized.replace("%ModDir%", str(folder)))
            if not within(path, folder):
                raise AssistantError(f"模组路径超出自身目录：{normalized}")
        else:
            path = env.game / normalized
            if not within(path, env.game):
                raise AssistantError(f"模组引用了安装目录外的文件：{normalized}")
        if not path.is_file():
            raise AssistantError(f"缺少模组资源：{normalized}")
    return warnings


@dataclass
class InstallResult:
    item_id: str
    copied: int
    reused: int
    bytes_copied: int
    backup: str
    fingerprint: str
    warnings: list[str] = field(default_factory=list)
    unchanged: bool = False


class Installer:
    def __init__(self, env: Environment, guard: Callable[[str], bool],
                 process_guard=game_running, fault=None):
        self.env = env
        self.guard = guard
        self.process_guard = scoped_game_guard(env, process_guard)
        self.fault = fault or (lambda phase: None)

    def check(self, item_id, cancel):
        if cancel.is_set():
            raise Cancelled("已停止，原有模组保留")
        if self.process_guard():
            raise AssistantError("游戏或服务器正在运行，安装已停止；关闭后可重试")
        if not self.guard(item_id):
            raise AssistantError("Steam 正在更新此模组，等待下载完成后重试")

    def install(self, item_id: str, source: Path, timestamp: int,
                cancel: threading.Event, emit=lambda stage, percent: None) -> InstallResult:
        if not item_id.isdecimal() or not source.is_dir():
            raise AssistantError("模组编号或缓存目录无效")
        if self.env.cache(item_id) is None or source.resolve() != self.env.cache(item_id).resolve():
            raise AssistantError("缓存路径与 Steam 模组编号不匹配")
        self.check(item_id, cancel)
        token = self.env.token(item_id)
        if not token.split(":", 1)[0] or timestamp <= 0:
            raise AssistantError("Steam 没有提供完整版本信息，暂不安装")
        if not self.env.work.parent.exists():
            self.env.work.parent.mkdir(parents=True, exist_ok=True)
        stage_root = self.env.work / "staging"
        backup_root = self.env.work / "backups"
        transactions = self.env.work / "transactions"
        stage = stage_root / (item_id + "-" + uuid.uuid4().hex)
        backup = backup_root / item_id / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        target = self.env.installed / item_id
        journal = transactions / (item_id + ".json")
        for root in (self.env.installed, stage_root, backup_root, transactions):
            root.mkdir(parents=True, exist_ok=True)
            reject_link(root)
        if target.exists():
            reject_link(target)
        if journal.exists():
            raise AssistantError("此模组有未完成的安装记录，请先执行恢复")
        snapshot = files_snapshot(source)
        warnings = validate_manifest(source, self.env)
        source_root = load_package(source)
        if source_root.get("steamworkshopid", item_id) != item_id:
            raise AssistantError("清单的工坊编号与目录不一致")
        receipt_path = self.env.work / "receipts" / (item_id + ".json")
        # A completed verified install can be reused when both trees' file states
        # and the Steam revision remain unchanged. Changed trees take the full hash path.
        try:
            prior = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior = {}
        signatures = {name: list(info) for name, info in snapshot.items()}
        if prior.get("manifest") == token and prior.get("source_snapshot") == signatures and target.is_dir():
            installed_signature = {name: list(info) for name, info in files_snapshot(target).items()}
            if prior.get("installed_snapshot") == installed_signature and prior.get("fingerprint"):
                self.check(item_id, cancel)
                if self.env.token(item_id) == token and files_snapshot(source) == snapshot:
                    emit("已完成", 100)
                    return InstallResult(item_id, 0, max(0, len(snapshot) - 1), 0, "",
                                         prior["fingerprint"], warnings, unchanged=True)
        stage.mkdir()
        previous_moved = False
        committed = False
        copied = reused = bytes_copied = 0
        hashes = {}
        try:
            emit("校验缓存", 0)
            last_check = 0.0
            for position, (relative, info) in enumerate(snapshot.items()):
                if time.monotonic() - last_check > 0.25:
                    self.check(item_id, cancel)
                    last_check = time.monotonic()
                origin = source / relative
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                checksum = digest(origin, cancel)
                hashes[relative] = checksum
                old_file = target / relative
                if relative != "filelist.xml" and old_file.is_file():
                    reject_link(old_file)
                can_reuse = (relative != "filelist.xml" and old_file.is_file()
                             and old_file.stat().st_size == info[0]
                             and digest(old_file, cancel) == checksum)
                if can_reuse:
                    try:
                        os.link(old_file, destination)
                    except OSError:
                        shutil.copy2(old_file, destination)
                    reused += 1
                else:
                    for attempt in range(3):
                        try:
                            shutil.copy2(origin, destination)
                            break
                        except PermissionError:
                            if attempt == 2:
                                raise
                            if cancel.wait(0.2 * (attempt + 1)):
                                raise Cancelled("已停止")
                    copied += 1
                    bytes_copied += info[0]
                if digest(destination, cancel) != checksum:
                    raise AssistantError(f"文件复制校验失败：{relative}")
                emit("安装准备", (position + 1) / max(1, len(snapshot)) * 90)
            # Only the manifest gets installation metadata. All content bytes stay unchanged.
            manifest = stage / "filelist.xml"
            package = ET.parse(manifest)
            package.getroot().set("steamworkshopid", item_id)
            package.getroot().set("installtime", str(timestamp))
            package.write(manifest, encoding="utf-8", xml_declaration=True)
            validate_manifest(stage, self.env)
            if files_snapshot(source) != snapshot or self.env.token(item_id) != token:
                raise AssistantError("缓存版本在安装中发生变化，原有模组已保留")
            self.check(item_id, cancel)
            self.fault("before_commit")
            data = {"id": item_id, "stage": str(stage), "target": str(target),
                    "backup": str(backup), "had_target": target.exists(), "phase": "prepared"}
            atomic_json(journal, data)
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                previous_moved = True
                data["phase"] = "old_moved"
                atomic_json(journal, data)
            self.fault("after_old_moved")
            # Recheck immediately before making the new directory visible to the game.
            self.check(item_id, cancel)
            if self.env.token(item_id) != token:
                raise AssistantError("提交前 Steam 更新了版本")
            os.replace(stage, target)
            committed = True
            data["phase"] = "committed"
            atomic_json(journal, data)
            fingerprint = hashlib.sha256()
            for name, checksum in hashes.items():
                if name != "filelist.xml":
                    fingerprint.update(name.encode("utf-8") + b"\0" + bytes.fromhex(checksum))
            receipt = {"id": item_id, "manifest": token, "timestamp": timestamp,
                       "mod_version": source_root.get("modversion", ""),
                       "fingerprint": fingerprint.hexdigest(), "hashes": hashes,
                       "backup": str(backup) if previous_moved else "", "installed_at": time.time(),
                       "source_snapshot": signatures,
                       "installed_snapshot": {name: list(info) for name, info in files_snapshot(target).items()}}
            atomic_json(receipt_path, receipt)
            journal.unlink()
            emit("已完成", 100)
            return InstallResult(item_id, copied, reused, bytes_copied,
                                 str(backup) if previous_moved else "", fingerprint.hexdigest(), warnings)
        except Exception:
            if previous_moved and not committed and not target.exists():
                os.replace(backup, target)
                previous_moved = False
            if not committed and journal.exists():
                journal.unlink()
            raise
        finally:
            if stage.exists():
                remove_owned_tree(stage, stage_root)

    def recover(self) -> list[str]:
        if self.process_guard():
            raise AssistantError("请先关闭游戏和服务器，再恢复安装记录")
        messages = []
        folder = self.env.work / "transactions"
        if not folder.exists():
            return messages
        for journal in folder.glob("*.json"):
            data = json.loads(journal.read_text(encoding="utf-8"))
            item_id = data["id"]
            if not item_id.isdecimal() or journal.stem != item_id:
                raise AssistantError("恢复记录中的模组编号无效")
            target = Path(data["target"])
            stage = Path(data["stage"])
            backup = Path(data["backup"])
            if target.resolve() != (self.env.installed / item_id).resolve() or not (
                within(stage, self.env.work / "staging") and within(backup, self.env.work / "backups")):
                raise AssistantError("恢复记录包含不合法路径")
            if backup.exists() and not target.exists():
                reject_link(backup)
                os.replace(backup, target)
                messages.append(f"{item_id}：已恢复原有模组")
            elif target.exists():
                load_package(target)
                messages.append(f"{item_id}：安装目录有效，保留现有副本")
            elif data.get("had_target"):
                raise AssistantError(f"{item_id} 的原有副本丢失，需要检查备份")
            else:
                messages.append(f"{item_id}：未提交的新安装已取消")
            if stage.exists():
                remove_owned_tree(stage, self.env.work / "staging")
            journal.unlink()
        return messages

    def restore(self, item_id: str) -> str:
        if self.process_guard():
            raise AssistantError("请先关闭游戏和服务器")
        if not item_id.isdecimal():
            raise AssistantError("模组编号无效")
        folder = self.env.work / "backups" / item_id
        backups = sorted(p for p in folder.iterdir() if p.is_dir()) if folder.exists() else []
        if not backups:
            raise AssistantError("此模组没有上一版备份")
        source = backups[-1]
        reject_link(source)
        load_package(source)
        target = self.env.installed / item_id
        stage_root = self.env.work / "staging"
        stage_root.mkdir(parents=True, exist_ok=True)
        stage = stage_root / (item_id + "-restore-" + uuid.uuid4().hex)
        shutil.copytree(source, stage)
        journal = self.env.work / "transactions" / (item_id + ".json")
        if journal.exists():
            remove_owned_tree(stage, stage_root)
            raise AssistantError("请先恢复未完成安装记录")
        current_backup = folder / (time.strftime("%Y%m%d-%H%M%S") + "-rollback-" + uuid.uuid4().hex[:8])
        atomic_json(journal, {"id": item_id, "stage": str(stage), "target": str(target),
                             "backup": str(current_backup), "had_target": target.exists(), "phase": "prepared"})
        moved = False
        try:
            if self.process_guard():
                raise AssistantError("游戏刚刚启动，恢复已停止")
            if target.exists():
                reject_link(target)
                os.replace(target, current_backup)
                moved = True
            os.replace(stage, target)
            journal.unlink()
            receipt = self.env.work / "receipts" / (item_id + ".json")
            if receipt.exists():
                receipt.unlink()
            return str(source)
        except Exception:
            if moved and not target.exists():
                os.replace(current_backup, target)
            raise
        finally:
            if stage.exists():
                remove_owned_tree(stage, stage_root)
