"""Subscribe/install profile requirements, then commit enabled state together."""
import threading
import json
import urllib.parse
import urllib.request
from .core import AssistantError, Cancelled, game_running, inventory
from .engine import UpdateEngine
from .profiles import apply_profile, normalize_profile, resolve_profile
from .snapshots import SnapshotStore
from .steam import SteamBridge

def verify_workshop_items(ids):
    """Check public ownership before subscribing a portable list of IDs."""
    for offset in range(0,len(ids),75):
        batch=ids[offset:offset+75]
        payload={'itemcount':len(batch),**{f'publishedfileids[{index}]':item for index,item in enumerate(batch)}}
        request=urllib.request.Request('https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/',
                                       data=urllib.parse.urlencode(payload).encode('ascii'),method='POST')
        try:
            with urllib.request.urlopen(request,timeout=15) as response:
                entries=json.loads(response.read(2*1024*1024))['response']['publishedfiledetails']
            known={str(entry['publishedfileid']):entry for entry in entries}
            for item in batch:
                entry=known.get(item,{})
                if entry.get('result')!=1 or int(entry.get('consumer_app_id',0))!=602960:
                    raise AssistantError('无法确认项目属于潜渊症或有访问权限，未订阅：'+item)
        except AssistantError: raise
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise AssistantError('无法核实工坊项目所属游戏，未订阅；请检查网络后重试') from error

def apply_with_downloads(env, data, download=False, allow_differences=False, emit=lambda event:None,
                         cancel=None, process_guard=game_running, bridge_factory=SteamBridge,
                         engine_factory=UpdateEngine, snapshot_factory=SnapshotStore,verify_items=verify_workshop_items):
    data=normalize_profile(data); cancel=cancel or threading.Event()
    if process_guard(): raise AssistantError('请先关闭游戏和服务器，再应用联机配置')
    mods=inventory(env); resolved,missing,differences=resolve_profile(env,data,mods)
    locals_missing=[entry for entry in missing if not entry['id'].isdecimal()]
    if locals_missing: raise AssistantError('缺少本地模组，无法从工坊自动取得：'+'、'.join(x.get('name',x['id']) for x in locals_missing))
    if missing and not download: raise AssistantError('配置有未安装的工坊模组，请使用“订阅下载并应用”')
    if differences and not download and not allow_differences:
        raise AssistantError('版本或文件与配置不同，未切换。\n'+'\n'.join(differences[:8]))
    targets={entry['id'] for entry in data['order'] if entry['id'].isdecimal()}
    if data.get('core') and data['core']['id'].isdecimal(): targets.add(data['core']['id'])
    store=snapshot_factory(env,emit=lambda message:emit({'kind':'scan_status','message':message}),
                           process_guard=process_guard,cancel=cancel)
    snapshot=store.capture('配置切换前',mods,targets)
    requested=[]
    if download:
        # Only missing/different requirements are refreshed; existing exact
        # matches are not needlessly replaced by a newer workshop revision.
        required = [entry for entry in data['order']] + ([data['core']] if data.get('core') else [])
        for entry in required:
            if entry['id'].isdecimal() and (entry['id'] not in resolved or
                entry.get('mod_version') and entry['mod_version'] != resolved[entry['id']].installed_version or
                entry.get('assistant_fingerprint') and any(resolved.get(entry['id']) and resolved[entry['id']].name in line for line in differences)):
                requested.append(entry['id'])
        if requested:
            verify_items(requested)
            if cancel.is_set(): raise Cancelled('配置应用已停止，启用状态未切换')
            if process_guard(): raise AssistantError('游戏刚刚启动，未订阅和切换配置')
            bridge=bridge_factory(env).connect()
            try:
                for item in requested:
                    emit({'kind':'scan_status','message':'订阅联机前置：'+item})
                    bridge.subscribe(item,cancel=cancel,process_guard=process_guard)
            finally: bridge.close()
            engine=engine_factory(env,emit,process_guard=process_guard); engine.cancel=cancel
            summary=engine.run(requested,online=True)
            if summary['errors']: raise AssistantError('部分模组下载或安装失败，启用配置未切换；可重试或恢复切换前快照')
    if cancel.is_set(): raise Cancelled('配置应用已停止，启用状态未切换')
    mods=inventory(env); _,missing,differences=resolve_profile(env,data,mods)
    if missing: raise AssistantError('仍有模组未安装，启用配置未切换')
    if differences and not allow_differences:
        raise AssistantError('本机当前工坊版本或文件与配置不一致，未切换。Steam 不提供按此清单下载旧版本；如接受差异，请勾选允许差异。\n'+'\n'.join(differences[:8]))
    backup=apply_profile(env,data,mods,process_guard)
    return {'backup':backup,'snapshot':snapshot['id'],'differences':differences,'downloaded':requested,
            'message':'配置已整体应用；下次启动游戏生效'+(' · 有版本/文件差异，联机一致性未确认' if differences else '')}
