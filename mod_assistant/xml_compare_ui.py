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
        app.label(self.window,'查看具体定义差异，帮助排查覆盖或制作兼容补丁。这里只读文件，不修改模组。',wraplength=950).pack(anchor='w',padx=16,pady=12)
        row=tk.Frame(self.window,bg='#0b1422'); row.pack(fill='x',padx=16)
        self.other=ttk.Combobox(row,state='readonly',values=[app.features[x].name+' ['+x+']' for x in self.others],width=45)
        self.other.pack(side='left',fill='x',expand=True); self.other.bind('<<ComboboxSelected>>',lambda event:self.select_other())
        self.key=ttk.Combobox(row,state='readonly',width=25); self.key.pack(side='left',fill='x',expand=True,padx=8)
        self.key.bind('<<ComboboxSelected>>',lambda event:self.clear_result())
        self.compare_button=app.button(row,'比较定义',self.compare,busy=True); self.compare_button.pack(side='left')
        self.note=app.locale.variable(app.root,value='选择同标识定义，查看两边 XML 和文本差异。')
        app.label(self.window,textvariable=self.note,wraplength=950,justify='left').pack(fill='x',padx=16,pady=8)
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
