"""Bounded structural changes and an explicitly scoped Item loading model.

The model follows GenericPrefabFile/PrefabSelector, not text similarity or
script regex. It does not evaluate prefab constructors, inheritance or Clear.
"""
from collections import Counter
import os
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from .core import AssistantError, reject_link, within
from .xml_compare import DefinitionTree

SOURCE = 'https://github.com/FakeFishGames/Barotrauma/blob/1fd2a51bbb1b44bac9ff3606f697bfa96142e7af/Barotrauma/BarotraumaShared/SharedSource/Prefabs/PrefabSelector.cs'
FIELD_SOURCE = 'https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/Items/ItemPrefab.cs'
ITEM_FIELDS = {
    '/item/@health':'物品耐久声明；默认 100，读取上限 1000000',
    '/item/@maxstacksize':'物品堆叠上限声明；默认 1，游戏还会限制允许范围',
    '/item/@allowasextracargo':'是否允许作为额外货物的声明',
    '/item/@tags':'物品标签声明，其他逻辑可能引用这些标签',
    '/item/price/@baseprice':'基础价格声明；商店、战役和脚本可进一步改变实际价格',
}
MAX_TOTAL = 64 * 1024 * 1024
MAX_FIELDS = 5000


def special_construct(node):
    return (node.tag.casefold()=='clear' or any(value and name.casefold() in ('variantof','inherit') for name,value in node.attrib.items())
            or any(name.casefold()=='identifier' and name!='identifier' for name in node.attrib))


def load_tree(folder,relative,check):
    name=PurePosixPath(relative)
    if name.is_absolute() or ':' in relative or '\\' in relative or any(part in ('..','.','') for part in relative.split('/')):
        raise AssistantError('XML 对照文件路径无效')
    path=folder/str(name)
    if not within(path,folder): raise AssistantError('XML 对照文件超出模组目录')
    for parent in [path,*path.parents]:
        if within(parent,folder): reject_link(parent)
    check()
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno()); data=stream.read(8_000_001); after=os.fstat(stream.fileno())
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise AssistantError('XML 文件在读取时变化，请重新分析')
    if len(data)>8_000_000: raise AssistantError('XML 对照文件过大，请在编辑器中查看')
    return ET.fromstring(data,parser=ET.XMLParser(target=DefinitionTree())),len(data)


def records(folder,feature,key,check,load=load_tree):
    result=[]; total=0; special=False
    for relative in feature.definition_files.get('|'.join(key),[]):
        root,size=load(folder,relative,check); total+=size
        if total>MAX_TOTAL: raise AssistantError('XML 语义读取总量超过上限')
        def walk(node,overriding=False):
            nonlocal special
            check(); tag=node.tag.casefold()
            if special_construct(node): special=True
            mode=overriding or tag=='override'
            if tag==key[1] and node.get('identifier','').strip().casefold()==key[2]:
                result.append({'file':relative,'override':mode,'node':node})
            if tag==key[1]: return
            if key[:2]==('item','item') and tag not in ('items','override','clear'): special=True
            for child in node: walk(child,mode)
        walk(root)
    return result,special


def fields(node,check):
    values={}; ambiguous=[]
    def walk(element,path,depth=0):
        check()
        if depth>128: raise AssistantError('XML 定义层级超过上限')
        if len(values)>MAX_FIELDS: raise AssistantError('XML 定义字段超过上限')
        values[path]='[node]'
        attrs={key.casefold():value for key,value in element.attrib.items()}
        if len(attrs)!=len(element.attrib): ambiguous.append(path)
        for key,value in attrs.items(): values[path+'/@'+key]=value
        if element.text and element.text.strip(): values[path+'/#text']=element.text.strip()
        counts=Counter(child.tag.casefold() for child in element); occurrences=Counter(); used=set()
        for child in element:
            tag=child.tag.casefold(); occurrences[tag]+=1
            identity=child.get('identifier','')
            if identity:
                segment=tag+'[identifier='+identity+']'
                if segment in used: ambiguous.append(path+'/'+segment)
            else:
                segment=tag+('['+str(occurrences[tag])+']' if counts[tag]>1 else '')
                if counts[tag]>1: ambiguous.append(path+'/'+tag)
            if segment in used: segment+='['+str(occurrences[tag])+']'
            used.add(segment); walk(child,path+'/'+segment,depth+1)
    walk(node,'/'+node.tag.casefold())
    if len(values)>MAX_FIELDS: raise AssistantError('XML 定义字段超过上限')
    return values,sorted(set(ambiguous))


def field_changes(left,right,baseline=None,check=lambda:None):
    a,amb_a=fields(left,check); b,amb_b=fields(right,check)
    base,amb_base=fields(baseline,check) if baseline is not None else ({},[])
    result=[]
    for path in sorted(set(a)|set(b)|set(base)):
        av,bv,original=a.get(path),b.get(path),base.get(path)
        if av==bv==original or baseline is None and av==bv: continue
        if baseline is None: kind='两边不同，原版基线未定位'
        elif av==bv: kind='双方相同修改'
        elif av!=original and bv!=original: kind='双方改变同一字段且结果不同'
        elif av!=original: kind='仅左方改变该字段'
        else: kind='仅右方改变该字段'
        result.append({'path':path,'baseline':original,'left':av,'right':bv,'kind':kind})
    return result,sorted(set(amb_a+amb_b+amb_base))


