"""Bounded read-only log triage; findings distinguish matches from guesses."""
from dataclasses import asdict
from pathlib import Path
import re
from .luacs import status

def recent_logs(env):
    candidates = set()
    for root in (env.game, env.player):
        for pattern in ('*.log','*crash*.txt','*Crash*.txt','DebugConsole*.txt'):
            candidates.update(root.glob(pattern))
        for name in ('Logs','logs','ServerLogs','DebugConsole','LuaCsLogs'):
            folder = root/name
            if folder.is_dir():
                candidates.update(folder.glob('*.txt')); candidates.update(folder.glob('*.log'))
    return sorted((p for p in candidates if p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True)[:20]

def redact(text, env=None):
    if env:
        for path in (env.game,env.player): text=text.replace(str(path),'[本机目录]').replace(path.as_posix(),'[本机目录]')
    text=re.sub(r'(?i)((?:token|password|authorization|secret|api[_ -]?key)\s*[:=]\s*)\S+',r'\1[隐藏]',text)
    text=re.sub(r'\b7656119\d{10}\b','[Steam 用户编号]',text)
    return text

def diagnose(path, mods, env=None):
    path=Path(path)
    with path.open('rb') as stream:
        length=path.stat().st_size
        bom=stream.read(2)
        offset=max(0,length-4*1024*1024)
        utf16=bom in (b'\xff\xfe',b'\xfe\xff')
        if utf16 and offset%2: offset+=1
        stream.seek(offset)
        raw=stream.read()
    if utf16: text=raw.decode('utf-16-le' if bom==b'\xff\xfe' else 'utf-16-be',errors='replace').lstrip('\ufeff')
    else: text=raw.decode('utf-8-sig',errors='replace')
    lines=text.splitlines(); findings=[]
    patterns=[('重复定义',r'duplicate|already exists|same identifier|重复定义', '核对重叠模组和 Override；普通重复定义通常需要兼容补丁或禁用其中一个。'),
              ('缺失资源/前置',r'missing dependency|dependencies.*missing|could not find|not found|找不到|不存在','检查必需模组是否安装启用、资源路径是否正确；必要时重新校验缓存。'),
              ('版本不匹配',r'incompatible|version mismatch|版本.*不.*匹配','对比游戏、LuaCs 和房主模组版本，避免混用更新前后的组件。'),
              ('脚本/程序异常',r'exception|stack traceback|lua.*error|syntax error|harmony.*error|脚本.*错误','核实 LuaCs/C# 状态；按日志中模组路径定位，分组启用复现。'),
              ('下载/读写问题',r'timeout|access denied|sharing violation|disk.*full|校验失败|超时','检查 Steam 下载状态、磁盘空间和文件占用，关闭游戏后重试。')]
    for index,line in enumerate(lines):
        for category,pattern,advice in patterns:
            if re.search(pattern,line,re.I):
                context='\n'.join(lines[max(0,index-1):min(len(lines),index+4)])
                matches=[]
                for mod in mods:
                    tokens=[mod.item_id] if mod.item_id.isdecimal() else []
                    if len(mod.name)>=4: tokens.append(mod.name)
                    if mod.source: tokens.append(mod.source.name)
                    if any(len(token)>=4 and token.casefold() in context.casefold() for token in tokens): matches.append(mod.name)
                findings.append({'category':category,'line_in_tail':index+1,'possible_mods':list(dict.fromkeys(matches)),
                                 'evidence':'日志原文命中；归属仍需核实' if matches else '日志关键词线索，未确定模组归属',
                                 'text':redact(context[:1500],env),'advice':advice})
                break
    return {'file':path.name,'tail_only':length>len(raw),'findings':findings[-80:],
            'note':'只读取最近最多 4 MB；行号相对于读取片段。关键词和路径匹配不等于已确认根因。'}

def lua_verification(env):
    detected=status(env)
    return {'disk_status':asdict(detected),'runtime_verified':False,
            'instructions':['先关闭并重新启动游戏，确认客户端加载的是当前文件。',
                            '在游戏 F3 控制台输入 cl_reloadluacs，查看是否出现未知命令或 LuaCs 加载错误。',
                            '在 LuaCs 设置中确认 Are C# Mods Allowed 为 ENABLED，并测试你信任的 C# 模组。',
                            '保存新的游戏日志，再用助手“日志诊断”排查；磁盘检测和无错误日志不等于所有模组运行正常。'],
            'official_guide':'https://github.com/evilfactory/LuaCsForBarotrauma/blob/master/luacs-docs/lua/manual/installing-lua-for-barotrauma-manually.md'}
