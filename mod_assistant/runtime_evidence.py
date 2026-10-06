"""Link explicit logged errors to current XML; no source-code regex analysis."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from .core import AssistantError,Cancelled,reject_link
from .profiles import installed_path
from .xml_semantics import records,vanilla_definition


def vanilla_active(env):
    from .game_config import package_regions
    try:
        reject_link(env.game/'config_player.xml')
        with (env.game/'config_player.xml').open('rb') as stream: raw=stream.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: return False
        _,core=package_regions(raw.decode('utf-8-sig'))
        if core is None: return False
        value=ET.fromstring(core.group()).get('path','').replace('\\','/')
        path=Path(value); path=path if path.is_absolute() else env.game/path
        return path.resolve()==(env.game/'Content/ContentPackages/Vanilla.xml').resolve()
    except (OSError,ValueError,AssistantError): return False


def locate(context,mods,features,env,check=lambda:None,cache=None):
    result=[]
    if env is None: return result
    folded=context.replace('\\','/').casefold()
    for mod in mods:
        check()
        folder=installed_path(env,mod)
        if folder is None: continue
        root=folder.as_posix().casefold()
        if not re.search(re.escape(root)+r'''(?=[/:\s"'\]\)]|$)''',folded): continue
        feature=features.get(mod.item_id)
        paths={file for values in feature.definition_files.values() for file in values} if feature else set()
        found=False
        for path in sorted(paths):
            if not re.search(re.escape(root+'/'+path.casefold())+r'''(?=[:\s"'\]\)]|$)''',folded): continue
            result.append({'mod_id':mod.item_id,'mod_name':mod.name,'file':path,'kind':'日志明确提及的文件路径'}); found=True
        if not found: result.append({'mod_id':mod.item_id,'mod_name':mod.name,'file':'','kind':'日志提及模组目录，不能单凭此确定责任'})
        line=re.search(re.escape(root)+r'''/([^\r\n"]{1,500}\.(?:cs|lua|xml))(?::line\s*(\d+)|:(\d+))''',folded)
        if line and '..' not in line[1].split('/'):
            result.append({'mod_id':mod.item_id,'mod_name':mod.name,'file':line[1],
                           'source_line':int(line[2] or line[3]),'kind':'日志报告的源码位置，尚未证明根因'})
    # This is a known game's exception message, not an inference from C# source.
    match=re.search(r'Failed to add the prefab\s+(.+?)\s+from\s+',context,re.I)
    if not match or 'same identifier' not in context.casefold(): return result
    quoted=re.findall(r'"([^"\r\n]+)"',match[1])
    if not quoted: return result
    identifier=quoted[-1].casefold()
    category='item' if 'ItemPrefab' in match[1] else None
    if category is None: return result
    key=(category,category,identifier)
    for mod in mods:
        check()
        feature=features.get(mod.item_id)
        if feature is None or key not in feature.definitions or feature.partial or feature.deferred: continue
        folder=installed_path(env,mod)
        if folder is None: continue
        try: definitions,_=records(folder,feature,key,check)
        except Cancelled: raise
        except (OSError,ET.ParseError,AssistantError): continue
        for definition in definitions:
            result.append({'mod_id':mod.item_id,'mod_name':mod.name,'file':definition['file'],
                           'identifier':identifier,'override':definition['override'],
                           'kind':'日志重复注册标识对应当前 XML 定义'})
    cache={} if cache is None else cache
    if 'vanilla_active' not in cache: cache['vanilla_active']=vanilla_active(env)
    if not cache['vanilla_active']: return result
    if key not in cache:
        try: cache[key]=vanilla_definition(env,key,check)[0]
        except Cancelled: raise
        except (OSError,ET.ParseError,AssistantError): cache[key]=[]
    for definition in cache[key]:
        result.append({'mod_id':'vanilla','mod_name':'Vanilla','file':definition['file'],
                       'identifier':identifier,'override':False,'kind':'日志重复注册标识对应当前 XML 定义'})
    return result


def steps(locations,category):
    definitions=[row for row in locations if 'identifier' in row]
    if len([row for row in definitions if not row['override']])>=2:
        return ['先保存当前清单和快照。',
                '当前文件存在同标识的多份普通 Item 定义；先停用其中一个涉及模组，完整重启并复现原操作。',
                '若需保留两者，应使用能移除重复普通定义的作者兼容方案，或在本地副本中修订定义。仅新增 Override 补丁或移动顺序不能消除两份普通定义的注册。',
                '重新读取本次启动产生的日志，确认相同标识的错误是否消失；消失不等于其他故障也已排除。']
    if locations:
        return ['日志提及的路径或定义是定位依据，不能直接证明该模组是唯一根因。',
                '保存现场后核对所列文件与版本，按相同操作复现；比较新日志中的第一条异常及完整调用栈。']
    return ['尚未从日志定位到模组文件；请保留完整异常与调用栈、使用的清单和复现步骤。']
