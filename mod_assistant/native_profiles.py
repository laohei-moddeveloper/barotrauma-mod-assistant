"""Read/write the game's ModLists XML without executing or modifying mod files."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
from .core import APP_ID, AssistantError, inventory, load_package, reject_link


def materialize_native(env, data, mods=None):
    if 'native_entries' not in data: return data
    mods=inventory(env) if mods is None else mods
    known={mod.item_id:mod for mod in mods}; result={**data,'core':None,'order':[]}
    for entry in data['native_entries']:
        mod=known.get(entry['id'])
        if entry['id'].startswith('local:'):
            matches=[m for m in mods if m.item_id.startswith('local:') and entry['name'].casefold() in {value.casefold() for value in (m.name,*m.aliases)}]
            mod=matches[0] if len(matches)==1 else None
        from .profiles import installed_path
        folder=installed_path(env,mod) if mod else None
        core=folder is not None and (folder/'filelist.xml').is_file() and load_package(folder).get('corepackage','false').casefold()=='true'
        if core:
            if result['core'] is not None: raise AssistantError('清单包含多个核心包，请先在游戏中核对')
            result['core']=entry
        else: result['order'].append(entry)
    return result


def read_native(env, raw, mods=None):
    from .profiles import SCHEMA, normalize_profile
    if len(raw)>2*1024*1024: raise AssistantError('配置文件过大')
    try:
        text=raw.decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper(): raise AssistantError('模组清单不能包含外部实体或文档类型')
        root=ET.fromstring(text)
    except (UnicodeError,ET.ParseError) as error: raise AssistantError('游戏模组清单 XML 无法读取') from error
    if root.tag.casefold()!='mods': raise AssistantError('这不是游戏 ModLists 清单')
    entries=[]; vanilla=False
    for node in root:
        kind=node.tag.casefold()
        if kind=='vanilla':
            if vanilla: raise AssistantError('模组清单包含重复的原版核心包')
            vanilla=True; continue
        if kind not in ('workshop','local') or len(node): raise AssistantError('模组清单包含不支持的项目')
        name=node.get('name','')
        if kind=='local' and not name.strip(): raise AssistantError('本地模组清单缺少名称')
        item=node.get('id','') if kind=='workshop' else 'local:'+hashlib.sha256(name.casefold().encode()).hexdigest()[:16]
        entries.append({'id':item,'name':name or item})
    data=normalize_profile({'schema':SCHEMA,'appid':APP_ID,'name':root.get('name','导入的游戏清单'),
                            'core':None,'order':entries,'native_entries':entries,
                            'note':'游戏清单记录核心包、启用模组和顺序，不记录历史版本或文件指纹。'})
    return materialize_native(env,data,mods)


def native_bytes(data):
    from .profiles import normalize_profile
    data=normalize_profile(data); root=ET.Element('mods',{'name':data.get('name','')})
    if not data.get('core'): ET.SubElement(root,'Vanilla')
    entries=([data['core']] if data.get('core') else [])+data['order']
    for entry in entries:
        kind='Local' if entry['id'].startswith('local:') else 'Workshop'
        attrs={'name':entry.get('name',entry['id'])}
        if kind=='Workshop': attrs['id']=entry['id']
        ET.SubElement(root,kind,attrs)
    ET.indent(root)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def write_native(path, data):
    path=Path(path)
    if path.exists(): reject_link(path)
    for parent in path.parents:
        if parent.exists(): reject_link(parent)
    raw=native_bytes(data); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists(): temporary.unlink()
    return path
