import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mod_assistant.core import (AssistantError, Cancelled, Environment, Installer,
                                InstallResult, atomic_json, load_package, parse_vdf,
                                validate_manifest, read_vdf)
from mod_assistant.engine import UpdateEngine


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="baro-assistant-test-")
        self.root = Path(self.temp.name)
        self.env = Environment(self.root / "steam", self.root / "game",
                               [self.root / "steam"], self.root / "player")
        self.env.game.mkdir()
        self.cancel = threading.Event()
        self.installer = Installer(self.env, lambda _: True, process_guard=lambda: False)
        self.source = self.package("101")

    def tearDown(self):
        self.temp.cleanup()

    def package(self, item, value="original"):
        folder = self.env.steam / "steamapps" / "workshop" / "content" / "602960" / item
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "items.xml").write_text(value, encoding="utf-8")
        (folder / "filelist.xml").write_text(
            f'<contentpackage name="Test {item}" steamworkshopid="{item}" '
            'modversion="1" gameversion="1.13.4.0" expectedhash="keep-original">'
            '<Item file="%ModDir%/items.xml" /></contentpackage>', encoding="utf-8")
        self.records()
        return folder

    def records(self, revision="v1", timestamp=1234):
        folder = self.env.steam / "steamapps" / "workshop"
        ids = [p.name for p in (folder / "content" / "602960").iterdir()]
        entries = "\n".join(f'"{i}" {{ "manifest" "{revision}" "timeupdated" "{timestamp}" "size" "100" }}' for i in ids)
        details = "\n".join(f'"{i}" {{ "latest_manifest" "{revision}" }}' for i in ids)
        (folder / "appworkshop_602960.acf").write_text(
            '"AppWorkshop" { "NeedsUpdate" "0" "NeedsDownload" "0" '
            f'"WorkshopItemsInstalled" {{ {entries} }} "WorkshopItemDetails" {{ {details} }} }}', encoding="utf-8")

    def install(self):
        return self.installer.install("101", self.source, 1234, self.cancel)


class InstallerTests(Fixture):
    def test_manifest_metadata_and_content_preserved(self):
        result = self.install()
        installed = self.env.installed / "101"
        self.assertEqual((installed / "items.xml").read_bytes(), (self.source / "items.xml").read_bytes())
        root = load_package(installed)
        self.assertEqual(root.get("installtime"), "1234")
        self.assertEqual(root.get("expectedhash"), "keep-original")
        self.assertEqual(result.copied, 2)

    def test_reuse_and_removed_files(self):
        self.install()
        target = self.env.installed / "101"
        (target / "removed.xml").write_text("old")
        result = self.install()
        self.assertEqual(result.reused, 1)
        self.assertFalse((target / "removed.xml").exists())
        self.assertTrue((Path(result.backup) / "removed.xml").exists())

    def test_missing_resource_preserves_previous(self):
        self.install()
        (self.source / "items.xml").unlink()
        with self.assertRaisesRegex(AssistantError, "缺少"):
            self.install()
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")

    def test_failure_between_renames_rolls_back(self):
        self.install()
        (self.source / "items.xml").write_text("new")
        def fail(phase):
            if phase == "after_old_moved":
                raise OSError("simulated switch failure")
        self.installer.fault = fail
        with self.assertRaises(OSError):
            self.install()
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")
        self.assertFalse(list((self.env.work / "transactions").glob("*.json")))

    def test_cache_revision_changes_preserve_previous(self):
        self.install()
        (self.source / "items.xml").write_text("new version")
        self.installer.fault = lambda phase: self.records("v2") if phase == "after_old_moved" else None
        with self.assertRaisesRegex(AssistantError, "Steam 更新"):
            self.install()
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")

    def test_source_mutation_detected(self):
        self.install()
        (self.source / "items.xml").write_text("new version")
        def mutate(stage, percent):
            if stage == "安装准备":
                (self.source / "items.xml").write_text("changed while staging")
        with self.assertRaisesRegex(AssistantError, "缓存版本"):
            self.installer.install("101", self.source, 1234, self.cancel, mutate)
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")

    def test_cancellation_and_running_game(self):
        self.cancel.set()
        with self.assertRaises(Cancelled):
            self.install()
        self.cancel.clear()
        self.installer.process_guard = lambda: True
        with self.assertRaisesRegex(AssistantError, "正在运行"):
            self.install()
        self.assertFalse((self.env.installed / "101").exists())

    def test_crash_journal_restores_previous(self):
        self.install()
        target = self.env.installed / "101"
        backup = self.env.work / "backups" / "101" / "crash"
        backup.parent.mkdir(parents=True)
        os.replace(target, backup)
        stage = self.env.work / "staging" / "101-crash"
        stage.mkdir()
        atomic_json(self.env.work / "transactions" / "101.json", {
            "id": "101", "target": str(target), "stage": str(stage),
            "backup": str(backup), "had_target": True, "phase": "old_moved"})
        self.assertTrue(self.installer.recover())
        self.assertEqual((target / "items.xml").read_text(), "original")
        self.assertFalse(stage.exists())

    def test_restore_previous_version(self):
        self.install()
        (self.source / "items.xml").write_text("new version")
        self.install()
        self.installer.restore("101")
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")
        self.assertFalse((self.env.work / "receipts" / "101.json").exists())

    def test_path_escape_rejected_and_named_self_supported(self):
        manifest = self.source / "filelist.xml"
        text = manifest.read_text().replace("%ModDir%", "%ModDir:Test 101%")
        manifest.write_text(text)
        self.assertEqual(validate_manifest(self.source, self.env), [])
        manifest.write_text(text.replace("%ModDir:Test 101%/items.xml", "%ModDir%/../../outside"))
        with self.assertRaisesRegex(AssistantError, "超出"):
            validate_manifest(self.source, self.env)

    def test_partial_copy_failure_leaves_old_directory(self):
        self.install()
        (self.source / "items.xml").write_text("new version")
        with patch("mod_assistant.core.shutil.copy2", side_effect=PermissionError("file locked")):
            with self.assertRaises(PermissionError):
                self.install()
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")

    def test_unchanged_install_skips_copy_and_backup(self):
        self.install()
        with patch("mod_assistant.core.shutil.copy2", side_effect=AssertionError("unnecessary copy")):
            result = self.install()
        self.assertTrue(result.unchanged)
        self.assertEqual(result.copied, 0)
        self.assertEqual(result.backup, "")

    def test_changed_installed_file_is_repaired(self):
        self.install()
        (self.env.installed / "101" / "items.xml").write_text("broken installed contents")
        result = self.install()
        self.assertFalse(result.unchanged)
        self.assertEqual((self.env.installed / "101" / "items.xml").read_text(), "original")


