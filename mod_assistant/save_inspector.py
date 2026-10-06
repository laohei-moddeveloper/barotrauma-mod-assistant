"""Read only a user-selected campaign archive; never extract or alter a save."""
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import struct
import zlib
import uuid
import xml.etree.ElementTree as ET
from .core import AssistantError, Cancelled, load_package, package_names, reject_link,atomic_json
from .profiles import capture_profile, installed_path, reference

MAX_COMPRESSED = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_SESSION = 8 * 1024 * 1024
MAX_ENTRIES = 4096


class SaveTree(ET.TreeBuilder):
    def doctype(self,*args): raise AssistantError('存档检查不读取文档类型或外部实体')
    def __init__(self):
        super().__init__(); self.depth=0; self.nodes=0
    def start(self,tag,attrs):
        self.depth+=1; self.nodes+=1
        if self.depth>128 or self.nodes>100000: raise AssistantError('存档 XML 结构超过读取上限')
        return super().start(tag,attrs)
    def end(self,tag):
        value=super().end(tag); self.depth-=1; return value


@dataclass
class SaveInfo:
    filename: str
    digest: str
    game_version: str
    saved_at: str
    names: list[str]
    notes: list[str]


def split_names(value):
    """Match the game's pipe escape convention without a regex XML parser."""
    names=[]; start=0
    for index,char in enumerate(value):
        if char != '|': continue
        slashes=0; pos=index-1
        while pos>=0 and value[pos]=='\\': slashes+=1; pos-=1
        if slashes % 2 == 0:
            names.append(value[start:index].replace('\\|','|')); start=index+1
    names.append(value[start:].replace('\\|','|'))
    return [name for name in names if name]


def read_save(path, cancel=None):
    path=Path(path)
    for parent in [path,*path.parents]: reject_link(parent)
    if path.suffix.casefold() != '.save': raise AssistantError('请选择战役 .save 文件')
    def check():
        if cancel and cancel.is_set(): raise Cancelled('存档读取已取消，存档和配置未改变')
    with path.open('rb') as source:
        observed=os.fstat(source.fileno())
        if observed.st_size>MAX_COMPRESSED: raise AssistantError('存档压缩文件超过读取上限')
        digest=hashlib.sha256()
        class HashedSource:
            def read(self,size=-1):
                check(); data=source.read(size); digest.update(data)
                if source.tell()>MAX_COMPRESSED: raise AssistantError('存档压缩文件超过读取上限')
                return data
        expanded=0; entries=0; session=None; names=set()
        try:
            with gzip.GzipFile(fileobj=HashedSource(),mode='rb') as archive:
                def read(size, optional=False):
                    nonlocal expanded
                    check()
                    if size<0 or size>MAX_EXPANDED-expanded and not optional: raise AssistantError('存档展开内容超过读取上限')
                    data=archive.read(size); expanded+=len(data)
                    if expanded>MAX_EXPANDED: raise AssistantError('存档展开内容超过读取上限')
                    if len(data)!=size and not(optional and not data): raise AssistantError('存档内容被截断')
                    return data
                while True:
                    header=read(4,optional=True)
                    if not header: break
                    entries+=1
                    if entries>MAX_ENTRIES: raise AssistantError('存档条目超过读取上限')
                    length=struct.unpack('<i',header)[0]
                    if not 0<length<=255: raise AssistantError('存档条目名称长度无效')
                    name=read(length*2).decode('utf-16-le').replace('\\','/')
                    relative=PurePosixPath(name)
                    if (relative.is_absolute() or ':' in name or '\x00' in name
                            or any(part in ('..','.','') for part in name.split('/'))):
                        raise AssistantError('存档含无效条目路径')
                    if name.casefold() in names: raise AssistantError('存档含重复条目，不能确定读取内容')
                    names.add(name.casefold()); size=struct.unpack('<i',read(4))[0]
                    if size<0 or size>MAX_EXPANDED-expanded: raise AssistantError('存档条目大小无效或超过上限')
                    if name.casefold()=='gamesession.xml':
                        if size>MAX_SESSION: raise AssistantError('存档会话 XML 超过读取上限')
                        session=read(size)
                    else:
                        remaining=size
                        while remaining: amount=min(65536,remaining); read(amount); remaining-=amount
        except (EOFError,gzip.BadGzipFile,UnicodeError,struct.error,zlib.error) as error:
            raise AssistantError('存档归档格式无效或损坏') from error
        current=os.fstat(source.fileno()); after=path.stat()
        # Windows fstat's legacy ctime differs from Path.stat's creation time.
        signature=lambda stat:(stat.st_size,stat.st_mtime_ns,stat.st_ino)
        if signature(observed)!=signature(current) or signature(observed)!=signature(after):
            raise AssistantError('存档在读取时发生变化，请重新选择')
    if session is None: raise AssistantError('存档没有根目录 gamesession.xml')
    try: document=ET.fromstring(session,parser=ET.XMLParser(target=SaveTree()))
    except ET.ParseError as error: raise AssistantError('存档会话 XML 无法读取') from error
    if document.tag.casefold()!='gamesession': raise AssistantError('存档会话根节点不受支持')
    if len(document.get('version',''))>100 or len(document.get('savetime',''))>200:
        raise AssistantError('存档版本或时间记录超过上限')
    if 'selectedcontentpackagenames' not in document.attrib:
        raise AssistantError('此旧存档没有模组名称记录，请使用原有清单或快照核对')
    names=split_names(document.get('selectedcontentpackagenames',''))
    if len(names)>1000 or any(len(name)>500 for name in names): raise AssistantError('存档模组记录超过上限')
    notes=['存档只提供已记录的同步包名称与顺序，不提供全部客户端模组、工坊编号或历史文件。',
           '名称匹配不证明版本或文件相同；这里只生成待审核配置，不修改存档或启用列表。']
    if len({name.casefold() for name in names})!=len(names): notes.append('存档含重复名称，必须人工核对，不能自动生成配置。')
    return SaveInfo(path.name,digest.hexdigest(),document.get('version',''),document.get('savetime',''),names,notes)


