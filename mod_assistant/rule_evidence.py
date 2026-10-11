"""Local provenance and exact-version scopes, never executable rule expressions."""
from datetime import date
from dataclasses import replace
from .core import AssistantError,load_package
from .file_evidence import SCOPE, ReadBudget, package_evidence, game_context_evidence
import re

SCHEMA = 'barodock-order-rules-v3'
METHODS = {'manual', 'author', 'local_test'}


def installed_context(env,mods,rules,cancel=None):
    result=dict(mods)
    records=rules.get('evidence',[])
    scoped={item for row in records for item in (*row.get('versions',{}),*row.get('fingerprints',{}))}
    hashed={item for row in records for item in row.get('fingerprints',{})}
    budget=ReadBudget()
    if any(row.get('context') for row in records):
        context=game_context_evidence(env,mods.values(),cancel,budget)
        result={item:replace(mod,context_digest=context['digest'],context_complete=context['complete']) for item,mod in result.items()}
    for item in scoped:
        mod=mods.get(item)
        if mod is None: continue
        path=env.installed/item if item.isdecimal() else mod.source
        try: version=load_package(path).get('modversion','') if path else ''
        except (OSError,ValueError,AssistantError): version=''
        result[item]=replace(result[item],installed_version=version)
        if item in hashed:
            evidence=package_evidence(path,cancel,budget)
            result[item]=replace(result[item],evidence_digest=evidence['digest'],evidence_scope=evidence['scope'],evidence_complete=evidence['complete'])
    return result


def normalize_evidence(values, pairs):
    if not isinstance(values, list) or len(values) > 2000:
        raise AssistantError('排序依据数量或格式无效')
    allowed = {tuple(pair) for pair in pairs}; seen = set(); result = []
    for value in values:
        if not isinstance(value, dict): raise AssistantError('排序依据格式无效')
        row = {}
        for key, limit in [('before',100),('after',100),('reason',2000),('source',2000),
                           ('checked_at',10),('game_version',100),('method',20)]:
            item = value.get(key, 'manual' if key == 'method' else '')
            if not isinstance(item, str) or len(item) > limit or '\x00' in item:
                raise AssistantError('排序依据字段无效')
            row[key] = item
        pair = (row['before'], row['after'])
        if pair not in allowed or pair in seen or row['method'] not in METHODS:
            raise AssistantError('排序依据必须唯一对应现有前后规则')
        if row['checked_at']:
            try:
                if date.fromisoformat(row['checked_at']).isoformat()!=row['checked_at']: raise ValueError()
            except ValueError as error: raise AssistantError('依据日期应为 YYYY-MM-DD') from error
        versions = value.get('versions', {})
        if not isinstance(versions, dict) or any(
            key not in pair or not isinstance(version,str) or not version or len(version)>100
            for key,version in versions.items()):
            raise AssistantError('依据模组版本无效')
        row['versions'] = dict(versions); seen.add(pair); result.append(row)
        fingerprints=value.get('fingerprints',{})
        if not isinstance(fingerprints,dict) or any(
            item not in pair or not isinstance(record,dict) or set(record)!={'scope','digest'}
            or record['scope']!=SCOPE or not isinstance(record['digest'],str)
            or re.fullmatch(r'[0-9a-f]{64}',record['digest']) is None
            for item,record in fingerprints.items()):
            raise AssistantError('排序依据文件摘要无效')
        if fingerprints: row['fingerprints']={item:dict(record) for item,record in fingerprints.items()}
        context=value.get('context')
        if context is not None:
            if not isinstance(context,dict) or set(context)!={'scope','digest'} or context['scope']!='game-core-runtime-v1' or not isinstance(context['digest'],str) or re.fullmatch(r'[0-9a-f]{64}',context['digest']) is None:
                raise AssistantError('排序依据核心摘要无效')
            row['context']=dict(context)
    return result


def scope_status(record, mods, game_version):
    if record.get('context'):
        context=mods.get(record['before'])
        if context is None or not context.context_complete:return 'unknown'
        if context.context_digest!=record['context']['digest']:return 'changed'
    if record.get('game_version'):
        if not game_version: return 'unknown'
        if record['game_version'] != game_version: return 'stale'
    for item, version in record.get('versions', {}).items():
        mod = mods.get(item)
        if mod is None or not mod.installed_version: return 'unknown'
        if mod.installed_version != version: return 'stale'
    for item, fingerprint in record.get('fingerprints',{}).items():
        mod=mods.get(item)
        if mod is None or not mod.evidence_complete or mod.evidence_scope!=fingerprint['scope']: return 'unknown'
        if mod.evidence_digest!=fingerprint['digest']: return 'changed'
    return 'applicable'


def effective_rules(rules, mods, game_version=''):
    records = {(row['before'],row['after']):row for row in rules.get('evidence',[])}
    active = []; evidence = []
    for before, after in rules['before']:
        record = records.get((before,after))
        status = scope_status(record,mods,game_version) if record else 'unrecorded'
        if status not in ('unknown','stale','changed'): active.append([before,after])
        evidence.append({'before':before,'after':after,'status':status,'record':record})
    return {**rules,'before':active}, evidence


def evidence_lines(rows):
    lines = []
    labels = {'applicable':'版本范围匹配，仍需核实游戏表现', 'stale':'版本已变化，本次不沿用',
              'changed':'相关文件已变化，本次不沿用旧依据',
              'unknown':'无法确认适用版本，本次不沿用', 'unrecorded':'没有来源或版本记录，按手工规则处理'}
    methods = {'manual':'手工判断', 'author':'用户记录的作者说明', 'local_test':'用户记录的实测'}
    for row in rows:
        lines.append(f"{row['before']} → {row['after']}：{labels[row['status']]}")
        record = row['record']
        if record:
            lines.append(methods[record['method']])
            for label,key in [('依据：','reason'),('来源：','source'),('记录日期：','checked_at'),('适用游戏版本：','game_version')]:
                if record[key]: lines.append(label + record[key])
            for item, version in record['versions'].items(): lines.append(f'适用模组版本：{item} = {version}')
            for item, fingerprint in record.get('fingerprints',{}).items():
                lines.append(f'文件依据：{item} · {fingerprint["scope"]} · {fingerprint["digest"]}')
            if record.get('context'):lines.append('核心与脚本环境摘要：'+record['context']['digest'])
            if not record['game_version'] or len(record['versions']) != 2:
                lines.append('版本范围未完整记录，不能据此证明新版组合适用')
    return lines
