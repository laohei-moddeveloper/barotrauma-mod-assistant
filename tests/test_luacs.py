import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from mod_assistant.core import AssistantError, Environment
from mod_assistant.luacs import LuaCsInstaller, MODERN_SETTINGS, status, restore_info


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
        result = self.installer.install(enable_csharp=True)
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

    def test_archive_cannot_add_unreviewed_files_elsewhere_in_game_folder(self):
        self.make_patch(extra={'UnrelatedTool.exe':b'not part of the approved patch'})
        with self.assertRaisesRegex(AssistantError,'尚未审核'): self.installer.install()
        self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),b'vanilla')
        self.assertFalse((self.env.game/'UnrelatedTool.exe').exists())

    def test_post_write_changes_are_reported_without_overwriting_unknown_bytes(self):
        def modify(phase):
            if phase=='replaced': (self.env.game/'Barotrauma.dll').write_bytes(b'changed by another writer')
        self.installer.fault=modify
        with self.assertRaises(AssistantError): self.installer.install()
        self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),b'changed by another writer')
        self.assertFalse((self.env.work/'luacs/last-install.json').exists())
        self.assertTrue(list((self.env.work/'luacs/backups').glob('*/Barotrauma.dll')))

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
        self.installer.set_csharp(True)
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
        self.installer.set_csharp(True)
        self.assertTrue(status(self.env).csharp)
        self.assertIn(b'UseCaching Value="false"', path.read_bytes())

    def test_runtime_install_does_not_enable_or_replace_existing_csharp_policy(self):
        self.make_patch(extra={'LuaCsSetupConfig.xml':b'<LuaCsSetupConfig EnableCsScripting="true"/>'})
        settings=self.env.game/'LuaCsSetupConfig.xml'
        original=b'<LuaCsSetupConfig EnableCsScripting="false" HideUserNames="false"/>'
        settings.write_bytes(original)
        self.installer.install()
        self.assertTrue(status(self.env).runtime); self.assertFalse(status(self.env).csharp)
        self.assertEqual(settings.read_bytes(),original)
        self.assertFalse((self.env.game/MODERN_SETTINGS).exists())

    def test_separate_csharp_switch_never_downloads_and_retains_runtime_backup(self):
        import json
        result=self.installer.install(); original_receipt=(self.env.work/'luacs/last-install.json').read_bytes()
        self.installer.release_loader=lambda:self.fail('C# settings must not download')
        self.installer.set_csharp(True); self.assertTrue(status(self.env).csharp)
        self.assertEqual(original_receipt,(self.env.work/'luacs/last-install.json').read_bytes())
        receipt=json.loads((self.env.work/'luacs/last-csharp.json').read_text())
        self.assertEqual({entry['name'] for entry in receipt['records']},{'LuaCsSetupConfig.xml',MODERN_SETTINGS})
        self.installer.set_csharp(False); self.assertFalse(status(self.env).csharp)
        self.installer.restore(); self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),b'vanilla')

    def test_legacy_runtime_upgrade_preserves_effective_csharp_choice_and_restores(self):
        for enabled in (True,False):
            with self.subTest(enabled=enabled):
                (self.env.game/'Barotrauma.dll').write_bytes(b'LuaCs legacy client')
                for name in ('BarotraumaCore.dll','MoonSharp.Interpreter.dll'):
                    (self.env.game/name).write_bytes(b'legacy dependency')
                legacy=self.env.game/'LuaCsSetupConfig.xml'
                original=('<LuaCsSetupConfig EnableCsScripting="'+str(enabled).lower()+'" HideUserNames="false"/>').encode()
                legacy.write_bytes(original)
                modern=self.env.game/MODERN_SETTINGS
                self.assertFalse(modern.exists())
                self.make_patch(extra={'Barotrauma.dll':b'LuaCs CsRunPolicy modern client'})
                self.installer.install(refresh=True)
                self.assertEqual(status(self.env).csharp,enabled)
                self.assertEqual(legacy.read_bytes(),original)
                self.assertIn(b'Enabled' if enabled else b'Disabled',modern.read_bytes())
                self.installer.restore('runtime')
                self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),b'LuaCs legacy client')
                self.assertFalse(modern.exists())

    def test_csharp_switch_requires_installed_runtime_and_rolls_back_failure(self):
        with self.assertRaisesRegex(AssistantError,'先安装'): self.installer.set_csharp(True)
        self.installer.install(); assembly=(self.env.game/'Barotrauma.dll').read_bytes()
        self.installer.fault=lambda phase:(_ for _ in ()).throw(OSError('settings write failure'))
        with self.assertRaises(OSError): self.installer.set_csharp(True)
        self.assertFalse(status(self.env).csharp); self.assertEqual(assembly,(self.env.game/'Barotrauma.dll').read_bytes())

    def test_existing_ready_runtime_has_no_invented_original_backup(self):
        (self.env.game/'Barotrauma.dll').write_bytes(b'LuaCs already installed')
        for name in ('BarotraumaCore.dll','MoonSharp.Interpreter.dll'):
            (self.env.game/name).write_bytes(b'existing')
        (self.env.game/'LuaCsSetupConfig.xml').write_text('<LuaCsSetupConfig EnableCsScripting="true"/>')
        self.installer.release_loader=lambda:self.fail('must not redownload')
        self.assertFalse(self.installer.install()['changed'])
        self.assertFalse(restore_info(self.env).available)
        with self.assertRaisesRegex(AssistantError,'没有助手安装备份'):self.installer.restore()
        self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),b'LuaCs already installed')

    def test_restore_scope_and_already_restored_state(self):
        self.installer.install()
        self.assertIn('完整安装备份',restore_info(self.env).text)
        self.installer.restore()
        self.assertFalse(restore_info(self.env).available)
        self.assertIn('已经恢复',restore_info(self.env).text)
        for name,data in [('Barotrauma.dll',b'LuaCs previously installed'),('BarotraumaCore.dll',b'core'),('MoonSharp.Interpreter.dll',b'lua')]:
            (self.env.game/name).write_bytes(data)
        self.installer.set_csharp(True)
        self.assertIn('设置备份',restore_info(self.env,'csharp').text)
        self.assertFalse(restore_info(self.env).available)
        self.installer.restore('csharp')
        self.assertTrue(status(self.env).runtime)
        self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),b'LuaCs previously installed')

    def test_damaged_or_missing_backup_never_changes_game_files(self):
        import json
        self.installer.install()
        path=self.env.work/'luacs/last-install.json'
        journal=json.loads(path.read_text())
        old=(self.env.game/'Barotrauma.dll').read_bytes()
        for data in [[],{'state':'complete','records':None,'backup':journal['backup']},
                     {**journal,'backup':str(self.env.game)}, {**journal,'records':[{'name':'../escape'}]}]:
            path.write_text(json.dumps(data))
            self.assertFalse(restore_info(self.env).available)
            with self.assertRaises(AssistantError):self.installer.restore()
            self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),old)
        path.write_text(json.dumps(journal))
        (Path(journal['backup'])/'Barotrauma.dll').unlink()
        self.assertFalse(restore_info(self.env).available)
        with self.assertRaises(AssistantError):self.installer.restore()
        self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),old)


    def test_restore_stops_if_game_starts_before_first_replacement(self):
        self.installer.install()
        original=(self.env.game/'Barotrauma.dll').read_bytes()
        checks=iter([False,True])
        self.installer.process_guard=lambda:next(checks,True)
        with self.assertRaisesRegex(AssistantError,'关闭游戏'):self.installer.restore()
        self.assertEqual((self.env.game/'Barotrauma.dll').read_bytes(),original)
        self.assertTrue(restore_info(self.env).available)

if __name__ == "__main__": unittest.main()