def candidates(env, info, mods):
    available={}; aliases={}
    for mod in mods:
        path=installed_path(env,mod)
        if path is None or not(path/'filelist.xml').is_file(): continue
        try:
            for parent in [path/'filelist.xml',path,*path.parents]: reject_link(parent)
            with (path/'filelist.xml').open('rb') as stream: raw=stream.read(2*1024*1024+1)
            if len(raw)>2*1024*1024: raise AssistantError('模组清单文件过大')
            root=ET.fromstring(raw,parser=ET.XMLParser(target=SaveTree())); name,other=package_names(root,mod.name)
            if root.tag.casefold()!='contentpackage': raise AssistantError('模组清单根节点无效')
        except (OSError,ET.ParseError,AssistantError) as error:
            info.notes.append('未读取的模组清单：'+mod.name+' · '+str(error)); continue
        available[mod.item_id]={'mod':mod,'name':name,'core':root.get('corepackage','false').casefold()=='true'}
        for value in (name,*other): aliases.setdefault(value.casefold(),set()).add(mod.item_id)
    path=env.game/'Content/ContentPackages/Vanilla.xml'
    if path.is_file():
        for parent in [path,*path.parents]: reject_link(parent)
        if path.stat().st_size>2*1024*1024: raise AssistantError('原版清单超过读取上限')
        root=ET.fromstring(path.read_bytes(),parser=ET.XMLParser(target=SaveTree()))
        name,other=package_names(root,'Vanilla')
        available['vanilla']={'mod':None,'name':name,'core':True}
        for value in (name,*other): aliases.setdefault(value.casefold(),set()).add('vanilla')
    return available,[{'name':name,'candidates':sorted(aliases.get(name.casefold(),set()))} for name in info.names]


def build_profile(env, info, available, rows, selections=None, keep_extra=True, mods=None):
    selections=selections or {}; ids=[]
    if not rows: raise AssistantError('存档未记录模组名称，不能推断配置')
    if len({row['name'].casefold() for row in rows})!=len(rows): raise AssistantError('存档名称重复，不能自动生成配置')
    for index,row in enumerate(rows):
        values=row['candidates']; chosen=selections.get(index)
        if chosen is None and len(values)==1: chosen=values[0]
        if chosen not in values: raise AssistantError('存在缺失或同名项目，请逐项确认后生成配置')
        if chosen in ids: raise AssistantError('多个存档项目对应同一模组，请核对名称')
        ids.append(chosen)
    cores=[item for item in ids if available[item]['core']]
    if len(cores)>1: raise AssistantError('存档对应多个核心内容包，不能自动生成配置')
    if cores and ids[0]!=cores[0]: raise AssistantError('存档核心包位置异常，请人工核对')
    current=capture_profile(env,mods=mods)
    regular=[item for item in ids if not available[item]['core']]
    extra=[entry for entry in current['order'] if entry['id'] not in regular]
    draft={**current,'name':info.filename+' · 待审核','game_version':info.game_version,
           'order':[reference(env,available[item]['mod']) for item in regular]+(extra if keep_extra else []),
           'save_reference':{'filename':info.filename,'sha256':info.digest,'saved_at':info.saved_at,
                             'recorded_names':list(info.names),'historical_files_verified':False},
           'note':'存档名称匹配生成的待审核配置；版本字段是当前本机文件，不是存档当时的版本。'}
    if cores: draft['core']=None if cores[0]=='vanilla' else reference(env,available[cores[0]]['mod'])
    return draft,extra


def profile_matches(info, profiles):
    result=[]; target=[name.casefold() for name in info.names]
    for data in profiles:
        core=data.get('core'); names=([core.get('name','')] if core else ['Vanilla'])+[entry.get('name','') for entry in data.get('order',[])]
        folded=[name.casefold() for name in names]
        indices={name:index for index,name in enumerate(folded)}
        positions=[indices[name] for name in target if name in indices]
        result.append({'name':data.get('name',''),'missing':[name for name in info.names if name.casefold() not in folded],
                       'order_matches':len(set(folded))==len(folded) and len(set(target))==len(target) and len(positions)==len(target) and positions==sorted(positions),
                       'extra':[name for name in names if name.casefold() not in target]})
    return result


def save_native_preset(env,draft):
    from .native_profiles import write_native
    path=write_native(env.game/'ModLists'/('Save-review-'+uuid.uuid4().hex[:12]+'.xml'),draft)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    source={key:draft['save_reference'][key] for key in ('filename','sha256','saved_at','historical_files_verified')}
    try: atomic_json(env.work/'save-associations'/(digest+'.json'),source)
    except OSError as error: raise AssistantError('原生清单已保存，但关联记录未保存：'+str(path)) from error
    return path


def association_for(env,raw):
    digest=hashlib.sha256(raw).hexdigest(); path=env.work/'save-associations'/(digest+'.json')
    try:
        for parent in [path,*path.parents]: reject_link(parent)
        if path.stat().st_size>16384: return None
        data=json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data,dict) or not isinstance(data.get('filename'),str) or len(data['filename'])>500
                or not isinstance(data.get('sha256'),str) or len(data['sha256'])!=64
                or any(char not in '0123456789abcdef' for char in data['sha256'])): return None
        return data
    except (OSError,ValueError,AssistantError): return None
