"""Explicit optional Lua diagnostic export and bounded import of game observations."""
import hashlib
import json
from pathlib import Path
import re
import uuid
import os
import xml.etree.ElementTree as ET

from .core import AssistantError, reject_link, within
from .profiles import game_version
from . import VERSION

SCHEMA='barodock-runtime-v1'
MAX_BYTES=2*1024*1024

LUA = r'''-- BaroDock optional read-only diagnostic. Autorun only; never ForcedAutorun.
local modPath = ...
local requested = __REQUESTED__
local sequence = 0
local function quoted(value)
    local text = tostring(value or "")
    return '"' .. text:gsub('[%z\1-\31\\"]', function(char)
        return string.format('\\u%04x', string.byte(char))
    end) .. '"'
end
local function num(value)
    local n = tonumber(value)
    if not n or n ~= n or n == math.huge or n == -math.huge then return 'null' end
    return tostring(n)
end
local function capture()
    local ok, err = pcall(function()
        sequence = sequence + 1
        local packages, items = {}, {}
        for _, package in pairs(Game.GetEnabledContentPackages()) do
            if #packages >= 1000 then error("package limit reached") end
            packages[#packages+1] = '{"name":' .. quoted(package.Name)
                .. ',"version":' .. quoted(package.ModVersion)
                .. ',"index":' .. num(package.Index)
                .. ',"manifest":' .. quoted(package.Path) .. '}'
        end
        for _, identifier in ipairs(requested) do
            local itemOk, itemText = pcall(function()
              local prefab = Game.GetItemPrefab(identifier)
            if prefab then
                return '{"requested":' .. quoted(identifier)
                    .. ',"identifier":' .. quoted(prefab.Identifier.Value)
                    .. ',"provider_manifest":' .. quoted(prefab.ContentPackage.Path)
                    .. ',"health":' .. num(prefab.Health)
                    .. ',"maxstacksize":' .. num(prefab.MaxStackSize) .. '}'
            else
                return '{"requested":' .. quoted(identifier) .. ',"missing":true}'
            end
            end)
            items[#items+1] = itemOk and itemText or ('{"requested":' .. quoted(identifier) .. ',"error":' .. quoted(itemText) .. '}')
        end
        local captured = os.time()
        local text = '{"schema":"barodock-runtime-v1","capture_id":'
            .. quoted(tostring(captured) .. '-' .. tostring(sequence))
            .. ',"captured_unix":' .. num(captured)
            .. ',"packages":[' .. table.concat(packages, ',') .. ']'
            .. ',"items":[' .. table.concat(items, ',') .. ']}'
        if #text > 2097152 then error("output size limit reached") end
        File.Write(modPath .. '/barodock-runtime-state.json', text)
        print('[BaroDock] Runtime capture attempted in the diagnostic mod folder. Check the output file in the assistant.')
    end)
    if not ok then print('[BaroDock] Runtime capture unavailable: ' .. tostring(err)) end
end
Hook.Add('roundStart', 'barodock.readonly.capture', capture)
'''


def lua_quote(value):
    # LuaCs/MoonSharp strings are .NET Unicode strings. Preserve Unicode source
    # text instead of spelling UTF-8 bytes as decimal escapes (mojibake there).
    return '"'+''.join(char if ord(char)>=32 and char not in ('"','\\') else '\\'+str(ord(char)).zfill(3) for char in value)+'"'


def create_diagnostic(env, identifiers):
    if not isinstance(identifiers,list) or len(identifiers)>100 or any(not isinstance(item,str) or not item or len(item)>200 or '\0' in item for item in identifiers):
        raise AssistantError('诊断标识列表无效')
    root=env.game/'LocalMods'
    if root.exists():reject_link(root)
    for parent in root.parents:
        if within(parent,env.game) and parent.exists():reject_link(parent)
    folder=root/('BaroDock-Diagnostics-'+uuid.uuid4().hex[:10])
    if folder.exists():raise AssistantError('诊断目录已存在，原文件保留')
    folder.mkdir(parents=True)
    manifest=ET.Element('contentpackage',{'name':'BaroDock Read-only Diagnostics','corepackage':'false',
                         'gameversion':game_version(env),'modversion':VERSION,'altnames':''})
    ET.ElementTree(manifest).write(folder/'filelist.xml',encoding='utf-8',xml_declaration=True)
    script_dir=folder/'Lua/Autorun';script_dir.mkdir(parents=True)
    script=LUA.replace('__REQUESTED__','{'+','.join(lua_quote(item) for item in dict.fromkeys(identifiers))+'}')
    (script_dir/'barodock_diagnostics.lua').write_text(script,encoding='utf-8')
    guide='Enable this optional local mod yourself, with an already working LuaCs client. It does not enable C# or change your current list.\nStart a separate test round. Output: barodock-runtime-state.json in this folder. Import it in BaroDock to compare actual loaded packages and selected Item fields.\nThe script only uses game APIs and writes this output. No network, process inspection, account data or ForcedAutorun. Runtime observations are not safety or universal compatibility certification.\nDisable/remove this local mod yourself when finished. Do not overwrite your original campaign save.\n'
    (folder/'README.txt').write_text(guide,encoding='utf-8')
    return folder


