"""Incremental analysis; running-game scans never walk resource trees."""
from dataclasses import asdict, fields, replace
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .core import AssistantError, Cancelled, atomic_json, load_package, within, mod_files
from .mod_analysis import Features, KIND_BY_TAG, inspect

SCHEMA = 2
SETS = {'definitions','overrides','path_dependencies','workshop_dependencies','hook_names','hook_events','patches','globals_written'}
TUPLE_SETS = {'definitions','overrides','hook_names','patches'}

def encode(feature):
    data = asdict(feature)
    for key in SETS: data[key] = sorted(data[key])
    return data

def decode(data):
    if not isinstance(data,dict): raise ValueError('无效分析缓存')
    if not all(isinstance(data.get(k),str) for k in ('item_id','name')): raise ValueError('无效分析缓存名称')
    for key in SETS:
        value=data.get(key,[])
        width=3 if key in ('definitions','overrides') else 2
        if not isinstance(value,list) or any(
            not isinstance(x,list) or len(x)!=width or not all(isinstance(part,str) for part in x)
            if key in TUPLE_SETS else not isinstance(x,str) for x in value):
            raise ValueError('无效分析缓存集合')
    for key in ('kinds','tags'):
        if not isinstance(data.get(key,[]),list) or any(not isinstance(x,str) for x in data.get(key,[])):
            raise ValueError('无效分析缓存类型')
    for key in ('code_files','opaque_code','csharp_files'):
        if type(data.get(key,0)) is not int or data.get(key,0)<0: raise ValueError('无效分析缓存计数')
    locations=data.get('definition_files',{})
    if not isinstance(locations,dict) or any(not isinstance(k,str) or not isinstance(v,list) or any(not isinstance(x,str) for x in v) for k,v in locations.items()):
        raise ValueError('无效分析缓存文件位置')
    valid = {f.name for f in fields(Features)}
    result = {k:v for k,v in data.items() if k in valid}
    for key in SETS:
        result[key] = {tuple(x) if key in TUPLE_SETS else x for x in result.get(key, [])}
    for key in ('kinds','tags'): result[key] = tuple(result.get(key, []))
    return Features(**result)

def signature(mod, metadata, cancel=None):
    rows = []
    if mod.source and mod.source.is_dir():
        try:
            for path in mod_files(mod.source):
                if cancel and cancel.is_set(): raise Cancelled('分析已停止')
                if path.suffix.casefold() in ('.xml','.lua','.cs','.dll'):
                    stat = path.stat()
                    rows.append((path.relative_to(mod.source).as_posix(),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
        except Cancelled:
            raise
        except (OSError,AssistantError):
            rows.append(('unsafe-or-unreadable',0,0,0))
    # Match the existing Path ordering, including Windows case folding, so
    # optimization does not invalidate unchanged caches from earlier versions.
    value = [str(mod.source),mod.name,sorted(rows,key=lambda row:Path(row[0])),metadata]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def inspect_cached(env, mods, metadata=None, light=False, force=False, cancel=None, emit=lambda message: None,
                   on_feature=lambda item, feature: None):
    metadata = metadata or {}
    folder = env.work / 'analysis/features-v2'
    results = {}; stats = {'reused':0,'scanned':0,'deferred':0}
    for mod in mods:
        if cancel and cancel.is_set(): raise Cancelled('分析已停止')
        if mod.item_id.isdecimal() and (env.installed/mod.item_id/'filelist.xml').is_file():
            mod = replace(mod, source=env.installed/mod.item_id)
        entry = metadata.get(mod.item_id,{})
        path = folder / (hashlib.sha256(mod.item_id.encode()).hexdigest()+'.json')
        cached = None
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(saved,dict) and saved.get('schema') == SCHEMA and saved.get('source') == str(mod.source):
                cached = decode(saved['feature'])
                if cached.item_id != mod.item_id: cached = None
        except (OSError, ValueError, TypeError, KeyError): saved = {}; cached = None
        if light:
            feature = cached or Features(mod.item_id,mod.name,partial=True)
            if not cached and mod.source and (mod.source/'filelist.xml').is_file():
                try:
                    package = load_package(mod.source)
                    feature.tags = tuple(sorted({node.tag.casefold() for node in package}))
                    feature.kinds = tuple(sorted({KIND_BY_TAG[x] for x in feature.tags if x in KIND_BY_TAG}))
                    feature.core = package.get('corepackage','false').casefold()=='true'
                except (OSError, ValueError, ET.ParseError, AssistantError): pass
            feature.name = mod.name
            feature.workshop_dependencies = set(entry.get('children',[]))
            feature.deferred = True
            stats['deferred'] += 1
        else:
            current = signature(mod,entry,cancel)
            if cached and not force and saved.get('signature') == current:
                feature = cached; stats['reused'] += 1
            else:
                emit('分析变化的模组：'+mod.name)
                feature = inspect(mod,entry); stats['scanned'] += 1
                try:
                    atomic_json(path,{'schema':SCHEMA,'source':str(mod.source),'signature':current,'feature':encode(feature)})
                except OSError:
                    emit('分析缓存无法保存；本次分析结果仍可使用，下次可能重新分析。')
        results[mod.item_id] = feature
        on_feature(mod.item_id, feature)
    return results, stats
