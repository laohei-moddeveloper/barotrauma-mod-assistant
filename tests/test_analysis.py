from pathlib import Path
import tempfile
import unittest

from mod_assistant.core import Mod
from mod_assistant.mod_analysis import Features, evaluate, inspect, pair_evidence


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def make_mod(self, item, name, identifiers=(), code="", enabled=False):
        folder = self.root / item
        folder.mkdir()
        (folder / "filelist.xml").write_text(
            f'<contentpackage name="{name}"><Item file="%ModDir%/items.xml" /></contentpackage>',
            encoding="utf-8")
        (folder / "items.xml").write_text(
            "<Items>" + "".join(f'<Item identifier="{value}" />' for value in identifiers) + "</Items>",
            encoding="utf-8")
        if code:
            (folder / "logic.lua").write_text(code, encoding="utf-8")
        return Mod(item, name, folder, enabled=enabled)

    def test_matching_script_strings_do_not_claim_execution_or_conflicts(self):
        a = self.make_mod("101", "A", code='Hook.Add("roundStart", "same", function() end)')
        b = self.make_mod("102", "B", code='Hook.Add("roundStart", "same", function() end)')
        features = {m.item_id: inspect(m) for m in (a, b)}
        self.assertEqual(pair_evidence(features["101"], features["102"])[0], 0)
        result = evaluate([a, b], features, runtime_luacs=True)
        self.assertEqual(result["101"].compatibility, "未知·脚本待核实")
        a.enabled = b.enabled = True
        result = evaluate([a, b], features, runtime_luacs=True)
        self.assertEqual(result["101"].compatibility, "未知·脚本待核实")

    def test_distinct_hook_names_on_same_event_are_not_marked_conflicting(self):
        a = self.make_mod("101", "A", code='Hook.Add("roundStart", "first", function() end)')
        b = self.make_mod("102", "B", code='Hook.Add("roundStart", "second", function() end)')
        features = {m.item_id: inspect(m) for m in (a, b)}
        self.assertEqual(pair_evidence(features["101"], features["102"])[0], 0)

    def test_shared_method_patch_and_xml_prefab_are_reported(self):
        a = self.make_mod("101", "A", ["duplicate_one", "duplicate_two"],
                          'Hook.Patch("Barotrauma.Character", "ApplyDamage", function() end)')
        b = self.make_mod("102", "B", ["duplicate_one", "duplicate_two"],
                          'Hook.Patch("Barotrauma.Character", "ApplyDamage", function() end)')
        features = {m.item_id: inspect(m) for m in (a, b)}
        score, reason = pair_evidence(features["101"], features["102"])
        self.assertEqual(score, 3)
        self.assertNotIn("applydamage", reason)
        self.assertIn("duplicate", reason)
        self.assertEqual(len(features["101"].definitions & features["102"].definitions), 2)

    def test_script_source_is_not_read_or_scored_as_behavior(self):
        from unittest.mock import patch
        mod = self.make_mod("101", "A", code=(
            'Hook.Patch("unique_patch_id", "Barotrauma.Character", "ApplyDamage", function() end)'))
        original=Path.read_text
        def read(path,*args,**kwargs):
            if path.suffix=='.lua': raise AssertionError('script source must not be read')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read): self.assertEqual(inspect(mod).code_files,1)

    def test_item_component_identifiers_do_not_create_false_prefab_collision(self):
        a = self.make_mod("101", "A", ["distinct_a"])
        b = self.make_mod("102", "B", ["distinct_b"])
        for mod in (a, b):
            (mod.source / "items.xml").write_text(
                f'<Items><Item identifier="{mod.item_id}"><SkillRequirementHint identifier="electrical" />'
                '</Item></Items>', encoding="utf-8")
        left, right = inspect(a), inspect(b)
        self.assertFalse(left.definitions & right.definitions)

    def test_publisher_dependency_and_script_runtime_are_separate_signals(self):
        a = self.make_mod("101", "A", code='-- Hook.Add("think", "ignored", noop)\nHook.Add("think", "real", noop)')
        b = self.make_mod("102", "B")
        features = {m.item_id: inspect(m) for m in (a, b)}
        self.assertEqual(features["101"].code_files,1)
        features["101"].workshop_dependencies.add("102")
        self.assertEqual(evaluate([a, b], features, runtime_luacs=True)["101"].compatibility, "低·缺前置")
        self.assertEqual(evaluate([a, b], features, runtime_luacs=False)["101"].compatibility, "低·缺前置")
        features['101'].workshop_dependencies.clear()
        self.assertEqual(evaluate([a,b],features,runtime_luacs=False)['101'].compatibility,'未知·脚本待核实')

    def test_commented_harmony_example_never_creates_method_conflict(self):
        mods=[self.make_mod(item,item) for item in ('101','102')]
        for mod in mods:
            (mod.source/'example.cs').write_text('/* [HarmonyPatch(typeof(ExampleOwner), "ExampleMethod")] */')
        features={mod.item_id:inspect(mod) for mod in mods}
        self.assertEqual(pair_evidence(features['101'],features['102'])[0],0)
        self.assertTrue(all(result.compatibility=='未知·脚本待核实' for result in evaluate(mods,features,True,csharp=True).values()))


if __name__ == "__main__": unittest.main()
