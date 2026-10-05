import unittest
from test_management import Fixture
from mod_assistant.core import AssistantError
from mod_assistant.mod_analysis import inspect
from mod_assistant.xml_compare import compare_definition

class XMLComparisonTests(Fixture):
    def test_specific_prefab_fields_are_compared_without_writing_mods(self):
        left=self.make('101'); right=self.make('102')
        (left.source/'items.xml').write_text('<Items><Item identifier="shared" price="5"><Component value="a"/></Item><Item identifier="unrelated" /></Items>')
        (right.source/'items.xml').write_text('<Items><Override><Item price="8" identifier="shared"><Component value="b"/></Item></Override></Items>')
        original=[(mod.source/'items.xml').read_bytes() for mod in (left,right)]
        result=compare_definition(left.source,inspect(left),right.source,inspect(right),('item','item','shared'))
        self.assertIn('price="5"',result['left']); self.assertIn('price="8"',result['right'])
        self.assertIn('-<Item',result['diff']); self.assertNotIn('unrelated',result['left'])
        self.assertEqual(original,[(mod.source/'items.xml').read_bytes() for mod in (left,right)])

    def test_changed_definition_external_entity_and_cached_path_escape_blocked(self):
        left=self.make('101'); right=self.make('102'); a,b=inspect(left),inspect(right); key=('item','item','shared')
        (right.source/'items.xml').write_text('<Items><Item identifier="changed"/></Items>')
        with self.assertRaisesRegex(AssistantError,'变化'): compare_definition(left.source,a,right.source,b,key)
        (right.source/'items.xml').write_text('<!DOCTYPE Items [<!ENTITY x "example">]><Items><Item identifier="shared" /></Items>')
        with self.assertRaisesRegex(AssistantError,'实体'): compare_definition(left.source,a,right.source,b,key)
        a.definition_files['|'.join(key)]=['../../outside.xml']
        with self.assertRaisesRegex(AssistantError,'路径'): compare_definition(left.source,a,right.source,b,key)
