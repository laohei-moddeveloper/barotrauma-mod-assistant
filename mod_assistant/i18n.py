"""Presentation-only localization; persisted mod identifiers and stages stay unchanged."""
from __future__ import annotations

import locale
import re
import string
import tkinter as tk
from tkinter import ttk, font as tkfont
import weakref

from .i18n_catalog import EN

LANGUAGES = {'zh': '中文', 'en': 'English'}


def language_preference(value=None):
    if isinstance(value, str) and value in LANGUAGES:
        return value
    try:
        language = locale.getlocale()[0] or ''
    except (ValueError, TypeError):
        language = ''
    return 'zh' if language.lower().startswith(('zh','chinese')) else 'en'


def _templates():
    values = []
    for source, target in EN.items():
        parts = list(string.Formatter().parse(source))
        fields = [field for _, field, _, _ in parts if field is not None]
        if not fields:
            continue
        expression = ''
        for literal, field, _, _ in parts:
            expression += re.escape(literal)
            if field is not None:
                expression += r'([\s\S]*?)'
        values.append((re.compile(expression), target, fields, len(source)))
    return sorted(values, key=lambda value: value[3], reverse=True)


TEMPLATES = _templates()
FRAGMENTS = sorted((source for source in EN if '{' not in source), key=len, reverse=True)
# Only these captured values are assistant-generated labels/messages, rather
# than mod names, resource IDs, versions, file names, or paths.
SEMANTIC_FIELDS = {
    'With {0} {1} mod {2}: {3}': {0, 1, 3},
    '{0}: {1}. Applies on the next game launch.': {1},
    '[{0}] Line {1} in the excerpt': {0},
    'XML declares Override for {0} {1} definitions (e.g. {2}). Check the intended override result.': {1},
}


class LocalizedVar(tk.StringVar):
    """Tk sees a translated value; application logic reads the original value."""
    def __init__(self, owner, master, value=''):
        self.owner = owner
        self.raw = str(value)
        self.rendered = owner.text(self.raw)
        super().__init__(master=master, value=self.rendered)
        owner.variables.append(weakref.ref(self))

    def set(self, value):
        self.raw = self.owner.source(str(value))
        self.rendered = self.owner.text(self.raw)
        super().set(self.rendered)

    def get(self):
        current = super().get()
        return self.raw if current == self.rendered else self.owner.source(current)

    def refresh(self):
        self.raw = self.get()
        self.rendered = self.owner.text(self.raw)
        super().set(self.rendered)