def vanilla_definition(env,key,check,load=load_tree):
    path=env.game/'Content/ContentPackages/Vanilla.xml'
    for parent in [path,*path.parents]: reject_link(parent)
    with path.open('rb') as stream: data=stream.read(2*1024*1024+1)
    if len(data)>2*1024*1024: raise AssistantError('原版清单超过读取上限')
    manifest=ET.fromstring(data,parser=ET.XMLParser(target=DefinitionTree()))
    result=[]; special=False; total=0; entries=[node for node in manifest if node.tag.casefold()==key[0]]
    if len(entries)>128: raise AssistantError('原版同类型文件数量超过上限')
    for entry in entries:
        relative=entry.get('file','').replace('\\','/')
        if not relative.casefold().startswith('content/'): raise AssistantError('原版资源路径不受支持')
        root,size=load(env.game,relative,check); total+=size
        if total>MAX_TOTAL: raise AssistantError('XML 语义读取总量超过上限')
        special|=any(node.tag.casefold()=='clear' for node in root.iter())
        for node in root.iter():
            check()
            if node.tag.casefold()==key[1] and node.get('identifier','').strip().casefold()==key[2]:
                special|=special_construct(node)
                result.append({'file':relative,'override':False,'node':node})
    return result,special


def loading_result(key,providers,baseline,complete=True,special=False,game_version=''):
    """Return a checkable registration outcome only for audited Item semantics."""
    supported=(key[:2]==('item','item') and game_version=='1.13.4.0')
    limits=[]
    if key[:2]!=('item','item'): limits.append('未建立加载模型的内容类型：'+key[0])
    if game_version!='1.13.4.0': limits.append('未核实的游戏版本：'+game_version)
    if not complete: limits.append('启用资料或原版基线未完整读取')
    if special: limits.append('发现 Clear、继承或不受支持的定义结构')
    for row in providers:
        if len(row['records'])!=1: limits.append('同一模组定义数量异常：'+row['name'])
    if not supported or not complete or special or any(len(row['records'])!=1 for row in providers):
        return {'status':'limited','winner':'','limits':limits,'message':'此定义包含未覆盖的类型、版本、继承、Clear 或不完整资料；下方字段差异可核对，不能计算完整加载结果。'}
    ordinary=[(row['id'],record) for row in providers for record in row['records'] if not record['override']]
    if len(ordinary)+len(baseline)>1:
        return {'status':'duplicate','winner':'','message':'按已核实的 Item 注册规则，多个普通定义注册同一标识会报错；移动顺序不能消除重复注册。'}
    override=[row for row in providers if row['records'][0]['override']]
    winner=override[0] if override else next((row for row in providers if not row['records'][0]['override']),None)
    return {'status':'selected','winner':winner['id'] if winner else 'vanilla',
            'message':'按 Item 注册规则选取一份完整定义；多个 Override 取启用列表中靠前者，不自动融合各自字段。'}


