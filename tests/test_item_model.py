import xml.etree.ElementTree as ET
from test_management import Fixture
from mod_assistant.item_model import build_registry,explain_identifier,merge_variant
from mod_assistant.mod_analysis import inspect


def package(item,index,xml):
    return {'id':item,'name':item,'index':index,'files':[('items.xml',ET.fromstring(xml))]}


class ItemModelTests(Fixture):
    def test_cancel_during_variant_composition_is_not_converted_into_a_result(self):
        from unittest.mock import patch
        from mod_assistant.core import Cancelled
        registry=build_registry([package('a',0,'<Items><Item identifier="base"/><Item identifier="child" variantof="base"/></Items>')])
        with patch('mod_assistant.item_model.merge_variant',side_effect=Cancelled('cancelled')):
            with self.assertRaises(Cancelled):explain_identifier(registry,'child')
    def test_reviewed_runtime_defaults_and_clamps_are_not_raw_xml_values(self):
        from mod_assistant.item_model import runtime_fields
        self.assertEqual(runtime_fields({}),{'health':100,'maxstacksize':1})
        self.assertEqual(runtime_fields({'/item/@health':'2000000','/item/@maxstacksize':'999'}),{'health':1000000,'maxstacksize':63})
        self.assertEqual(runtime_fields({'/item/@health':'NaN','/item/@maxstacksize':'not a number'}),{})

    def test_unmodeled_identifiers_do_not_invent_unicode_collisions_or_winners(self):
        registry=build_registry([package('a',0,'<Items><Item identifier="ss"/><Item identifier="ß"/><Item name="legacy"/></Items>')])
        result=explain_identifier(registry,'ss')
        self.assertEqual(result['status'],'limited');self.assertFalse(result['winner'])
        self.assertNotIn('ss',registry['failures'])
        self.assertEqual({row['reason'] for row in result['unsupported']},{'unicode_identifier','legacy_identifier'})
        mod=self.make('101');(mod.source/'items.xml').write_text('<Items><Item identifier="ss"/><Item identifier="ß"/></Items>')
        feature=inspect(mod);self.assertTrue(feature.partial);self.assertEqual(feature.definitions,{('item','item','ss')})
    def test_clear_hides_selected_early_override_without_falling_back(self):
        registry=build_registry([package('vanilla',-1,'<Items><Item identifier="a"/></Items>'),
            package('early',0,'<Override><Item identifier="a" health="200"/></Override>'),
            package('later',1,'<Items><Clear/><Override><Item identifier="a" health="300"/></Override></Items>')])
        self.assertEqual(explain_identifier(registry,'a')['status'],'cleared')

    def test_clear_does_not_erase_registration_errors(self):
        registry=build_registry([package('vanilla',-1,'<Item identifier="a"/>'),package('a',0,'<Item identifier="a"/>'),package('clear',1,'<Clear/>')])
        self.assertEqual(explain_identifier(registry,'a')['status'],'duplicate')

    def test_inherited_xml_numeric_operations_and_parent_asset_scope(self):
        parent=ET.fromstring('<Item identifier="base" health="100" speed="1.5"><Sprite texture="%ModDir%/a.png"/><Fabricate><RequiredItem identifier="iron" amount="2"/><RequiredItem identifier="copper"/></Fabricate></Item>')
        variant=ET.fromstring('<Item identifier="child" variantof="base" health="+25" speed="*2"><Fabricate><RequiredItem identifier="steel"/><RequiredItem/></Fabricate></Item>')
        result=merge_variant(parent,variant,'Base','Child')
        self.assertEqual(result.get('health'),'125');self.assertEqual(float(result.get('speed')),3)
        self.assertEqual(result.find('Sprite').get('texture'),'%ModDir:Base%/a.png')
        self.assertEqual(len(result.find('Fabricate')),1)
        self.assertEqual(result.find('Fabricate/RequiredItem').get('amount'),'2')
        self.assertEqual(parent.get('identifier'),'base')

    def test_clear_and_clearall_in_variants_follow_sibling_order(self):
        parent=ET.fromstring('<Item identifier="a"><Sprite x="1"/><Fabricate x="1"/><Fabricate x="2"/><Sound x="1"/></Item>')
        result=merge_variant(parent,ET.fromstring('<Item identifier="b"><ClearAll><Fabricate/></ClearAll><Sprite x="2"/></Item>'))
        self.assertEqual([node.tag for node in result],['Sprite','Sound']);self.assertEqual(result.find('Sprite').get('x'),'2')
        result=merge_variant(parent,ET.fromstring('<Item identifier="b"><Sprite x="9"/><Clear/><Sound x="2"/></Item>'))
        self.assertEqual([node.tag for node in result],['Sound']);self.assertEqual(result[0].get('x'),'2')

    def test_whole_definition_selection_reports_the_lost_stack_change(self):
        registry=build_registry([package('vanilla',-1,'<Item identifier="a" health="100" maxstacksize="1"/>'),
            package('a',0,'<Override><Item identifier="a" health="200" maxstacksize="1"/></Override>'),
            package('b',1,'<Override><Item identifier="a" health="100" maxstacksize="10"/></Override>')])
        result=explain_identifier(registry,'a')
        self.assertEqual(result['winner'],'a');self.assertEqual(result['final_fields']['/item/@maxstacksize'],'1')
        self.assertTrue(any(row['id']=='b' and row['path']=='/item/@maxstacksize' and row['declared']=='10' for row in result['lost_changes']))

    def test_ancestry_missing_cycle_and_tied_overrides_are_distinct(self):
        registry=build_registry([package('a',0,'<Items><Item identifier="child" variantof="missing"/><Item identifier="x" variantof="y"/><Item identifier="y" variantof="x"/><Override><Item identifier="tie"/><Item identifier="tie"/></Override></Items>')])
        self.assertEqual(explain_identifier(registry,'child')['status'],'missing_parent')
        self.assertEqual(explain_identifier(registry,'x')['status'],'inheritance_cycle')
        self.assertEqual(explain_identifier(registry,'tie')['status'],'ambiguous')

    def test_components_are_not_registered_as_prefabs_and_nested_overrides_work(self):
        mod=self.make('101')
        (mod.source/'items.xml').write_text('<Override><Items><Override><CustomItem identifier="a"><Holdable identifier="component"/></CustomItem></Override></Items></Override>')
        feature=inspect(mod)
        self.assertEqual(feature.definitions,{('item','item','a')});self.assertEqual(feature.overrides,feature.definitions)

    def test_other_identifier_failure_blocks_a_false_whole_package_winner(self):
        registry=build_registry([package('vanilla',-1,'<Items><Item identifier="bad"/><Item identifier="good"/></Items>'),
            package('broken',0,'<Items><Override><Item identifier="good" health="200"/></Override><Item identifier="bad"/></Items>')])
        result=explain_identifier(registry,'good')
        self.assertEqual(result['status'],'package_registration_failure');self.assertFalse(result['winner'])
        self.assertEqual(result['package_errors'][0]['identifier'],'bad')

    def test_broken_clear_or_inheritance_provider_blocks_a_false_result(self):
        core=package('vanilla',-1,'<Items><Item identifier="bad"/><Item identifier="base"/></Items>')
        clear=package('broken',0,'<Items><Clear/><Item identifier="bad"/></Items>')
        self.assertEqual(explain_identifier(build_registry([core,clear]),'base')['status'],'package_registration_failure')
        parent=package('broken',0,'<Items><Item identifier="bad"/><Item identifier="parent"/></Items>')
        child=package('child',1,'<Item identifier="child" variantof="parent"/>')
        self.assertEqual(explain_identifier(build_registry([core,parent,child]),'child')['status'],'package_registration_failure')
