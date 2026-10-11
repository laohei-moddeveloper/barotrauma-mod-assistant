"""Bounded read-only log triage; findings distinguish matches from guesses."""
from dataclasses import asdict
from collections import OrderedDict
import hashlib
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

def diagnose(path, mods, env=None, features=None,cancel=None,baseline=None):
    path=Path(path)
    reject_link(path)
    with path.open('rb') as stream:
        observed=os.fstat(stream.fileno()); length=observed.st_size
        bom=stream.read(2)
        maximum=16*1024*1024
        offset=max(0,length-maximum//2)
        utf16=bom in (b'\xff\xfe',b'\xfe\xff')
        if utf16 and offset%2: offset+=1
        if length<=maximum:
            stream.seek(0); pieces=[(0,stream.read(maximum))]
        else:
            stream.seek(0); first=stream.read(maximum//2)
            stream.seek(offset); pieces=[(0,first),(offset,stream.read(maximum//2))]
        after=os.fstat(stream.fileno())
        changed=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns)
    reject_link(path)
    final=path.stat()
    changed|=(final.st_ino,final.st_size,final.st_mtime_ns,getattr(final,'st_birthtime_ns',None))!=(observed.st_ino,observed.st_size,observed.st_mtime_ns,getattr(observed,'st_birthtime_ns',None))
    checksum=hashlib.sha256()
    segments=[]
    for start,raw in pieces:
        checksum.update(str(start).encode()+b'\0'+raw)
        if utf16:text=raw.decode('utf-16-le' if bom==b'\xff\xfe' else 'utf-16-be',errors='replace').lstrip('\ufeff')
        else:text=raw.decode('utf-8-sig',errors='replace')
        lines=text.splitlines()
        if start and lines:lines=lines[1:]
        if len(pieces)>1 and start==0 and lines:lines=lines[:-1]
        segments.append((start,lines))
    # For an append-only log, evaluate only bytes produced since the baseline.
    # Verify the entire old prefix rather than assuming that a larger file is
    # an append. A partial line at the boundary cannot be compared reliably.
    window=None
    if baseline is not None and len(pieces)==1 and not changed:
        old_size=baseline.get('log_size')
        if type(old_size) is int and 0<=old_size<=length and not baseline.get('tail_only') and not baseline.get('changed_during_read'):
            raw=pieces[0][1]
            prefix=hashlib.sha256(b'0\0'+raw[:old_size]).hexdigest()
            if prefix==baseline.get('sha256'):
                ending=b'\n\0' if bom==b'\xff\xfe' else b'\0\n' if bom==b'\xfe\xff' else b'\n'
                boundary=old_size==0 or raw[:old_size].endswith(ending)
                window={'baseline_sha256':prefix,'baseline_size':old_size,'start':old_size,'end':length,'complete':boundary,'kind':'append'}
                suffix=raw[old_size:]
                codec=('utf-16-le' if bom==b'\xff\xfe' else 'utf-16-be') if utf16 else 'utf-8'
                segments=[(old_size,suffix.decode(codec,errors='replace').splitlines())] if boundary else []
            else:
                window={'baseline_sha256':baseline.get('sha256'),'baseline_size':old_size,'start':0,'end':length,'complete':True,'kind':'replacement'}
    findings=OrderedDict(); cache={}; total=0; omitted=0; sessions=0
    def check():
        if cancel and cancel.is_set(): raise Cancelled('日志检查已取消，文件未改变')
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
    for segment_offset,lines in segments:
      skip_until=0
      for index,line in enumerate(lines):
        check()
        if index<skip_until:continue
        if re.match(r'^\s*(?:Barotrauma (?:Client|Dedicated Server)|Game version:|Barotrauma version:)',line,re.I):sessions+=1
        for category,pattern,advice in patterns:
            if re.search(pattern,line,re.I):
                total+=1
                end=index+1
                for next_line in range(index+1,min(len(lines),index+129)):
                    following=lines[next_line]
                    if not following.strip():break
                    if following[:1].isspace() or re.match(r'^(?:at |--->|--- |stack traceback:|Caused by:)',following):end=next_line+1
                    else:break
                context='\n'.join(lines[index:end])
                skip_until=end
                # Equal headlines with different call sites are different
                # failures. Continuation frames belong to their message block,
                # not independent keyword matches for another error group.
                key_text='\n'.join(re.sub(r'^\s*\[[0-9TZ:./ -]+\]\s*','',part).strip() for part in context[:16000].splitlines())
                signature=hashlib.sha256((category+'\n'+key_text).encode()).hexdigest()
                if signature in findings:
                    finding=findings[signature];finding['occurrences']+=1
                    finding['last_line_in_segment']=index+1;finding['last_segment_offset']=segment_offset
                    break
                if len(findings)>=80:
                    omitted+=1;break
                matches=[]; folded=context.casefold()
                for name,tokens,item in names:
                    if any(token in folded for token in tokens) or item and re.search(r'(?:Installed|LocalMods)[/\\]+'+re.escape(item)+r'(?:[/\\]|$)',context,re.I): matches.append(name)
                from .runtime_evidence import locate,steps
                locations=locate(context,mods,features or {},env,check,cache)
                findings[signature]={'category':category,'line_in_tail':index+1,'possible_mods':list(dict.fromkeys(matches)),
                                 'line_in_file':index+1 if len(pieces)==1 and segment_offset==0 else None,
                                 'signature':signature,'occurrences':1,'segment_offset':segment_offset,
                                 'last_line_in_segment':index+1,'last_segment_offset':segment_offset,
                                 'stack_truncated':end==min(len(lines),index+129) and end<len(lines) or len(context)>16000,
                                 'evidence':'日志原文命中；归属仍需核实' if matches else '日志关键词线索，未确定模组归属',
                                 'text':redact(context[:16000],env),'advice':advice,
                                 'locations':locations,'steps':steps(locations,category)}
                break
    return {'file':path.name,'path':str(path),'tail_only':len(pieces)>1,'byte_offset':0,'changed_during_read':changed,
            'sha256':checksum.hexdigest(),'log_size':length,'segments':[{'offset':start,'bytes':len(raw)} for start,raw in pieces],
            'total_occurrences':total,'findings_truncated':omitted>0,'omitted_occurrences':omitted,'recognized_session_markers':sessions,
            'modified_utc':datetime.fromtimestamp(observed.st_mtime,tz=timezone.utc).isoformat(),
            'encoding':('UTF-16 LE' if bom==b'\xff\xfe' else 'UTF-16 BE') if utf16 else 'UTF-8',
            'findings':list(findings.values()),
            'signature_scope':'headline-stack-v2',
            'comparison_window':window,
            'note':'最多读取 16 MB；超大日志读取头尾并标明缺口。保留最早的 80 种错误并归并重复次数；关键词和路径不等于已确认根因。'}

def lua_verification(env):
    detected=status(env)
    return {'disk_status':asdict(detected),'runtime_verified':False,
            'instructions':['先关闭并重新启动游戏，确认客户端加载的是当前文件。',
                            '检查本次完整启动后的 LuaCs 日志和设置入口；不要用脚本热重载代替完整重启验证。',
                            '在 LuaCs 设置中确认 Are C# Mods Allowed 为 ENABLED，并测试你信任的 C# 模组。',
                            '保存新的游戏日志，再用助手“日志诊断”排查；磁盘检测和无错误日志不等于所有模组运行正常。'],
            'official_guide':'https://github.com/evilfactory/LuaCsForBarotrauma/blob/master/luacs-docs/lua/manual/installing-lua-for-barotrauma-manually.md'}
