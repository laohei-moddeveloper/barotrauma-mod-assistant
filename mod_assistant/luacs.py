"""Install the official Windows client patch and enable its C# configuration."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .core import AssistantError, Cancelled, Environment, atomic_json, game_running, reject_link, within

RELEASE_API = "https://api.github.com/repos/evilfactory/LuaCsForBarotrauma/releases/tags/latest"
ASSET_NAME = "luacsforbarotrauma_patch_windows_client.zip"
MODERN_SETTINGS = "Data/Mods/LuaCsForBarotrauma/SettingsData.xml"

RESTORE_GUIDE = "\n".join(('这个按钮只恢复最近一次由助手保存的原文件，不是通用卸载按钮。', '如果安装前已经有 LuaCs，助手可能只备份 C# 设置；恢复设置不会卸载已有 LuaCs。', '没有备份时，继续使用正常的 LuaCs 不需要处理，也不需要反复点击安装。', '若要移除客户端补丁：先关闭游戏和助手，再在 Steam 中打开游戏属性 → 已安装文件 → 验证游戏文件完整性。', '如果 Steam 启动选项含 LuaCs/Luatrauma 自动安装命令，先移除该命令；否则启动游戏时可能再次安装。', '依赖 LuaCs/C# 的模组需要脚本支持；卸载前先在游戏里停用这些模组。', '验证完整性还原游戏原版文件，与恢复助手安装前的状态不同。'))


@dataclass
class RestoreInfo:
    available: bool
    text: str
    journal: dict | None = None


def restore_info(env: Environment) -> RestoreInfo:
    path = env.work / 'luacs/last-install.json'
    try:
        if not path.exists():
            return RestoreInfo(False, '没有助手安装备份；恢复操作不可用。当前 LuaCs 不受影响。')
        if path.stat().st_size > 1_000_000:
            raise ValueError('Oversized journal')
        journal = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(journal, dict) or journal.get('state') not in ('complete', 'restored'):
            raise ValueError('Invalid state')
        if journal['state'] == 'restored':
            return RestoreInfo(False, '最近一次助手备份已经恢复，暂无新的可恢复安装。')
        backup = Path(journal['backup'])
        if not within(backup, env.work / 'luacs/backups') or not backup.is_dir():
            raise ValueError('Missing backup')
        records = journal['records']
        if not isinstance(records, list) or not records or len(records) > 502:
            raise ValueError('Invalid records')
        names = set()
        for record in records:
            name = record['name']
            if not isinstance(name, str) or not name or name.casefold() in names:
                raise ValueError('Invalid file')
            relative = PurePosixPath(name.replace('\\', '/'))
            if relative.is_absolute() or '..' in relative.parts or not relative.parts or ':' in name:
                raise ValueError('Invalid path')
            names.add(name.casefold())
            if not within(env.game / name, env.game) or not within(backup / name, backup):
                raise ValueError('Invalid path')
            if type(record['existed']) is not bool or not re.fullmatch('[a-f0-9]{64}', record['new_hash']):
                raise ValueError('Invalid record')
            if record['existed'] and (not re.fullmatch('[a-f0-9]{64}', record['old_hash']) or not (backup / name).is_file()):
                raise ValueError('Missing file')
        text = ('助手完整安装备份可用；只恢复助手更改的文件，操作前会校验。'
                if 'barotrauma.dll' in names else
                '助手设置备份可用；恢复只撤销设置更改，不会卸载原有 LuaCs。')
        return RestoreInfo(True, text, journal)
    except (OSError, ValueError, TypeError, KeyError):
        return RestoreInfo(False, '助手备份记录损坏或文件缺失，暂不可恢复；原文件未改动。')


@dataclass
class LuaCsStatus:
    runtime: bool
    csharp: bool
    text: str


def status(env: Environment) -> LuaCsStatus:
    try:
        assembly = (env.game / "Barotrauma.dll").read_bytes()
        runtime = b"LuaCs" in assembly and all(
            (env.game / name).is_file() for name in ("BarotraumaCore.dll", "MoonSharp.Interpreter.dll"))
    except OSError:
        assembly = b""
        runtime = False
    try:
        if b"CsRunPolicy" in assembly or (env.game / MODERN_SETTINGS).exists():
            root = ET.fromstring((env.game / MODERN_SETTINGS).read_bytes())
            setting = root.find("LuaCsForBarotrauma/CsRunPolicy")
            csharp = setting is not None and setting.get("Value", "").casefold() == "enabled"
        else:
            root = ET.fromstring((env.game / "LuaCsSetupConfig.xml").read_bytes())
            csharp = root.get("EnableCsScripting", "false").casefold() == "true"
    except (OSError, ET.ParseError):
        csharp = False
    text = "LuaCs 已安装 · C# 已开启" if runtime and csharp else (
        "LuaCs 已安装 · C# 未开启" if runtime else "LuaCs 客户端未完整检出")
    return LuaCsStatus(runtime, csharp, text)


def release_info() -> dict:
    request = urllib.request.Request(RELEASE_API, headers={"User-Agent": "BarotraumaModAssistant"})
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset:
        raise AssistantError("官方发布中没有 Windows 客户端补丁")
    digest = asset.get("digest", "")
    url = asset.get("browser_download_url", "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) or not url.startswith(
            "https://github.com/evilfactory/LuaCsForBarotrauma/releases/download/"):
        raise AssistantError("官方补丁缺少可验证的下载信息，暂不安装")
    return {"url": url, "sha256": digest.split(":", 1)[1].lower(),
            "size": int(asset.get("size", 0)), "release": release.get("published_at", "")}


def cs_config(env: Environment) -> bytes:
    path = env.game / "LuaCsSetupConfig.xml"
    if path.exists():
        data = path.read_bytes()
        try:
            root = ET.fromstring(data)
        except ET.ParseError as error:
            raise AssistantError("LuaCs 设置文件损坏，保留原文件，未开启 C#") from error
        if root.tag != "LuaCsSetupConfig":
            raise AssistantError("LuaCs 设置格式不受支持")
        if root.get("EnableCsScripting", "false").casefold() == "true":
            return data
        root.set("EnableCsScripting", "true")
    else:
        root = ET.Element("LuaCsSetupConfig", {"EnableCsScripting": "true"})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def modern_cs_config(env: Environment) -> bytes:
    path = env.game / MODERN_SETTINGS
    if path.exists():
        original = path.read_bytes()
        try:
            root = ET.fromstring(original)
        except ET.ParseError as error:
            raise AssistantError("LuaCs 新版设置文件损坏，未改动原设置") from error
        if root.tag != "Configuration":
            raise AssistantError("LuaCs 新版设置格式不受支持")
    else:
        original = b""
        root = ET.Element("Configuration")
    package = root.find("LuaCsForBarotrauma")
    if package is None:
        package = ET.SubElement(root, "LuaCsForBarotrauma")
    policy = package.find("CsRunPolicy")
    if policy is None:
        policy = ET.SubElement(package, "CsRunPolicy")
    if policy.get("Value", "").casefold() == "enabled" and original:
        return original
    policy.set("Value", "Enabled")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LuaCsInstaller:
    def __init__(self, env: Environment, emit=lambda message: None, process_guard=game_running,
                 release_loader=release_info, opener=urllib.request.urlopen, fault=lambda phase: None):
        self.env, self.emit, self.process_guard = env, emit, process_guard
        self.release_loader, self.opener, self.fault = release_loader, opener, fault
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set():
            raise Cancelled("LuaCs 安装已停止")
        if self.process_guard():
            raise AssistantError("请先关闭游戏和服务器，再安装 LuaCs 或开启 C#")

    def download(self, info: dict) -> Path:
        folder = self.env.work / "luacs" / "downloads"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (info["sha256"] + ".zip")
        if path.is_file() and _hash(path) == info["sha256"]:
            self.emit("沿用已校验的 LuaCs 官方补丁")
            return path
        temporary = path.with_suffix(".tmp")
        total, digest = 0, hashlib.sha256()
        try:
            with self.opener(info["url"], timeout=30) as response, temporary.open("wb") as stream:
                while True:
                    self.check()
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 100_000_000:
                        raise AssistantError("补丁下载大小超出预期")
                    digest.update(chunk)
                    stream.write(chunk)
                    self.emit(f"下载 LuaCs 补丁：{total / 1048576:.1f} MB")
            if digest.hexdigest() != info["sha256"] or total != info["size"]:
                raise AssistantError("LuaCs 补丁校验失败，请重试")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path

    def payload(self, archive: Path) -> dict[str, bytes]:
        with ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > 500 or sum(x.file_size for x in entries) > 250_000_000:
                raise AssistantError("LuaCs 补丁解压大小超出预期")
            files = {}
            folded = set()
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or ":" in name
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise AssistantError("补丁包含不安全的文件路径")
                if entry.is_dir():
                    continue
                if name.casefold() in folded:
                    raise AssistantError("补丁包含重复文件路径")
                folded.add(name.casefold())
                if not within(self.env.game / name, self.env.game):
                    raise AssistantError("补丁路径超出游戏目录")
                files[name] = zipped.read(entry)
            required = {"Barotrauma.dll", "DedicatedServer.dll", "BarotraumaCore.dll",
                        "MoonSharp.Interpreter.dll", "Barotrauma.deps.json"}
            if not required.issubset(files) or b"LuaCs" not in files["Barotrauma.dll"]:
                raise AssistantError("下载文件不是完整的 LuaCs 客户端补丁")
            vanilla = ET.parse(self.env.game / "Content/ContentPackages/Vanilla.xml").getroot()
            game_version = vanilla.get("gameversion", "")
            match = re.search(rb'"Barotrauma/([0-9.]+)"', files["Barotrauma.deps.json"])
            if not match or not game_version or match[1].decode() != game_version:
                raise AssistantError("LuaCs 官方补丁与本机游戏版本不一致，未修改游戏文件")
            return files

    def install(self) -> dict:
        self.check()
        self.recover()
        detected = status(self.env)
        if detected.runtime and detected.csharp:
            return {"changed": False, "message": "LuaCs 和 C# 已就绪，无需重复安装", "backup": ""}
        files = {}
        if not detected.runtime:
            self.emit("正在读取 LuaCs 官方发布信息…")
            info = self.release_loader()
            archive = self.download(info)
            self.emit("正在核对补丁与游戏版本…")
            files = self.payload(archive)
        files["LuaCsSetupConfig.xml"] = cs_config(self.env)
        files[MODERN_SETTINGS] = modern_cs_config(self.env)
        files = {name: data for name, data in files.items()
                 if not (self.env.game / name).is_file() or (self.env.game / name).read_bytes() != data}
        if not files:
            return {"changed": False, "message": "LuaCs 和 C# 已就绪", "backup": ""}
        self.check()
        root = self.env.work / "luacs"
        backup = root / "backups" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        records = []
        for name, data in files.items():
            target = self.env.game / name
            for parent in [target] + list(target.parents):
                if within(parent, self.env.game) and parent.exists():
                    reject_link(parent)
            existed = target.is_file()
            old_hash = _hash(target) if existed else ""
            if existed:
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                if _hash(saved) != old_hash:
                    raise AssistantError("游戏文件备份时发生变化，安装已停止")
            records.append({"name": name, "existed": existed, "old_hash": old_hash,
                            "new_hash": hashlib.sha256(data).hexdigest()})
        journal = {"backup": str(backup), "records": records, "written": [], "state": "pending"}
        atomic_json(root / "transaction.json", journal)
        try:
            for record in records:
                self.check()
                name = record["name"]
                target = self.env.game / name
                if target.is_file() != record["existed"] or (record["existed"] and _hash(target) != record["old_hash"]):
                    raise AssistantError("游戏文件被其他程序修改，安装已停止")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + "." + uuid.uuid4().hex[:8] + ".assistant.tmp")
                try:
                    temporary.write_bytes(files[name])
                    # Record before replacement so crash recovery can inspect either hash.
                    journal["written"].append(name)
                    atomic_json(root / "transaction.json", journal)
                    os.replace(temporary, target)
                finally:
                    if temporary.exists():
                        temporary.unlink()
                self.emit("安装 LuaCs：" + name)
                self.fault("replaced")
            self.check()
            journal["state"] = "complete"
            atomic_json(root / "transaction.json", journal)
            atomic_json(root / "last-install.json", journal)
        except Exception:
            self._restore(journal, partial=True)
            journal["state"] = "rolled_back"
            atomic_json(root / "transaction.json", journal)
            raise
        return {"changed": True, "message": "LuaCs 客户端和 C# 已就绪；下次启动游戏生效", "backup": str(backup)}

    def _restore(self, journal: dict, partial=False):
        backup = Path(journal["backup"])
        if not within(backup, self.env.work / "luacs" / "backups"):
            raise AssistantError("LuaCs 备份路径无效")
        allowed = set(journal.get("written", [])) if partial else {x["name"] for x in journal["records"]}
        records = [x for x in journal["records"] if x["name"] in allowed]
        for record in records:
            target = self.env.game / record["name"]
            if not within(target, self.env.game):
                raise AssistantError("LuaCs 恢复路径无效")
            for parent in [target] + list(target.parents):
                if within(parent, self.env.game) and parent.exists():
                    reject_link(parent)
            value = _hash(target) if target.is_file() else ""
            if value not in (record["new_hash"], record["old_hash"]):
                raise AssistantError("LuaCs 文件后来已被修改，保留备份，请通过 Steam 检查游戏完整性")
            if record["existed"]:
                saved = backup / record["name"]
                if not within(saved, backup) or _hash(saved) != record["old_hash"]:
                    raise AssistantError("LuaCs 备份校验失败")
        for record in reversed(records):
            if not partial:
                self.check()
            target = self.env.game / record["name"]
            if record["existed"]:
                saved = backup / record["name"]
                if _hash(saved) != record["old_hash"]:
                    raise AssistantError("LuaCs 备份校验失败")
                temporary = target.with_name(target.name + ".restore.tmp")
                shutil.copy2(saved, temporary)
                os.replace(temporary, target)
            elif target.exists():
                target.unlink()

    def recover(self):
        path = self.env.work / "luacs" / "transaction.json"
        if path.is_file():
            journal = json.loads(path.read_text(encoding="utf-8"))
            if journal.get("state") == "pending":
                self.check()
                self._restore(journal, partial=True)
                journal["state"] = "rolled_back"
                atomic_json(path, journal)
                self.emit("已恢复上次未完成的 LuaCs 安装")

    def restore(self):
        self.check()
        self.recover()
        path = self.env.work / "luacs" / "last-install.json"
        info = restore_info(self.env)
        if not info.available:
            raise AssistantError(info.text)
        journal = info.journal
        self._restore(journal)
        journal["state"] = "restored"
        atomic_json(path, journal)
        atomic_json(self.env.work / "luacs" / "transaction.json", journal)
