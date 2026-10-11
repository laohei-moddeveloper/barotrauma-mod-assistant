"""Resolve declared game/mod resource paths within approved roots only."""
from pathlib import Path
import re

from .core import AssistantError, reject_link, within

MACRO=re.compile(r'%ModDir(?::([^%]+))?%',re.I)


def resolve_resource(value, env, owner, packages):
    if not isinstance(value,str) or len(value)>2000 or not value or '\0' in value:
        return {'status':'invalid','file':value,'provider':''}
    names={}
    for item,row in packages.items():
        for name in dict.fromkeys((item,row['name'],*row.get('aliases',()))):
            names.setdefault(name.casefold(),[]).append(item)
    matches=list(MACRO.finditer(value));provider=owner
    if len(matches)>1:return {'status':'unresolved','file':value,'provider':''}
    if matches:
        match=matches[0]
        if match.start()!=0:return {'status':'unresolved','file':value,'provider':''}
        if match[1]:
            candidates=names.get(match[1].casefold(),[])
            if len(candidates)!=1:return {'status':'ambiguous' if candidates else 'unresolved','file':value,'provider':''}
            provider=candidates[0]
        if provider not in packages:return {'status':'unresolved','file':value,'provider':''}
        root=Path(packages[provider]['folder'])
        if not value[match.end():].startswith(('/','\\')):return {'status':'unresolved','file':value,'provider':provider}
        relative=value[match.end():].replace('\\','/').lstrip('/')
    else:
        root=env.game;provider='game';relative=value.replace('\\','/')
    if Path(value).is_absolute() and not matches:
        candidate=Path(value)
        approved=[('game',env.game),*[(item,Path(row['folder'])) for item,row in packages.items()]]
        match_root=next(((item,base) for item,base in approved if within(candidate,base)),None)
        if match_root is None:return {'status':'outside_scope','file':value,'provider':''}
        provider,root=match_root;relative=candidate.resolve().relative_to(root.resolve()).as_posix()
    if '%' in relative or ':' in relative or relative.startswith('/') or any(part in ('..','') for part in relative.split('/')):
        return {'status':'outside_scope','file':value,'provider':provider}
    candidate=root/relative
    if not within(candidate,root):return {'status':'outside_scope','file':value,'provider':provider}
    try:
        for parent in (candidate,*candidate.parents):
            if within(parent,root) and parent.exists():reject_link(parent)
        exists=candidate.is_file()
    except (OSError,AssistantError):return {'status':'unreadable','file':relative,'provider':provider}
    return {'status':'exists' if exists else 'missing','file':relative,'provider':provider}


def item_references(node,env,owner,packages,registry,check=lambda:None):
    rows=[]
    def walk(element,path,depth=0):
        check()
        if depth>128:raise AssistantError('XML 定义层级超过上限')
        if len(rows)>1000:raise AssistantError('引用数量超过专项检查上限')
        tag=element.tag.casefold()
        if tag.endswith('sprite'):
            for key,value in element.attrib.items():
                if key.casefold()=='texture':rows.append({'kind':'声明的纹理路径','path':path+'/@'+key,'declared':value,**resolve_resource(value,env,owner,packages)})
        if tag in ('fabricate','deconstruct'):
            for child in element:
                child_tag=child.tag.casefold()
                if child_tag not in ('requireditem','item'):continue
                value=next((value for key,value in child.attrib.items() if key.casefold()=='identifier'),'').strip().casefold()
                if not value or ',' in value:continue
                result=registry['resolve'](value)
                if result['status']=='selected':
                    providers=[result['record']['id'],*[registry['resolve'](parent)['record']['id'] for parent in result.get('parents',[])]]
                    if registry.get('unsupported') or any(registry['package_failures'].get(item) for item in providers):
                        result={**result,'status':'package_registration_failure'}
                rows.append({'kind':'配方声明的物品标识','path':path+'/'+child_tag+'/@identifier','declared':value,
                             'status':'definition_available' if result['status']=='selected' else 'not_found_in_model' if result['status']=='missing_parent' else 'target_unavailable',
                             'target_status':result['status'],'provider':result.get('record',{}).get('id',''),'file':result.get('record',{}).get('file','')})
        for index,child in enumerate(element):walk(child,path+'/'+child.tag.casefold()+'['+str(index+1)+']',depth+1)
    walk(node,'/item')
    return rows


LABELS={
    'exists':'文件存在','missing':'声明文件不存在','ambiguous':'同名资源包有多个候选',
    'unresolved':'资源路径未完整定位','outside_scope':'路径超出允许读取范围','unreadable':'资源路径不可读取',
    'invalid':'资源路径格式无效','definition_available':'当前模型中有可用定义',
    'not_found_in_model':'当前模型中未找到声明标识','target_unavailable':'目标定义在当前模型中不可用',
}
