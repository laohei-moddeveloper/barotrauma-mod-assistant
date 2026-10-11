import xml.etree.ElementTree as ET
from test_management import Fixture
from mod_assistant.mod_analysis import inspect
from mod_assistant.xml_semantics import field_changes,compare_semantics


class SemanticTests(Fixture):
    def test_custom_item_root_text_comparison_does_not_pick_component_identifier(self):
        from mod_assistant.xml_compare import definition_text
        mod=self.make('101')
        (mod.source/'items.xml').write_text('<Items><CustomItem identifier="shared"><Component identifier="shared" /></CustomItem></Items>')
        text=definition_text(mod.source,inspect(mod),('item','item','shared'))
        self.assertEqual(text.count('<CustomItem'),1)
        self.assertEqual(text.count('<Component'),1)

    def setup_mods(self):
        left=self.make('101'); right=self.make('102')
        (left.source/'items.xml').write_text('<Items><Override><Item identifier="shared" price="5"><Attack damage="10" /></Item></Override></Items>')
        (right.source/'items.xml').write_text('<Items><Override><Item identifier="shared" price="8"><Attack damage="3" /></Item></Override></Items>')
        original=self.env.game/'Content/Items/base.xml'; original.parent.mkdir(parents=True)
        original.write_text('<Items><Item identifier="shared" price="5"><Attack damage="3" /></Item></Items>')
        (self.env.game/'Content/ContentPackages/Vanilla.xml').write_text('<contentpackage name="Vanilla" gameversion="1.13.4.0"><Item file="Content/Items/base.xml" /></contentpackage>')
        return left,right

    def result(self,left,right,other=()):
        a,b=inspect(left),inspect(right)
        self.configure(['101','102',*[row[0] for row in other]])
        return compare_semantics(self.env,left.source,a,right.source,b,('item','item','shared'),[(left.item_id,left.source,a),(right.item_id,right.source,b),*other],['101','102',*[row[0] for row in other]])

    def test_base_changes_and_selected_whole_definition_are_explained(self):
        left,right=self.setup_mods(); before=[(mod.source/'items.xml').read_bytes() for mod in (left,right)]
        result=self.result(left,right); changes={row['path']:row for row in result['changes']}
        self.assertEqual(changes['/item/@price']['kind'],'仅右方改变该字段')
        self.assertEqual(changes['/item/attack/@damage']['kind'],'仅左方改变该字段')
        self.assertEqual(result['loading']['winner'],'101'); self.assertEqual(result['loading']['status'],'selected')
        self.assertEqual(before,[(mod.source/'items.xml').read_bytes() for mod in (left,right)])

    def test_two_ordinary_definitions_report_registration_error(self):
        left,right=self.setup_mods()
        for mod in (left,right): (mod.source/'items.xml').write_text('<Items><Item identifier="shared"/></Items>')
        self.assertEqual(self.result(left,right)['loading']['status'],'duplicate')

    def test_custom_core_is_the_field_baseline_and_not_vanilla(self):
        left,right=self.setup_mods();core=self.make('103',core=True)
        (core.source/'items.xml').write_text('<Item identifier="shared" price="8"><Attack damage="10"/></Item>')
        a,b,c=inspect(left),inspect(right),inspect(core)
        self.configure(['101','102'],core='103')
        result=compare_semantics(self.env,left.source,a,right.source,b,('item','item','shared'),
            [('101',left.source,a),('102',right.source,b),('103',core.source,c)],['101','102'])
        self.assertEqual(result['baseline_name'],'Mod 103')
        change=next(row for row in result['changes'] if row['path']=='/item/@price')
        self.assertEqual(change['baseline'],'8');self.assertEqual(change['kind'],'仅左方改变该字段')
        self.assertEqual(result['loading']['winner'],'101')

    def test_clear_in_package_without_matching_identifier_is_resolved(self):
        left,right=self.setup_mods(); other=self.make('104')
        (other.source/'items.xml').write_text('<Items><Clear /></Items>'); feature=inspect(other)
        result=self.result(left,right,[(other.item_id,other.source,feature)])
        self.assertEqual(result['loading']['status'],'cleared'); self.assertFalse(result['loading']['winner'])

    def test_other_version_or_inheritance_does_not_invent_winner(self):
        left,right=self.setup_mods(); path=self.env.game/'Content/ContentPackages/Vanilla.xml'
        path.write_text(path.read_text().replace('1.13.4.0','9.0'))
        self.assertEqual(self.result(left,right)['loading']['status'],'limited')
        path.write_text(path.read_text().replace('9.0','1.13.4.0'))
        (left.source/'items.xml').write_text('<Items><Override><Item identifier="shared" variantof="base"/></Override></Items>')
        self.assertEqual(self.result(left,right)['loading']['status'],'missing_parent')

    def test_repeated_unidentified_children_are_flagged_and_missing_attribute_is_not_zero(self):
        a=ET.fromstring('<Item identifier="shared"><Price value="5"/><Price value="8"/></Item>')
        b=ET.fromstring('<Item identifier="shared" price="0"><Price value="8"/><Price value="5"/></Item>')
        changes,ambiguous=field_changes(a,b)
        self.assertTrue(ambiguous); row=next(row for row in changes if row['path']=='/item/@price')
        self.assertIsNone(row['left']); self.assertEqual(row['right'],'0')

    def test_missing_configuration_keeps_field_comparison_without_a_loading_claim(self):
        left,right=self.setup_mods(); a,b=inspect(left),inspect(right); self.config.unlink()
        result=compare_semantics(self.env,left.source,a,right.source,b,('item','item','shared'),[],[])
        self.assertTrue(result['changes']); self.assertEqual(result['loading']['status'],'limited')

    def test_configuration_changed_during_comparison_is_rejected(self):
        from unittest.mock import patch
        from mod_assistant.core import AssistantError
        import mod_assistant.xml_semantics as semantics
        left,right=self.setup_mods(); a,b=inspect(left),inspect(right); original=semantics.vanilla_definition
        def change(*args):
            result=original(*args); self.configure(['102','101']); return result
        with patch.object(semantics,'vanilla_definition',side_effect=change):
            with self.assertRaisesRegex(AssistantError,'期间变化'):
                compare_semantics(self.env,left.source,a,right.source,b,('item','item','shared'),[],['101','102'])
