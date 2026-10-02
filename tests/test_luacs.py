import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from mod_assistant.core import AssistantError, Environment
from mod_assistant.luacs import LuaCsInstaller, MODERN_SETTINGS, status


class LuaCsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = Environment(root / "steam", root / "game", [], root / "player")
        content = self.env.game / "Content/ContentPackages"
        content.mkdir(parents=True)
        (content / "Vanilla.xml").write_text('<contentpackage gameversion="1.13.4.0"/>')
        (self.env.game / "Barotrauma.dll").write_bytes(b"vanilla")
        self.make_patch()

    def tearDown(self): self.temp.cleanup()

    def make_patch(self, version="1.13.4.0", extra=None):
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            for name, data in {"Barotrauma.dll": b"LuaCs client",
                               "DedicatedServer.dll": b"LuaCs server",
                               "BarotraumaCore.dll": b"core",
                               "MoonSharp.Interpreter.dll": b"lua",
                               "Barotrauma.deps.json": ('{"Barotrauma/' + version + '":{}}').encode(),
                               **(extra or {})}.items():
                archive.writestr(name, data)
        self.archive = stream.getvalue()
        info = {"url": "https://github.com/evilfactory/LuaCsForBarotrauma/releases/download/latest/patch.zip",
                "size": len(self.archive), "sha256": hashlib.sha256(self.archive).hexdigest()}
        self.installer = LuaCsInstaller(self.env, process_guard=lambda: False,
                                       release_loader=lambda: info,
                                       opener=lambda *args, **kwargs: io.BytesIO(self.archive))

    def test_install_enable_cs_and_restore_original_files(self):
        result = self.installer.install()
        self.assertTrue(result["changed"])
        self.assertTrue(status(self.env).runtime)
        self.assertTrue(status(self.env).csharp)
        self.assertIn(b'Value="Enabled"', (self.env.game / MODERN_SETTINGS).read_bytes())
        self.assertFalse(self.installer.install()["changed"])
        self.installer.restore()
        self.assertEqual((self.env.game / "Barotrauma.dll").read_bytes(), b"vanilla")
        self.assertFalse((self.env.game / "LuaCsSetupConfig.xml").exists())

    def test_version_mismatch_does_not_modify_game(self):
        self.make_patch(version="1.12.0.0")
        with self.assertRaisesRegex(AssistantError, "版本不一致"):
            self.installer.install()
        self.assertEqual((self.env.game / "Barotrauma.dll").read_bytes(), b"vanilla")

    def test_checksum_and_unsafe_archive_rejected(self):
        info = self.installer.release_loader()
        info["sha256"] = "0" * 64
        with self.assertRaisesRegex(AssistantError, "校验失败"):
            self.installer.install()
        self.make_patch(extra={"../outside.dll": b"bad"})
        with self.assertRaisesRegex(AssistantError, "不安全"):
            self.installer.install()

    def test_failed_install_rolls_back(self):
        self.installer.fault = lambda phase: (_ for _ in ()).throw(OSError("file locked"))
        with self.assertRaisesRegex(OSError, "file locked"):
            self.installer.install()
        self.assertEqual((self.env.game / "Barotrauma.dll").read_bytes(), b"vanilla")

    def test_interrupted_install_recovers_next_time(self):
        self.installer.fault = lambda phase: (_ for _ in ()).throw(SystemExit("crash"))
        with self.assertRaises(SystemExit):
            self.installer.install()
        self.installer.recover()
        self.assertEqual((self.env.game / "Barotrauma.dll").read_bytes(), b"vanilla")

    def test_existing_runtime_only_enables_cs_preserving_options(self):
        (self.env.game / "Barotrauma.dll").write_bytes(b"LuaCs already installed")
        for name in ("BarotraumaCore.dll", "MoonSharp.Interpreter.dll"):
            (self.env.game / name).write_bytes(b"existing")
        (self.env.game / "LuaCsSetupConfig.xml").write_text(
            '<LuaCsSetupConfig EnableCsScripting="false" HideUserNames="false" />')
        self.installer.release_loader = lambda: self.fail("should not download")
        self.installer.install()
        self.assertTrue(status(self.env).csharp)
        self.assertIn(b'HideUserNames="false"', (self.env.game / "LuaCsSetupConfig.xml").read_bytes())

    def test_running_game_rejects_before_network(self):
        self.installer.process_guard = lambda: True
        self.installer.release_loader = lambda: self.fail("should not download")
        with self.assertRaisesRegex(AssistantError, "关闭游戏"):
            self.installer.install()

    def test_modern_policy_takes_precedence_over_stale_legacy_setting(self):
        (self.env.game / "Barotrauma.dll").write_bytes(b"LuaCs CsRunPolicy")
        for name in ("BarotraumaCore.dll", "MoonSharp.Interpreter.dll"):
            (self.env.game / name).write_bytes(b"existing")
        (self.env.game / "LuaCsSetupConfig.xml").write_text('<LuaCsSetupConfig EnableCsScripting="true"/>')
        path = self.env.game / MODERN_SETTINGS
        path.parent.mkdir(parents=True)
        path.write_text('<Configuration><LuaCsForBarotrauma><CsRunPolicy Value="Prompt"/>'
                        '<UseCaching Value="false"/></LuaCsForBarotrauma></Configuration>')
        self.assertFalse(status(self.env).csharp)
        self.installer.install()
        self.assertTrue(status(self.env).csharp)
        self.assertIn(b'UseCaching Value="false"', path.read_bytes())


if __name__ == "__main__": unittest.main()
