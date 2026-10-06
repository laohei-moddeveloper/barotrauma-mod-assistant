"""Bounded read-only log triage; findings distinguish matches from guesses."""
from dataclasses import asdict
from collections import deque
from pathlib import Path
import os
from datetime import datetime, timezone
import re
from .luacs import status
from .core import AssistantError, Cancelled,reject_link, within

def recent_logs(env):
    candidates = set()
    for root in (env.game, env.player):
        for pattern in ('*.log','*crash*.txt','*Crash*.txt','DebugConsole*.txt'):
            candidates.update(root.glob(pattern))
        for name in ('Logs','logs','ServerLogs','DebugConsole','LuaCsLogs'):
            folder = root/name
            if folder.is_dir():
                try: reject_link(folder)
                except AssistantError: continue
                candidates.update(folder.glob('*.txt')); candidates.update(folder.glob('*.log'))
    approved=[]
    for path in candidates:
        try:
            reject_link(path)
            if path.is_file() and any(within(path,root) for root in (env.game,env.player)):
                approved.append(path)
        except (OSError,AssistantError):continue
    return sorted(approved,key=lambda p:p.stat().st_mtime,reverse=True)[:20]

def redact(text, env=None):
    text=str(text)
    if env:
        for path in (env.game,env.player):
            for value in (str(path).replace('\\','\\\\'),str(path),path.as_posix()): text=re.sub(re.escape(value),'[本机目录]',text,flags=re.I)
    for value in (str(Path.home()).replace('\\','\\\\'),str(Path.home()),Path.home().as_posix()): text=re.sub(re.escape(value),'[用户目录]',text,flags=re.I)
    text=re.sub(r'''(?im)((?:token|password|authorization|secret|api[_ -]?key)\s*["']?\s*[:=]\s*)("[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;]+)''',r'\1[隐藏]',text)
    text=re.sub(r'\b7656119\d{10}\b','[Steam 用户编号]',text)
    return text

def diagnose(path, mods, env=None, features=None,cancel=None):
    path=Path(path)
    reject_link(path)
    with path.open('rb') as stream:
        observed=os.fstat(stream.fileno()); length=observed.st_size
        bom=stream.read(2)
        offset=max(0,length-4*1024*1024)
        utf16=bom in (b'\xff\xfe',b'\xfe\xff')
        if utf16 and offset%2: offset+=1
        stream.seek(offset)
        raw=stream.read(4*1024*1024)
        changed=os.fstat(stream.fileno()).st_mtime_ns!=observed.st_mtime_ns
    if utf16: text=raw.decode('utf-16-le' if bom==b'\xff\xfe' else 'utf-16-be',errors='replace').lstrip('\ufeff')
    else: text=raw.decode('utf-8-sig',errors='replace')
    lines=text.splitlines(); findings=deque(maxlen=80); cache={}
    def check():
        if cancel and cancel.is_set(): raise Cancelled('日志检查已取消，文件未改变')
    if offset and lines: lines=lines[1:]  # A partial first line is not evidence.
    names=[]
    for mod in mods:
        tokens=[mod.name.casefold()] if len(mod.name)>=4 else []
        if mod.source and len(mod.source.name)>=4: tokens.append(mod.source.name.casefold())
        names.append((mod.name,list(dict.fromkeys(tokens)),mod.item_id if mod.item_id.isdecimal() else ''))
    patterns=[('重复定义',r'duplicate|already exists|same identifier|重复定义', '核对重叠模组和 Override；普通重复定义通常需要兼容补丁或禁用其中一个。'),
              ('缺失资源/前置',r'missing dependency|dependencies.*missing|could not find|not found|找不到|不存在','检查必需模组是否安装启用、资源路径是否正确；必要时重新校验缓存。'),
              ('版本不匹配',r'incompatible|version mismatch|版本.*不.*匹配','对比游戏、LuaCs 和房主模组版本，避免混用更新前后的组件。'),
              ('脚本/程序异常',r'exception|stack traceback|lua.*error|syntax error|harmony.*error|脚本.*错误','核实 LuaCs/C# 状态；按日志中模组路径定位，分组启用复现。'),
              ('下载/读写问题',r'timeout|access denied|sharing violation|disk.*full|校验失败|超时','检查 Steam 下载状态、磁盘空间和文件占用，关闭游戏后重试。')]
    for index,line in enumerate(lines):
        check()
        for category,pattern,advice in patterns:
            if re.search(pattern,line,re.I):
                end=min(len(lines),index+16)
                for next_line in range(index+1,end):
                    if not lines[next_line].strip(): end=next_line; break
                context='\n'.join(lines[max(0,index-1):end])
                matches=[]; folded=context.casefold()
                for name,tokens,item in names:
                    if any(token in folded for token in tokens) or item and re.search(r'(?:Installed|LocalMods)[/\\]+'+re.escape(item)+r'(?:[/\\]|$)',context,re.I): matches.append(name)
                from .runtime_evidence import locate,steps
                locations=locate(context,mods,features or {},env,check,cache)
                findings.append({'category':category,'line_in_tail':index+1,'possible_mods':list(dict.fromkeys(matches)),
                                 'line_in_file':index+1 if offset==0 else None,
                                 'evidence':'日志原文命中；归属仍需核实' if matches else '日志关键词线索，未确定模组归属',
                                 'text':redact(context[:1500],env),'advice':advice,
                                 'locations':locations,'steps':steps(locations,category)})
                break
    return {'file':path.name,'path':str(path),'tail_only':offset>0,'byte_offset':offset,'changed_during_read':changed,
            'modified_utc':datetime.fromtimestamp(observed.st_mtime,tz=timezone.utc).isoformat(),
            'encoding':('UTF-16 LE' if bom==b'\xff\xfe' else 'UTF-16 BE') if utf16 else 'UTF-8',
            'findings':list(findings),
            'note':'最多读取最近 4 MB；截取日志的行号仅属于读取片段。关键词和路径匹配不等于已确认根因。'}

def lua_verification(env):
    detected=status(env)
    return {'disk_status':asdict(detected),'runtime_verified':False,
            'instructions':['先关闭并重新启动游戏，确认客户端加载的是当前文件。',
                            '检查本次完整启动后的 LuaCs 日志和设置入口；不要用脚本热重载代替完整重启验证。',
                            '在 LuaCs 设置中确认 Are C# Mods Allowed 为 ENABLED，并测试你信任的 C# 模组。',
                            '保存新的游戏日志，再用助手“日志诊断”排查；磁盘检测和无错误日志不等于所有模组运行正常。'],
            'official_guide':'https://github.com/evilfactory/LuaCsForBarotrauma/blob/master/luacs-docs/lua/manual/installing-lua-for-barotrauma-manually.md'}
