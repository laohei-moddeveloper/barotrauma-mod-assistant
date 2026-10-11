"""Bounded hashes of explicitly identified analysis inputs, not a safety certificate."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from .core import AssistantError, Cancelled, mod_files, reject_link, within

INPUT_SUFFIXES = {'.xml', '.lua', '.cs', '.dll'}
MAX_FILES = 12000
MAX_BYTES = 512 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
SCOPE = 'xml-lua-cs-dll-v1'


@dataclass
class ReadBudget:
    files: int = 0
    bytes: int = 0


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled('证据读取已取消')


def relative_name(value):
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise AssistantError('证据文件路径无效')
    name = PurePosixPath(value)
    if name.is_absolute() or ':' in value or '\\' in value or any(p in ('', '.', '..') for p in value.split('/')):
        raise AssistantError('证据文件路径无效')
    return value


def read_stable(path, root, cancel=None, budget=None, retain=False, limit=MAX_FILE, inspect_chunk=None):
    """Hash the bytes actually read and reject replacements/concurrent writes."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    # Absolute lexical containment plus rejecting every descendant reparse
    # point establishes this boundary without resolving the same tree per file.
    if not path.is_relative_to(root):
        raise AssistantError('证据文件超出选定目录')
    for parent in (path, *path.parents):
        reject_link(parent)
        if parent==root:break
    check_cancel(cancel)
    budget = budget or ReadBudget()
    if budget.files >= MAX_FILES:
        raise AssistantError('证据文件数量超过上限')
    checksum = hashlib.sha256()
    chunks = []
    size = 0
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        while True:
            check_cancel(cancel)
            chunk = stream.read(256 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit or budget.bytes + len(chunk) > MAX_BYTES:
                raise AssistantError('证据读取大小超过上限')
            budget.bytes += len(chunk)
            checksum.update(chunk)
            if inspect_chunk is not None:inspect_chunk(chunk)
            if retain:
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
    for parent in (path,*path.parents):
        reject_link(parent)
        if parent==root:break
    current = path.stat()
    # Windows Python 3.12 exposes different ctime meanings in fstat vs stat.
    # Compare ctime only within the same handle API; birthtime is consistent.
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, getattr(s,'st_birthtime_ns',None))
    if identity(before) != identity(after) or before.st_ctime_ns!=after.st_ctime_ns or identity(after) != identity(current) or size != after.st_size:
        raise AssistantError('证据文件在读取期间变化，请重试')
    budget.files += 1
    result = {'sha256': checksum.hexdigest(), 'size': size}
    return (result, b''.join(chunks)) if retain else result


def package_evidence(folder, cancel=None, budget=None, require_manifest=True):
    """No metadata-only cache is used when creating or checking evidence."""
    files, errors, stamps = {}, [], {}
    budget = budget or ReadBudget()
    if folder is None or not Path(folder).is_dir():
        return {'scope': SCOPE, 'complete': False, 'files': {}, 'digest': '', 'errors': ['模组目录缺失']}
    folder = Path(folder)
    try:
        for path in mod_files(folder):
            check_cancel(cancel)
            if path.suffix.casefold() not in INPUT_SUFFIXES:
                continue
            name = path.relative_to(folder).as_posix()
            relative_name(name)
            files[name] = read_stable(path, folder, cancel, budget)
            info=path.stat()
            stamps[name]=(info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        latest={path.relative_to(folder).as_posix() for path in mod_files(folder) if path.suffix.casefold() in INPUT_SUFFIXES}
        if latest!=set(files):raise AssistantError('证据文件清单在读取期间变化')
        for name,stamp in stamps.items():
            check_cancel(cancel);info=(folder/name).stat()
            if stamp!=(info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns):raise AssistantError('证据文件在读取期间变化，请重试')
    except Cancelled:
        raise
    except (OSError, AssistantError) as error:
        errors.append(str(error))
    if require_manifest and 'filelist.xml' not in files:
        errors.append('未完整读取 filelist.xml')
    complete = not errors
    digest = hashlib.sha256(json.dumps(sorted(files.items()), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest() if complete else ''
    return {'scope': SCOPE, 'complete': complete, 'files': files, 'digest': digest, 'errors': errors, '_stamps':stamps}


def confirm_package(evidence,folder,cancel=None):
    """Use stat-to-stat checks only to guard a capture, never to reuse a hash."""
    if not evidence['complete']:return False
    latest={path.relative_to(folder).as_posix() for path in mod_files(folder) if path.suffix.casefold() in INPUT_SUFFIXES}
    if latest!=set(evidence['files']):return False
    for name,stamp in evidence.get('_stamps',{}).items():
        check_cancel(cancel);path=folder/name;reject_link(path);info=path.stat()
        if stamp!=(info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns):return False
    return True


def changed_files(before, after):
    old, new = before.get('files', {}), after.get('files', {})
    return [{'file': name, 'change': '新增' if name not in old else '删除' if name not in new else '内容改变'}
            for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)]


def game_context_evidence(env,mods=None,cancel=None,budget=None):
    """Bind reviewed rules to core inputs and script settings, not audio/UI prefs."""
    from .profiles import capture_profile,installed_path
    from .core import inventory
    from .luacs import MODERN_SETTINGS
    mods=list(mods if mods is not None else inventory(env))
    profile=capture_profile(env,mods=mods,include_receipts=False,cancel=cancel)
    known={mod.item_id:mod for mod in mods};core=profile.get('core')
    folder=installed_path(env,known[core['id']]) if core else env.game/'Content'
    budget=budget or ReadBudget()
    inputs=package_evidence(folder,cancel,budget,require_manifest=core is not None)
    runtime={};runtime_stamps={}
    runtime_names=('Barotrauma.dll','BarotraumaCore.dll','MoonSharp.Interpreter.dll','LuaCsSetupConfig.xml',MODERN_SETTINGS)
    for name in runtime_names:
        path=env.game/name
        if path.is_file():
            runtime[name]=read_stable(path,env.game,cancel,budget)
            info=path.stat();runtime_stamps[name]=(info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    if inputs['complete'] and not confirm_package(inputs,folder,cancel):raise AssistantError('核心证据在读取期间变化')
    latest=capture_profile(env,mods=mods,include_receipts=False,cancel=cancel)
    if (latest.get('core'),latest['game_version'])!=(profile.get('core'),profile['game_version']):raise AssistantError('核心配置在读取期间变化')
    guards={'folder':folder,'inputs':dict(inputs),'runtime':runtime_stamps,'runtime_names':runtime_names}
    inputs.pop('_stamps',None)
    payload={'scope':'game-core-runtime-v1','core':core['id'] if core else 'vanilla',
             'game_version':profile['game_version'],'inputs':inputs,'runtime':runtime}
    payload['complete']=inputs['complete']
    payload['digest']=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest() if payload['complete'] else ''
    payload['_guards']=guards
    if payload['complete'] and not confirm_game_context(payload,env,cancel):raise AssistantError('核心证据在读取期间变化')
    return payload


def confirm_game_context(context,env,cancel=None):
    guards=context['_guards']
    if not confirm_package(guards['inputs'],guards['folder'],cancel):return False
    if {name for name in guards['runtime_names'] if (env.game/name).is_file()}!=set(guards['runtime']):return False
    for name,stamp in guards['runtime'].items():
        check_cancel(cancel);path=env.game/name;reject_link(path);info=path.stat()
        if stamp!=(info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns):return False
    return True
