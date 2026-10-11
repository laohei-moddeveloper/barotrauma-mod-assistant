"""Explicit attribute-only companion drafts, written outside installed mods."""
from collections import Counter
import copy
import json
import re
import uuid
import xml.etree.ElementTree as ET

from .core import AssistantError, reject_link
from .xml_compare import DefinitionTree
from .xml_semantics import fields


def editable_changes(report):
    item=report.get('item_result') or {}
    if item.get('status')!='selected' or not item.get('selected_xml'):return []
    result=[];seen=set()
    for row in item.get('lost_changes',[]):
        path=row['path']
        if '/@' not in path or path.endswith(('/@identifier','/@inherit','/@variantof')):continue
        if any(path.startswith(part) for part in item.get('ambiguous_fields',[])):continue
        if path not in item['final_fields']:continue
        identity=(row['id'],row['file'],path,row['declared'])
        if identity in seen:continue
        seen.add(identity);result.append(copy.deepcopy(row))
    return result


def compose(report,choices):
    available=editable_changes(report)
    if not isinstance(choices,list) or not choices or len(choices)>100 or any(type(index) is not int or not 0<=index<len(available) for index in choices):
        raise AssistantError('兼容草稿字段选择无效')
    selected=[available[index] for index in dict.fromkeys(choices)]
    if len({row['path'] for row in selected})!=len(selected):raise AssistantError('同一字段只能选择一个来源值')
    item=report['item_result'];text=item['selected_xml']
    if len(text)>200000:raise AssistantError('XML 定义对照过大，请在编辑器中查看')
    root=ET.fromstring(text,parser=ET.XMLParser(target=DefinitionTree()));root.tag='Item'
    nodes={}
    def walk(node,path):
        nodes[path]=node;counts=Counter(child.tag.casefold() for child in node);occurrences=Counter()
        for child in node:
            tag=child.tag.casefold();occurrences[tag]+=1;identity=child.get('identifier','')
            segment=tag+'[identifier='+identity+']' if identity else tag+('['+str(occurrences[tag])+']' if counts[tag]>1 else '')
            walk(child,path+'/'+segment)
    walk(root,'/item')
    before,_=fields(root,lambda:None)
    for row in selected:
        path,name=row['path'].rsplit('/@',1);node=nodes.get(path)
        if node is None:raise AssistantError('兼容草稿字段选择无效')
        actual=next((key for key in node.attrib if key.casefold()==name),None)
        if actual is None or before.get(row['path'])!=row['selected']:raise AssistantError('兼容草稿字段选择无效')
        source_name=row['name']
        if not source_name or any(char in source_name for char in '%:\r\n') or len({provider['id'] for provider in report['providers'] if provider['name'].casefold()==source_name.casefold()})>1:raise AssistantError('兼容草稿资源来源名称无效')
        value=re.sub(r'%ModDir%',lambda match:'%ModDir:'+source_name+'%',row['declared'],flags=re.I)
        node.set(actual,value)
    # Moving a definition into a companion mod changes %ModDir%. Bind its
    # existing paths to the original package; inherited named paths stay bound.
    name=item['winner_name']
    if not name or any(char in name for char in '%:\r\n'):raise AssistantError('兼容草稿资源来源名称无效')
    if len({row['id'] for row in report['providers'] if row['name'].casefold()==name.casefold()})>1:raise AssistantError('兼容草稿资源来源名称无效')
    for node in root.iter():
        for key,value in list(node.attrib.items()):
            node.set(key,re.sub(r'%ModDir%',lambda match:'%ModDir:'+name+'%',value,flags=re.I))
    wrapper=ET.Element('Override');wrapper.append(root)
    return wrapper,selected


def export_draft(env,report,choices):
    root,selected=compose(report,choices)
    parent=env.work/'patch-drafts'
    if parent.exists():reject_link(parent)
    folder=parent/('BaroDock-Patch-'+uuid.uuid4().hex[:12]);folder.mkdir(parents=True)
    package=ET.Element('contentpackage',{'name':folder.name,'corepackage':'false','modversion':'0.1-draft','gameversion':report['game_version']})
    ET.SubElement(package,'Item',{'file':'%ModDir%/Items/patch.xml'})
    (folder/'Items').mkdir()
    ET.ElementTree(package).write(folder/'filelist.xml',encoding='utf-8',xml_declaration=True)
    ET.indent(root);ET.ElementTree(root).write(folder/'Items/patch.xml',encoding='utf-8',xml_declaration=True)
    metadata=ET.Element('metadata');dependencies=ET.SubElement(metadata,'dependencies')
    names={row['id']:row['name'] for row in report['providers']}
    for item in dict.fromkeys([report['item_result']['winner'],*report['item_result'].get('parent_providers',[]),*[row['id'] for row in selected]]):
        if item=='vanilla':continue
        attributes={'name':names.get(item,report['item_result']['winner_name'])}
        if item.isdecimal():attributes['steamID']=item
        ET.SubElement(dependencies,'requiredAnyOrder',attributes)
    ET.ElementTree(metadata).write(folder/'metadata.xml',encoding='utf-8',xml_declaration=True)
    (folder/'choices.json').write_text(json.dumps({'schema':'barodock-patch-draft-v1','identifier':report['key'][2],'choices':selected},ensure_ascii=False,indent=2),encoding='utf-8')
    guide=('REVIEW REQUIRED\n'
           'This is an attribute-only draft from the displayed XML comparison. No installed mod or active list was changed.\n'
           'Review paths and dependencies; refresh the comparison if sources changed. Copy this folder into LocalMods only after review.\n'
           'Place this draft BEFORE competing regular Override packages in the enabled list. A core Override may prevent it from winning.\n'
           'It cannot fix duplicate ordinary registration, scripts, constructors, or other content types. Use a separate test round and import game observations to verify.\n')
    (folder/'README.txt').write_text(guide,encoding='utf-8')
    return folder
