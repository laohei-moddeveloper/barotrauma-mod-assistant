"""Bounded XML definition comparison for investigating companion patches."""
import difflib
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from .core import AssistantError, reject_link, within

class DefinitionTree(ET.TreeBuilder):
    def doctype(self,*args): raise AssistantError('XML 对照不读取文档类型或外部实体')
    def __init__(self):
        super().__init__(); self.depth=0; self.nodes=0
    def start(self,tag,attrs):
        self.depth+=1; self.nodes+=1
        if self.depth>128 or self.nodes>100000: raise AssistantError('XML 定义结构超过读取上限')
        return super().start(tag,attrs)
    def end(self,tag):
        value=super().end(tag); self.depth-=1; return value

def definition_text(folder, feature, key, check=lambda:None):
    values=[]; size=0
    for relative in feature.definition_files.get('|'.join(key),[]):
        check(); name=PurePosixPath(relative)
        if name.is_absolute() or ':' in relative or '\\' in relative or any(part in ('..','.','') for part in relative.split('/')):
            raise AssistantError('XML 对照文件路径无效')
        path=folder/str(name)
        if not within(path,folder): raise AssistantError('XML 对照文件超出模组目录')
        for parent in [path]+list(path.parents):
            if within(parent,folder): reject_link(parent)
        if path.stat().st_size>8_000_000: raise AssistantError('XML 对照文件过大，请在编辑器中查看')
        with path.open('rb') as stream: raw=stream.read(8_000_001)
        if len(raw)>8_000_000: raise AssistantError('XML 对照文件过大，请在编辑器中查看')
        document=ET.fromstring(raw,parser=ET.XMLParser(target=DefinitionTree()))
        found=[]
        for node in document.iter():
            check()
            if node.tag.casefold()!=key[1] or node.get('identifier','').strip().casefold()!=key[2]: continue
            for child in node.iter(): child.attrib=dict(sorted(child.attrib.items()))
            ET.indent(node); found.append(ET.tostring(node,encoding='unicode'))
        if not found: raise AssistantError('XML 定义在扫描后发生变化，请重新分析后对照')
        text='\n\n'.join(found); size+=len(text)
        if size>200_000: raise AssistantError('XML 定义对照过大，请在编辑器中查看')
        values.append('<!-- '+relative+' -->\n'+text)
    if not values: raise AssistantError('没有可定位的 XML 定义文件，请重新分析')
    return '\n\n'.join(values)

def compare_definition(left_folder,left,right_folder,right,key,check=lambda:None):
    a=definition_text(left_folder,left,key,check); b=definition_text(right_folder,right,key,check)
    diff='\n'.join(difflib.unified_diff(a.splitlines(),b.splitlines(),fromfile=left.name,tofile=right.name,lineterm=''))
    return {'left':a,'right':b,'diff':diff,'equal':a==b}
