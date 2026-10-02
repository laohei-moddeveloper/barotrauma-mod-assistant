from pathlib import Path
import tempfile
import unittest

from mod_assistant.core import AssistantError, Environment
from mod_assistant.mod_toggle import enabled_ids, local_id, set_enabled


class ToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = Environment(root / "steam", root / "game", [root / "steam"], root / "player")
        self.env.game.mkdir()
        self.config = self.env.game / "config_player.xml"
        self.original = (b'<?xml version="1.0" encoding="utf-8"?>\r\n'
            b'<config sensitive="keep"><graphics resolution="1920" />\r\n'
            b'  <contentpackages>\r\n'
            b'    <corepackage path="Content/ContentPackages/Vanilla.xml" />\r\n'
            b'    <regularpackages>\r\n'
            b'      <package path="LocalMods/Other/filelist.xml" />\r\n'
            b'    </regularpackages>\r\n'
            b'  </contentpackages><audio volume="77" /></config>')
        self.config.write_bytes(self.original)
        self.make_installed("101")

    def tearDown(self): self.temp.cleanup()

    def make_installed(self, item, core=False):
        folder = self.env.installed / item
        folder.mkdir(parents=True)
        (folder / "filelist.xml").write_text(
            f'<contentpackage name="Mod {item}" corepackage="{str(core).lower()}" />', encoding="utf-8")

    def test_enable_disable_preserves_unrelated_settings_and_order(self):
        r = set_enabled(self.env, "101", True, process_guard=lambda: False)
        self.assertTrue(r.changed)
        self.assertEqual(Path(r.backup).read_bytes(), self.original)
        self.assertEqual(enabled_ids(self.env), {"101"})
        changed = self.config.read_bytes()
        self.assertIn(b'LocalMods/Other/filelist.xml', changed)
        self.assertIn(b'<audio volume="77" />', changed)
        self.assertIn(b'<graphics resolution="1920" />', changed)
        self.assertLess(changed.index(b'LocalMods/Other'), changed.index(b'Installed/101'))
        self.assertFalse(set_enabled(self.env, "101", True, process_guard=lambda: False).changed)
        set_enabled(self.env, "101", False, process_guard=lambda: False)
        self.assertEqual(enabled_ids(self.env), set())
        self.assertIn(b'LocalMods/Other/filelist.xml', self.config.read_bytes())

    def test_core_switch_and_restore_vanilla(self):
        self.make_installed("202", core=True)
        set_enabled(self.env, "202", True, process_guard=lambda: False)
        self.assertEqual(enabled_ids(self.env), {"202"})
        self.assertIn(b'Installed/202/filelist.xml', self.config.read_bytes())
        set_enabled(self.env, "202", False, process_guard=lambda: False)
        self.assertEqual(enabled_ids(self.env), set())
        self.assertIn(b'Content/ContentPackages/Vanilla.xml', self.config.read_bytes())

    def test_open_game_and_missing_install_rejected(self):
        with self.assertRaisesRegex(AssistantError, "关闭游戏"):
            set_enabled(self.env, "101", True, process_guard=lambda: True)
        with self.assertRaisesRegex(AssistantError, "尚未安装"):
            set_enabled(self.env, "999", True, process_guard=lambda: False)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_game_started_before_commit_no_write(self):
        checks = iter([False, True])
        with self.assertRaisesRegex(AssistantError, "刚刚启动"):
            set_enabled(self.env, "101", True, process_guard=lambda: next(checks))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_bom_preserved(self):
        self.config.write_bytes(b'\xef\xbb\xbf' + self.original)
        set_enabled(self.env, "101", True, process_guard=lambda: False)
        self.assertTrue(self.config.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_local_mod_can_be_enabled_and_disabled(self):
        folder = self.env.game / "LocalMods" / "Chinese Patch"
        folder.mkdir(parents=True)
        (folder / "filelist.xml").write_text('<contentpackage name="Chinese Patch" />')
        item = local_id(folder)
        set_enabled(self.env, item, True, process_guard=lambda: False, source=folder)
        self.assertIn(item, enabled_ids(self.env))
        self.assertIn(b'LocalMods/Chinese Patch/filelist.xml', self.config.read_bytes())
        set_enabled(self.env, item, False, process_guard=lambda: False, source=folder)
        self.assertNotIn(item, enabled_ids(self.env))


if __name__ == "__main__": unittest.main()
