import ast
import json
from pathlib import Path
import re
import string
import tkinter as tk
import unittest
from unittest.mock import patch

from mod_assistant.i18n import Localizer, language_preference
from mod_assistant.i18n_catalog import EN
from mod_assistant.management_ui import ManagementDialog
from mod_assistant.order_ui import OrderDialog
import test_ui


class TranslationTests(unittest.TestCase):
    def test_all_user_facing_chinese_strings_have_translations(self):
        missing=[]
        # Regexes are analysis input, not displayed copy. Never translate them.
        for path in (Path(__file__).resolve().parents[1]/'mod_assistant').glob('*.py'):
            if path.stem.startswith('i18n'):
                continue
            tree=ast.parse(path.read_text(encoding='utf-8'))
            parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                value=None
                if isinstance(node,ast.Constant) and isinstance(node.value,str) and not isinstance(parents.get(node),ast.JoinedStr):
                    value=node.value
                elif isinstance(node,ast.JoinedStr):
                    value=''; index=0
                    for part in node.values:
                        if isinstance(part,ast.Constant):value+=part.value.replace('{','{{').replace('}','}}')
                        else:value+='{'+str(index)+'}'; index+=1
                if value and re.search('[\u4e00-\u9fff]',value) and '|' not in value and value not in EN:
                    missing.append((path.name,node.lineno,value))
        self.assertEqual(missing,[])

    def test_templates_keep_placeholders_and_user_values(self):
        fields=lambda value: sorted(field for _,field,_,_ in string.Formatter().parse(value) if field is not None)
        for source,target in EN.items():
            self.assertEqual(fields(source),fields(target),source)
        tr=Localizer('en').text
        self.assertEqual(tr('尚未下载的订阅模组 123'),'Subscribed mod not downloaded yet 123')
        self.assertEqual(tr('版本不同：中文潜艇（本机 1.2，配置 1.0）'),
                         'Version differs: 中文潜艇 (local 1.2, profile 1.0)')
        path='D:\\模组\\汉化\\潜艇.xml'
        self.assertEqual(tr('缺少模组资源：'+path),'Missing mod resource: '+path)
        self.assertEqual(tr('third-party error: leave this alone'),'third-party error: leave this alone')
        self.assertEqual(tr('12:34:56  任务未完成：Steam 正忙'),'12:34:56  Task incomplete: Steam is busy')

    def test_invalid_language_uses_os_default(self):
        with patch('mod_assistant.i18n.locale.getlocale',return_value=('zh_CN','UTF-8')):
            self.assertEqual(language_preference([]),'zh')
        with patch('mod_assistant.i18n.locale.getlocale',return_value=('en_US','UTF-8')):
            self.assertEqual(language_preference(None),'en')

    def test_exported_report_translates_prose_without_mutating_user_data(self):
        data={'schema':'barotrauma-mod-analysis-v1','mods':[{'id':'101','name':'其他',
              'types':['潜艇/舰船'],'compatibility':'高·未见冲突',
              'path':'D:\\汉化\\潜艇.xml','reasons':['部分资源未能分析，结论不完整']}],
              'errors':{'102':'Steam 正忙'}}
        result=Localizer('en').report(data)
        self.assertEqual(result['schema'],data['schema'])
        self.assertEqual(result['mods'][0]['name'],'其他')
        self.assertEqual(result['mods'][0]['path'],data['mods'][0]['path'])
        self.assertEqual(result['mods'][0]['types'],['Submarines / ships'])
        self.assertEqual(result['errors']['102'],'Steam is busy')
        self.assertEqual(data['mods'][0]['types'],['潜艇/舰船'])


class LanguageUiTests(test_ui.UiTests):
    test_drag_preview_respects_lock_and_never_writes_live_order=None
    test_manager_callback_and_operation_result_are_handled=None
    test_rule_editor_and_luacs_report_open=None

    def test_live_switch_preserves_order_names_filters_worker_and_game_config(self):
        app=self.app; app.set_language('zh'); before=self.config.read_bytes()
        app.selected={'101'}; app.filter.set('已启用'); app.search.set('102')
        app.tree.selection_set('102'); raw_stages={key:value['stage'] for key,value in app.mods.items()}
        order=OrderDialog(app); order.try_move(0,1); preview=list(order.ids)
        manager=ManagementDialog(app); app.worker=object()
        for language in ('en','zh','en'):
            app.set_language(language)
            self.assertEqual(order.ids,preview); self.assertEqual(self.config.read_bytes(),before)
            self.assertEqual(app.filter.get(),'已启用'); self.assertEqual(app.search.get(),'102')
            self.assertEqual(app.selected,{'101'}); self.assertEqual(app.tree.get_children(),('102',))
            self.assertEqual(app.tree.item('102','values')[2],app.mods['102']['mod'].name)
            self.assertEqual(raw_stages,{key:value['stage'] for key,value in app.mods.items()})
            self.assertEqual(app.update_button.cget('text'), 'Start parallel updates' if language=='en' else '开始并行更新')
            self.assertEqual(manager.window.title(),'Profiles, multiplayer & snapshots' if language=='en' else '配置、联机与快照')
            self.assertEqual(order.window.title(),'Mod load order' if language=='en' else '模组加载顺序')
        app.worker=None; manager.window.destroy(); order.window.destroy()

    def test_language_persists_and_reset_appearance_retains_it(self):
        app=self.app; app.set_language('en')
        self.assertEqual(json.loads(app.settings_file.read_text(encoding='utf-8'))['language'],'en')
        root=tk.Toplevel(app.root); root.withdraw()
        reopened=test_ui.App(root,auto_scan=False)
        self.assertEqual(reopened.locale.language,'en')
        self.assertEqual(reopened.update_button.cget('text'),'Start parallel updates')
        reopened.close()
        from mod_assistant.appearance import DEFAULTS
        app.interface.apply(DEFAULTS)
        self.assertEqual(app.locale.language,'en')

    def test_event_messages_reports_and_theme_filter_choices_translate(self):
        app=self.app; app.set_language('en')
        app.events.put({'kind':'scan_status','message':'正在读取 Steam 工坊状态…'})
        app.events.put({'kind':'log','message':'复制 2 个，复用 5 个文件'})
        app.drain()
        self.assertEqual(app.status.get(),'正在读取 Steam 工坊状态…')
        self.assertEqual(app.root.getvar(app.status._name),'Reading Steam Workshop status…')
        self.assertIn('Copied 2 files; reused 5',app.logs.get('1.0','end'))
        app.interface.theme.set('Graphite'); app.interface.density.set('Compact')
        self.assertEqual(app.interface.log_button.cget('text'),'Task log ▾')
        self.assertEqual(app.appearance.prefs['theme'],'graphite')
        self.assertEqual(app.appearance.prefs['density'],'compact')
        app.filter.set('Disabled'); self.assertEqual(app.tree.get_children(),('103',))
        app.text_report('任务未完成','缺少模组资源：D:\\汉化\\潜艇.xml')
        windows=[child for child in app.root.winfo_children() if isinstance(child,tk.Toplevel)]
        content=next(iter(app.locale.documents)); self.assertEqual(windows[-1].title(),'Task incomplete')
        self.assertIn('Missing mod resource: D:\\汉化\\潜艇.xml',content.get('1.0','end'))
        app.set_language('zh'); self.assertIn('缺少模组资源：D:\\汉化\\潜艇.xml',content.get('1.0','end'))
        windows[-1].destroy()
