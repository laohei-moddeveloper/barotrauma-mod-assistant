"""Independent mod/config snapshots with journalled multi-directory restore."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from .core import AssistantError, Cancelled, atomic_json, game_running, inventory, reject_link, within
from .profiles import capture_profile, game_version, installed_path
from .mod_toggle import BLOCK, CORE

def digest(path, check=lambda:None):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            check(); value.update(chunk)
    return value.hexdigest()

def safe_name(value):
    if not isinstance(value,str): raise AssistantError('快照包含无效路径')
    path = PurePosixPath(value)
    if not value or '\\' in value or ':' in value or path.is_absolute() or any(x in ('..','.','') for x in value.split('/')):
        raise AssistantError('快照包含无效路径')
    return path

def tree(folder, hashes=True, check=lambda:None):
    if not folder.exists(): return None
    reject_link(folder)
    rows = {}
    for path in sorted(folder.rglob('*')):
        check(); reject_link(path)
        if not within(path,folder): raise AssistantError('快照文件超出模组目录')
        if path.is_file():
            stat = path.stat()
            rows[path.relative_to(folder).as_posix()] = digest(path,check) if hashes else [stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
    return rows

class SnapshotStore:
    def __init__(self, env, emit=lambda message:None, process_guard=game_running, cancel=None, fault=lambda phase:None):
        self.env, self.emit, self.guard = env, emit, process_guard
        self.cancel = cancel or threading.Event(); self.fault = fault
        self.last_guard=0
        self.root = env.work / 'snapshots'

    def check(self):
        if self.cancel.is_set(): raise Cancelled('快照任务已停止')
        if self.guard(): raise AssistantError('请先关闭游戏和服务器，再保存或恢复快照')
        self.last_guard=time.monotonic()

    def check_io(self):
        if self.cancel.is_set(): raise Cancelled('快照任务已停止')
        if time.monotonic()-self.last_guard>=0.25: self.check()

    def copy_file(self, source, destination):
        reject_link(Path(source))
        with open(source,'rb') as incoming,open(destination,'xb') as outgoing:
            for chunk in iter(lambda:incoming.read(1024*1024),b''):
                self.check_io(); outgoing.write(chunk)
        shutil.copystat(source,destination)
        return destination

    def descriptor(self, mod):
        if mod.item_id.isdecimal(): return {'kind':'workshop','id':mod.item_id,'name':mod.name}
        for kind,root in [('game_local',self.env.game/'LocalMods'),('player_local',self.env.player/'LocalMods')]:
            if mod.source and within(mod.source,root):
                folder = mod.source.relative_to(root).as_posix(); safe_name(folder)
                return {'kind':kind,'folder':folder,'id':mod.item_id,'name':mod.name}
        raise AssistantError('本地模组路径无法保存到快照')

    def target(self, record):
        if record.get('kind') == 'workshop':
            item = record.get('id','')
            if not re.fullmatch(r'[1-9][0-9]{0,19}',item) or int(item)>=2**64: raise AssistantError('快照模组编号无效')
            root = self.env.installed; target = root / item
        else:
            roots = {'game_local':self.env.game/'LocalMods','player_local':self.env.player/'LocalMods'}
            root = roots.get(record.get('kind'))
            if root is None: raise AssistantError('快照模组类型无效')
            target = root / str(safe_name(record.get('folder','')))
        if not within(target,root): raise AssistantError('恢复目标超出模组目录')
        for parent in [target] + list(target.parents):
            if within(parent,root) and parent.exists(): reject_link(parent)
        return target

    def list(self):
        values = []
        for path in self.root.glob('*/snapshot.json'):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data,dict) and data.get('state') == 'ready' and data.get('id')==path.parent.name and isinstance(data.get('records'),list): values.append(data)
            except (OSError,ValueError): continue
        return sorted(values,key=lambda x:x['id'],reverse=True)

    def capture(self, name='更新前', mods=None, targets=(), reuse=True):
        self.check(); self.recover()
        if not game_version(self.env): raise AssistantError('无法确认游戏版本，未保存快照')
        original = (self.env.game/'config_player.xml').read_bytes()
        mods = mods if mods is not None else inventory(self.env)
        profile = capture_profile(self.env,name,mods)
        if (self.env.game/'config_player.xml').read_bytes()!=original: raise AssistantError('配置在读取时变化，请重试保存快照')
        selected = {m.item_id:m for m in mods if m.enabled or m.item_id in targets}
        from .core import Mod
        for item in targets:
            if item not in selected and item.isdecimal(): selected[item] = Mod(item,item,self.env.installed/item)
        records = [self.descriptor(selected[item]) for item in sorted(selected)]
        signatures = [(r,tree(self.target(r),False,self.check_io)) for r in records]
        token = hashlib.sha256(json.dumps([profile,signatures],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if reuse:
            for old in self.list()[:1]:
                if old.get('signature') == token:
                    self.emit('沿用未变化的更新前快照：'+old['id']); return old
        total = sum(sum(v[0] for v in rows.values()) for _,rows in signatures if rows)
        self.root.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(self.root).free < total + 64*1024*1024:
            raise AssistantError('磁盘空间不足以独立保存快照，请释放空间后再更新')
        key = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        folder = self.root / key; folder.mkdir()
        (folder/'config.xml').write_bytes(original)
        catalog = []
        for index,record in enumerate(records):
            self.check(); source = self.target(record)
            self.emit('保存快照：'+record.get('name',record['id']))
            before = tree(source,True,self.check_io)
            saved = folder/'payload'/str(index)
            if before is not None:
                saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copytree(source,saved,copy_function=self.copy_file)
                if tree(saved,True,self.check_io)!=before or tree(source,False,self.check_io)!=signatures[index][1]:
                    raise AssistantError('模组在保存快照时变化，未生成可恢复快照')
            catalog.append({**record,'payload':str(index),'files':before})
        if (self.env.game/'config_player.xml').read_bytes()!=original: raise AssistantError('配置在保存快照时变化，请重试')
        data = {'schema':1,'state':'ready','id':key,'name':str(name)[:100], 'game_version':game_version(self.env),
                'profile':profile,'records':catalog,'config_sha256':digest(folder/'config.xml'),
                'signature':token,'bytes':total}
        atomic_json(folder/'snapshot.json',data)
        return data

    def config_replacement(self, original, saved, records):
        document = ET.fromstring(saved)
        allowed = {str((self.target(record)/'filelist.xml').resolve()).casefold() for record in records}
        vanilla = str((self.env.game/'Content/ContentPackages/Vanilla.xml').resolve()).casefold()
        for node in document.iter():
            if node.tag.casefold() in ('package','corepackage'):
                value = Path(node.get('path','').replace('\\','/'))
                if not value.is_absolute(): value = self.env.game/value
                if str(value.resolve()).casefold() not in allowed|{vanilla}: raise AssistantError('快照配置引用了未保存的模组路径')
        text = original.decode('utf-8-sig'); old = saved.decode('utf-8-sig')
        changes = []
        for pattern in (BLOCK,CORE):
            a,b = pattern.search(text),pattern.search(old)
            if a is None or b is None: raise AssistantError('快照内容包配置格式不受支持')
            changes.append((a.start(),a.end(),b.group()))
        for start,end,value in sorted(changes,reverse=True): text=text[:start]+value+text[end:]
        return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'')+text.encode('utf-8')

    def restore(self, key):
        self.check(); self.recover()
        if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9a-f]{8}',key): raise AssistantError('快照编号无效')
        folder=self.root/key; reject_link(folder)
        data=json.loads((folder/'snapshot.json').read_text(encoding='utf-8'))
        if data.get('schema')!=1 or data.get('state')!='ready' or not game_version(self.env) or data.get('game_version')!=game_version(self.env):
            raise AssistantError('快照未完成或游戏版本已变化，未恢复')
        if digest(folder/'config.xml')!=data['config_sha256']: raise AssistantError('快照配置校验失败')
        records=data['records']; targets=set()
        if not isinstance(records,list) or len(records)>1001: raise AssistantError('快照项目数量无效')
        needed=sum((folder/'payload'/str(safe_name(record['payload']))/str(safe_name(name))).stat().st_size
                   for record in records if isinstance(record.get('files'),dict) for name in record['files'])
        if shutil.disk_usage(self.root).free < needed+64*1024*1024: raise AssistantError('空间不足以暂存完整恢复文件，未恢复')
        transaction=self.root/'transactions'/uuid.uuid4().hex; transaction.mkdir(parents=True)
        entries=[]
        for index,record in enumerate(records):
            self.check(); target=self.target(record)
            if str(target).casefold() in targets: raise AssistantError('快照含重复恢复目标')
            targets.add(str(target).casefold())
            saved=folder/'payload'/str(safe_name(record['payload']))
            if not within(saved,folder/'payload'): raise AssistantError('快照文件路径无效')
            if record['files'] is not None:
                for name in record['files']: safe_name(name)
                if tree(saved,True,self.check_io)!=record['files']: raise AssistantError('快照模组文件校验失败')
                stage=transaction/'stage'/str(index); stage.parent.mkdir(parents=True,exist_ok=True)
                shutil.copytree(saved,stage,copy_function=self.copy_file)
                if tree(stage,True,self.check_io)!=record['files']: raise AssistantError('恢复暂存文件校验失败')
            entries.append({**record,'index':index,'before':tree(target,True,self.check_io)})
        config=self.env.game/'config_player.xml'; reject_link(config)
        original=config.read_bytes(); replacement=self.config_replacement(original,(folder/'config.xml').read_bytes(),records)
        journal={'state':'pending','entries':entries,'written':[],
                 'config_before':base64.b64encode(original).decode(),'config_after':base64.b64encode(replacement).decode()}
        path=transaction/'transaction.json'; atomic_json(path,journal)
        try:
            for record in entries:
                self.check(); target=self.target(record); index=str(record['index'])
                if tree(target,True,self.check)!=record['before']: raise AssistantError('恢复目标刚被其他程序修改')
                journal['written'].append(record['index']); atomic_json(path,journal)
                if target.exists():
                    rescue=transaction/'before'/index; rescue.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(target,rescue)
                if record['files'] is not None:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(transaction/'stage'/index,target)
                self.fault('replaced')
            self.check()
            if config.read_bytes()!=original: raise AssistantError('游戏配置已被其他程序修改，未切换')
            temporary=config.with_name('config_player.xml.snapshot.tmp')
            try:
                with temporary.open('wb') as stream:
                    stream.write(replacement); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary,config)
            finally:
                if temporary.exists(): temporary.unlink()
            self.fault('config_replaced')
            for record in entries:
                if record['kind']=='workshop':
                    receipt=self.env.work/'receipts'/(record['id']+'.json')
                    if receipt.exists(): receipt.unlink()
            journal['state']='complete'; atomic_json(path,journal)
            return {'restored':len(entries),'snapshot':key,'backup':str(transaction/'before')}
        except Exception:
            self.rollback(transaction,journal)
            journal['state']='rolled_back'; atomic_json(path,journal)
            raise

    def rollback(self, transaction, journal):
        if not within(transaction,self.root/'transactions'): raise AssistantError('恢复事务路径无效')
        reject_link(transaction)
        entries_all=journal.get('entries'); written=journal.get('written')
        if not isinstance(entries_all,list) or not isinstance(written,list) or len(entries_all)>1001:
            raise AssistantError('恢复事务记录无效')
        indices=[r.get('index') if isinstance(r,dict) else None for r in entries_all]
        if any(type(i) is not int or i<0 or i>=len(entries_all) for i in indices) or len(set(indices))!=len(indices) or any(type(i) is not int or i not in indices for i in written):
            raise AssistantError('恢复事务索引无效')
        config=self.env.game/'config_player.xml'
        before=base64.b64decode(journal['config_before']); after=base64.b64decode(journal['config_after'])
        if config.read_bytes() not in (before,after): raise AssistantError('配置后来被修改，保留快照和恢复备份，请手动检查')
        entries=[r for r in journal['entries'] if r['index'] in journal['written']]
        for record in entries:
            target=self.target(record); rescue=transaction/'before'/str(record['index'])
            if rescue.exists() and tree(rescue)!=record['before']: raise AssistantError('恢复前备份校验失败')
            value=tree(target)
            allowed=[record['files'],None] if rescue.exists() or record['before'] is None else [record['before']]
            if value not in allowed: raise AssistantError('模组后来被修改，保留恢复备份，请手动检查')
        for record in reversed(entries):
            target=self.target(record); rescue=transaction/'before'/str(record['index'])
            if rescue.exists() or record['before'] is None:
                if target.exists():
                    discard=transaction/'discard'/str(record['index']); discard.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(target,discard)
                if rescue.exists(): os.replace(rescue,target)
        if config.read_bytes()!=before:
            temporary=config.with_name('config_player.xml.rollback.tmp'); temporary.write_bytes(before); os.replace(temporary,config)

    def recover(self):
        for path in (self.root/'transactions').glob('*/transaction.json'):
            journal=json.loads(path.read_text(encoding='utf-8'))
            if journal.get('state')=='pending':
                self.check(); self.rollback(path.parent,journal)
                journal['state']='rolled_back'; atomic_json(path,journal)
                self.emit('已回滚上次未完成的整套快照恢复')
