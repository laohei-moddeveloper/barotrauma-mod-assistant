import xml.etree.ElementTree as ET
from test_management import Fixture
from test_item_model import package
from mod_assistant.core import AssistantError
from mod_assistant.item_model import build_registry,explain_identifier
from mod_assistant.patch_draft import editable_changes,compose,export_draft


class PatchDraftTests(Fixture):
    def report(self):
        registry=build_registry([package('vanilla',-1,'<Item identifier="a" health="100" maxstacksize="1"/>'),
            package('101',0,'<Override><Item identifier="a" health="200" maxstacksize="1"><Sprite texture="%ModDir%/sprite.png"/></Item></Override>'),
            package('102',1,'<Override><Item identifier="a" health="100" maxstacksize="10"/></Override>')])
        return {'item_result':explain_identifier(registry,'a'),'providers':[{'id':'101','name':'101'},{'id':'102','name':'102'}],
                'key':('item','item','a'),'game_version':'1.13.4.0'}

    def test_explicit_field_choice_preserves_winner_and_original_asset_scope(self):
        report=self.report();choices=editable_changes(report)
        index=next(index for index,row in enumerate(choices) if row['path']=='/item/@maxstacksize')
        root,selected=compose(report,[index]);item=root.find('Item')
        self.assertEqual(item.get('health'),'200');self.assertEqual(item.get('maxstacksize'),'10')
        self.assertEqual(item.find('Sprite').get('texture'),'%ModDir:101%/sprite.png')
        self.assertEqual(report['item_result']['final_fields']['/item/@maxstacksize'],'1')
        self.assertEqual(len(selected),1)

    def test_export_is_an_uninstalled_draft_and_records_both_dependencies(self):
        report=self.report();before=self.config.read_bytes()
        index=next(index for index,row in enumerate(editable_changes(report)) if row['path']=='/item/@maxstacksize')
        folder=export_draft(self.env,report,[index]);metadata=ET.parse(folder/'metadata.xml')
        self.assertTrue(folder.is_relative_to(self.env.work/'patch-drafts'))
        self.assertEqual({node.get('steamID') for node in metadata.findall('dependencies/requiredAnyOrder')},{'101','102'})
        self.assertTrue((folder/'README.txt').is_file());self.assertEqual(before,self.config.read_bytes())
        self.assertFalse((self.env.game/'LocalMods'/folder.name).exists())

    def test_invalid_choices_and_ambiguous_origin_are_rejected(self):
        report=self.report()
        for choices in ([],[True],[999],[-1]):
            with self.assertRaises(AssistantError):compose(report,choices)
        report['providers'].append({'id':'999','name':'101'})
        with self.assertRaises(AssistantError):compose(report,[0])
