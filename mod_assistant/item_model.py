"""Item registration and variant XML model, independently implemented from game sources.

This models registry selection/XML composition, not constructors, assets or scripts.
Each input package supplies the actual Item-file roots in manifest order.
"""
from collections import defaultdict
import copy
import math
import re
import struct
import xml.etree.ElementTree as ET

from .core import AssistantError, Cancelled

SOURCE_REVISION = 'e6e95da83b1b5ca8b55ec52653c7cf6b40e30247'
SOURCE = 'https://github.com/FakeFishGames/Barotrauma/blob/'+SOURCE_REVISION+'/Barotrauma/BarotraumaShared/SharedSource/Prefabs/IImplementsVariants.cs'
MAX_DEFINITIONS = 20000


def runtime_fields(values):
    """Reviewed Health/MaxStackSize defaults and setters, finite numeric subset."""
    result={}
    health=values.get('/item/@health','100')
    if len(health)<=100 and re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',health.strip()):
        try:
            value=f32(health)
            if math.isfinite(value):result['health']=min(value,1000000)
        except AssistantError:pass
    stack=values.get('/item/@maxstacksize','1')
    if len(stack)<=100 and re.fullmatch(r'[+-]?[0-9]+',stack.strip()):
        value=int(stack)
        if -2147483648<=value<=2147483647:result['maxstacksize']=max(1,min(value,63))
    return result


def attribute(node,name,default=''):
    return next((value for key,value in node.attrib.items() if key.casefold()==name),default)


def item_nodes(root,check=lambda:None):
    """ItemFile accepts any singular tag; Item component identifiers are not prefabs."""
    def walk(node,override=False):
        check();tag=node.tag.casefold()
        if tag=='override':
            for child in node:yield from walk(child,True)
        elif tag=='items':
            for child in node:yield from walk(child,override)
        elif tag=='clear':yield 'clear',node,False
        else:yield 'item',node,override
    yield from walk(root)


def f32(value):
    try:return struct.unpack('f',struct.pack('f',float(value)))[0]
    except (OverflowError,ValueError):raise AssistantError('继承数值超出已核实范围')


def arithmetic(old,new):
    """Supported finite invariant-number subset of the game's float32 operations."""
    if not new.startswith(('*','+')):return new
    try:left=f32(old.replace(',',''));right=f32(new[1:].replace(',',''))
    except AssistantError:raise AssistantError('继承数值无法按已核实格式计算')
    result=f32(left*right if new[0]=='*' else left+right)
    if not math.isfinite(result):raise AssistantError('继承数值超出已核实范围')
    if '.' not in old and '.' not in new[1:]:
        if not -2147483648<=result<=2147483647:raise AssistantError('继承整数超出已核实范围')
        return str(int(result))
    # A shortest decimal that round-trips the computed float32 value.
    for precision in range(1,10):
        text=format(result,f'.{precision}g')
        if f32(text)==result:return text
    return format(result,'.9g')


def merge_variant(parent,variant,parent_package='',variant_package='',check=lambda:None):
    result=copy.deepcopy(parent)
    if parent_package and parent_package!=variant_package:
        for node in list(result.iter())[1:]:
            for key,value in list(node.attrib.items()):
                if '%ModDir%' in value:node.set(key,value.replace('%ModDir%','%ModDir:'+parent_package+'%'))
    def replace(target,source,depth=0):
        check()
        if depth>128:raise AssistantError('XML 定义层级超过上限')
        for name,value in source.attrib.items():
            existing=next((key for key in target.attrib if key.casefold()==name.casefold()),None)
            if existing is None:target.set(name,value)
            else:target.set(existing,arithmetic(target.get(existing),value))
        remove=[];counts=defaultdict(int)
        clear_names={child.tag.casefold() for node in source if node.tag.casefold()=='clearall' for child in node}
        source_children=list(source)
        for source_index,replacement in enumerate(source_children):
            check();tag=replacement.tag.casefold();ordinal=counts[tag];counts[tag]+=1
            matches=[child for child in target if child.tag.casefold()==tag]
            if tag=='clearall':
                found=[child for child in target if child.tag.casefold() in clear_names]
                remove.extend(child for child in found if child not in remove)
                if not found:target.append(copy.deepcopy(replacement))
            elif tag=='clear' and len(target):
                remove.extend(list(target))
                for child in source_children[source_index+1:]:target.append(copy.deepcopy(child))
                break
            elif ordinal<len(matches):
                child=matches[ordinal]
                if not replacement.attrib and not len(replacement):remove.append(child)
                else:replace(child,replacement,depth+1)
            else:target.append(copy.deepcopy(replacement))
        for child in dict.fromkeys(remove):
            if child in list(target):target.remove(child)
    replace(result,variant)
    return result


