"""Read, propose and safely persist Barotrauma's regular-package load order."""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
import os
from pathlib import Path
import stat
import time
import uuid
import xml.etree.ElementTree as ET

from .core import AssistantError, Environment, Mod, atomic_json, game_running, scoped_game_guard
from .mod_analysis import Features
from .mod_toggle import BLOCK, configured_key


@dataclass
class OrderSuggestion:
    ids: list[str]
    reasons: list[str]


def read_order(env: Environment, strict=True) -> list[str]:
    try:
        root = ET.fromstring((env.game / "config_player.xml").read_bytes())
    except (OSError, ET.ParseError) as error:
        raise AssistantError(f"无法读取游戏加载顺序：{error}") from error
    regular = next((node for node in root.iter() if node.tag.lower() == "regularpackages"), None)
    if regular is None:
        raise AssistantError("游戏配置没有普通模组列表")
    ids = []
    for node in regular:
        if node.tag.lower() != "package":
            continue
        item = configured_key(node.get("path", ""), env)
        if item is None:
            if not strict:
                continue
            raise AssistantError("启用列表里有无法识别的模组路径；请在游戏内检查后再排序")
        if item in ids:
            if not strict:
                continue
            raise AssistantError("启用列表里有重复模组，暂不改动顺序")
        ids.append(item)
    return ids


def load_rules(env):
    path = env.work / 'order-rules.json'
    try: return check_rules(json.loads(path.read_text(encoding='utf-8')))
    except FileNotFoundError: return {'before': [], 'locks': []}
    except (ValueError, TypeError): raise AssistantError('排序规则文件损坏，请在规则窗口重建')


def check_rules(data):
    if not isinstance(data, dict): raise AssistantError('排序规则格式无效')
    before,locks = data.get('before',[]),data.get('locks',[])
    if not isinstance(before,list) or not isinstance(locks,list) or len(before)>2000 or len(locks)>1000:
        raise AssistantError('排序规则数量或格式无效')
    if any(not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(x,str) for x in pair) or pair[0]==pair[1] for pair in before):
        raise AssistantError('前后顺序规则无效')
    if any(not isinstance(x,str) for x in locks): raise AssistantError('锁定规则无效')
    return {'before':[list(pair) for pair in dict.fromkeys(tuple(x) for x in before)],'locks':list(dict.fromkeys(locks))}


def save_rules(env, data):
    atomic_json(env.work/'order-rules.json',check_rules(data))


def validate_order(ids, original, rules):
    rules = check_rules(rules)
    for before,after in rules['before']:
        if before in ids and after in ids and ids.index(before)>ids.index(after):
            raise AssistantError('此移动违反自定义前后顺序规则，请先调整规则')
    for item in rules['locks']:
        if item in original and item in ids and original.index(item)!=ids.index(item):
            raise AssistantError('此移动会改变已锁定模组的位置，请先解锁')