def read_runtime_capture(path):
    path=Path(path);reject_link(path)
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise AssistantError('游戏内诊断文件超过读取上限')
    try:value=json.loads(raw)
    except (ValueError,RecursionError) as error:raise AssistantError('游戏内诊断 JSON 无效') from error
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA:raise AssistantError('游戏内诊断格式无效')
    if not isinstance(value.get('capture_id'),str) or len(value['capture_id'])>100 or type(value.get('captured_unix')) not in (int,float):raise AssistantError('游戏内诊断时间无效')
    if not value['capture_id'] or not 0<=value['captured_unix']<=253402300799:raise AssistantError('游戏内诊断时间无效')
    for key,maximum in [('packages',1000),('items',100)]:
        if not isinstance(value.get(key),list) or len(value[key])>maximum:raise AssistantError('游戏内诊断数量无效')
    for row in value['packages']:
        if not isinstance(row,dict) or type(row.get('index')) is not int or not 0<=row['index']<=1000 or any(not isinstance(row.get(key),str) or len(row[key])>2000 for key in ('name','version','manifest')):raise AssistantError('游戏内诊断内容包无效')
    if len({row['index'] for row in value['packages']})!=len(value['packages']):raise AssistantError('游戏内诊断内容包索引重复')
    for row in value['items']:
        if not isinstance(row,dict) or not isinstance(row.get('requested'),str) or not row['requested'] or len(row['requested'])>200 or '\0' in row['requested']:raise AssistantError('游戏内诊断标识无效')
        if 'missing' in row and type(row['missing']) is not bool:raise AssistantError('游戏内诊断定义无效')
        if 'error' in row:
            if not isinstance(row['error'],str) or not row['error'] or len(row['error'])>16000 or 'missing' in row:raise AssistantError('游戏内诊断定义无效')
            continue
        if row.get('missing') is True:continue
        if any(not isinstance(row.get(key),str) or len(row[key])>2000 for key in ('identifier','provider_manifest')):raise AssistantError('游戏内诊断定义无效')
        for key in ('health','maxstacksize'):
            if row.get(key) is not None and (type(row[key]) not in (int,float) or not -1e9<=row[key]<=1e9):raise AssistantError('游戏内诊断字段数值无效')
    if len({row['requested'] for row in value['items']})!=len(value['items']):raise AssistantError('游戏内诊断标识无效')
    value['input_sha256']=hashlib.sha256(raw).hexdigest()
    return value


def compare_runtime(env,capture,model=None):
    """Map observations to known game inventory; never read an imported path."""
    from .profiles import capture_profile,installed_path
    from .core import inventory
    mods=inventory(env);known={mod.item_id:mod for mod in mods}
    paths={str((installed_path(env,mod)/'filelist.xml').resolve()).casefold():mod.item_id for mod in mods if installed_path(env,mod) is not None}
    paths[str((env.game/'Content/ContentPackages/Vanilla.xml').resolve()).casefold()]='vanilla'
    def identify(value):
        # Imported paths are labels for matching only. No imported location is opened.
        path=Path(value.replace('\\','/'))
        if not path.is_absolute():path=env.game/path
        return paths.get(os.path.normcase(os.path.normpath(str(path))))
    observed=[];unmapped=[]
    for row in sorted(capture['packages'],key=lambda row:row['index']):
        item=identify(row['manifest'])
        if item:observed.append(item)
        else:unmapped.append(row['name'])
    profile=capture_profile(env,mods=mods,include_receipts=False)
    configured=[profile['core']['id'] if profile.get('core') else 'vanilla',*[row['id'] for row in profile['order']]]
    items=[]
    for row in capture['items']:
        item=identify(row.get('provider_manifest','')) if not row.get('missing') else None
        result={'identifier':row['requested'],'observed_missing':row.get('missing') is True,'observed_provider':item,
                'observed_fields':{key:row.get(key) for key in ('health','maxstacksize')}}
        if row.get('error'):result['observation_error']=row['error']
        if row.get('identifier','').casefold()!=row['requested'].casefold() and not row.get('missing'):result['different_returned_identifier']=row.get('identifier')
        if model and row['requested'] in model:
            result['model_provider']=model[row['requested']].get('winner')
            if result['model_provider'] and model[row['requested']].get('status','selected')=='selected' and not row.get('error'):
                result['provider_matches']=item==result['model_provider'] and not result.get('different_returned_identifier') and not result['observed_missing']
                if not result['observed_missing']:
                    expected=model[row['requested']].get('expected_runtime_fields',{})
                    result['field_comparisons']=[{'field':key,'expected':value,'observed':row[key],'matches':value==row[key]}
                                                for key,value in expected.items() if key in ('health','maxstacksize') and row.get(key) is not None]
        items.append(result)
    return {'configured':configured,'observed':observed,'order_matches':configured==observed and not unmapped,
            'configured_but_not_observed':[item for item in configured if item not in observed],
            'observed_but_not_configured':[item for item in observed if item not in configured],
            'unmapped_packages':unmapped,'items':items,'capture_id':capture['capture_id'],
            'note':'这是用户选择导入的会话观察；未证明生成来源、历史文件或其他运行行为。'}
