from test_management import Fixture
from mod_assistant.diagnostics import diagnose
from mod_assistant.mod_analysis import inspect


class RuntimeEvidenceTests(Fixture):
    def test_logged_duplicate_is_linked_to_actual_files_and_a_repair_plan(self):
        mods=[self.make('101'),self.make('102')]; features={mod.item_id:inspect(mod) for mod in mods}
        path=self.env.game/'crash.log'
        path.write_text('Failed to add the prefab "shared" (Barotrauma.ItemPrefab) from "Mod 101": a prefab with the same identifier from "Mod 102" already exists; try overriding\n')
        result=diagnose(path,mods,self.env,features); finding=result['findings'][0]
        locations=[row for row in finding['locations'] if row.get('identifier')=='shared']
        self.assertEqual({row['mod_id'] for row in locations},{'101','102'}); self.assertTrue(all(row['file']=='items.xml' for row in locations))
        self.assertTrue(any('两份普通定义' in step and '不能' in step for step in finding['steps']))

    def test_unrelated_number_is_not_a_mod_attribution(self):
        path=self.env.game/'crash.log'; path.write_text('Exception after 101 rounds\n')
        result=diagnose(path,[self.make('101')],self.env)
        self.assertFalse(result['findings'][0]['possible_mods']); self.assertFalse(result['findings'][0]['locations'])

    def test_old_log_identifier_cannot_point_to_a_changed_definition(self):
        mod=self.make('101'); feature=inspect(mod); (mod.source/'items.xml').write_text('<Items><Item identifier="different"/></Items>')
        path=self.env.game/'crash.log'; path.write_text('Failed to add the prefab "shared" (Barotrauma.ItemPrefab) from "Mod 101": a prefab with the same identifier already exists\n')
        finding=diagnose(path,[mod],self.env,{mod.item_id:feature})['findings'][0]
        self.assertFalse([row for row in finding['locations'] if row.get('identifier')])
