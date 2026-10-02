"""Portable enabled-mod profiles and a single atomic configuration commit."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
import xml.etree.ElementTree as ET
from .core import APP_ID, AssistantError, atomic_json, files_snapshot, game_running, inventory, load_package, reject_link, within
from .mod_toggle import BLOCK, CORE, configured_key, local_id
from .mod_order import read_order

SCHEMA = 'barotrauma-mod-profile-v2'

def game_version(env):
    try: return ET.parse(env.game / 'Content/ContentPackages/Vanilla.xml').getroot().get('gameversion', '')
    except (OSError, ET.ParseError): return ''

def installed_path(env, mod):
    return env.installed / mod.item_id if mod.item_id.isdecimal() else mod.source

def reference(env, mod):
    path = installed_path(env, mod)
    package = load_package(path) if path and (path / 'filelist.xml').is_file() else None
    fingerprint = ''
    if mod.item_id.isdecimal() and path and path.exists():
        try:
            receipt = json.loads((env.work/'receipts'/(mod.item_id+'.json')).read_text(encoding='utf-8'))
            if receipt.get('installed_snapshot') == {name:list(value) for name,value in files_snapshot(path).items()}:
                fingerprint = receipt.get('fingerprint','')
        except (OSError,ValueError): pass
    return {'id': mod.item_id, 'name': package.get('name',mod.name) if package is not None else mod.name, 'mod_version': package.get('modversion', '') if package is not None else '',
            'assistant_fingerprint':fingerprint,
            'core': package.get('corepackage', 'false').casefold() == 'true' if package is not None else False}

def capture_profile(env, name='当前配置', mods=None):
    mods = mods if mods is not None else inventory(env)
    known = {mod.item_id: mod for mod in mods}
    original=(env.game/'config_player.xml').read_bytes()
    document = ET.fromstring(original)
    core = next((node for node in document.iter() if node.tag.casefold() == 'corepackage'), None)
    key = configured_key(core.get('path', ''), env) if core is not None else None
    core_path=Path(core.get('path','').replace('\\','/')) if core is not None else None
    if core_path is not None and not core_path.is_absolute(): core_path=env.game/core_path
    if core is None or (key is None and core_path.resolve() != (env.game/'Content/ContentPackages/Vanilla.xml').resolve()):
        raise AssistantError('核心内容包无法识别，请先在游戏中核对')
    order = read_order(env)
    if (env.game/'config_player.xml').read_bytes()!=original: raise AssistantError('配置在读取时变化，请重新检测')
    if any(item not in known for item in order) or (key and key not in known):
        raise AssistantError('有启用模组尚未安装，无法保存完整配置')
    return {'schema': SCHEMA, 'appid': APP_ID, 'name': str(name)[:100], 'game_version': game_version(env),
            'core': reference(env, known[key]) if key else None,
            'order': [reference(env, known[item]) for item in order],
            'note': '配置记录启用状态和顺序；Steam 只能提供当前工坊版本，不能按此文件获取历史版本。'}

def normalize_profile(data):
    if not isinstance(data, dict) or data.get('appid') != APP_ID:
        raise AssistantError('这不是潜渊症模组配置')
    if data.get('schema') == 'barotrauma-mod-assistant-profile-v1':
        if not isinstance(data.get('mods'),list) or not isinstance(data.get('load_order',[]),list):
            raise AssistantError('旧版清单格式无效')
        entries = {str(x.get('id')): x for x in data.get('mods', []) if isinstance(x, dict)}
        order = data.get('load_order', list(entries))
        data = {'schema': SCHEMA, 'appid': APP_ID, 'name': data.get('name', '导入的联机清单'), 'core': None,
                'order': [entries.get(str(item), {'id': str(item), 'name': str(item)}) for item in order]}
    if data.get('schema') != SCHEMA or not isinstance(data.get('order'), list) or len(data['order']) > 1000:
        raise AssistantError('配置格式或模组数量不受支持')
    result = dict(data)
    seen = set()
    values = list(data['order']) + ([data['core']] if data.get('core') is not None else [])
    for entry in values:
        if not isinstance(entry, dict): raise AssistantError('配置中的模组项目无效')
        item = entry.get('id', '')
        if not isinstance(item, str) or not (re.fullmatch(r'[1-9][0-9]{0,19}', item) and int(item) < 2**64
                                             or re.fullmatch(r'local:[0-9a-f]{16}', item)):
            raise AssistantError('配置中的模组编号无效')
        if item in seen: raise AssistantError('配置中有重复模组或核心包混入普通列表')
        seen.add(item)
        if not isinstance(entry.get('name', ''), str) or len(entry.get('name', '')) > 500:
            raise AssistantError('配置中的名称无效')
        for field in ('mod_version','assistant_fingerprint'):
            if not isinstance(entry.get(field,''),str) or len(entry.get(field,''))>500:
                raise AssistantError('配置中的版本或指纹无效')
    if not isinstance(data.get('name',''),str) or not isinstance(data.get('game_version',''),str):
        raise AssistantError('配置中的名称或游戏版本无效')
    return result

def resolve_profile(env, data, mods=None):
    data = normalize_profile(data)
    mods = mods if mods is not None else inventory(env)
    known = {mod.item_id: mod for mod in mods}
    resolved, missing, differences = {}, [], []
    refs = list(data['order']) + ([data['core']] if data.get('core') else [])
    for entry in refs:
        item = entry['id']; mod = known.get(item)
        if item.startswith('local:') and mod is None:
            matches = [m for m in mods if m.item_id.startswith('local:') and m.name == entry.get('name')]
            if len(matches) == 1: mod = matches[0]
        path = installed_path(env, mod) if mod else None
        if mod is None or path is None or not (path / 'filelist.xml').is_file():
            missing.append(entry); continue
        resolved[item] = mod
        package = load_package(path)
        if entry.get('mod_version') and package.get('modversion', '') != entry['mod_version']:
            differences.append(f"版本不同：{mod.name}（本机 {package.get('modversion','未知')}，配置 {entry['mod_version']}）")
        if entry.get('assistant_fingerprint') and reference(env,mod).get('assistant_fingerprint') != entry['assistant_fingerprint']:
            differences.append(f'文件指纹不同或本机尚未校验：{mod.name}')
    if len({mod.item_id for mod in resolved.values()}) != len(resolved):
        raise AssistantError('多个配置项目映射到同一本地模组，请核对名称')
    if data.get('game_version') and data['game_version'] != game_version(env):
        differences.append('游戏版本与保存配置时不同')
    return resolved, missing, differences

def config_bytes(env, data, mods=None, original=None):
    data = normalize_profile(data)
    resolved, missing, _ = resolve_profile(env, data, mods)
    if missing: raise AssistantError('缺少已安装模组：' + '、'.join(x.get('name', x['id']) for x in missing[:8]))
    original = (env.game / 'config_player.xml').read_bytes() if original is None else original
    ET.fromstring(original)
    source = original.decode('utf-8-sig'); block, core_block = BLOCK.search(source), CORE.search(source)
    if block is None or core_block is None: raise AssistantError('游戏内容包配置格式不受支持')
    regular = ET.fromstring(block.group(), parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    existing = {}; pending = []
    for node in regular:
        if node.tag is ET.Comment: pending.append(node); continue
        if not isinstance(node.tag, str) or node.tag.casefold() != 'package':
            raise AssistantError('普通模组配置含未知节点')
        key = configured_key(node.get('path',''), env)
        if key in existing: raise AssistantError('当前启用列表有重复模组')
        existing[key] = pending + [node]; pending = []
    def path_value(mod):
        path = installed_path(env, mod) / 'filelist.xml'
        if not within(path,env.game) and not within(path,env.player): raise AssistantError('配置模组路径超出游戏或玩家目录')
        for parent in [path] + list(path.parents):
            if within(parent, env.game) or within(parent, env.player):
                if parent.exists(): reject_link(parent)
        return path.relative_to(env.game).as_posix() if within(path, env.game) else path.as_posix()
    nodes = []
    for entry in data['order']:
        mod = resolved[entry['id']]
        if load_package(installed_path(env, mod)).get('corepackage','false').casefold() == 'true':
            raise AssistantError('核心内容包不能放入普通模组顺序')
        group = existing.get(mod.item_id, [ET.Element('package')])
        group[-1].set('path', path_value(mod)); nodes.extend(group)
    regular[:] = nodes + pending
    core = ET.fromstring(core_block.group())
    if data.get('core'):
        mod = resolved[data['core']['id']]
        if load_package(installed_path(env, mod)).get('corepackage','false').casefold() != 'true':
            raise AssistantError('选定核心内容包不是核心模组')
        core.set('path', path_value(mod))
    else: core.set('path', 'Content/ContentPackages/Vanilla.xml')
    newline = '\r\n' if '\r\n' in source else '\n'
    replacements = [(block.start(),block.end(),ET.tostring(regular,encoding='unicode').replace('\n',newline)),
                    (core_block.start(),core_block.end(),ET.tostring(core,encoding='unicode'))]
    for start,end,value in sorted(replacements,reverse=True): source = source[:start]+value+source[end:]
    return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + source.encode('utf-8')

def commit_config(env, replacement, original, process_guard=game_running):
    if process_guard(): raise AssistantError('请先关闭游戏和服务器，再切换配置')
    config = env.game / 'config_player.xml'; reject_link(config)
    if config.read_bytes() != original: raise AssistantError('游戏配置已经被其他程序修改，请重新检测')
    if replacement == original: return ''
    suffix = uuid.uuid4().hex[:8]
    backup = env.work / 'config-backups' / (time.strftime('%Y%m%d-%H%M%S') + '-profile-' + suffix + '.xml')
    backup.parent.mkdir(parents=True,exist_ok=True); backup.write_bytes(original)
    temporary = config.with_name(config.name + '.' + suffix + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(replacement); stream.flush(); os.fsync(stream.fileno())
        if process_guard(): raise AssistantError('游戏刚刚启动，配置未切换')
        if config.read_bytes() != original: raise AssistantError('游戏配置刚被其他程序修改，未切换')
        os.replace(temporary,config)
    finally:
        if temporary.exists(): temporary.unlink()
    return str(backup)

def apply_profile(env, data, mods=None, process_guard=game_running):
    if process_guard(): raise AssistantError('请先关闭游戏和服务器，再切换配置')
    original = (env.game / 'config_player.xml').read_bytes()
    return commit_config(env, config_bytes(env,data,mods,original), original, process_guard)

def save_profile(env, data):
    data = normalize_profile(data)
    path = env.work / 'profiles' / (uuid.uuid4().hex + '.json')
    atomic_json(path,data)
    return path
