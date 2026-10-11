"""Use the existing log entry point for local evidence, repair drafts and rechecks."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import uuid
import json
import subprocess

from .core import AssistantError, atomic_json, Cancelled
from .diagnostics import diagnose, redact
from .investigation import capture_scene, compare_logs, compare_scenes, read_scene, repair_candidates, save_scene
from .native_profiles import write_native
from .profiles import capture_profile


def format_log(report, tr=lambda value:value):
    lines=[report['file'],tr(report['note'])]
    if report.get('changed_during_read'):lines.append(tr('日志在读取期间变化，不能用于确认修复。'))
    if report.get('findings_truncated'):lines.append(tr('错误种类超过显示上限，不能据此确认其他错误已消失。'))
    for finding in report['findings']:
        lines.extend(['['+tr(finding['category'])+'] '+tr('首次行：')+str(finding['line_in_tail'])+' · '+tr('出现次数：')+str(finding.get('occurrences',1)),
                      finding['text'],tr(finding['evidence'])])
        for row in finding['locations']:
            lines.append(tr(row['kind'])+'：'+row['mod_name']+' ['+row['mod_id']+'] '+row['file'])
        lines.extend(tr(step) for step in finding['steps']);lines.append('')
    if not report['findings']:lines.append(tr('读取范围内没有已识别的错误；需要完成相同操作复现。'))
    return '\n'.join(lines)


def format_scene(scene,tr=lambda value:value):
    lines=[scene['name'],scene['created_at'],tr('复现步骤：')+scene['steps'],tr('游戏版本：')+scene['game_version'],
           tr('核心：')+scene['core'],tr('已记录输入完整：')+str(scene['complete'])]
    for index,item in enumerate(scene['order'],1):
        row=scene['mods'][item]
        lines.append(f"{index}. {row['name']} [{item}] · {row['version']}")
        lines.extend(tr(error) for error in row['evidence'].get('errors',[]))
    lines.extend(tr(note) for note in scene['notes'])
    return '\n'.join(lines)


def format_changes(report,tr=lambda value:value):
    lines=[tr('已记录输入一致' if report['same_recorded_inputs'] else '已记录输入存在差异或资料不完整')]
    for row in report['differences']:
        lines.append(tr(row['kind'])+'：'+row.get('name','')+' '+row.get('file','')+' '+tr(row.get('change','')))
    return '\n'.join(lines)


class InvestigationDialog:
    def __init__(self,app,path,report):
        self.app=app;self.path=Path(path);self.report=report;self.before=None;self.latest=None;self.changes=None;self.recheck=None;self.candidates=[]
        self.window=tk.Toplevel(app.root,bg='#0b1422');self.window.title('日志与排查记录');self.window.geometry('1000x750');self.window.minsize(850,640);self.window.transient(app.root)
        heading=app.label(self.window,'先记录文件和复现步骤，再生成修复草稿。测试后读取新日志核对。',wraplength=800)
        heading.pack(fill='x',padx=16,pady=12)
        self.window.bind('<Configure>',lambda event:heading.configure(wraplength=max(200,event.width-32)) if event.widget is self.window else None,add='+')
        book=ttk.Notebook(self.window);book.pack(fill='both',expand=True,padx=16,pady=6)
        self.views={}
        for key,title in [('log','日志证据'),('scene','文件与清单'),('repair','修复与复查')]:
            page=tk.Frame(book,bg='#142237');book.add(page,text=title)
            bar=ttk.Scrollbar(page);bar.pack(side='right',fill='y')
            text=tk.Text(page,wrap='word',height=10,width=1,state='disabled',yscrollcommand=bar.set,bg='#142237',fg='#e8f0fa',insertbackground='#e8f0fa');text.pack(fill='both',expand=True);bar.configure(command=text.yview);self.views[key]=text
        selection=tk.Frame(self.window,bg='#0b1422');selection.pack(fill='x',padx=16,pady=5)
        app.label(selection,'修复候选：').pack(side='left')
        self.picker=ttk.Combobox(selection,state='readonly',width=1);self.picker.pack(side='left',fill='x',expand=True);self.picker.bind('<<ComboboxSelected>>',lambda event:self.render())
        more=tk.Menubutton(selection,text='更多操作',relief='flat');more.pack(side='right',padx=8)
        menu=tk.Menu(more,tearoff=False)
        menu.add_command(label='导出排查记录',command=self.export_record)
        menu.add_command(label='打开记录位置',command=self.open_records)
        more.configure(menu=menu)
        controls=tk.Frame(self.window,bg='#0b1422');controls.pack(fill='x',padx=16,pady=(5,14))
        self.controls=[]
        for index,(title,command) in enumerate([('保存测试前记录',self.capture_before),('读取排查记录',self.load),('比较当前文件',self.compare_current),
                                                ('生成修复候选',self.prepare_repair),('保存选中修复草稿',self.save_repair),('测试后读取新日志',self.recheck_log)]):
            button=app.button(controls,title,command,busy=False);button._language_wraplength=240;button.grid(row=index//3,column=index%3,sticky='ew',padx=4,pady=4);self.controls.append(button)
        for column in range(3):controls.columnconfigure(column,weight=1)
        self.window._language_refresh=self.render;self.render();app.skin(self.window)

    def busy(self):return self.app.task_active or self.app.worker and self.app.worker.is_alive()

    def capture(self,**kwargs):
        return capture_scene(self.app.env,cancel=self.app.cancel,emit=lambda message:self.app.events.put({'kind':'log','message':message}),**kwargs)

    def work(self,operation,finish):
        if self.busy():return
        from .core import game_running
        try:
            if game_running(self.app.env):raise AssistantError('请先关闭选定游戏，再记录或深入分析文件。')
        except Exception as error:
            self.app.report_error(error,'排查环境检查');return
        for button in self.controls:button.configure(state='disabled')
        def run():
            result=error=None
            try:result=operation()
            except Exception as caught:error=caught
            def show():
                if not self.window.winfo_exists():return
                for button in self.controls:button.configure(state='normal')
                if error:self.app.report_error(error,'排查与复查');return
                finish(result);self.render()
            self.app.events.put({'kind':'ui_callback','callback':show})
        self.app.work(run)

    def put(self,key,text):
        widget=self.views[key];widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',text);widget.configure(state='disabled')

    def render(self):
        if not self.window.winfo_exists():return
        tr=self.app.tr
        self.put('log',format_log(self.report,tr))
        scene=format_scene(self.before,tr) if self.before else tr('尚未保存测试前记录；旧日志不能重建未记录的历史文件。')
        if self.changes:scene+='\n\n'+format_changes(self.changes,tr)
        self.put('scene',scene)
        lines=[]
        selected=self.picker.current()
        if 0<=selected<len(self.candidates):
            candidate=self.candidates[selected];lines.extend([tr(candidate['note']),tr('将从草稿移除：')+'、'.join(candidate['removed']),tr('标识符：')+candidate['identifier']])
            if candidate.get('unchecked_dependencies'):lines.append(tr('以下项目的依赖资料不完整，应用前需另行核对：')+'、'.join(candidate['unchecked_dependencies']))
        if self.recheck:
            lines.append(tr('新日志可复查' if self.recheck['fresh_log'] else '日志未更新或读取不稳定，无法复查'))
            if not self.recheck['complete_comparison']:lines.append(tr('读取范围不完整，不能确认错误消失。'))
            for label,key in [('仍然出现：','still_present'),('本次未复现：','not_reproduced'),('新增错误：','new_errors')]:
                for row in self.recheck[key]:lines.append(tr(label)+row['text'].splitlines()[0])
            lines.append(tr('本次未复现只描述本次操作，不代表所有功能已修复。'))
        if not lines:lines.append(tr('修复草稿保存为游戏原生清单，需要另行审核与应用。'))
        self.put('repair','\n'.join(lines))

    def capture_before(self):
        if self.busy():return
        from tkinter import simpledialog
        from .i18n import Dialogs
        prompts=Dialogs(self.app.locale,simpledialog)
        steps=prompts.askstring('保存排查记录','请输入要重复执行的操作步骤：',parent=self.window)
        if not steps:return
        def capture():
            scene=self.capture(steps=steps,log=self.report)
            save_scene(self.app.env,scene);return scene
        def done(scene):self.before=scene;self.latest=scene;self.changes=None;self.recheck=None;self.candidates=[];self.picker.configure(values=[])
        self.work(capture,done)

    def load(self):
        if self.busy():return
        path=self.app.files.askopenfilename(title='读取排查记录',initialdir=str(self.app.env.work/'investigations'),filetypes=[('JSON','*.json')],parent=self.window)
        if not path:return
        def done(scene):self.before=scene;self.latest=None;self.changes=None;self.recheck=None;self.candidates=[];self.picker.configure(values=[])
        self.work(lambda:read_scene(path),done)

    def compare_current(self):
        if self.before is None:return
        before=self.before
        def compare():
            current=self.capture(steps=before['steps'],phase='after')
            return current,compare_scenes(before,current)
        def done(value):self.latest,self.changes=value
        self.work(compare,done)

    def prepare_repair(self):
        def prepare():
            source=self.capture()
            from .core import inventory
            mods=inventory(self.app.env)
            from .analysis_cache import inspect_cached
            features,_=inspect_cached(self.app.env,mods,cancel=self.app.cancel)
            fresh=diagnose(self.path,mods,self.app.env,features,self.app.cancel)
            if fresh['changed_during_read']:raise AssistantError('日志在读取期间变化，不能用于确认修复。')
            current=self.capture()
            if not compare_scenes(source,current)['same_recorded_inputs']:raise AssistantError('配置或文件已变化，请重新生成修复候选')
            def check():
                if self.app.cancel.is_set():raise Cancelled('排查已取消')
            return fresh,repair_candidates(fresh,source['profile'],features,check),source
        def done(value):
            self.report,self.candidates,self.repair_source=value
            self.picker.configure(values=[self.app.tr('排查停用：')+row['profile']['name'] for row in self.candidates])
            self.picker.set('')
            if not self.candidates:self.app.dialogs.showinfo('修复候选','没有可定位到当前文件的重复普通定义，未生成停用草稿。',parent=self.window)
        self.work(prepare,done)

    def save_repair(self):
        index=self.picker.current()
        if self.busy() or not 0<=index<len(self.candidates):return
        candidate=self.candidates[index]
        def save():
            current=self.capture()
            draft=candidate['profile']
            if not compare_scenes(self.repair_source,current)['same_recorded_inputs']:raise AssistantError('配置或文件已变化，请重新生成修复候选')
            path=self.app.env.game/'ModLists'/('BaroDock-Repair-'+uuid.uuid4().hex[:12]+'.xml')
            write_native(path,draft);return path
        self.work(save,lambda path:self.app.dialogs.showinfo('修复草稿已保存',self.app.tr('请在配置窗口审核与应用：')+str(path),parent=self.window))

    def recheck_log(self):
        if self.busy() or self.before is None:return
        if not self.app.dialogs.askyesno('复查条件','是否已按记录步骤完成新的测试会话？请使用独立测试会话，不覆盖原战役存档。',parent=self.window):return
        path=self.app.files.askopenfilename(title='选择测试后新日志',filetypes=[('日志','*.log *.txt')],parent=self.window)
        if not path:return
        before=self.before;old=before.get('log') or self.report
        def recheck():
            mods=[entry['mod'] for entry in self.app.mods.values()]
            new=diagnose(path,mods,self.app.env,self.app.features,self.app.cancel,baseline=old)
            scene=self.capture(steps=before['steps'],phase='after',log=new)
            result=compare_logs(old,new)
            from datetime import datetime
            if datetime.fromisoformat(new['modified_utc'])<datetime.fromisoformat(before['created_at']):
                result.update(fresh_log=False,complete_comparison=False,not_reproduced=[],new_errors=[])
            if result['fresh_log']:
                scene['recheck']={key:[row['signature'] for row in value] if isinstance(value,list) else value for key,value in result.items()}
                save_scene(self.app.env,scene)
            return scene,compare_scenes(before,scene),result,new
        def done(value):self.latest,self.changes,self.recheck,self.report=value
        self.work(recheck,done)

    def export_record(self):
        if self.busy() or self.before is None:return
        path=self.app.files.asksaveasfilename(title='导出排查记录',defaultextension='.json',initialfile='BaroDock-Investigation.json',parent=self.window)
        if not path:return
        # Only known log strings were already redacted. Free-form steps remain
        # user text; do not promise a general sensitive-data detector.
        atomic_json(Path(path),self.latest or self.before)

    def open_records(self):
        folder=self.app.env.work/'investigations'
        if not folder.is_dir():
            self.app.dialogs.showinfo('排查记录','请先保存一份排查记录。',parent=self.window);return
        from .core import reject_link
        reject_link(folder)
        subprocess.Popen(['explorer.exe',str(folder)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