def suggest_order(ids: list[str], mods: dict[str, Mod], features: dict[str, Features], rules=None) -> OrderSuggestion:
    """Stable suggestion; preserve precedence where definitions already overlap."""
    if len(set(ids)) != len(ids) or any(item not in mods for item in ids):
        raise AssistantError("模组顺序与当前清单不一致，请重新检测")
    names = {mods[item].name.casefold(): item for item in ids}
    edges = {item: set() for item in ids}
    incoming = {item: 0 for item in ids}
    reasons = []
    rules = check_rules(rules or {})
    def edge(before, after):
        if before != after and after not in edges[before]:
            edges[before].add(after)
            incoming[after] += 1

    for item in ids:
        feature = features.get(item, Features(item, mods[item].name))
        for dependency in sorted(feature.workshop_dependencies - set(ids)):
            reasons.append(f"{mods[item].name} 的工坊前置 {dependency} 不在本列表中，请核实是否由核心包或客户端提供")
        for name in sorted(feature.path_dependencies):
            prerequisite = names.get(name.casefold())
            if prerequisite is None:
                reasons.append(f"{mods[item].name} 引用了 {name}，但它不在已启用列表中")
            elif prerequisite != item and item not in edges[prerequisite]:
                edge(prerequisite, item)
                reasons.append(f"{mods[prerequisite].name} 排在 {mods[item].name} 前：资源路径依赖")

    # Upper packages take precedence for competing overrides. A type/name guess
    # must not silently reverse the user's current choice of the winning mod.
    for index, before in enumerate(ids):
        left = features.get(before)
        if left is None:
            continue
        for after in ids[index + 1:]:
            right = features.get(after)
            if right and left.definitions & right.definitions:
                if [after,before] in rules['before']: continue
                edge(before, after)
                reasons.append(f"{mods[before].name} 与 {mods[after].name} 有重复定义，保留现有相对顺序以维持覆盖优先级")
    for before,after in rules['before']:
        if before in edges and after in edges:
            edge(before,after)
            reasons.append(f"自定义规则：{mods[before].name} 必须在 {mods[after].name} 之前")
        else: reasons.append('有自定义规则涉及未启用模组，本次暂不应用')
    for item in rules['locks']:
        if item in ids:
            position = ids.index(item)
            for earlier in ids[:position]: edge(earlier,item)
            for later in ids[position+1:]: edge(item,later)
            reasons.append('保留锁定位置：'+mods[item].name)

    position = {item: index for index, item in enumerate(ids)}
    # A category/name is not evidence of a load-order relationship. Retain the
    # user's relative order unless resource dependencies or reviewed rules
    # require moving entries. Do not import RimWorld's precedence semantics.
    ready = [(position[item], item) for item in ids if incoming[item] == 0]
    heapq.heapify(ready)
    proposed = []
    while ready:
        _, item = heapq.heappop(ready)
        proposed.append(item)
        for dependent in edges[item]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                heapq.heappush(ready, (position[dependent], dependent))
    if len(proposed) != len(ids):
        raise AssistantError("依赖与当前覆盖优先级形成循环，无法自动排序；请手动核对作者说明")
    if proposed != ids:
        reasons.append("只根据已识别的资源依赖和前后规则调整，不按模组类型推测顺序；其余尽量保留原顺序。作者说明优先")
    elif not reasons:
        reasons.append("未发现需要改变顺序的依赖或规则；保留当前顺序，不代表已经证明兼容")
    return OrderSuggestion(proposed, reasons)


def save_order(env: Environment, ids: list[str], process_guard=game_running) -> str:
    process_guard = scoped_game_guard(env, process_guard)
    if process_guard():
        raise AssistantError("请先关闭游戏和服务器，再保存模组顺序")
    current = read_order(env)
    validate_order(ids,current,load_rules(env))
    if len(ids) != len(current) or set(ids) != set(current) or len(set(ids)) != len(ids):
        raise AssistantError("启用模组清单已经变化，请重新检测后排序")
    if ids == current:
        return ""
    config = env.game / "config_player.xml"
    original = config.read_bytes()
    try:
        source = original.decode("utf-8-sig")
    except UnicodeError as error:
        raise AssistantError("游戏配置编码不受支持") from error
    block = BLOCK.search(source)
    if block is None:
        raise AssistantError("游戏配置的普通模组区域格式不受支持")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    regular = ET.fromstring(block.group(), parser=parser)
    groups: dict[str, list[ET.Element]] = {}
    pending: list[ET.Element] = []
    for node in list(regular):
        if node.tag is ET.Comment:
            pending.append(node)
            continue
        if not isinstance(node.tag, str) or node.tag.casefold() != "package":
            raise AssistantError("普通模组列表含未知节点，暂不自动改写")
        item = configured_key(node.get("path", ""), env)
        if item is None or item in groups:
            raise AssistantError("普通模组列表包含无法识别或重复的路径")
        groups[item] = pending + [node]
        pending = []
    regular[:] = [node for item in ids for node in groups[item]] + pending
    newline = "\r\n" if "\r\n" in source else "\n"
    changed_block = ET.tostring(regular, encoding="unicode").replace("\n", newline)
    updated = source[:block.start()] + changed_block + source[block.end():]
    if updated == source:
        return ""
    backup_dir = env.work / "config-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:8]
    backup = backup_dir / (time.strftime("%Y%m%d-%H%M%S") + "-order-" + suffix + ".xml")
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
            raise AssistantError("游戏刚刚启动，模组顺序未更改")
        if config.read_bytes() != original:
            raise AssistantError("游戏配置刚被其他程序修改，请重新检测后重试")
        os.replace(temporary, config)
    finally:
        if temporary.exists():
            temporary.unlink()
    return str(backup)
