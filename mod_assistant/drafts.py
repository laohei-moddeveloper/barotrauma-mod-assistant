"""Atomic, local enabled-list drafts. An open draft cannot overwrite newer config."""
import xml.etree.ElementTree as ET
from pathlib import Path
from .core import APP_ID, AssistantError, game_running
from .mod_toggle import configured_key
from .mod_order import validate_order, load_rules
from .profiles import SCHEMA, config_bytes, commit_config, game_version
from .rule_evidence import installed_context


def commit_draft(env, ids, baseline, original_ids, mods, process_guard=game_running):
    if len(set(ids)) != len(ids) or any(item not in {mod.item_id for mod in mods} for item in ids):
        raise AssistantError('草稿含未知或重复模组，请重新检测。')
    rules=load_rules(env)
    validate_order(ids,original_ids,rules,installed_context(env,{mod.item_id:mod for mod in mods},rules),game_version(env))
    document = ET.fromstring(baseline)
    core = next((node for node in document.iter() if node.tag.casefold() == 'corepackage'), None)
    if core is None:
        raise AssistantError('核心内容包无法识别，请先在游戏中核对')
    key = configured_key(core.get('path',''), env)
    if key is None:
        path=Path(core.get('path','').replace('\\','/'))
        path=path if path.is_absolute() else env.game/path
        if path.resolve() != (env.game/'Content/ContentPackages/Vanilla.xml').resolve():
            raise AssistantError('核心内容包无法识别，请先在游戏中核对')
    data = {'schema':SCHEMA,'appid':APP_ID,'name':'draft','order':[{'id':item} for item in ids],
            'core':{'id':key} if key else None}
    replacement = config_bytes(env, data, mods, baseline)
    return commit_config(env, replacement, baseline, process_guard)