def compare_semantics(env,left_folder,left,right_folder,right,key,providers,order,check=lambda:None):
    cache={}; signatures={}; total=0; config_known=True; config_bytes=None; config_notes=[]
    try:
        reject_link(env.game/'config_player.xml')
        with (env.game/'config_player.xml').open('rb') as stream: config_bytes=stream.read(2*1024*1024+1)
        if len(config_bytes)>2*1024*1024: raise AssistantError('游戏配置超过读取上限')
        from .mod_order import read_order
        if read_order(env)!=order: raise AssistantError('启用顺序在对照期间变化，请重新分析')
    except (OSError,AssistantError) as error:
        config_known=False; config_notes.append('启用配置未能核对：'+str(error))
        order=[]
    def load(folder,relative,check):
        nonlocal total
        name=PurePosixPath(relative)
        if name.is_absolute() or ':' in relative or '\\' in relative or any(part in ('..','.','') for part in relative.split('/')):
            raise AssistantError('XML 对照文件路径无效')
        path=(folder/relative).resolve()
        if path not in cache:
            before=path.stat()
            value=load_tree(folder,relative,check); total+=value[1]
            if total>MAX_TOTAL: raise AssistantError('XML 语义读取总量超过上限')
            signatures[path]=(before.st_size,before.st_mtime_ns,before.st_ino)
            cache[path]=value
        return cache[path]
    a,special_a=records(left_folder,left,key,check,load); b,special_b=records(right_folder,right,key,check,load)
    if not a or not b: raise AssistantError('XML 定义在扫描后发生变化，请重新分析后对照')
    notes=list(config_notes); base=[]; special=False; complete=config_known
    try: base,special=vanilla_definition(env,key,check,load)
    except (OSError,ET.ParseError,AssistantError) as error:
        complete=False; notes.append('原版基线读取未完成：'+str(error))
    changes,ambiguous=field_changes(a[0]['node'],b[0]['node'],base[0]['node'] if len(base)==1 else None,check)
    if len(a)!=1 or len(b)!=1: notes.append('同一模组中有多份定义，字段对照只显示第一份；需逐文件核对。')
    chain=[]
    for item,folder,feature in providers:
        check()
        if item not in order: continue
        if folder is None or feature.partial or feature.deferred: complete=False; continue
        if key[0] not in feature.tags and key not in feature.definitions: continue
        # Clear can be present in an enabled package with no identifiers at all.
        manifest,_=load(folder,'filelist.xml',check)
        from .mod_analysis import _resource_path
        from .core import package_names
        name,aliases=package_names(manifest,feature.name)
        for entry in manifest:
            if entry.tag.casefold()!=key[0]: continue
            path=_resource_path(folder,entry.get('file',''),name,(item,*aliases))
            if path is None: complete=False; continue
            root,_=load(folder,path.relative_to(folder).as_posix(),check)
            special|=any(special_construct(node) for node in root.iter())
            for node in root.iter():
                if special_construct(node): notes.append('需要专项处理的结构：'+feature.name+' · '+path.relative_to(folder).as_posix()+' · '+node.tag)
        if key not in feature.definitions: continue
        rows,flags=records(folder,feature,key,check,load)
        if rows: chain.append({'id':item,'name':feature.name,'records':rows})
        complete &= bool(rows)
        special|=flags
    chain.sort(key=lambda row:order.index(row['id']))
    from .profiles import capture_profile,game_version
    try:
        current=capture_profile(env)
        if current.get('core') is not None: complete=False; notes.append('当前使用自定义核心包，原版基线不能代表完整加载环境。')
    except (OSError,ValueError,AssistantError) as error:
        complete=False; notes.append('启用配置未能核对：'+str(error))
    result=loading_result(key,chain,base,complete,special or special_a or special_b,game_version(env))
    if key[:2]==('item','item') and game_version(env)=='1.13.4.0':
        for change in changes:
            if change['path'] in ITEM_FIELDS: change['meaning']=ITEM_FIELDS[change['path']]
    if not chain and config_known: result={'status':'inactive','winner':'','message':'所选定义未启用，没有当前加载结果；这里只比较文件内容。'}
    if ambiguous: notes.append('重复子节点缺少唯一标识，按位置显示差异，不能当作已确认的功能对应。')
    if not chain and config_known: notes.append('所选定义不在当前启用列表中；本次只比较文件内容。')
    if any(feature.code_files or feature.opaque_code for _,_,feature in providers if feature.item_id in order):
        notes.append('启用模组含脚本或程序集；XML 注册结果不证明脚本执行后的实际结果。')
    for path,signature in signatures.items():
        reject_link(path); observed=path.stat()
        if (observed.st_size,observed.st_mtime_ns,observed.st_ino)!=signature: raise AssistantError('XML 文件在读取时变化，请重新分析')
    if config_bytes is not None:
        reject_link(env.game/'config_player.xml')
        with (env.game/'config_player.xml').open('rb') as stream: latest=stream.read(2*1024*1024+1)
        if latest!=config_bytes: raise AssistantError('启用顺序在对照期间变化，请重新分析')
    return {'changes':changes,'ambiguous':ambiguous,'notes':notes,'baseline_files':[row['file'] for row in base],
            'loading':result,'chain':[{'id':row['id'],'name':row['name'],
                                      'files':[{'file':record['file'],'override':record['override']} for record in row['records']]} for row in chain],
            'source':SOURCE,'field_source':FIELD_SOURCE}


def format_semantics(report,tr=lambda value:value):
    lines=[tr('字段变化与定义来源'),tr(report['loading']['message'])]
    lines.extend(tr(value) for value in report['loading'].get('limits',[]))
    if report['loading']['winner']: lines.append(tr('XML 注册模型选取的定义：')+report['loading']['winner'])
    lines.append(tr('当前启用顺序中的来源：'))
    for row in report['chain']:
        lines.append(row['name']+' ['+row['id']+']')
        for file in row['files']: lines.append(tr('Override：' if file['override'] else '普通定义：')+file['file'])
    for row in report['changes']:
        if row.get('meaning'): lines.append(tr(row['meaning']))
        lines.extend([row['path']+' · '+tr(row['kind']),
                      tr('原版：')+(row['baseline'] if row['baseline'] is not None else '[not declared]'),
                      tr('左方：')+(row['left'] if row['left'] is not None else '[not declared]'),
                      tr('右方：')+(row['right'] if row['right'] is not None else '[not declared]')])
    if not report['changes']: lines.append(tr('所比较的声明字段没有差异。'))
    for file in report.get('baseline_files',[]): lines.append(tr('原版定义文件：')+file)
    lines.extend(tr(note) for note in report['notes'])
    lines.extend([tr('未声明字段不等于数值为零；默认值和继承需另行核对。'),
                  tr('注册模型检查定义选取与重复注册，不验证构造函数、资源加载或实际游戏运行。'),tr('加载规则来源：')+report['source']])
    if any(row.get('meaning') for row in report['changes']): lines.append(tr('字段含义来源：')+report['field_source'])
    return '\n'.join(lines)
