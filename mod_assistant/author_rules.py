"""A small, read-only subset of BMT's documented metadata dependencies.

No mod parts, settings, expressions, or Python from a package are executed.
Unknown conditions are reported rather than guessed.
"""
import re
import xml.etree.ElementTree as ET
from .core import AssistantError, reject_link, within

TYPES={'patch','requirement','requiredAnyOrder','conflict'}
TOKEN=re.compile(r'''\s*(ifhas\s*\(\s*(['"])([^'"\r\n]{1,500})\2\s*\)|[&|()])''')


def condition_value(expression, active, ambiguous=()):
    if not expression or expression.casefold()=='none': return True
    if not isinstance(expression,str) or len(expression)>2000: return None
    tokens=[]; position=0
    while position<len(expression.rstrip()):
        match=TOKEN.match(expression,position)
        if match is None or len(tokens)>=100: return None
        tokens.append(('has',match.group(3).casefold()) if match.group(3) else match.group(1))
        position=match.end()
    cursor=0; active={x.casefold() for x in active}; ambiguous={x.casefold() for x in ambiguous}
    def atom(depth):
        nonlocal cursor
        if depth>25 or cursor>=len(tokens): raise ValueError()
        token=tokens[cursor]; cursor+=1
        if isinstance(token,tuple): return None if token[1] in ambiguous else token[1] in active
        if token!='(': raise ValueError()
        value=parse_or(depth+1)
        if cursor>=len(tokens) or tokens[cursor]!=')': raise ValueError()
        cursor+=1; return value
    def parse_and(depth):
        nonlocal cursor
        value=atom(depth)
        while cursor<len(tokens) and tokens[cursor]=='&':
            cursor+=1; other=atom(depth)
            value=False if value is False or other is False else None if value is None or other is None else True
        return value
    def parse_or(depth):
        nonlocal cursor
        value=parse_and(depth)
        while cursor<len(tokens) and tokens[cursor]=='|':
            cursor+=1; other=parse_and(depth)
            value=True if value is True or other is True else None if value is None or other is None else False
        return value
    try:
        value=parse_or(0)
        return value if cursor==len(tokens) else None
    except ValueError: return None


def read_rules(folder):
    path=folder/'metadata.xml'
    if not path.exists(): return [],[]
    try:
        reject_link(path)
        if not within(path,folder) or path.stat().st_size>1024*1024: raise ValueError()
        with path.open('rb') as stream: raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError()
        text=raw.decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper(): raise ValueError()
        root=ET.fromstring(text)
        if root.tag!='metadata': raise ValueError()
        rules=[]; notes=[]
        for node in root.findall('./dependencies/*'):
            item=node.get('steamID',''); name=node.get('name',''); condition=node.get('condition','')
            valid_id=bool(re.fullmatch('[1-9][0-9]{0,19}',item)) and int(item)<2**64
            if node.tag not in TYPES or not (valid_id or name.strip()) or len(name)>500 or len(condition)>2000 or len(node):
                notes.append('metadata.xml 含不支持的依赖声明，该声明未参与排序。'); continue
            rules.append({'type':node.tag,'id':item if valid_id else '', 'name':name,'condition':condition,'source':'metadata.xml'})
            if len(rules)>1000: raise ValueError()
        return rules,list(dict.fromkeys(notes))
    except (OSError,ValueError,UnicodeError,ET.ParseError,AssistantError):
        return [],['metadata.xml 无法安全读取，作者声明未参与排序。']


def rule_context(mods):
    names={}
    for item,mod in mods.items():
        for name in {value.casefold() for value in (mod.name,*mod.aliases)}: names.setdefault(name,[]).append(item)
    unique={name:values[0] for name,values in names.items() if len(values)==1}
    ambiguous={name for name,values in names.items() if len(values)>1}
    return unique,ambiguous


def applicable(rule, active, mods, context=None):
    if context is None:
        unique,ambiguous=rule_context(mods)
        labels=set(active)|{name for name,item in unique.items() if item in active}
    else: unique,ambiguous,labels=context
    value=condition_value(rule['condition'],labels,ambiguous)
    target=rule['id'] or unique.get(rule['name'].casefold())
    return value,target,not rule['id'] and rule['name'].casefold() in ambiguous
