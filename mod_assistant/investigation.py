"""Local investigation records and reviewable native repair presets."""
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import re
import uuid

from .core import AssistantError, atomic_json, inventory, reject_link
from .file_evidence import ReadBudget, SCOPE, changed_files, package_evidence, read_stable, relative_name, confirm_package, game_context_evidence, confirm_game_context
from .profiles import capture_profile, installed_path

SCHEMA = 'barodock-investigation-v1'
MAX_RECORD = 8 * 1024 * 1024
ID = re.compile(r'(?:[0-9]{1,20}|local:[0-9a-f]{16})\Z')


def validate_input_files(files):
    if not isinstance(files,dict) or len(files)>12000:raise AssistantError('排查记录文件数量无效')
    for name,record in files.items():
        relative_name(name)
        if not isinstance(record,dict) or set(record)!={'sha256','size'} or not isinstance(record.get('sha256'),str) or re.fullmatch(r'[0-9a-f]{64}',record['sha256']) is None or type(record.get('size')) is not int or not 0<=record['size']<=64*1024*1024:
            raise AssistantError('排查记录文件摘要无效')


def validate_evidence(evidence):
    if not isinstance(evidence,dict) or evidence.get('scope')!=SCOPE or type(evidence.get('complete')) is not bool:raise AssistantError('排查记录文件范围无效')
    files=evidence.get('files');validate_input_files(files)
    expected=hashlib.sha256(json.dumps(sorted(files.items()),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if evidence['complete'] and evidence.get('digest')!=expected:raise AssistantError('排查记录文件摘要不一致')
    if not evidence['complete'] and evidence.get('digest')!='':raise AssistantError('排查记录完整性字段不一致')


def capture_scene(env, mods=None, name='', steps='', phase='before', cancel=None, log=None, emit=lambda message:None):
    if phase not in ('before', 'after') or len(name) > 100 or len(steps) > 4000:
        raise AssistantError('排查记录字段无效')
    mods = list(mods if mods is not None else inventory(env))
    config, raw = read_stable(env.game/'config_player.xml', env.game, cancel, retain=True, limit=2*1024*1024)
    profile = capture_profile(env, name or '排查记录', mods,include_receipts=False,cancel=cancel)
    known = {mod.item_id: mod for mod in mods}
    active = [entry['id'] for entry in profile['order']]
    core = profile.get('core')
    ids = list(dict.fromkeys(([core['id']] if core else []) + active))
    budget = ReadBudget()
    rows = {}
    for number,item in enumerate(ids,1):
        mod = known[item]
        emit('记录文件证据：{0}/{1} · {2}'.format(number,len(ids),mod.name))
        folder = installed_path(env, mod)
        evidence = package_evidence(folder, cancel, budget)
        rows[item] = {'name':mod.name, 'version':next((entry.get('mod_version','') for entry in ([core] if core else [])+profile['order'] if entry['id']==item),''), 'evidence':evidence}
    vanilla = read_stable(env.game/'Content/ContentPackages/Vanilla.xml', env.game, cancel, limit=2*1024*1024)
    from .luacs import status
    emit('记录核心内容与脚本设置…')
    core_context=game_context_evidence(env,mods,cancel,budget)
    disk=status(env)
    runtime_files=core_context['runtime']
    final_profile=capture_profile(env,name or '排查记录',mods,include_receipts=False,cancel=cancel)
    if any(final_profile[key]!=profile[key] for key in ('game_version','core','order')) or core_context['game_version']!=profile['game_version']:
        raise AssistantError('配置在记录期间变化，请重新记录')
    current, latest = read_stable(env.game/'config_player.xml', env.game, cancel, retain=True, limit=2*1024*1024)
    if latest != raw:
        raise AssistantError('配置在记录期间变化，请重新记录')
    for item,row in rows.items():
        if row['evidence']['complete'] and not confirm_package(row['evidence'],installed_path(env,known[item]),cancel):
            raise AssistantError('证据文件在记录期间变化，请重新记录')
        row['evidence'].pop('_stamps',None)
    if core_context['complete'] and not confirm_game_context(core_context,env,cancel):raise AssistantError('核心证据在读取期间变化')
    result = {'schema':SCHEMA, 'id':uuid.uuid4().hex, 'created_at':datetime.now(timezone.utc).isoformat(),
              'name':name or '排查记录', 'steps':steps, 'phase':phase, 'game_version':profile['game_version'],
              'game_binding':hashlib.sha256(str(env.game.resolve()).casefold().encode()).hexdigest(),
              'config_hash':config['sha256'], 'core':core['id'] if core else 'vanilla',
              'core_manifest':vanilla if core is None else rows[core['id']]['evidence']['files'].get('filelist.xml'),
              'order':active, 'mods':rows, 'profile':profile,
              'scope':SCOPE, 'complete':all(row['evidence']['complete'] for row in rows.values()) and core_context['complete'],
              'core_inputs':core_context['inputs'],
              'runtime':{'disk_luacs_trace':disk.runtime,'csharp_policy':disk.policy,'files':runtime_files},
              'notes':['文件摘要覆盖 XML、Lua、C# 和 DLL；不包含所有纹理、音频和游戏程序。',
                       '核心内容记录 XML、Lua、C# 与 DLL 输入，不包含所有纹理和音频。',
                       '这是文件与配置记录，不是成功加载或安全认证。']}
    if log is not None:
        result['log'] = log_reference(log)
    validate_scene(result)
    return result


def log_reference(report):
    return {key:copy.deepcopy(report.get(key)) for key in
            ('file','modified_utc','byte_offset','sha256','log_size','encoding','tail_only','changed_during_read','findings_truncated','findings','comparison_window','signature_scope')}


def validate_scene(value):
    if not isinstance(value,dict) or value.get('schema') != SCHEMA:
        raise AssistantError('排查记录格式无效')
    if len(json.dumps(value,ensure_ascii=False).encode()) > MAX_RECORD:
        raise AssistantError('排查记录超过读取上限')
    if not isinstance(value.get('id'),str) or re.fullmatch(r'[0-9a-f]{32}',value['id']) is None:
        raise AssistantError('排查记录编号无效')
    for key,limit in [('name',100),('steps',4000),('game_version',100),('created_at',100)]:
        if not isinstance(value.get(key),str) or len(value[key])>limit:
            raise AssistantError('排查记录字段无效')
    try:
        if datetime.fromisoformat(value['created_at']).tzinfo is None:raise ValueError()
    except ValueError as error:raise AssistantError('排查记录日期无效') from error
    if value.get('scope') != SCOPE or value.get('phase') not in ('before','after') or type(value.get('complete')) is not bool:
        raise AssistantError('排查记录范围无效')
    for key in ('game_binding','config_hash'):
        if not isinstance(value.get(key),str) or re.fullmatch(r'[0-9a-f]{64}',value[key]) is None:
            raise AssistantError('排查记录摘要无效')
    order,mods=value.get('order'),value.get('mods')
    if not isinstance(order,list) or len(order)>1000 or any(not isinstance(item,str) or not ID.fullmatch(item) for item in order) or len(set(order))!=len(order):
        raise AssistantError('排查记录清单无效')
    if not isinstance(mods,dict) or len(mods)>1001 or any(not isinstance(item,str) or not ID.fullmatch(item) for item in mods):
        raise AssistantError('排查记录模组无效')
    if any(item not in mods for item in order) or value.get('core') not in ('vanilla',*mods):
        raise AssistantError('排查记录清单不完整')
    for row in mods.values():
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or len(row['name'])>2000:
            raise AssistantError('排查记录名称无效')
        if not isinstance(row.get('version'),str) or len(row['version'])>100:raise AssistantError('排查记录版本无效')
        validate_evidence(row.get('evidence'))
    validate_evidence(value.get('core_inputs'))
    runtime=value.get('runtime',{})
    if not isinstance(runtime,dict) or type(runtime.get('disk_luacs_trace')) is not bool or runtime.get('csharp_policy') not in ('Enabled','Disabled','Prompt','Unknown'):raise AssistantError('排查记录运行设置无效')
    validate_input_files(runtime.get('files',{}))
    manifest=value.get('core_manifest')
    if manifest is not None:validate_input_files({'filelist.xml':manifest})
    if value['complete'] != (all(row['evidence']['complete'] for row in mods.values()) and value.get('core_inputs',{}).get('complete',True)):raise AssistantError('排查记录完整性字段不一致')
    if not isinstance(value.get('notes'),list) or len(value['notes'])>30 or any(not isinstance(note,str) or len(note)>2000 for note in value['notes']):raise AssistantError('排查记录说明无效')
    from .profiles import normalize_profile
    profile=normalize_profile(value.get('profile'))
    if [entry['id'] for entry in profile['order']]!=order or (profile['core']['id'] if profile.get('core') else 'vanilla')!=value['core']:
        raise AssistantError('排查记录原生清单不一致')
    if set(mods)!=set(order)|({value['core']} if value['core']!='vanilla' else set()) or profile['game_version']!=value['game_version']:
        raise AssistantError('排查记录原生清单不一致')
    for entry in profile['order']+([profile['core']] if profile.get('core') else []):
        if entry.get('mod_version','')!=mods[entry['id']]['version']:raise AssistantError('排查记录原生清单不一致')
    log=value.get('log')
    if log is not None:
        if not isinstance(log,dict) or not isinstance(log.get('findings'),list) or len(log['findings'])>80:raise AssistantError('排查记录日志无效')
        if log.get('signature_scope') not in (None,'headline-stack-v2'):raise AssistantError('排查记录日志无效')
        for key in ('tail_only','changed_during_read','findings_truncated'):
            if type(log.get(key)) is not bool:raise AssistantError('排查记录日志无效')
        for key in ('byte_offset','log_size'):
            if type(log.get(key)) is not int or not 0<=log[key]<=2**63-1:raise AssistantError('排查记录日志无效')
        if log['byte_offset']>log['log_size'] or not isinstance(log.get('file'),str) or len(log['file'])>2000:raise AssistantError('排查记录日志无效')
        if not isinstance(log.get('sha256'),str) or re.fullmatch(r'[0-9a-f]{64}',log['sha256']) is None or not isinstance(log.get('modified_utc'),str):raise AssistantError('排查记录日志无效')
        try:
            if datetime.fromisoformat(log['modified_utc']).tzinfo is None:raise ValueError()
        except ValueError as error:raise AssistantError('排查记录日志日期无效') from error
        window=log.get('comparison_window')
        if window is not None:
            if not isinstance(window,dict) or window.get('kind') not in ('append','replacement') or type(window.get('complete')) is not bool:raise AssistantError('排查记录日志无效')
            if not isinstance(window.get('baseline_sha256'),str) or re.fullmatch('[0-9a-f]{64}',window['baseline_sha256']) is None:raise AssistantError('排查记录日志无效')
            for key in ('baseline_size','start','end'):
                if type(window.get(key)) is not int or not 0<=window[key]<=log['log_size']:raise AssistantError('排查记录日志无效')
            if window['start']>window['end'] or window['end']!=log['log_size']:raise AssistantError('排查记录日志无效')
            if window['kind']=='append' and window['start']!=window['baseline_size'] or window['kind']=='replacement' and window['start']!=0:raise AssistantError('排查记录日志无效')
        for row in log['findings']:
            if not isinstance(row,dict) or any(not isinstance(row.get(key),str) or len(row[key])>20000 for key in ('category','text','signature')):raise AssistantError('排查记录异常无效')
            if re.fullmatch('[0-9a-f]{64}',row['signature']) is None or type(row.get('occurrences')) is not int or not 1<=row['occurrences']<=2**63-1 or type(row.get('stack_truncated')) is not bool:raise AssistantError('排查记录异常无效')
    return value


def save_scene(env, scene):
    validate_scene(scene)
    folder=env.work/'investigations'
    if folder.exists():reject_link(folder)
    path=folder/(scene['id']+'.json')
    if path.exists():raise AssistantError('排查记录已存在，原记录保留')
    atomic_json(path,scene)
    return path


def read_scene(path):
    path=Path(path); reject_link(path)
    with path.open('rb') as stream:raw=stream.read(MAX_RECORD+1)
    if len(raw)>MAX_RECORD:raise AssistantError('排查记录超过读取上限')
    try:return validate_scene(json.loads(raw))
    except (ValueError,TypeError,KeyError,RecursionError) as error:raise AssistantError('排查记录损坏，原文件保留') from error


def compare_scenes(before, after):
    validate_scene(before); validate_scene(after)
    differences=[]
    for key,label in [('game_binding','选定游戏目录'),('game_version','游戏版本'),('core','核心包'),('core_manifest','核心清单'),('order','启用状态或顺序')]:
        if before.get(key)!=after.get(key):differences.append({'kind':label,'before':before.get(key),'after':after.get(key)})
    old_runtime,new_runtime=before.get('runtime',{}),after.get('runtime',{})
    if old_runtime.get('csharp_policy')!=new_runtime.get('csharp_policy'):
        differences.append({'kind':'C# 磁盘策略变化','before':old_runtime.get('csharp_policy'),'after':new_runtime.get('csharp_policy')})
    for change in changed_files({'files':old_runtime.get('files',{})},{'files':new_runtime.get('files',{})}):
        differences.append({'kind':'游戏程序集或脚本设置',**change})
    for change in changed_files(before.get('core_inputs',{}),after.get('core_inputs',{})):
        differences.append({'kind':'核心内容文件变化',**change})
    if before['config_hash']!=after['config_hash'] and before['order']==after['order'] and before['core']==after['core']:
        differences.append({'kind':'其他游戏配置变化'})
    for item in sorted(set(before['mods'])|set(after['mods'])):
        old,new=before['mods'].get(item),after['mods'].get(item)
        if old is None or new is None:
            differences.append({'kind':'启用项目新增' if old is None else '启用项目移除','id':item,'name':(new or old)['name']});continue
        if old['version']!=new['version']:differences.append({'kind':'模组版本变化','id':item,'name':new['name'],'before':old['version'],'after':new['version']})
        for change in changed_files(old['evidence'],new['evidence']):
            differences.append({'kind':'模组文件变化','id':item,'name':new['name'],**change})
    return {'differences':differences,'complete':before['complete'] and after['complete'],
            'same_scope':before['scope']==after['scope'],'same_recorded_inputs':not differences and before['complete'] and after['complete']}


def compare_logs(before, after):
    """Require new, stable log bytes; disappearance means not reproduced, not cured."""
    valid=bool(before.get('sha256') and after.get('sha256') and not before.get('changed_during_read') and not after.get('changed_during_read'))
    fresh=valid and (before['sha256'],before.get('byte_offset'),before.get('log_size'))!=(after['sha256'],after.get('byte_offset'),after.get('log_size'))
    signature=lambda row:row.get('signature') or hashlib.sha256((row['category']+'\n'+row['text']).encode()).hexdigest()
    old={signature(row):row for row in before.get('findings',[])}
    new={signature(row):row for row in after.get('findings',[])}
    matching_scope=before.get('signature_scope')==after.get('signature_scope')
    comparable=fresh and matching_scope and not before.get('tail_only') and not after.get('tail_only') and not before.get('findings_truncated') and not after.get('findings_truncated')
    comparable=comparable and not any(row.get('stack_truncated') for row in (*before.get('findings',[]),*after.get('findings',[])))
    window=after.get('comparison_window')
    if window is not None:
        comparable=comparable and window.get('complete') is True and window.get('baseline_sha256')==before.get('sha256') and window.get('baseline_size')==before.get('log_size')
    elif before.get('file')==after.get('file') and after.get('log_size',0)>before.get('log_size',0):
        # A legacy/full-file report may include errors from an older session.
        comparable=False
    return {'fresh_log':fresh,'complete_comparison':comparable,
            'still_present':[old[key] for key in old.keys()&new.keys()] if matching_scope else [],
            'not_reproduced':[old[key] for key in old.keys()-new.keys()] if comparable else [],
            'new_errors':[new[key] for key in new.keys()-old.keys()] if fresh and matching_scope else []}


def repair_candidates(report, profile, features, check=lambda:None):
    """Offer one removal per actual duplicate provider; never auto-apply it."""
    active={entry['id'] for entry in profile['order']}
    core=profile['core']['id'] if profile.get('core') else 'vanilla'
    candidates=[]; seen=set()
    for finding in report.get('findings',[]):
        check()
        rows=[row for row in finding.get('locations',[]) if row.get('identifier') and not row.get('override') and row['mod_id'] in active|{core}]
        if len(rows)<2:continue
        for row in rows:
            check()
            item=row['mod_id']
            if item not in active or item in seen:continue
            seen.add(item)
            removed={item};uncertain=set()
            # Keep declared necessary prerequisites: include dependents in removal,
            # never enable an unselected package or assume names imply dependencies.
            from .author_rules import applicable
            mods={entry['id']:type('ModName',(),{'name':entry['name'],'aliases':()})() for entry in profile['order']}
            changed=True
            while changed:
                changed=False
                for other in active-removed:
                    check()
                    feature=features.get(other)
                    if feature is None or feature.partial or feature.deferred:continue
                    for rule in feature.declared_rules:
                        check()
                        if rule['type'] not in ('requirement','requiredAnyOrder'):continue
                        condition,target,ambiguous=applicable(rule,active-removed,mods)
                        if condition is None or ambiguous or condition is True and target is None:uncertain.add(other)
                        if condition is True and not ambiguous and target in removed:
                            removed.add(other);changed=True;break
            draft=copy.deepcopy(profile)
            draft['order']=[entry for entry in draft['order'] if entry['id'] not in removed]
            draft['name']='排查草稿 · '+row['mod_name']
            unchecked=sorted(other for other in active-removed if other in uncertain or features.get(other) is None or features[other].partial or features[other].deferred or features[other].rule_notes)
            candidates.append({'target':item,'removed':sorted(removed),'identifier':row['identifier'],'profile':draft,'unchecked_dependencies':unchecked,
                               'note':'这是重复注册的排查候选；请在独立测试会话复现，尚未证明唯一根因。'})
    return candidates