class Localizer:
    def __init__(self, language):
        self.language = language_preference(language)
        self.variables = []
        self.documents = weakref.WeakKeyDictionary()
        self.reverse = {value: key for key, value in EN.items() if '{' not in key}

    def source(self, text):
        return self.reverse.get(text, text)

    def text(self, text, depth=0):
        text = str(text)
        if self.language == 'zh' or not re.search(r'[\u4e00-\u9fff]', text):
            return text
        if text in EN:
            return EN[text]
        if depth > 12:
            return text
        stripped = text.strip()
        if stripped != text and stripped in EN:
            return text[:len(text)-len(text.lstrip())] + EN[stripped] + text[len(text.rstrip()):]
        timestamp = re.match(r'^(\d\d:\d\d:\d\d  )(.*)$',text,re.S)
        if timestamp:
            return timestamp[1] + self.text(timestamp[2],depth+1)
        for pattern, target, fields, _ in TEMPLATES:
            match = pattern.fullmatch(text)
            if match:
                arguments = {field: value for field, value in zip(fields, match.groups())}
                for index in SEMANTIC_FIELDS.get(target, set()):
                    key = str(index)
                    arguments[key] = self.text(arguments[key], depth+1)
                return re.sub(r'\{(\d+)\}', lambda m: arguments[m[1]], target)
        # Reports concatenate independently generated messages. Split at their
        # presentation separators, never replace Chinese substrings in user data.
        for separator, translated_separator in (('\n','\n'), ('  ·  ','  ·  '), (' · ',' · '),
                                                   ('；','; '), ('、',', ')):
            if separator in text:
                return translated_separator.join(self.text(part, depth+1) for part in text.split(separator))
        for source in FRAGMENTS:
            if source.endswith(('：', '： ', ' · ', '；')) and text.startswith(source):
                return EN[source] + self.text(text[len(source):], depth+1)
            if source.startswith(('。', '（')) and text.endswith(source):
                return self.text(text[:-len(source)], depth+1) + EN[source]
        return text

    def report(self, data):
        """Translate human-facing report fields, preserving schema and user data."""
        if isinstance(data,list):
            return [self.report(value) for value in data]
        if not isinstance(data,dict):
            return data
        translated={}
        prose={'note','message','status','stage','detail','importance','compatibility','reason','advice','evidence'}
        for key,value in data.items():
            if key in prose and isinstance(value,str):
                translated[key]=self.text(value)
            elif key in ('types','reasons') and isinstance(value,(list,tuple)):
                translated[key]=[self.text(item) for item in value]
            elif key=='errors' and isinstance(value,dict):
                translated[key]={item:self.text(error) for item,error in value.items()}
            else:
                translated[key]=self.report(value)
        return translated

    def variable(self, master, value=''):
        return LocalizedVar(self, master, value)

    def bind_text(self, widget, raw, protected=()):
        self.documents[widget] = (str(raw), frozenset(protected))
        self.refresh_text(widget)

    def refresh_text(self, widget):
        if not widget.winfo_exists():
            return
        raw, protected = self.documents[widget]
        value = '\n'.join(line if line in protected else self.text(line) for line in raw.split('\n'))
        state = widget.cget('state')
        position = widget.yview()
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        if position:
            widget.yview_moveto(position[0])
        widget.configure(state=state)

    def localize(self, window):
        def update(widget, key, current, setter):
            labels = getattr(widget, '_language_labels', {})
            source, previous = labels.get(key, (current, current))
            if current != previous:
                source = self.source(current)
            translated = self.text(source)
            setter(translated)
            labels[key] = (source, translated)
            widget._language_labels = labels

        def walk(widget):
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                update(widget, 'title', widget.title(), widget.title)
            if 'text' in widget.keys() and not ('textvariable' in widget.keys() and widget.cget('textvariable')):
                update(widget, 'text', str(widget.cget('text')), lambda value: widget.configure(text=value))
            if isinstance(widget, tk.Menu):
                last = widget.index('end')
                for index in range((last+1) if last is not None else 0):
                    if widget.type(index) in ('separator','tearoff'):
                        continue
                    update(widget, ('menu',index), widget.entrycget(index,'label'),
                           lambda value,i=index: widget.entryconfigure(i,label=value))
            if isinstance(widget, ttk.Notebook):
                for tab in widget.tabs():
                    update(widget, ('tab',tab), widget.tab(tab,'text'), lambda value,t=tab:widget.tab(t,text=value))
            if isinstance(widget, ttk.Treeview):
                size=abs(tkfont.Font(root=widget,font=ttk.Style(widget).lookup('Treeview','font')).actual('size'))
                minimums={'check':70,'enable':80,'kind':160,'importance':90,'compat':220,
                          'version':100,'installed':95,'size':75,'stage':160,'progress':80}
                for column in widget['columns']:
                    update(widget, ('heading',column), widget.heading(column,'text'),
                           lambda value,c=column:widget.heading(c,text=value))
                    if self.language=='en' and column in minimums:
                        minimum=int(minimums[column]*max(1,size/10))
                        widget.column(column,minwidth=minimum,width=max(minimum,widget.column(column,'width')))
            if isinstance(widget, ttk.Combobox) and isinstance(widget.getvar(widget.cget('textvariable')) if widget.cget('textvariable') else '', str):
                values = tuple(widget['values'])
                previous = getattr(widget, '_language_values', None)
                if previous is None or values != previous[1]:
                    source = tuple(self.source(value) for value in values)
                else:
                    source = previous[0]
                translated = tuple(self.text(value) for value in source)
                widget.configure(values=translated)
                widget._language_values = (source, translated)
            if isinstance(widget, tk.Button):
                siblings = sum(isinstance(child,tk.Button) for child in widget.master.winfo_children())
                widget.configure(wraplength=(100 if siblings>=5 else 180) if self.language=='en' else 0)
            for child in widget.winfo_children():
                walk(child)
        walk(window)

    def switch(self, language, window):
        if language not in LANGUAGES:
            raise ValueError('Unsupported language')
        self.language = language
        self.localize(window)
        self.variables = [reference for reference in self.variables if reference() is not None]
        for reference in self.variables:
            variable = reference()
            try:
                variable.refresh()
            except tk.TclError:
                pass
        for widget in list(self.documents):
            self.refresh_text(widget)


class Dialogs:
    """Localize native dialog copy without modifying tkinter's global functions."""
    def __init__(self, owner, module):
        self.owner, self.module = owner, module

    def __getattr__(self, name):
        function = getattr(self.module, name)
        def call(*args, **kwargs):
            arguments = tuple(self.owner.text(value) if isinstance(value,str) else value for value in args)
            for key in ('title','message','prompt','initialfile','initialvalue'):
                if key in kwargs:
                    kwargs[key] = self.owner.text(kwargs[key])
            if 'filetypes' in kwargs:
                kwargs['filetypes'] = [(self.owner.text(label),pattern) for label,pattern in kwargs['filetypes']]
            return function(*arguments, **kwargs)
        return call
