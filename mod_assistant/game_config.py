"""Locate real game XML elements while preserving every byte outside edits.

Expat supplies structural element boundaries. Comments and quoted examples are
never mistaken for a selected package list; empty and paired elements work alike.
"""
from dataclasses import dataclass
from xml.parsers import expat

from .core import AssistantError


@dataclass(frozen=True)
class ElementSpan:
    text: str
    first: int
    last: int

    def start(self):
        return self.first

    def end(self):
        return self.last

    def group(self):
        return self.text[self.first:self.last]


def _tag_end(raw, start):
    quote = None
    for position in range(start, len(raw)):
        value = raw[position]
        if quote is not None:
            if value == quote:
                quote = None
        elif value in (34, 39):
            quote = value
        elif value == 62:
            return position + 1
    raise AssistantError('游戏配置 XML 不完整，原文件未改动')


def package_regions(text):
    raw = text.encode('utf-8')
    parser = expat.ParserCreate()
    stack, active, found = [], {}, {}

    def start(name, attributes):
        name = name.casefold()
        parent = stack[-1] if stack else None
        stack.append(name)
        if len(stack)!=3 or parent != 'contentpackages' or name not in ('regularpackages', 'corepackage'):
            return
        if name in found or name in active:
            raise AssistantError('游戏配置含重复的模组区域，请先在游戏中核对')
        first = parser.CurrentByteIndex
        end = _tag_end(raw, first)
        active[name] = (len(stack), first, end, raw[first:end].rstrip().endswith(b'/>'))

    def end(name):
        name = name.casefold()
        value = active.get(name)
        if value is not None and value[0] == len(stack):
            _, first, tag_end, empty = active.pop(name)
            last = tag_end if empty else _tag_end(raw, parser.CurrentByteIndex)
            found[name] = ElementSpan(text, len(raw[:first].decode('utf-8')),
                                      len(raw[:last].decode('utf-8')))
        stack.pop()

    def reject_doctype(*args):
        raise AssistantError('游戏配置不支持外部声明，原文件未改动')

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as error:
        raise AssistantError('游戏配置 XML 无法读取，原文件未改动') from error
    return found.get('regularpackages'), found.get('corepackage')


class PackageRegion:
    """Small compatibility adapter for the existing region editing call sites."""
    def __init__(self, index):
        self.index = index

    def search(self, text):
        return package_regions(text)[self.index]
