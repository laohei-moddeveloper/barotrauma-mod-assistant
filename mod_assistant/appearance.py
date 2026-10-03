"""Validated local appearance preferences and live Tk/ttk styling."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont, ttk

THEMES = {'ocean': '深海蓝', 'graphite': '石墨灰', 'daylight': '明亮'}
COLUMNS = ('check', 'enable', 'name', 'kind', 'importance', 'compat',
           'version', 'installed', 'size', 'stage', 'progress')
TITLES = ('更新', '启用', '模组', '类型', '重要程度', '兼容性',
          '缓存版本', '已安装版本', '大小', '状态', '进度')
DEFAULTS = {'theme': 'ocean', 'accent': '#57dac4', 'font_size': 10,
            'density': 'comfortable', 'show_logs': False,
            'columns': ['check', 'enable', 'name', 'kind', 'importance', 'compat',
                        'installed', 'stage', 'progress']}

PALETTES = {
    'ocean': dict(bg='#0b1422', panel='#142237', raised='#1c304a', text='#e8f0fa',
                  muted='#9aadc2', button='#20354e', hover='#2e4c6b', selected='#294866',
                  selected_text='#ffffff', border='#314760', dim='#8294a9',
                  log='#0e1b2d', warning='#f1c67b', error='#ff9f9f', active='#8eceff'),
    'graphite': dict(bg='#17191f', panel='#23262e', raised='#2d313c', text='#f2f3f7',
                    muted='#afb6c5', button='#303540', hover='#414856', selected='#424b60',
                    selected_text='#ffffff', border='#454c5c', dim='#8e98ac',
                    log='#1c1f26', warning='#efca80', error='#ffabb1', active='#aacdff'),
    'daylight': dict(bg='#f2f5f9', panel='#ffffff', raised='#e6edf5', text='#17283d',
                    muted='#4c6078', button='#e2eaf4', hover='#cfdeef', selected='#d3e8ed',
                    selected_text='#17283d', border='#bac9da', dim='#63758c',
                    log='#e9eff6', warning='#805211', error='#ae2636', active='#195c99'),
}

# Legacy windows use these semantic colours. Roles are recorded once, so a
# second theme switch never guesses a role from the newly applied colour.
ALIASES = {'#0b1422': 'bg', '#142237': 'panel', '#1c304a': 'raised',
           '#e8f0fa': 'text', '#8fa6bf': 'muted', '#20354e': 'button',
           '#2e4c6b': 'hover', '#294866': 'selected', '#ffffff': 'selected_text',
           '#627890': 'dim', '#0e1b2d': 'log', '#f1c67b': 'warning',
           '#ff9f9f': 'error', '#8eceff': 'active'}


def normalize(data):
    data = data if isinstance(data, dict) else {}
    result = {**DEFAULTS, 'columns': list(DEFAULTS['columns'])}
    if isinstance(data.get('theme'),str) and data['theme'] in THEMES: result['theme'] = data['theme']
    accent = data.get('accent')
    if isinstance(accent, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', accent):
        result['accent'] = accent.lower()
    if type(data.get('font_size')) is int and data['font_size'] in (10, 11, 12):
        result['font_size'] = data['font_size']
    if data.get('density') in ('comfortable', 'compact'): result['density'] = data['density']
    if type(data.get('show_logs')) is bool: result['show_logs'] = data['show_logs']
    if isinstance(data.get('columns'), list):
        result['columns'] = [key for key in COLUMNS if key in ('check', 'enable', 'name') or key in data['columns']]
    return result


def luminance(colour):
    parts = [int(colour[index:index+2], 16) / 255 for index in (1, 3, 5)]
    parts = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055)**2.4 for value in parts]
    return sum(value * weight for value, weight in zip(parts, (.2126, .7152, .0722)))


def contrast(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def mix(first, second, amount):
    return '#' + ''.join(f'{round(int(first[i:i+2],16)*(1-amount)+int(second[i:i+2],16)*amount):02x}' for i in (1,3,5))


def palette(data):
    prefs = normalize(data); colours = dict(PALETTES[prefs['theme']])
    accent = prefs['accent']
    primary_text = max(('#071119', '#ffffff'), key=lambda colour: contrast(colour, accent))
    readable = accent
    target = '#17283d' if prefs['theme'] == 'daylight' else '#ffffff'
    for _ in range(20):
        if min(contrast(readable, colours['bg']), contrast(readable, colours['panel'])) >= 4.5: break
        readable = mix(readable, target, .15)
    colours.update(accent=accent, accent_text=readable, primary_text=primary_text,
                   accent_hover=mix(accent, primary_text, .1))
    return colours


class Appearance:
    def __init__(self, prefs):
        self.update(prefs)

    def update(self, prefs):
        self.prefs = normalize(prefs); self.colours = palette(self.prefs)

    def configure_style(self, root):
        colour = self.colours; size = self.prefs['font_size']
        font = ('Microsoft YaHei UI', size)
        style = ttk.Style(root)
        if style.theme_use() != 'clam': style.theme_use('clam')
        style.configure('.', background=colour['bg'], foreground=colour['text'], font=font)
        style.configure('Treeview', background=colour['panel'], fieldbackground=colour['panel'],
                        foreground=colour['text'], rowheight=size*2+(6 if self.prefs['density']=='compact' else 14),
                        borderwidth=0, bordercolor=colour['border'], lightcolor=colour['panel'],darkcolor=colour['panel'],font=font)
        style.configure('Treeview.Heading', background=colour['raised'], foreground=colour['muted'],
                        padding=(8,7), bordercolor=colour['border'],lightcolor=colour['raised'],darkcolor=colour['raised'],font=font)
        style.map('Treeview', background=[('selected',colour['selected'])],
                  foreground=[('selected',colour['selected_text'])])
        style.map('Treeview.Heading', background=[('active',colour['hover'])])
        style.configure('TNotebook', background=colour['bg'], borderwidth=0,bordercolor=colour['border'],
                        lightcolor=colour['bg'],darkcolor=colour['bg'])
        style.configure('TNotebook.Tab', background=colour['button'], foreground=colour['muted'],
                        padding=(20,7),bordercolor=colour['border'],lightcolor=colour['button'],darkcolor=colour['button'],font=font)
        style.map('TNotebook.Tab', background=[('selected',colour['panel']),('active',colour['hover'])],
                  foreground=[('selected',colour['accent_text']),('active',colour['text'])])
        style.configure('TScrollbar', background=colour['button'], troughcolor=colour['bg'],
                        bordercolor=colour['border'], arrowcolor=colour['muted'], borderwidth=0)
        style.configure('TCombobox', fieldbackground=colour['panel'], foreground=colour['text'],
                        background=colour['button'], arrowcolor=colour['text'], font=font)
        style.map('TCombobox', fieldbackground=[('readonly',colour['panel'])],
                  foreground=[('readonly',colour['text']),('disabled',colour['dim'])],
                  selectbackground=[('readonly',colour['selected'])],
                  selectforeground=[('readonly',colour['selected_text'])])
        style.configure('TProgressbar', background=colour['accent'], troughcolor=colour['panel'], borderwidth=0)
        root.option_add('*TCombobox*Listbox.background',colour['panel'])
        root.option_add('*TCombobox*Listbox.foreground',colour['text'])
        root.option_add('*TCombobox*Listbox.selectBackground',colour['selected'])
        root.option_add('*TCombobox*Listbox.selectForeground',colour['selected_text'])
        root.option_add('*TCombobox*Listbox.font',font)

    def skin(self, window):
        colour = self.colours
        def walk(widget):
            roles = getattr(widget, '_appearance_roles', None)
            if roles is None:
                roles = {}; widget._appearance_roles = roles
                keys = widget.keys()
                for key in ('background','foreground','activebackground','activeforeground',
                            'selectbackground','selectforeground','selectcolor','insertbackground',
                            'disabledforeground','buttonbackground','highlightbackground','highlightcolor'):
                    if key not in keys: continue
                    value = str(widget.cget(key)).lower()
                    role = ALIASES.get(value)
                    if value == '#57dac4': role = 'accent_text' if key.endswith('foreground') else 'accent'
                    if value == '#78e8d5': role = 'accent_hover'
                    if key == 'highlightbackground': role = 'border'
                    if key == 'highlightcolor': role = 'accent_text'
                    if key == 'buttonbackground': role = 'button'
                    if isinstance(widget, tk.Menu):
                        role = {'background':'panel','foreground':'text','activebackground':'selected',
                                'activeforeground':'selected_text','disabledforeground':'dim'}.get(key,role)
                    if getattr(widget,'_appearance_primary',False) and key in ('foreground','activeforeground'):
                        role = 'primary_text'
                    if role: roles[key] = role
                if 'font' in keys:
                    actual = tkfont.Font(root=widget, font=widget.cget('font')).actual()
                    widget._appearance_font = (actual['family'], abs(actual['size'])-10,
                                               actual['weight'], actual['slant'])
            if not getattr(widget,'_appearance_fixed',False):
                for key,role in roles.items(): widget.configure(**{key:colour[role]})
            if hasattr(widget,'_appearance_font'):
                family,offset,weight,slant=widget._appearance_font
                widget.configure(font=(family,max(9,self.prefs['font_size']+offset),weight,slant))
            for child in widget.winfo_children(): walk(child)
        walk(window)
