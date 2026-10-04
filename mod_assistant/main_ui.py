"""Focused navigation and appearance controls for the desktop assistant."""
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from . import VERSION
from .appearance import COLUMNS, DEFAULTS, THEMES, TITLES, normalize
from .i18n import LANGUAGES
from .luacs import RESTORE_GUIDE

BG, PANEL, TEXT, MUTED = '#0b1422', '#142237', '#e8f0fa', '#8fa6bf'


class MainInterface:
    def __init__(self, app):
        self.app = app; self.updating = False
        self.build()
        self.apply(app.appearance.prefs, persist=False)

    def frame(self, parent, panel=False, **kwargs):
        return tk.Frame(parent, bg=PANEL if panel else BG, **kwargs)

    def heading(self, parent, title, description):
        self.app.label(parent,title,font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w',pady=(0,6))
        label=self.app.label(parent,description,fg=MUTED,justify='left',wraplength=1000)
        label.pack(anchor='w',pady=(0,12))
        parent.bind('<Configure>',lambda event:label.configure(wraplength=max(350,event.width-50)),add='+')

    def card(self,parent,title,description,column):
        card=self.frame(parent,panel=True,padx=20,pady=18)
        card.grid(row=0,column=column,sticky='nsew',padx=(0,14) if column==0 else (0,0),pady=8)
        # Labels inherit a card's background instead of drawing dark rectangles.
        title_label=self.app.label(card,title,bg=PANEL,font=('Microsoft YaHei UI',14,'bold'))
        title_label.pack(anchor='w',pady=(0,8))
        self.app.label(card,description,bg=PANEL,fg=MUTED,wraplength=400,justify='left').pack(anchor='w',pady=(0,18))
        return card

    def scroll_page(self,parent):
        panel=self.frame(parent); panel.pack(fill='both',expand=True)
        bar=ttk.Scrollbar(panel); bar.pack(side='right',fill='y')
        canvas=tk.Canvas(panel,bg=BG,highlightthickness=0,yscrollcommand=bar.set)
        canvas.pack(side='left',fill='both',expand=True); bar.configure(command=canvas.yview)
        content=self.frame(canvas,padx=20,pady=12)
        item=canvas.create_window(0,0,window=content,anchor='nw')
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
        content.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        def wheel(event):
            if isinstance(event.widget,(ttk.Combobox,tk.Spinbox,tk.Text)):
                return
            widget=event.widget
            while widget is not None:
                if widget is content or widget is canvas:
                    if canvas.bbox('all') and canvas.bbox('all')[3]>canvas.winfo_height():
                        canvas.yview_scroll(-int(event.delta/120),'units')
                    return 'break'
                widget=getattr(widget,'master',None)
        self.app.root.bind_all('<MouseWheel>',wheel,add='+')
        return content

    def build(self):
        app=self.app
        header=self.frame(app.root,padx=22,pady=6); header.pack(fill='x')
        identity=self.frame(header); identity.pack(side='left')
        self.identity_label=app.label(identity,'BaroDock',font=('Microsoft YaHei UI',20,'bold'))
        self.identity_label.pack(anchor='w')
        app.button(header,'外观设置',lambda:self.notebook.select(self.settings_page),busy=False).pack(side='right')
        self.language=tk.StringVar(value=LANGUAGES[app.locale.language])
        self.language_picker=ttk.Combobox(header,textvariable=self.language,
                                         values=list(LANGUAGES.values()),state='readonly',width=9)
        self.language_picker.pack(side='right',padx=(10,12))
        self.language_picker.bind('<<ComboboxSelected>>',lambda event:
                                  app.set_language(next(key for key,value in LANGUAGES.items() if value==self.language.get())))
        app.label(header,'语言 / Language',fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='right')
        app.label(header,'v'+VERSION,fg=MUTED).pack(side='right',padx=16)
        toolbar=self.frame(app.root,padx=22,pady=2); toolbar.pack(fill='x')
        app.update_button=app.button(toolbar,'开始并行更新',lambda:app.start_update(True),primary=True)
        app.update_button.pack(side='left',padx=(0,10))
        app.refresh_button=app.button(toolbar,'重新检测',app.scan,requires_game=False); app.refresh_button.pack(side='left',padx=(0,10))
        app.button(toolbar,'联网检测',app.online_scan,requires_game=False).pack(side='left',padx=(0,10))
        app.button(toolbar,'启动游戏',app.launch).pack(side='left')
        app.stop_button=app.button(toolbar,'停止任务',app.stop,busy=False)
        app.stop_button.pack(side='right'); app.stop_button.configure(state='disabled')
        status=self.frame(app.root,padx=22,pady=4); status.pack(side='bottom',fill='x')
        self.status_label=app.label(status,textvariable=app.status,fg=MUTED,anchor='w',justify='left',wraplength=1200)
        self.status_label.pack(side='left',fill='both',expand=True)
        self.log_panel=self.frame(app.root,padx=22,pady=3)
        self.log_button=app.button(status,'任务记录 ▾',self.toggle_logs,busy=False)
        self.log_button.configure(pady=2,padx=10); self.log_button.pack(side='right')
        app.logs=tk.Text(self.log_panel,height=4,bg='#0e1b2d',fg=MUTED,relief='flat',bd=0,
                         padx=12,pady=8,font=('Microsoft YaHei UI',9),state='disabled',wrap='word')
        self.notebook=ttk.Notebook(app.root); self.notebook.pack(fill='both',expand=True,padx=22,pady=(8,5))
        self.mods_page=self.frame(self.notebook,padx=16,pady=10)
        self.tools_page=self.frame(self.notebook)
        self.settings_page=self.frame(self.notebook)
        for page,title in ((self.mods_page,'模组管理'),(self.tools_page,'工具与脚本'),(self.settings_page,'设置与外观')):
            self.notebook.add(page,text=title)
        self.build_mods(); self.build_tools(); self.build_settings()
        app.root.bind('<Configure>',self.resize,add='+')
        app.root.bind('<Control-f>',self.focus_search)
        app.root.bind('<F5>',lambda event:app.refresh_button.invoke())
        app.root.bind('<Control-u>',lambda event:app.update_button.invoke())
        app.root.bind('<Escape>',lambda event:app.stop() if app.worker and app.worker.is_alive() else None)

    def build_mods(self):
        app=self.app; container=self.mods_page
        actions=self.frame(container); actions.pack(fill='x',pady=(0,8))
        for title,command in [('启用 / 禁用',app.toggle_selected),('加载顺序',app.show_order),
                              ('配置 / 联机 / 快照',app.show_management)]:
            app.button(actions,title,command).pack(side='left',padx=(0,8))
        menu_button=tk.Menubutton(actions,text='更多操作 ▾',bg='#20354e',fg=TEXT,relief='flat',
                                  padx=12,pady=6,font=('Microsoft YaHei UI',10))
        menu=tk.Menu(menu_button,tearoff=False)
        for title,command in [('继续未完成更新',app.resume_update),('重试失败项',app.retry_failed),('恢复选中模组上一版',app.restore),
                              ('查看完整分析',app.show_full_analysis),('导出兼容分析',app.export_analysis),
                              ('导出联机清单',app.export_profile),('对比联机清单',app.compare_profile),
                              ('导出更新报告',app.export_report)]: menu.add_command(label=title,command=command)
        menu_button.configure(menu=menu); menu_button.pack(side='right'); app.busy_buttons.append(menu_button)
        controls=self.frame(container); controls.pack(fill='x',pady=(0,8))
        for title,command in [('全选',app.select_all),('只选已启用',app.select_enabled),('清空',app.select_none)]:
            app.button(controls,title,command).pack(side='left',padx=(0,6))
        app.filter=app.locale.variable(app.root,value='全部模组')
        filters=ttk.Combobox(controls,textvariable=app.filter,values=['全部模组','已启用','未启用','需要处理'],
                             state='readonly',width=10); filters.pack(side='left',padx=(8,8))
        app.search_entry=tk.Entry(controls,textvariable=app.search,bg=PANEL,fg=TEXT,relief='flat',
                                  insertbackground=TEXT,font=('Microsoft YaHei UI',10),width=22)
        app.search_entry.pack(side='left',fill='x',expand=True,ipady=7)
        app.search_entry.bind('<Escape>',self.clear_search)
        app.search.trace_add('write',lambda *_:app.render())
        app.filter.trace_add('write',lambda *_:app.render())
        columns_button=tk.Menubutton(controls,text='显示列 ▾',bg='#20354e',fg=TEXT,relief='flat',
                                     padx=10,pady=6,font=('Microsoft YaHei UI',10))
        self.column_menu=tk.Menu(columns_button,tearoff=False); self.column_vars={}
        for key,title in zip(COLUMNS,TITLES):
            if key in ('check','enable','name'): continue
            variable=tk.BooleanVar(value=key in app.appearance.prefs['columns']); self.column_vars[key]=variable
            self.column_menu.add_checkbutton(label=title,variable=variable,command=self.change_columns)
        columns_button.configure(menu=self.column_menu); columns_button.pack(side='right',padx=(8,0))
        summary=self.frame(container); summary.pack(fill='x',pady=(0,5))
        app.label(summary,textvariable=app.summary,fg=MUTED).pack(side='left')
        app.label(summary,'搜索名称或编号 · Ctrl+F',fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='right')
        details=self.frame(container,pady=4); details.pack(side='bottom',fill='x')
        app.detail=app.locale.variable(app.root,value='“更新”勾选与“启用”开关分别控制。选中一行可查看类型与兼容原因。')
        app.detail_label=app.label(details,textvariable=app.detail,fg=MUTED,anchor='nw',justify='left',wraplength=1100,height=2)
        app.detail_label.pack(fill='x')
        table=self.frame(container,panel=True); table.pack(fill='both',expand=True)
        app.tree=ttk.Treeview(table,columns=COLUMNS,show='headings',selectmode='extended',height=3)
        widths=(48,64,300,160,86,155,90,100,72,160,66)
        saved=app.settings.get('column_widths',{})
        for key,title,width in zip(COLUMNS,TITLES,widths):
            value=saved.get(key,width) if isinstance(saved,dict) else width
            value=max(width,min(1000,value)) if type(value) is int else width
            app.tree.heading(key,text=title)
            app.tree.column(key,width=value,minwidth=width if key!='name' else 180,
                            stretch=key in ('name','stage'),anchor='w' if key in ('name','kind','stage') else 'center')
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=app.tree.xview)
        horizontal.pack(side='bottom',fill='x')
        bar=ttk.Scrollbar(table,command=app.tree.yview); bar.pack(side='right',fill='y')
        app.tree.pack(fill='both',expand=True)
        app.tree.configure(xscrollcommand=horizontal.set,yscrollcommand=bar.set)
        app.tree.bind('<Button-1>',app.click_checkbox); app.tree.bind('<space>',app.toggle_highlight)
        app.tree.bind('<<TreeviewSelect>>',app.show_detail)
        app.tree.bind('<Control-c>',app.copy_selected)
        app.tree.bind('<Button-3>',self.context_menu)
        self.context=tk.Menu(app.tree,tearoff=False)
        for title,command in [('复制名称与编号',app.copy_selected),('启用 / 禁用选中模组',app.toggle_selected),('查看完整分析',app.show_full_analysis),
                              ('调整加载顺序',app.show_order)]: self.context.add_command(label=title,command=command)

    def build_tools(self):
        app=self.app; body=self.scroll_page(self.tools_page)
        self.heading(body,'需要时再打开这些工具','脚本支持、检查与导出集中在这里，日常更新仍在模组管理页完成。')
        grid=self.frame(body); grid.pack(fill='x'); grid.columnconfigure((0,1),weight=1,uniform='tools')
        lua=self.card(grid,'LuaCs 脚本支持','安装客户端、开启 C#，或检查游戏启动后的脚本状态。',0)
        app.label(lua,textvariable=app.luacs_text,bg=PANEL,fg=MUTED,wraplength=400,justify='left').pack(anchor='w',pady=(0,14))
        app.label(lua,textvariable=app.luacs_backup_text,bg=PANEL,fg=MUTED,wraplength=400,justify='left').pack(anchor='w',pady=(0,8))
        app.button(lua,'LuaCs 恢复说明',lambda:app.text_report('LuaCs 恢复说明', RESTORE_GUIDE),busy=False).pack(anchor='w',pady=5)
        for title,command,primary in [('一键安装 LuaCs + C#',app.install_luacs,True),
                                     ('安装后验证指引',app.verify_luacs,False),('恢复 LuaCs 安装前',app.restore_luacs,False)]:
            button=app.button(lua,title,command,primary)
            button.pack(anchor='w',pady=5)
            if command == app.restore_luacs:
                self.restore_button=button
        checks=self.card(grid,'检查与报告','遇到问题先看日志；需要分享时可导出模组与更新信息。',1)
        for title,command in [('游戏 / LuaCs 日志诊断',app.diagnose_logs),('选择其他日志',lambda:app.diagnose_logs(choose=True)),
                              ('完整重新分析',lambda:app.scan(force=True)),('仅同步本地缓存',lambda:app.start_update(False)),
                              ('导出兼容分析',app.export_analysis),('导出更新报告',app.export_report)]:
            app.button(checks,title,command).pack(anchor='w',pady=5)
        app.label(body,'Steam 负责实际网络下载；停止助手任务后，Steam 已接受的下载可能继续。',
                  fg=MUTED,wraplength=1000,justify='left').pack(anchor='w',pady=(18,8))

    def build_settings(self):
        app=self.app; body=self.scroll_page(self.settings_page)
        self.heading(body,'按你的习惯使用助手','外观立即生效并自动保存。更新设置可以单独保存，原有模组配置不受影响。')
        grid=self.frame(body); grid.pack(fill='x'); grid.columnconfigure((0,1),weight=1,uniform='settings')
        appearance=self.card(grid,'外观与阅读','选择主题、强调色和列表样式。可以随时恢复默认外观。',0)
        self.theme=app.locale.variable(app.root); self.font=tk.StringVar(); self.density=app.locale.variable(app.root)
        self.logs_visible=tk.BooleanVar()
        for title,variable,values in [('主题',self.theme,list(THEMES.values())),
                                       ('字号',self.font,['10','11','12']),('列表疏密',self.density,['舒适','紧凑'])]:
            row=self.frame(appearance,panel=True); row.pack(fill='x',pady=6)
            app.label(row,title,bg=PANEL,width=10,anchor='w').pack(side='left')
            combo=ttk.Combobox(row,textvariable=variable,values=values,state='readonly',width=14)
            combo.pack(side='left'); variable.trace_add('write',self.preference_changed)
        row=self.frame(appearance,panel=True); row.pack(fill='x',pady=(12,5))
        app.label(row,'强调色',bg=PANEL,width=10,anchor='w').pack(side='left')
        self.accent_caption=app.label(row,'',bg=PANEL,fg=MUTED); self.accent_caption.pack(side='left')
        swatches=self.frame(appearance,panel=True); swatches.pack(fill='x',pady=(0,8))
        for colour in ('#57dac4','#6fb5ff','#b9a3ff','#ffb07c','#f2cc70','#f095b3'):
            button=tk.Button(swatches,text=' ',width=2,bg=colour,activebackground=colour,relief='flat',
                             command=lambda value=colour:self.apply({**app.appearance.prefs,'accent':value}))
            button._appearance_fixed=True; button.pack(side='left',padx=(0,7),ipady=3)
        app.button(appearance,'自选颜色…',self.choose_accent,busy=False).pack(anchor='w',pady=(0,10))
        checkbox=tk.Checkbutton(appearance,text='默认展开任务记录',variable=self.logs_visible,command=self.preference_changed,
                                bg=PANEL,fg=TEXT,selectcolor=PANEL,activebackground=PANEL,font=('Microsoft YaHei UI',10))
        checkbox.pack(anchor='w',pady=5)
        app.button(appearance,'恢复默认外观',lambda:self.apply(DEFAULTS),busy=False).pack(anchor='w',pady=(14,6))
        app.label(appearance,'外观已自动保存 · 显示列可在模组管理页选择',bg=PANEL,fg=MUTED,
                  wraplength=400,justify='left',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=5)
        operations=self.card(grid,'更新与检测','这些设置沿用你已有的选择；调整后点击保存更新设置。',1)
        for title,variable,low,high in [('同时更新',app.download_slots,1,12),('同时安装',app.install_slots,1,6),
                                       ('无进度超时（秒）',app.timeout,30,900)]:
            row=self.frame(operations,panel=True); row.pack(fill='x',pady=8)
            app.label(row,title,bg=PANEL,width=17,anchor='w').pack(side='left')
            spin=tk.Spinbox(row,from_=low,to=high,textvariable=variable,width=6,bg=BG,fg=TEXT,
                            buttonbackground='#29405b',insertbackground=TEXT,relief='flat',font=('Microsoft YaHei UI',10))
            spin.pack(side='left'); app.busy_buttons.append(spin)
        for title,variable in [('更新前保存整套快照',app.auto_snapshot),('游玩时使用轻量检测',app.light_detection)]:
            checkbox=tk.Checkbutton(operations,text=title,variable=variable,bg=PANEL,fg=TEXT,
                                    selectcolor=BG,activebackground=PANEL,font=('Microsoft YaHei UI',10))
            checkbox.pack(anchor='w',pady=7); app.busy_buttons.append(checkbox)
        app.button(operations,'保存更新设置',self.save_operations,requires_game=False).pack(anchor='w',pady=(12,6))
        app.button(operations,'选择游戏目录',app.choose_game,requires_game=False).pack(anchor='w',pady=6)
        app.button(operations,'首次使用与环境检查',app.environment_help,busy=False).pack(anchor='w',pady=6)
        app.button(operations,'访问范围与隐私',app.show_access,busy=False).pack(anchor='w',pady=6)
        app.label(operations,textvariable=app.storage_status,bg=PANEL,fg=MUTED,wraplength=400,justify='left').pack(anchor='w',pady=6)
        app.label(operations,'F5 重新检测 · Ctrl+U 开始更新\nEsc 停止助手任务 · Ctrl+F 搜索模组',bg=PANEL,fg=MUTED,
                  justify='left',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(16,0))

    def preference_changed(self,*args):
        if self.updating: return
        theme=next(key for key,title in THEMES.items() if title==self.theme.get())
        self.apply({**self.app.appearance.prefs,'theme':theme,'font_size':int(self.font.get()),
                    'density':'compact' if self.density.get()=='紧凑' else 'comfortable',
                    'show_logs':self.logs_visible.get()})

    def apply(self,prefs,persist=True):
        app=self.app; prefs=normalize(prefs); self.updating=True
        try:
            app.appearance.update(prefs); app.make_style(); app.skin(app.root)
            self.theme.set(THEMES[prefs['theme']]); self.font.set(str(prefs['font_size']))
            self.density.set('紧凑' if prefs['density']=='compact' else '舒适')
            self.logs_visible.set(prefs['show_logs']); self.accent_caption.configure(text=prefs['accent'].upper())
            for key,variable in self.column_vars.items(): variable.set(key in prefs['columns'])
            app.tree.configure(displaycolumns=prefs['columns'])
            if prefs['show_logs']:
                self.log_panel.pack(side='bottom',fill='x',before=self.notebook)
                app.logs.pack(fill='x',pady=(4,0)); self.log_button.configure(text='收起记录 ▴')
            else:
                app.logs.pack_forget(); self.log_panel.pack_forget(); self.log_button.configure(text='任务记录 ▾')
            app.locale.localize(app.root)
            self.fit_header(app.root.winfo_width())
            app.settings['appearance']=prefs
            if persist: app.save_settings()
        finally: self.updating=False

    def change_columns(self):
        self.apply({**self.app.appearance.prefs,'columns':[key for key in COLUMNS
                    if key in ('check','enable','name') or self.column_vars[key].get()]})

    def toggle_logs(self):
        self.apply({**self.app.appearance.prefs,'show_logs':not self.app.appearance.prefs['show_logs']})

    def choose_accent(self):
        result=colorchooser.askcolor(initialcolor=self.app.appearance.prefs['accent'],title=self.app.tr('选择强调色'),parent=self.app.root)[1]
        if result: self.apply({**self.app.appearance.prefs,'accent':result})

    def save_operations(self):
        app=self.app
        try:
            values=dict(download_slots=max(1,min(12,app.download_slots.get())),
                        install_slots=max(1,min(6,app.install_slots.get())),timeout=max(30,min(900,app.timeout.get())))
        except tk.TclError:
            self.app.dialogs.showerror('设置无效','并行数量和超时必须填写数字。',parent=app.root); return
        app.download_slots.set(values['download_slots']); app.install_slots.set(values['install_slots']); app.timeout.set(values['timeout'])
        app.settings.update(values,auto_snapshot=app.auto_snapshot.get(),light_detection=app.light_detection.get())
        if app.save_settings(): app.log('更新设置已保存。')
        app.status.set('更新设置已保存')

    def context_menu(self,event):
        app=self.app; item=app.tree.identify_row(event.y)
        if not item or app.worker and app.worker.is_alive(): return
        app.tree.selection_set(item); app.tree.focus(item)
        try: self.context.tk_popup(event.x_root,event.y_root)
        finally: self.context.grab_release()

    def focus_search(self,event=None):
        self.notebook.select(self.mods_page); self.app.search_entry.focus_set(); self.app.search_entry.select_range(0,'end')
        return 'break'

    def clear_search(self,event=None):
        self.app.search.set('')
        return 'break'

    def resize(self,event):
        if event.widget is self.app.root:
            self.fit_header(event.width)
            self.status_label.configure(wraplength=max(600,event.width-170))
            self.app.detail_label.configure(wraplength=max(650,event.width-85))

    def fit_header(self, width):
        size = self.app.appearance.prefs['font_size'] + (6 if width < 1150 else 10)
        self.identity_label.configure(font=('Microsoft YaHei UI',size,'bold'))
        self.app.search_entry.configure(width=14 if width < 1150 else 22)
