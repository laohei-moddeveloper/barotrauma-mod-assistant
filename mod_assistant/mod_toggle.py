"""Edit only the game's selected content-package XML block while the game is closed."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import uuid
import xml.etree.ElementTree as ET

from .core import AssistantError, Environment, game_running, load_package, within, scoped_game_guard
from .game_config import PackageRegion, package_regions


BLOCK = PackageRegion(0)
CORE = PackageRegion(1)
WORKSHOP_PATH = re.compile(r"(?:^|/)workshopmods/installed/(\d+)/filelist\.xml$", re.I)


def configured_id(value: str) -> str | None:
    match = WORKSHOP_PATH.search(value.replace("\\", "/"))
    return match.group(1) if match else None


def local_id(folder: Path) -> str:
    key = folder.resolve().as_posix().casefold().encode("utf-8")
    return "local:" + hashlib.sha256(key).hexdigest()[:16]


def configured_key(value: str, env: Environment) -> str | None:
    item = configured_id(value)
    if item:
        return item
    path = Path(value.replace("\\", "/"))
    if not path.is_absolute():
        path = env.game / path
    if path.name.casefold() != "filelist.xml":
        return None
    for root in (env.game / "LocalMods", env.player / "LocalMods"):
        if within(path, root) and path.is_file():
            return local_id(path.parent)
    return None


def enabled_ids(env: Environment) -> set[str]:
    path = env.game / "config_player.xml"
    try:
        text=path.read_bytes().decode('utf-8-sig')
        regular,core=package_regions(text)
        if regular is None or core is None: raise AssistantError('游戏内容包配置格式不受支持')
        roots=[ET.fromstring(region.group()) for region in (regular,core)]
    except (OSError, UnicodeError, ET.ParseError) as error:
        raise AssistantError(f"无法读取游戏模组配置：{error}") from error
    ids = set()
    for element in (element for root in roots for element in root.iter()):
        if element.tag.lower() in ("package", "corepackage"):
            item = configured_key(element.get("path", ""), env)
            if item:
                ids.add(item)
    return ids


@dataclass
class ToggleResult:
    item_id: str
    enabled: bool
    backup: str
    changed: bool


def set_enabled(env: Environment, item_id: str, enabled: bool,
                process_guard=game_running, source: Path | None = None) -> ToggleResult:
    process_guard = scoped_game_guard(env, process_guard)
    is_workshop = item_id.isdecimal()
    if not is_workshop and (source is None or local_id(source) != item_id or not any(
            within(source, root) for root in (env.game / "LocalMods", env.player / "LocalMods"))):
        raise AssistantError("本地模组路径或编号无效")
    if process_guard():
        raise AssistantError("请先关闭游戏和服务器，再切换模组启用状态")
    config = env.game / "config_player.xml"
    target = (env.installed / item_id if is_workshop else source) / "filelist.xml"
    if enabled:
        if not target.is_file():
            raise AssistantError("模组尚未安装，请先更新此模组")
        package = load_package(target.parent)
        is_core = package.get("corepackage", "false").casefold() == "true"
    else:
        is_core = False
    try:
        original = config.read_bytes()
        document = ET.fromstring(original)
        source = original.decode("utf-8-sig")
    except (OSError, UnicodeError, ET.ParseError) as error:
        raise AssistantError(f"无法读取游戏模组配置：{error}") from error
    section = next((x for x in document.iter() if x.tag.lower() == "contentpackages"), None)
    if section is None:
        raise AssistantError("游戏配置缺少 contentpackages，无法安全切换模组")
    regular = next((x for x in section if x.tag.lower() == "regularpackages"), None)
    core = next((x for x in section if x.tag.lower() == "corepackage"), None)
    if regular is None or core is None:
        raise AssistantError("游戏配置缺少核心或普通模组列表")
    block, core_block = package_regions(source)
    if block is None or core_block is None:
        raise AssistantError("游戏配置的模组区域格式不受支持，请在游戏内调整")
    current_regular = [x for x in regular if x.tag.lower() == "package"]
    has_regular = any(configured_key(x.get("path", ""), env) == item_id for x in current_regular)
    has_core = configured_key(core.get("path", ""), env) == item_id
    if ((enabled and is_core and has_core and not has_regular)
            or (enabled and not is_core and has_regular and not has_core)
            or (not enabled and not has_regular and not has_core)):
        return ToggleResult(item_id, enabled, "", False)
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    edit_regular = ET.fromstring(block.group(), parser=parser)
    for child in list(edit_regular):
        if isinstance(child.tag, str) and child.tag.casefold() == "package" and configured_key(child.get("path", ""), env) == item_id:
            edit_regular.remove(child)
    path_value = (target.relative_to(env.game).as_posix() if within(target, env.game)
                  else target.as_posix())
    new_core = core_block.group()
    if enabled and is_core:
        core_element = ET.fromstring(new_core)
        core_element.set("path", path_value)
        new_core = ET.tostring(core_element, encoding="unicode")
    elif has_core and not enabled:
        core_element = ET.fromstring(new_core)
        core_element.set("path", "Content/ContentPackages/Vanilla.xml")
        new_core = ET.tostring(core_element, encoding="unicode")
    elif enabled:
        child = ET.Element("package", {"path": path_value})
        existing = list(edit_regular)
        newline = "\r\n" if "\r\n" in source else "\n"
        if existing:
            last = existing[-1]
            closing_tail = last.tail or (newline + "    ")
            last.tail = newline + "      "
            child.tail = closing_tail
        else:
            edit_regular.text = newline + "      "
            child.tail = newline + "    "
        edit_regular.append(child)
    new_regular = ET.tostring(edit_regular, encoding="unicode")
    newline = "\r\n" if "\r\n" in source else "\n"
    new_regular = new_regular.replace("\n", newline)
    # Replace in descending offset order to keep the untouched settings byte-for-byte.
    replacements = [(block.start(), block.end(), new_regular),
                    (core_block.start(), core_block.end(), new_core)]
    updated = source
    for start, end, value in sorted(replacements, reverse=True):
        updated = updated[:start] + value + updated[end:]
    if updated == source:
        return ToggleResult(item_id, enabled, "", False)
    suffix = uuid.uuid4().hex[:8]
    backups = env.work / "config-backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / (time.strftime("%Y%m%d-%H%M%S") + "-" + suffix + ".xml")
    with backup.open("xb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    replacement = (b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"") + updated.encode("utf-8")
    temporary = config.with_name(config.name + "." + suffix + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(config.stat().st_mode))
        if process_guard():
            raise AssistantError("游戏刚刚启动，启用状态未更改")
        if config.read_bytes() != original:
            raise AssistantError("游戏配置刚刚被其他程序修改，请重新检测后重试")
        os.replace(temporary, config)
    finally:
        if temporary.exists():
            temporary.unlink()
    return ToggleResult(item_id, enabled, str(backup), True)
