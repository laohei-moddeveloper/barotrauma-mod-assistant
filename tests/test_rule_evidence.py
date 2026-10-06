import copy
from test_management import Fixture
from mod_assistant.core import AssistantError
from mod_assistant.mod_analysis import Features
from mod_assistant.mod_order import check_rules,suggest_order,validate_order


class RuleEvidenceTests(Fixture):
    def rule(self):
        return {'before':[['102','101']],'locks':[], 'evidence':[{'before':'102','after':'101',
                'method':'author','source':'https://example.com/author','reason':'Reviewed order',
                'checked_at':'2026-10-06','game_version':'1.13.4.0','versions':{'101':'1','102':'1'}}]}

    def test_applicable_and_outdated_scopes_have_different_results(self):
        mods={item:self.make(item) for item in ('101','102')}; features={item:Features(item,mod.name) for item,mod in mods.items()}
        before=self.config.read_bytes(); rules=self.rule()
        result=suggest_order(['101','102'],mods,features,rules,game_version='1.13.4.0')
        self.assertEqual(result.ids,['102','101']); self.assertEqual(result.evidence[0]['status'],'applicable')
        mods['102'].installed_version='2'
        result=suggest_order(['101','102'],mods,features,rules,game_version='1.13.4.0')
        self.assertEqual(result.ids,['101','102']); self.assertEqual(result.evidence[0]['status'],'stale')
        validate_order(['101','102'],['101','102'],rules,mods,'1.13.4.0')
        self.assertEqual(before,self.config.read_bytes())

    def test_unknown_game_version_does_not_apply_scoped_rule(self):
        mods={item:self.make(item) for item in ('101','102')}
        result=suggest_order(['101','102'],mods,{},self.rule())
        self.assertEqual(result.ids,['101','102']); self.assertEqual(result.evidence[0]['status'],'unknown')
        self.assertTrue(result.coverage)

    def test_legacy_manual_rules_are_preserved_but_not_certified(self):
        mods={item:self.make(item) for item in ('101','102')}
        result=suggest_order(['101','102'],mods,{}, {'before':[['102','101']]})
        self.assertEqual(result.ids,['102','101']); self.assertEqual(result.evidence[0]['status'],'unrecorded')

    def test_forged_duplicate_or_invalid_scope_is_rejected(self):
        for mutate in (lambda r:r['evidence'].append(copy.deepcopy(r['evidence'][0])),
                       lambda r:r['evidence'][0].update(versions={'999':'2'}),
                       lambda r:r['evidence'][0].update(checked_at='not a date'),
                       lambda r:r['evidence'][0].update(method='certified')):
            rules=self.rule(); mutate(rules)
            with self.assertRaises(AssistantError): check_rules(rules)

    def test_directory_references_do_not_invent_order_cycles_or_require_activation(self):
        from mod_assistant.mod_analysis import evaluate
        mods={item:self.make(item) for item in ('101','102')}; mods['102'].enabled=False
        features={'101':Features('101','Mod 101',path_dependencies={'102'}),
                  '102':Features('102','Mod 102',path_dependencies={'101'})}
        result=suggest_order(['101','102'],mods,features)
        self.assertEqual(result.ids,['101','102'])
        assessment=evaluate(list(mods.values()),features)['101']
        self.assertNotEqual(assessment.compatibility,'低·缺前置')

    def test_own_workshop_id_macro_is_a_local_resource_not_an_external_dependency(self):
        from mod_assistant.mod_analysis import inspect
        mod=self.make('101'); (mod.source/'filelist.xml').write_text('<contentpackage name="Mod 101"><Item file="%ModDir:101%/items.xml"/></contentpackage>')
        feature=inspect(mod)
        self.assertFalse(feature.partial); self.assertFalse(feature.path_dependencies)
        self.assertIn(('item','item','shared'),feature.definitions)