def build_registry(packages,check=lambda:None):
    definitions=defaultdict(list);clears=[];count=0;unsupported=[]
    for package in packages:
        for filename,root in package['files']:
            for kind,node,override in item_nodes(root,check):
                count+=1
                if count>MAX_DEFINITIONS:raise AssistantError('定义数量超过专项模型上限')
                record={'id':package['id'],'name':package['name'],'index':package['index'],'file':filename,'node':node,'override':override}
                if kind=='clear':clears.append(record);continue
                identifier=attribute(node,'identifier').strip().casefold()
                if not identifier:
                    # Legacy generated identifiers require additional enum/name logic.
                    unsupported.append({'id':package['id'],'file':filename,'reason':'legacy_identifier'})
                    continue
                # Python casefold expands e.g. ß into ss; .NET OrdinalIgnoreCase
                # does not. Never report a collision based on that expansion.
                if not attribute(node,'identifier').isascii():
                    unsupported.append({'id':package['id'],'file':filename,'reason':'unicode_identifier'})
                    continue
                definitions[identifier].append(record)
    threshold=max((row['index'] for row in clears),default=-10**9)
    selected={};failures={};package_failures=defaultdict(list)
    for identifier,rows in definitions.items():
        bases=[row for row in rows if not row['override']]
        overrides=sorted((row for row in rows if row['override']),key=lambda row:row['index'])
        if len(bases)>1:
            for row in bases[1:]:package_failures[row['id']].append({'identifier':identifier,'file':row['file']})
            failures[identifier]={'status':'duplicate','records':bases,'message':'多个普通定义注册同一标识，排序或 Clear 不能消除注册错误。'};continue
        chosen=overrides[0] if overrides else bases[0] if bases else None
        if len(overrides)>1 and overrides[0]['index']==overrides[1]['index']:
            failures[identifier]={'status':'ambiguous','records':overrides,'message':'同一内容包存在同标识的多个 Override，包内同优先级不能据此确定唯一结果。'};continue
        if chosen and chosen['index']<threshold:
            failures[identifier]={'status':'cleared','records':[chosen], 'message':'选中的定义被后面的 Clear 内容包屏蔽，不会回退选择另一份 Override。'};continue
        if chosen:selected[identifier]=chosen
    resolved={};resolving=[]
    def resolve(identifier):
        check()
        if identifier in resolved:return resolved[identifier]
        if identifier in failures:return failures[identifier]
        if identifier in resolving:
            return {'status':'inheritance_cycle','message':'继承形成循环：'+' → '.join(resolving[resolving.index(identifier):]+[identifier])}
        row=selected.get(identifier)
        if row is None:return {'status':'missing_parent','message':'继承父定义未找到：'+identifier}
        if len(resolving)>=128:return {'status':'limited','message':'继承层级超过读取上限'}
        resolving.append(identifier)
        parent=attribute(row['node'],'inherit',attribute(row['node'],'variantof')).strip().casefold()
        result={'status':'selected','record':row,'node':copy.deepcopy(row['node']),'parents':[]}
        if parent:
            inherited=resolve(parent)
            if inherited['status']!='selected':
                result={'status':inherited['status'],'message':inherited.get('message','父定义不可用'),'parent':parent,'record':row}
            else:
                try:
                    result['node']=merge_variant(inherited['node'],row['node'],inherited['record']['name'],row['name'],check)
                    result['parents']=[parent,*inherited['parents']]
                except Cancelled:raise
                except AssistantError as error:result={'status':'limited','message':str(error),'record':row}
        resolving.pop();resolved[identifier]=result
        return result
    return {'definitions':dict(definitions),'clears':clears,'selected':selected,'failures':failures,'resolve':resolve,'package_failures':dict(package_failures),'unsupported':unsupported}


def explain_identifier(registry,identifier,check=lambda:None):
    from .xml_semantics import fields
    result=registry['resolve'](identifier)
    output={'status':result['status'],'winner':result.get('record',{}).get('id',''),'message':result.get('message',''),
            'parents':result.get('parents',[]),'lost_changes':[],'final_fields':{},'ambiguous_fields':[]}
    if result['status']!='selected':
        if result['status']=='cleared':
            blocking=[{**error,'provider':row['id']} for row in registry['clears'] for error in registry['package_failures'].get(row['id'],[])]
            if blocking:output.update(status='package_registration_failure',winner='',message='选中来源包的其他标识存在注册错误，不能假定该包完整加载。',package_errors=blocking)
        return output
    if registry.get('unsupported'):
        output.update(status='limited',winner='',message='专项加载模型未完成，原始字段仍可对照。',unsupported=registry['unsupported'])
        return output
    required=[result['record']['id'],*[registry['resolve'](parent)['record']['id'] for parent in result['parents']]]
    blocking=[{**error,'provider':item} for item in dict.fromkeys(required) for error in registry['package_failures'].get(item,[])]
    if blocking:
        output.update(status='package_registration_failure',winner='',message='选中来源包的其他标识存在注册错误，不能假定该包完整加载。',package_errors=blocking)
        return output
    def projected(node):
        canonical=copy.deepcopy(node);canonical.tag='Item';return fields(canonical,check)
    final,ambiguity=projected(result['node']);output['final_fields']=final;output['ambiguous_fields']=ambiguity
    output['expected_runtime_fields']=runtime_fields(final)
    output['selected_xml']=ET.tostring(result['node'],encoding='unicode');output['winner_name']=result['record']['name']
    output['parent_providers']=list(dict.fromkeys(registry['resolve'](parent)['record']['id'] for parent in result['parents']))
    baseline=next((row for row in registry['definitions'].get(identifier,[]) if row['index']==-1),None)
    base_values=projected(baseline['node'])[0] if baseline else {}
    for row in registry['definitions'].get(identifier,[]):
        if row is result['record']:continue
        values,ambiguous=projected(row['node'])
        for path,value in values.items():
            if path.endswith(('/@identifier','/@variantof','/@inherit')) or any(path.startswith(part) for part in (*ambiguity,*ambiguous)):continue
            if value!=base_values.get(path) and value!=final.get(path):
                output['lost_changes'].append({'id':row['id'],'name':row['name'],'file':row['file'],'path':path,'declared':value,'selected':final.get(path)})
    output['message']='按 Item 模型选取定义并解析继承；下方显示未进入选中定义的声明变化。'
    return output
