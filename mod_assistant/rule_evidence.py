"""Local provenance and exact-version scopes, never executable rule expressions."""
from datetime import date
from dataclasses import replace
from .core import AssistantError,load_package

SCHEMA = 'barodock-order-rules-v2'
METHODS = {'manual', 'author', 'local_test'}


def installed_context(env,mods,rules):
    result=dict(mods)
    scoped={item for row in rules.get('evidence',[]) for item in row.get('versions',{})}
    for item in scoped:
        mod=mods.get(item)
        if mod is None: continue
        path=env.installed/item if item.isdecimal() else mod.source
        try: version=load_package(path).get('modversion','') if path else ''
        except (OSError,ValueError,AssistantError): version=''
        result[item]=replace(mod,installed_version=version)
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
    return result


def scope_status(record, mods, game_version):
    if record.get('game_version'):
        if not game_version: return 'unknown'
        if record['game_version'] != game_version: return 'stale'
    for item, version in record.get('versions', {}).items():
        mod = mods.get(item)
        if mod is None or not mod.installed_version: return 'unknown'
        if mod.installed_version != version: return 'stale'
    return 'applicable'


def effective_rules(rules, mods, game_version=''):
    records = {(row['before'],row['after']):row for row in rules.get('evidence',[])}
    active = []; evidence = []
    for before, after in rules['before']:
        record = records.get((before,after))
        status = scope_status(record,mods,game_version) if record else 'unrecorded'
        if status not in ('unknown','stale'): active.append([before,after])
        evidence.append({'before':before,'after':after,'status':status,'record':record})
    return {**rules,'before':active}, evidence


def evidence_lines(rows):
    lines = []
    labels = {'applicable':'版本范围匹配，仍需核实游戏表现', 'stale':'版本已变化，本次不沿用',
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
            if not record['game_version'] or len(record['versions']) != 2:
                lines.append('版本范围未完整记录，不能据此证明新版组合适用')
    return lines
