"""A focused, read-only comparison, without a new mod authoring system."""
import tkinter as tk
from tkinter import ttk
from .core import Cancelled,AssistantError
from .mod_analysis import pair_detail
from .mod_order import read_order
from .profiles import installed_path
from .xml_compare import compare_definition
from .xml_semantics import compare_semantics,format_semantics

class XMLCompareDialog:
    def __init__(self,app,item):
        self.app=app; self.item=item; self.left=app.features[item]
        self.others=[other for other,feature in app.features.items() if other!=item and feature.definitions & self.left.definitions]
        self.window=tk.Toplevel(app.root); self.window.title('XML 覆盖对照'); self.window.geometry('1000x740')
        self.window.minsize(850,600); self.window.transient(app.root); self.window.configure(bg='#0b1422')
        heading=app.label(self.window,'查看具体定义差异，帮助排查覆盖或制作兼容补丁。这里只读文件，不修改模组。',wraplength=800)
        heading.pack(fill='x',padx=16,pady=12)
        row=tk.Frame(self.window,bg='#0b1422'); row.pack(fill='x',padx=16)
        row.columnconfigure(0,weight=3);row.columnconfigure(1,weight=2)
        self.other=ttk.Combobox(row,state='readonly',values=[app.features[x].name+' ['+x+']' for x in self.others],width=1)
        self.other.grid(row=0,column=0,sticky='ew'); self.other.bind('<<ComboboxSelected>>',lambda event:self.select_other())
        self.key=ttk.Combobox(row,state='readonly',width=1); self.key.grid(row=0,column=1,sticky='ew',padx=8)
        self.key.bind('<<ComboboxSelected>>',lambda event:self.clear_result())
        self.compare_button=app.button(row,'比较定义',self.compare,busy=True); self.compare_button.grid(row=0,column=2)
        more=tk.Menubutton(row,text='更多分析',relief='flat');more.grid(row=0,column=3,padx=6)
        menu=tk.Menu(more,tearoff=False)
        menu.add_command(label='生成可选游戏内诊断模块',command=self.create_diagnostic)
        menu.add_command(label='导入游戏内诊断记录',command=self.import_runtime)
        menu.add_command(label='导出所选字段兼容草稿',command=self.patch_draft)
        more.configure(menu=menu)
        self.note=app.locale.variable(app.root,value='选择同标识定义，查看两边 XML 和文本差异。')
        note_label=app.label(self.window,textvariable=self.note,wraplength=800,justify='left');note_label.pack(fill='x',padx=16,pady=8)
        def resize(event):
            if event.widget is self.window:
                width=max(200,event.width-32);heading.configure(wraplength=width);note_label.configure(wraplength=width)
        self.window.bind('<Configure>',resize,add='+')
        book=ttk.Notebook(self.window); book.pack(fill='both',expand=True,padx=16,pady=(0,16))
        sides=tk.Frame(book,bg='#142237'); book.add(sides,text='定义对照')
        panels=tk.PanedWindow(sides,orient='horizontal',sashwidth=8,bg='#142237',relief='flat'); panels.pack(fill='both',expand=True)
        self.a=self.text(panels); self.b=self.text(panels)
        self.a._definition_header.configure(text=self.left.name+' ['+self.item+']')
        panels.bind('<Configure>',lambda event:panels.sash_place(0,event.width//2,0))
        diff=tk.Frame(book,bg='#142237'); book.add(diff,text='文本差异'); self.diff=self.text(diff,paned=False)
        semantic=tk.Frame(book,bg='#142237'); book.add(semantic,text='字段变化与定义来源'); self.semantic=self.text(semantic,paned=False)
        self.semantic_result=None; self.window._language_refresh=self.render_semantic
        app.skin(self.window)
        if self.others: self.other.current(0); self.select_other()
        else: self.note.set('当前模组没有已定位的共享 XML 定义。')

    def text(self,parent,paned=True):
        frame=tk.Frame(parent,bg='#142237')
        if paned: parent.add(frame,minsize=250,stretch='always')
        else: frame.pack(fill='both',expand=True)
        heading=self.app.label(frame,'',bg='#142237',wraplength=450,anchor='w',justify='left')
        if paned: heading.pack(fill='x',padx=8,pady=5)
        bar=ttk.Scrollbar(frame); bar.pack(side='right',fill='y')
        text=tk.Text(frame,wrap='none',font=('Consolas',10),yscrollcommand=bar.set,state='disabled',bg='#142237',fg='#e8f0fa',width=35,
                     insertbackground='#e8f0fa',selectbackground='#294866',selectforeground='#e8f0fa')
        text.pack(fill='both',expand=True); bar.configure(command=text.yview)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=text.xview); horizontal.pack(fill='x')
        text.configure(xscrollcommand=horizontal.set); text._definition_header=heading; return text

    def select_other(self):
        if self.other.current()<0: return
        right=self.app.features[self.others[self.other.current()]]
        self.b._definition_header.configure(text=right.name+' ['+right.item_id+']')
        self.keys=sorted(self.left.definitions & right.definitions)
        self.key.configure(values=[' / '.join(key) for key in self.keys])
        if self.keys: self.key.current(0)
        self.clear_result()

    def clear_result(self):
        self.semantic_result=None
        for widget in (self.a,self.b,self.diff,self.semantic):
            widget.configure(state='normal'); widget.delete('1.0','end'); widget.configure(state='disabled')
        self.note.set('选择同标识定义，查看两边 XML 和文本差异。')

    def compare(self):
        if self.app.task_active or self.app.worker and self.app.worker.is_alive(): return
        if self.key.current()<0 or self.other.current()<0: return
        other=self.others[self.other.current()]; right=self.app.features[other]; key=self.keys[self.key.current()]
        left_folder=installed_path(self.app.env,self.app.mods[self.item]['mod']); right_folder=installed_path(self.app.env,self.app.mods[other]['mod'])
        self.note.set('正在读取所选 XML 定义…')
        self.other.configure(state='disabled'); self.key.configure(state='disabled')
        def check():
            if self.app.cancel.is_set(): raise Cancelled('XML 对照已停止')
        def show(result,detail,semantic,error):
            if not self.window.winfo_exists(): return
            self.other.configure(state='readonly'); self.key.configure(state='readonly')
            if error:
                self.note.set('读取未完成，请查看错误详情后重试。')
                self.app.report_error(error,'对照文件或配置'); return
            for widget,value in ((self.a,result['left']),(self.b,result['right']),(self.diff,result['diff'] or self.app.tr('两边显示的 XML 文本相同；运行结果仍需核实。'))):
                widget.configure(state='normal'); widget.delete('1.0','end'); widget.insert('end',value); widget.configure(state='disabled')
            self.note.set(semantic['loading']['message'])
            self.semantic_result=semantic; self.render_semantic()
        def work():
            result=detail=semantic=error=None
            try:
                result=compare_definition(left_folder,self.left,right_folder,right,key,check)
                try: order=read_order(self.app.env)
                except (OSError,AssistantError): order=[]
                detail=pair_detail(self.left,right,order)
                providers=[(item,installed_path(self.app.env,self.app.mods[item]['mod']),feature) for item,feature in self.app.features.items() if item in self.app.mods]
                semantic=compare_semantics(self.app.env,left_folder,self.left,right_folder,right,key,providers,order,check)
            except Exception as caught: error=caught
            finally: self.app.events.put({'kind':'ui_callback','callback':lambda:show(result,detail,semantic,error)})
        self.app.work(work)

    def render_semantic(self):
        if self.semantic_result is None or not self.window.winfo_exists(): return
        self.semantic.configure(state='normal'); self.semantic.delete('1.0','end')
        self.semantic.insert('end',format_semantics(self.semantic_result,self.app.tr)); self.semantic.configure(state='disabled')

    def create_diagnostic(self):
        if self.app.task_active or self.app.worker and self.app.worker.is_alive() or self.key.current()<0:return
        identifier=self.keys[self.key.current()][2]
        if self.keys[self.key.current()][0]!='item':return
        if not self.app.dialogs.askyesno('可选游戏内诊断模块','将在 LocalMods 创建一个独立的 Lua 诊断模块。需要你自行启用并在独立测试会话运行；助手不会安装 LuaCs、开启 C#、启动游戏或改变清单。继续创建？',parent=self.window):return
        def work():
            from .runtime_capture import create_diagnostic
            from .core import game_running
            if game_running(self.app.env):raise AssistantError('请先关闭选定游戏，再记录或深入分析文件。')
            folder=create_diagnostic(self.app.env,[identifier])
            self.app.events.put({'kind':'text_report','title':'诊断模块已创建','text':self.app.tr('请自行启用该本地模块，开始独立测试回合。输出文件位于：')+str(folder/'barodock-runtime-state.json')})
        self.app.work(work)

    def patch_draft(self):
        if self.app.task_active or self.app.worker and self.app.worker.is_alive() or not self.semantic_result:return
        from .patch_draft import editable_changes,export_draft
        choices=editable_changes(self.semantic_result)
        if not choices:
            self.app.dialogs.showinfo('兼容草稿','没有可直接选择的明确属性差异，请先完成定义对照。',parent=self.window);return
        window=tk.Toplevel(self.window);window.title('兼容草稿');window.geometry('760x460');window.transient(self.window)
        self.app.label(window,'选择希望保留的来源值。仅导出草稿，不安装启用；需要审核并在独立测试会话验证。',wraplength=700).pack(fill='x',padx=12,pady=12)
        frame=tk.Frame(window);frame.pack(fill='both',expand=True,padx=12)
        picker=tk.Listbox(frame,selectmode='extended',exportselection=False)
        scroll=ttk.Scrollbar(frame,command=picker.yview);scroll.pack(side='right',fill='y');picker.configure(yscrollcommand=scroll.set);picker.pack(fill='both',expand=True)
        for row in choices:picker.insert('end',row['name']+' · '+row['path']+' = '+row['declared'])
        report=self.semantic_result
        def export():
            selected=list(picker.curselection())
            if not selected:return
            def run():
                folder=export_draft(self.app.env,report,selected)
                self.app.events.put({'kind':'text_report','title':'兼容草稿已导出','text':self.app.tr('请先审核 README、资源路径与依赖，再自行安装并测试：')+str(folder)})
            window.destroy();self.app.work(run)
        self.app.button(window,'导出所选字段',export,busy=False).pack(pady=12);self.app.skin(window)

    def import_runtime(self):
        if self.app.task_active or self.app.worker and self.app.worker.is_alive():return
        path=self.app.files.askopenfilename(title='导入游戏内诊断记录',filetypes=[('JSON','*.json')],parent=self.window)
        if not path:return
        model={}
        if self.semantic_result and self.key.current()>=0:model[self.keys[self.key.current()][2]]={**self.semantic_result['loading'],'expected_runtime_fields':(self.semantic_result.get('item_result') or {}).get('expected_runtime_fields',{})}
        def work():
            from .runtime_capture import read_runtime_capture,compare_runtime
            result=compare_runtime(self.app.env,read_runtime_capture(path),model)
            lines=[self.app.tr(result['note']),self.app.tr('清单与游戏观察一致' if result['order_matches'] else '清单与游戏观察存在差异')]
            for item in result['configured_but_not_observed']:lines.append(self.app.tr('配置启用但观察中没有：')+item)
            for item in result['observed_but_not_configured']:lines.append(self.app.tr('观察中存在但当前配置没有：')+item)
            for item in result['unmapped_packages']:lines.append(self.app.tr('观察项目未匹配到本机包：')+item)
            for row in result['items']:
                if row.get('observation_error'):
                    lines.append(row['identifier']+' · '+self.app.tr('游戏内观察读取失败：')+row['observation_error']);continue
                if row.get('different_returned_identifier'):lines.append(self.app.tr('请求标识与游戏返回标识不同：')+row['identifier']+' → '+row['different_returned_identifier'])
                lines.append(row['identifier']+' · '+self.app.tr('游戏观察中缺失' if row['observed_missing'] else '游戏观察中的提供者：')+(row['observed_provider'] or ''))
                if 'provider_matches' in row:lines.append(self.app.tr('模型提供者与观察一致' if row['provider_matches'] else '模型提供者与观察不一致'))
                for key,value in row['observed_fields'].items():lines.append(key+' = '+str(value))
                for field in row.get('field_comparisons',[]):
                    lines.append(field['field']+' · '+self.app.tr('模型值：')+str(field['expected'])+' · '+self.app.tr('观察值：')+str(field['observed'])+' · '+self.app.tr('一致' if field['matches'] else '不一致，请核对当前文件与脚本修改'))
            self.app.events.put({'kind':'text_report','title':'游戏内诊断对照','text':'\n'.join(lines)})
        self.app.work(work)
