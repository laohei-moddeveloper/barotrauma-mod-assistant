"""Explainable, conservative mod type and compatibility estimates."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .core import APP_ID, AssistantError, Cancelled, Environment, Mod, atomic_json, load_package, within, mod_files, reject_link


KIND_BY_TAG = {
    "item": "物品/装备", "structure": "物品/装备", "submarine": "潜艇/舰船",
    "character": "生物/敌人", "npcsets": "生物/敌人",
    "afflictions": "医疗/状态", "jobs": "职业/天赋", "talents": "职业/天赋",
    "talenttrees": "职业/天赋", "missions": "任务/事件", "randomevents": "任务/事件",
    "eventmanagersettings": "任务/事件", "disembarkperk": "任务/事件",
    "outpostmodule": "地图/站点", "outpostconfig": "地图/站点",
    "locationtypes": "地图/站点", "levelobjectprefabs": "地图/站点",
    "mapgenerationparameters": "地图/站点", "wreck": "地图/站点",
    "beaconstation": "地图/站点", "text": "语言/文本", "uistyle": "界面/音效",
    "sounds": "界面/音效", "particles": "界面/音效",
    "serverexecutable": "框架/脚本", "clientexecutable": "框架/脚本",
}
SYSTEM_KINDS = {"医疗/状态", "职业/天赋", "任务/事件", "地图/站点"}
DEFINITION_TAGS = {"item", "structure", "character", "afflictions", "jobs", "talents",
                   "talenttrees", "missions", "randomevents", "locationtypes",
                   "levelobjectprefabs", "mapgenerationparameters", "outpostconfig", "npcsets"}
PATH_REF = re.compile(r"%(?:Other)?ModDir:([^%]+)%", re.I)
ADDON_NAME = re.compile(r"汉化|翻译|localization|translation|补丁|patch|addon|expansion|rebalance|整合", re.I)
LUA_ADD = re.compile(r'\bHook\.Add\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]', re.I)
LUA_PATCH = re.compile(r'\bHook\.Patch\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"](?:\s*,\s*[\'"]([^\'"]+)[\'"])?', re.I)
CS_PATCH = re.compile(r'\[HarmonyPatch\s*\(\s*typeof\s*\(\s*([\w.]+)\s*\)\s*,\s*(?:nameof\s*\(\s*[\w.]+\.([\w]+)\s*\)|[\'"]([^\'"]+)[\'"])', re.I)
LUA_GLOBAL = re.compile(r'\b((?:NTC|NT|Tsm|TSM|EHA|EW)\.[A-Za-z_]\w*)\s*=\s*(?![=])')
PREFAB_TAGS = {
    "item": {"item"}, "structure": {"structure"}, "character": {"character"},
    "afflictions": {"affliction"}, "jobs": {"job"}, "talents": {"talent"},
    "talenttrees": {"talenttree"}, "locationtypes": {"locationtype"},
    "levelobjectprefabs": {"levelobjectprefab", "levelobject"},
    "mapgenerationparameters": {"mapgenerationparameters", "levelgenerationparameters"},
    "outpostconfig": {"outpostconfig"}, "npcsets": {"npc", "npcset"},
}


@dataclass
class Features:
    item_id: str
    name: str
    kinds: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    definitions: set[tuple[str, str, str]] = field(default_factory=set)
    path_dependencies: set[str] = field(default_factory=set)
    workshop_dependencies: set[str] = field(default_factory=set)
    core: bool = False
    partial: bool = False
    hook_names: set[tuple[str, str]] = field(default_factory=set)
    hook_events: set[str] = field(default_factory=set)
    patches: set[tuple[str, str]] = field(default_factory=set)
    globals_written: set[str] = field(default_factory=set)
    code_files: int = 0
    opaque_code: int = 0
    overrides: set[tuple[str, str, str]] = field(default_factory=set)
    definition_files: dict[str, list[str]] = field(default_factory=dict)
    csharp_files: int = 0
    deferred: bool = False


@dataclass
class Assessment:
    item_id: str
    kinds: tuple[str, ...]
    importance: str
    compatibility: str
    reasons: list[str]
    compared: int = 0
    risky_pairs: int = 0
    evidence: str = "静态线索"
    pairs: list[dict] = field(default_factory=list)


def workshop_details(env: Environment, ids: list[str], allow_network=True, force=False,
                     cancel=None, emit=lambda message: None) -> tuple[dict, bool]:
    """Reuse validated public metadata; temporary failures get a short retry delay."""
    ids = list(dict.fromkeys(item for item in ids if isinstance(item, str) and item.isdecimal()))
    cache = env.work / "analysis" / "workshop-details.json"
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(saved, dict): saved = {}
    except (OSError, ValueError):
        saved = {}
    raw = saved.get('entries', {})
    entries = {}
    if isinstance(raw, dict):
        for item, value in raw.items():
            if (isinstance(item, str) and item.isdecimal() and isinstance(value, dict)
                    and isinstance(value.get('tags', []), list) and isinstance(value.get('children', []), list)):
                entries[item] = {'tags':[tag for tag in value.get('tags', []) if isinstance(tag, str)],
                                 'children':[child for child in value.get('children', []) if isinstance(child, str) and child.isdecimal()]}
    now = time.time()
    fetched = saved.get('fetched_at', 0)
    retry = saved.get('retry_after', 0)
    recent = type(fetched) in (int, float) and 0 <= now - fetched < 86400
    waiting = type(retry) in (int, float) and now < retry <= now + 60
    if not ids or not allow_network or waiting or (not force and recent and set(ids).issubset(entries)):
        return entries, bool(entries)
    try:
        for index in range(0, len(ids), 75):
            if cancel and cancel.is_set(): raise Cancelled('分析已停止')
            batch = ids[index:index + 75]
            data = {"itemcount": len(batch)}
            data.update({f"publishedfileids[{n}]": item for n, item in enumerate(batch)})
            request = urllib.request.Request(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data=urllib.parse.urlencode(data).encode("ascii"), method="POST")
            with urllib.request.urlopen(request, timeout=9) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get('response'), dict):
                raise ValueError('Invalid metadata response')
            values = payload['response'].get('publishedfiledetails')
            if not isinstance(values, list): raise ValueError('Invalid metadata list')
            for value in values:
                if not isinstance(value, dict): continue
                item = str(value.get("publishedfileid", ""))
                if item in batch and value.get("result") == 1 and value.get("consumer_app_id") == APP_ID:
                    tags, children = value.get('tags', []), value.get('children', [])
                    if not isinstance(tags, list) or not isinstance(children, list):
                        raise ValueError('Invalid dependency data')
                    entries[item] = {
                        "tags": [x['tag'] for x in tags if isinstance(x, dict) and isinstance(x.get('tag'), str)],
                        "children": [str(x.get("publishedfileid", "")) for x in children
                                     if isinstance(x, dict) and str(x.get("publishedfileid", "")).isdecimal()],
                    }
        state = {"fetched_at": time.time(), "entries": entries}
        available = True
    except (OSError, ValueError, KeyError, TypeError):
        emit('公开资料查询暂不可用，沿用已有资料；一分钟内不重复请求。')
        state = {'fetched_at': fetched if type(fetched) in (int, float) else 0,
                 'retry_after': time.time() + 60, 'entries': entries}
        available = bool(entries)
    if cancel and cancel.is_set(): raise Cancelled('分析已停止')
    try:
        atomic_json(cache, state)
    except OSError:
        emit('公开资料缓存无法保存；本次已读取的资料仍可使用。')
    return entries, available


def _resource_path(folder: Path, name: str, own_name: str) -> Path | None:
    value = name.replace("\\", "/")
    for match in PATH_REF.finditer(value):
        if match.group(1).casefold() != own_name.casefold():
            return None
        value = value.replace(match.group(), "%ModDir%")
    if not value.startswith("%ModDir%/"):
        return None
    path = folder / value[len("%ModDir%/"):]
    if not within(path, folder) or not path.is_file():
        return None
    for part in [path, *path.parents]:
        reject_link(part)
        if part == folder:
            break
    return path


def _definitions(path: Path, category: str) -> set[tuple[str, str, str]]:
    return _definition_info(path, category)[0]


def _definition_info(path: Path, category: str):
    found = set()
    overrides = set()
    root = ET.parse(path).getroot()
    wrapped_elements = {element for node in root.iter() if node.tag.casefold() == 'override' for element in node.iter()}
    candidates = [root] + list(root)
    for child in list(root):
        if child.tag.casefold() == "override":
            candidates.extend(list(child))
            for group in child:
                candidates.extend(list(group))
    for element in candidates:
        identifier = element.get("identifier", "").strip().casefold()
        tag = element.tag.casefold()
        allowed = PREFAB_TAGS.get(category)
        if category == "missions":
            allowed_match = tag.endswith("mission")
        elif category == "randomevents":
            allowed_match = tag in {"eventset", "event"} or tag.endswith("eventprefab")
        else:
            allowed_match = allowed is not None and tag in allowed
        if identifier and allowed_match:
            key = (category, element.tag.casefold(), identifier)
            found.add(key)
            if element in wrapped_elements: overrides.add(key)
    return found, overrides


def _code_signals(folder: Path, result: Features):
    for path in mod_files(folder):
        if not path.is_file():
            continue
        if not within(path, folder) or path.is_symlink():
            result.partial = True
            continue
        suffix = path.suffix.casefold()
        if suffix == ".dll":
            result.opaque_code += 1
            continue
        if suffix not in (".lua", ".cs"):
            continue
        result.code_files += 1
        if suffix == ".cs": result.csharp_files += 1
        try:
            if path.stat().st_size > 2_000_000:
                result.partial = True
                continue
            source = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            result.partial = True
            continue
        # Strip only whole-line comments. The scanner deliberately stays
        # conservative: dynamic hook arguments and generated code are unknown.
        marker = "--" if suffix == ".lua" else "//"
        source = "\n".join(line for line in source.splitlines()
                           if not line.lstrip().startswith(marker))
        result.hook_names.update((event.casefold(), name.casefold()) for event, name in LUA_ADD.findall(source))
        result.hook_events.update(event.casefold() for event, _ in LUA_ADD.findall(source))
        result.patches.update(((method_or_owner if named_method else owner_or_id).casefold(),
                               (named_method or method_or_owner).casefold())
                              for owner_or_id, method_or_owner, named_method in LUA_PATCH.findall(source))
        result.patches.update((owner.casefold(), (named or literal).casefold())
                              for owner, named, literal in CS_PATCH.findall(source))
        result.globals_written.update(name.casefold() for name in LUA_GLOBAL.findall(source))


def inspect(mod: Mod, metadata: dict | None = None) -> Features:
    metadata = metadata or {}
    result = Features(mod.item_id, mod.name,
                      workshop_dependencies=set(metadata.get("children", [])))
    if mod.source is None or not (mod.source / "filelist.xml").is_file():
        result.partial = True
        return result
    try:
        root = load_package(mod.source)
        result.core = root.get("corepackage", "false").casefold() == "true"
        tags = [element.tag.casefold() for element in root]
        result.tags = tuple(sorted(set(tags)))
        kinds = {KIND_BY_TAG[x] for x in tags if x in KIND_BY_TAG}
        name = mod.name.casefold()
        external_tags = {str(x).casefold() for x in metadata.get("tags", [])}
        if (result.core or "framework" in name or "library" in external_tags
                or any(x in tags for x in ("serverexecutable", "clientexecutable"))):
            kinds.add("框架/脚本")
        if "汉化" in name or "翻译" in name or "localization" in name or "translation" in name:
            kinds.add("语言/文本")
        if "neurotrauma" in name or "医疗" in name:
            kinds.add("医疗/状态")
        if "patch" in name or "补丁" in name or "rebalance" in name:
            kinds.add("补丁/调整")
        if "lua" in name or "(cs)" in name:
            kinds.add("脚本/工具")
        if kinds - {"语言/文本", "界面/音效"} and not re.search(
                r"汉化|翻译|localization|translation", name, re.I):
            kinds.discard("语言/文本")
        if kinds - {"语言/文本", "界面/音效"}:
            kinds.discard("界面/音效")
        if not kinds:
            kinds.add("其他")
        weights = {"框架/脚本": 0, "脚本/工具": 1, "补丁/调整": 2, "医疗/状态": 3,
                   "地图/站点": 3, "任务/事件": 4, "生物/敌人": 5,
                   "职业/天赋": 6, "物品/装备": 7, "潜艇/舰船": 8,
                   "语言/文本": 9, "界面/音效": 10, "其他": 11}
        if "语言/文本" in kinds and ADDON_NAME.search(name):
            weights["语言/文本"] = -1
        result.kinds = tuple(sorted(kinds, key=lambda x: weights.get(x, 99)))
        for element in root:
            filename = element.get("file", "")
            for dependency in PATH_REF.findall(filename):
                if dependency.casefold() != mod.name.casefold():
                    result.path_dependencies.add(dependency)
            tag = element.tag.casefold()
            if tag not in DEFINITION_TAGS or not filename.lower().endswith(".xml"):
                continue
            path = _resource_path(mod.source, filename, mod.name)
            if path is None:
                result.partial = True
                continue
            try:
                if path.stat().st_size > 8_000_000:
                    result.partial = True
                    continue
                definitions, overrides = _definition_info(path, tag)
                result.definitions.update(definitions)
                result.overrides.update(overrides)
                for key in definitions:
                    result.definition_files.setdefault("|".join(key), []).append(path.relative_to(mod.source).as_posix())
            except (OSError, ET.ParseError):
                result.partial = True
        _code_signals(mod.source, result)
        if result.code_files and "框架/脚本" not in result.kinds and "脚本/工具" not in result.kinds:
            result.kinds = result.kinds + ("脚本/工具",)
        return result
    except (OSError, ET.ParseError, AssistantError):
        result.partial = True
        return result


def inspect_all(mods: list[Mod], metadata: dict | None = None) -> dict[str, Features]:
    metadata = metadata or {}
    return {mod.item_id: inspect(mod, metadata.get(mod.item_id)) for mod in mods}


def luacs_runtime_detected(env: Environment) -> bool | None:
    from .luacs import status
    return status(env).runtime


def pair_evidence(left: Features, right: Features) -> tuple[int, str]:
    overlaps = left.definitions & right.definitions
    same_names = left.hook_names & right.hook_names
    patches = left.patches & right.patches
    globals_written = left.globals_written & right.globals_written
    signals=[]
    if same_names:
        example = next(iter(sorted(same_names)))
        signals.append((3, f"Lua Hook.Add 重复注册 {example[0]}/{example[1]}，名称可能互相覆盖"))
    if globals_written:
        example = next(iter(sorted(globals_written)))
        signals.append((2, f"脚本都写入共享变量 {example}，执行顺序可能改变结果"))
    if patches:
        example = next(iter(sorted(patches)))
        signals.append((2, f"脚本都修改方法 {example[0]}.{example[1]}，需核对补丁顺序"))
    if overlaps:
        example = "、".join(sorted({definition[2] for definition in overlaps})[:2])
        category = "、".join(sorted({definition[0] for definition in overlaps})[:2])
        unmarked = overlaps - left.overrides - right.overrides
        if unmarked:
            signals.append((3, f"同标识普通定义 {len(unmarked)} 个（如 {example}），未声明 Override；排序通常不能解决重复注册"))
        else:
            signals.append((1, f"XML 明确声明 Override，涉及 {len(overlaps)} 个{category}定义（如 {example}）；需确认期望覆盖结果"))
    return max((x[0] for x in signals),default=0), '；'.join(x[1] for x in signals)


def evaluate(mods: list[Mod], features: dict[str, Features],
             runtime_luacs: bool | None = None, order=None, csharp=None) -> dict[str, Assessment]:
    active = {mod.item_id for mod in mods if mod.enabled}
    names = {feature.name.casefold(): item for item, feature in features.items()}
    pair_signals = defaultdict(list)
    # Only shared facts can trigger pair_evidence. Index those facts once, rather
    # than comparing every unrelated pair. Preserve original pair iteration order.
    index = defaultdict(list)
    candidates = set()
    for number, mod in enumerate(mods):
        feature = features.get(mod.item_id)
        if feature is None:
            continue
        for kind in ('definitions', 'hook_names', 'patches', 'globals_written'):
            for value in getattr(feature, kind):
                key = (kind, value)
                for previous in index[key]:
                    candidates.add((previous, number))
                index[key].append(number)
    for first_index, second_index in sorted(candidates):
        left, right = mods[first_index], mods[second_index]
        score, reason = pair_evidence(features[left.item_id], features[right.item_id])
        if score:
            pair_signals[left.item_id].append((score, right, reason))
            pair_signals[right.item_id].append((score, left, reason))
    result = {}
    for mod in mods:
        feature = features.get(mod.item_id, Features(mod.item_id, mod.name, partial=True))
        reasons, severity = [], 0
        missing = [item for item in sorted(feature.workshop_dependencies) if item not in active
                   and not (item == "2559634234" and runtime_luacs is True)]
        if missing:
            labels = [features[x].name if x in features else x for x in missing]
            reasons.append("发布者标注的依赖未启用：" + "、".join(labels[:3]))
            severity = 3
        for name in sorted(feature.path_dependencies):
            dependency = names.get(name.casefold())
            if dependency is None or dependency not in active:
                reasons.append(f"资源路径需要另一模组：{name}（未检测到启用）")
                severity = 3
        if runtime_luacs is False and feature.code_files:
            reasons.append(f"含 {feature.code_files} 个 Lua/C# 文件；本机游戏主程序未检出 LuaCs，脚本功能需先核实")
            severity = max(severity, 3)
        if csharp is False and feature.csharp_files:
            reasons.append("含 C# 源码，但永久 C# 设置未开启；请核实运行条件")
            severity = max(severity, 3)
        signals = sorted(pair_signals[mod.item_id],
                         key=lambda value: (-int(value[1].item_id in active), -value[0], value[1].name))
        for score, other, reason in signals[:4]:
            state = "已启用" if other.item_id in active else "未启用"
            other_kinds = features.get(other.item_id, Features(other.item_id, other.name)).kinds
            kind = other_kinds[0] if other_kinds else "未知类型"
            reasons.append(f"与{state}的 {kind} 模组 {other.name}：{reason}")
            severity = max(severity, score)
        if ADDON_NAME.search(mod.name):
            matched = [other for other in mods if other.item_id != mod.item_id
                       and len(other.name) >= 6 and other.name.casefold() in mod.name.casefold()]
            for other in sorted(matched, key=lambda x: -len(x.name))[:1]:
                if not other.enabled:
                    reasons.append(f"名称显示可能配套 {other.name}，目前未启用；请核对发布者说明")
                    severity = max(severity, 1)
        if feature.partial:
            reasons.append("部分资源未能分析，结论不完整")
        if feature.deferred:
            reasons.append("游戏运行中的轻量检测：深度扫描已延后，缓存结果可能过时")
        if feature.opaque_code:
            reasons.append("含编译后的程序库，部分内部行为无法仅凭文本资源判断")
        if not reasons:
            reasons.append(f"已与其他 {max(0, len(mods) - 1)} 个缓存模组比对资源及可读取的脚本，未发现直接重叠；仍需游戏内验证")
        if feature.core or "框架/脚本" in feature.kinds:
            importance = "关键组件"
        elif len(feature.definitions) > 200 or len(set(feature.kinds) & SYSTEM_KINDS) >= 2:
            importance = "高"
        elif set(feature.kinds) <= {"语言/文本", "界面/音效", "其他", "补丁/调整"}:
            importance = "低"
        else:
            importance = "中"
        max_signal = max((score for score, _, _ in signals), default=0)
        active_signal = max((score for score, other, _ in signals if other.item_id in active), default=0)
        compatibility = ("低·运行条件" if (runtime_luacs is False and feature.code_files or csharp is False and feature.csharp_files) else
                         "低·缺前置" if missing or any("资源路径需要" in text for text in reasons) else
                         "低·当前冲突风险" if mod.enabled and active_signal >= 3 else
                         "低·潜在冲突风险" if max_signal >= 3 else
                         "中·当前重叠" if mod.enabled and active_signal >= 2 else
                         "中·潜在重叠" if max_signal >= 2 else
                         "中·需核对" if severity == 1 else
                         "未知·资料不足" if feature.partial or feature.opaque_code else "未见直接冲突·待实测")
        if feature.deferred: compatibility='待刷新·缓存结论'
        result[mod.item_id] = Assessment(mod.item_id, feature.kinds, importance,
                                         compatibility, reasons, max(0, len(mods) - 1), len(signals))
        result[mod.item_id].evidence = "缓存待刷新" if feature.deferred else "资料不完整" if feature.partial or feature.opaque_code else "已读取文件事实，兼容结论仍需实测"
        result[mod.item_id].pairs = [pair_detail(feature, features.get(other.item_id, Features(other.item_id, other.name)),
                                               order or [], other.item_id in active) for _, other, _ in signals]
    return result


def pair_detail(left, right, order, other_active=True):
    score, reason = pair_evidence(left, right)
    shared = left.definitions & right.definitions
    winner = ""
    if shared and shared <= left.overrides | right.overrides:
        left_only = shared <= left.overrides and not shared & right.overrides
        right_only = shared <= right.overrides and not shared & left.overrides
        if left_only: winner = left.name
        elif right_only: winner = right.name
        elif shared <= left.overrides & right.overrides and left.item_id in order and right.item_id in order:
            winner = left.name if order.index(left.item_id) < order.index(right.item_id) else right.name
    special_override = any(key[0]=='afflictions' for key in shared) and bool(shared & (left.overrides|right.overrides))
    if special_override:
        winner = ''
    if shared - left.overrides - right.overrides:
        advice = "同标识普通定义需兼容补丁或禁用其中一个；移动顺序通常不足以解决。"
    elif special_override:
        advice = '含医疗/状态 Override：具体加载条件可能与物品不同。请核对作者说明和当前游戏版本；助手不单凭上下位置判定覆盖结果。'
    elif winner:
        advice = f"可识别的 XML Override 预计由 {winner} 优先；请确认这符合你的期望，多个 Override 可调整相对顺序。"
    else:
        advice = "按作者说明核对脚本/覆盖顺序，分组启用实测；助手不会自动禁用模组。"
    locations = []
    for key in sorted(shared)[:12]:
        locations.append({'identifier': key[2], 'category': key[0],
                          'left_files': left.definition_files.get('|'.join(key), []),
                          'right_files': right.definition_files.get('|'.join(key), [])})
    return {'other_id': right.item_id, 'other_name': right.name, 'other_enabled': other_active,
            'score': score, 'reason': reason, 'evidence': 'XML 文件事实' if shared else '源码静态线索',
            'expected_xml_winner': winner, 'advice': advice, 'locations': locations}
