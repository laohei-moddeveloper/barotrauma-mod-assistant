from pathlib import Path
import tempfile
import unittest

from mod_assistant.core import AssistantError, Environment, Mod
from mod_assistant.mod_analysis import Features
from mod_assistant.mod_order import read_order, save_order, suggest_order


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = Environment(root / "steam", root / "game", [], root / "player")
        self.env.game.mkdir()
        for item in ("101", "102", "103"):
            folder = self.env.installed / item
            folder.mkdir(parents=True)
            (folder / "filelist.xml").write_text(f'<contentpackage name="{item}" />')
        self.config = self.env.game / "config_player.xml"
        self.original = (b'<config other="keep"><contentpackages>\r\n'
                         b'  <corepackage path="Content/ContentPackages/Vanilla.xml" />\r\n'
                         b'  <regularpackages>\r\n'
                         b'    <!-- Addon -->\r\n'
                         b'    <package path="WorkshopMods/Installed/103/filelist.xml" />\r\n'
                         b'    <!-- Base -->\r\n'
                         b'    <package path="WorkshopMods/Installed/101/filelist.xml" />\r\n'
                         b'    <package path="WorkshopMods/Installed/102/filelist.xml" />\r\n'
                         b'  </regularpackages>\r\n'
                         b'</contentpackages><audio volume="77" /></config>')
        self.config.write_bytes(self.original)

    def tearDown(self): self.temp.cleanup()

    def test_auto_order_respects_dependency_without_guessing_category_order(self):
        ids = ["103", "101", "102"]
        mods = {"101": Mod("101", "Base", self.env.installed / "101"),
                "102": Mod("102", "LuaCs", self.env.installed / "102"),
                "103": Mod("103", "Base 汉化补丁", self.env.installed / "103")}
        features = {"101": Features("101", "Base", kinds=("物品/装备",)),
                    "102": Features("102", "LuaCs", kinds=("框架/脚本",)),
                    "103": Features("103", "Base 汉化补丁", kinds=("语言/文本",),
                                    path_dependencies={"Base"})}
        result = suggest_order(ids, mods, features)
        self.assertEqual(result.ids, ["101", "103", "102"])
        self.assertIn("资源路径依赖", " ".join(result.reasons))

    def test_save_order_moves_comments_with_packages_and_keeps_other_settings(self):
        self.assertEqual(read_order(self.env), ["103", "101", "102"])
        backup = save_order(self.env, ["101", "103", "102"], process_guard=lambda: False)
        self.assertEqual(Path(backup).read_bytes(), self.original)
        self.assertEqual(read_order(self.env), ["101", "103", "102"])
        changed = self.config.read_bytes()
        self.assertIn(b'<audio volume="77" />', changed)
        self.assertLess(changed.index(b'<!-- Base -->'), changed.index(b'<!-- Addon -->'))
        self.assertFalse(save_order(self.env, ["101", "103", "102"], process_guard=lambda: False))

    def test_rejects_running_game_and_stale_selection(self):
        with self.assertRaisesRegex(AssistantError, "关闭游戏"):
            save_order(self.env, ["101", "102", "103"], process_guard=lambda: True)
        with self.assertRaisesRegex(AssistantError, "清单已经变化"):
            save_order(self.env, ["101", "102"], process_guard=lambda: False)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_overlap_precedence_is_not_reversed_by_type_guess(self):
        mods = {item: Mod(item, item, self.env.installed / item) for item in ("101", "102")}
        shared = {("item", "item", "wrench")}
        features = {"101": Features("101", "Base", definitions=shared),
                    "102": Features("102", "Patch", kinds=("补丁/调整",), definitions=shared)}
        result = suggest_order(["101", "102"], mods, features)
        self.assertEqual(result.ids, ["101", "102"])
        self.assertIn("覆盖优先级", " ".join(result.reasons))

    def test_dependency_cycles_rejected_without_writing_configuration(self):
        mods = {item: Mod(item, item, self.env.installed / item) for item in ("101", "102")}
        features = {"101": Features("101", "101", path_dependencies={"102"}),
                    "102": Features("102", "102", path_dependencies={"101"})}
        with self.assertRaisesRegex(AssistantError, "循环"):
            suggest_order(["101", "102"], mods, features)
        self.assertEqual(self.config.read_bytes(), self.original)


if __name__ == "__main__": unittest.main()
