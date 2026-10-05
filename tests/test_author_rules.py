import threading
import unittest
from test_management import Fixture
from mod_assistant.author_rules import condition_value
from mod_assistant.core import AssistantError, Cancelled, Mod
from mod_assistant.mod_analysis import Features, inspect, evaluate
from mod_assistant.mod_order import suggest_order


class AuthorRuleTests(Fixture):
    def test_declared_patch_and_requirement_preview_without_automatic_enable_or_writes(self):
        mods={item:self.make(item) for item in ('101','102')}
        before=self.config.read_bytes()
        (mods['101'].source/'metadata.xml').write_text('<metadata><dependencies><requirement steamID="102"/><requiredAnyOrder steamID="999"/></dependencies></metadata>')
        features={item:inspect(mod) for item,mod in mods.items()}
        result=suggest_order(['101','102'],mods,features)
        self.assertEqual(result.ids,['102','101']); self.assertTrue(result.movements)
        self.assertTrue(any('metadata.xml' in reason for reason in result.reasons))
        self.assertEqual(before,self.config.read_bytes()); self.assertEqual(set(result.ids),set(mods))
        self.assertEqual(evaluate(list(mods.values()),features,True)['101'].compatibility,'低·缺前置')

    def test_safe_boolean_conditions_and_unknown_grammar_or_names(self):
        self.assertTrue(condition_value("ifhas('101') & (ifhas('absent') | ifhas('A'))",{'101','a'}))
        self.assertFalse(condition_value("ifhas('absent') & ifhas('A')",{'a'}))
        self.assertIsNone(condition_value("ifhas('A')",{'a'},{'a'}))
        for value in ("__import__('os')", "ifhas('A') unknown", '(' * 30+"ifhas('A')"+')'*30):
            self.assertIsNone(condition_value(value,{'a'}))
        mods={item:self.make(item) for item in ('101','102')}
        (mods['101'].source/'metadata.xml').write_text('<metadata><dependencies><requirement steamID="102" condition="ifhas(\'absent\')"/></dependencies></metadata>')
        result=suggest_order(['101','102'],mods,{item:inspect(mod) for item,mod in mods.items()})
        self.assertEqual(result.ids,['101','102'])

    def test_duplicate_names_not_arbitrarily_chosen_and_cycle_contains_chain(self):
        mods={item:Mod(item,'Same' if item!='103' else 'Dependent',None) for item in ('101','102','103')}
        feature=Features('103','Dependent',path_dependencies={'Same'})
        result=suggest_order(['103','102','101'],mods,{'103':feature})
        self.assertEqual(result.ids,['103','102','101']); self.assertTrue(any('同名' in x for x in result.reasons))
        with self.assertRaises(AssistantError) as error:
            suggest_order(['101','102','103'],mods,{}, {'before':[['101','102'],['102','103'],['103','101']]})
        self.assertIn('循环',str(error.exception))
        for item in mods: self.assertIn('['+item+']',str(error.exception))
        self.assertIn('自定义规则',str(error.exception))

    def test_conflict_declaration_and_invalid_metadata_are_visible(self):
        mods=[self.make('101'),self.make('102')]
        (mods[0].source/'metadata.xml').write_text('<metadata><dependencies><conflict steamID="102"/></dependencies></metadata>')
        features={mod.item_id:inspect(mod) for mod in mods}
        self.assertEqual(evaluate(mods,features,True)['101'].compatibility,'低·声明冲突')
        (mods[0].source/'metadata.xml').write_text('<!DOCTYPE metadata><metadata/>')
        self.assertTrue(inspect(mods[0]).rule_notes)

    def test_cancelled_large_preview_and_sparse_definitions_preserve_draft(self):
        ids=[str(n) for n in range(1,1501)]; mods={item:Mod(item,item,None) for item in ids}
        features={item:Features(item,item,definitions={('item','item','shared')}) for item in ids}
        result=suggest_order(ids,mods,features)
        self.assertEqual(result.ids,ids); self.assertLess(len(result.reasons),1600)
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): suggest_order(ids,mods,features,cancel=cancel)
        self.assertEqual(ids[0],'1')