class FakeBridge:
    def __init__(self, env):
        self.env = env
        self.requests = []
        self.pending = {}
        self.pump_batches = []
        self.closed = False
        self.fail_once = set()
        self.ready_after = 0

    def connect(self): return self
    def close(self): self.closed = True
    def subscribed(self): return ["101", "102", "103", "104"]
    def request(self, item):
        self.requests.append(item)
        self.pending[item] = time.monotonic()
        return True
    def pump(self):
        self.pump_batches.append(list(self.pending))
        callbacks = {}
        for item, since in list(self.pending.items()):
            if time.monotonic() - since > .15:
                callbacks[item] = 3 if item in self.fail_once else 1
                self.fail_once.discard(item)
                del self.pending[item]
        return callbacks
    def ready(self, item): return time.monotonic() >= self.ready_after
    def progress(self, item): return (1, 2)
    def state(self, item): return 4
    def installation(self, item): return self.env.cache(item), 1234


class EngineTests(Fixture):
    def setUp(self):
        super().setUp()
        for item in ["102", "103", "104"]: self.package(item)
        self.bridge = FakeBridge(self.env)
        self.events = []
        self.engine = UpdateEngine(self.env, self.events.append, 4, 2,
                                  bridge_factory=lambda _: self.bridge, process_guard=lambda: False)

    def test_parallel_requests_and_installs_with_independent_failure(self):
        lock = threading.Lock()
        running = [0, 0]
        class SlowInstaller:
            def __init__(self, *args, **kwargs): pass
            def recover(self): return []
            def install(self, item, *args):
                with lock:
                    running[0] += 1
                    running[1] = max(running)
                time.sleep(.3)
                with lock: running[0] -= 1
                if item == "103": raise AssistantError("bad mod")
                return InstallResult(item, 1, 0, 10, "", "fingerprint")
        self.engine.installer_factory = SlowInstaller
        result = self.engine.run(["101", "102", "103", "104"])
        self.assertEqual(len(self.bridge.pump_batches[0]), 4)
        self.assertEqual(running[1], 2)
        self.assertEqual(len(result["completed"]), 3)
        self.assertEqual(result["errors"], {"103": "bad mod"})
        self.assertTrue(self.bridge.closed)

    def test_success_callback_remains_valid_until_ready(self):
        self.bridge.ready_after = time.monotonic() + .5
        result = self.engine.run(["101"])
        self.assertIn("101", result["completed"])

    def test_transient_network_error_retries(self):
        self.bridge.fail_once.add("101")
        result = self.engine.run(["101"])
        self.assertEqual(self.bridge.requests.count("101"), 2)
        self.assertIn("101", result["completed"])

    def test_cancel_does_not_submit_requests_and_records_all(self):
        self.engine.cancel.set()
        result = self.engine.run(["101", "102"])
        self.assertEqual(self.bridge.requests, [])
        self.assertEqual(set(result["errors"]), {"101", "102"})
        self.assertTrue(result["cancelled"])

    def test_unsubscribed_and_duplicate_ids(self):
        result = self.engine.run(["101", "101", "999"])
        self.assertEqual(self.bridge.requests.count("101"), 1)
        self.assertIn("999", result["errors"])

    def test_offline_uses_complete_cache(self):
        result = self.engine.run(["101", "102"], online=False)
        self.assertEqual(len(result["completed"]), 2)
        self.assertFalse(self.bridge.requests)


class VdfTests(unittest.TestCase):
    def test_steam_manifest_temporarily_locked(self):
        with patch.object(Path, "read_text", side_effect=[PermissionError("Steam commit"),
                   FileNotFoundError("Steam rename"), '"root" { "key" "value" }']) as reader:
            with patch("mod_assistant.core.time.sleep"):
                self.assertEqual(read_vdf(Path("appworkshop.acf")), {"root": {"key": "value"}})
            self.assertEqual(reader.call_count, 3)
    def test_empty_and_escaped_values(self):
        self.assertEqual(parse_vdf('"root" { "empty" "" "path" "D:\\\\steam" }'),
                         {"root": {"empty": "", "path": "D:\\steam"}})
    def test_partial_document_rejected(self):
        with self.assertRaises(AssistantError): parse_vdf('"root" { "key" "value"')


if __name__ == "__main__": unittest.main()
