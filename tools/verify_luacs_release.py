"""Exercise the real official archive in a temporary game, never the live game."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mod_assistant.core import Environment, atomic_json
from mod_assistant.luacs import LuaCsInstaller, MODERN_SETTINGS, release_info, status

project = Path(__file__).resolve().parents[1]
archive = project / "Research/luacs-client-patch-inspect.zip"
info = release_info()
assert hashlib.sha256(archive.read_bytes()).hexdigest() == info["sha256"]
assert archive.stat().st_size == info["size"]

def fingerprint(folder):
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}

with tempfile.TemporaryDirectory(prefix="barotrauma-luacs-qa-") as directory:
    root = Path(directory)
    env = Environment(root / "steam", root / "game", [], root / "player")
    vanilla = env.game / "Content/ContentPackages/Vanilla.xml"
    vanilla.parent.mkdir(parents=True)
    vanilla.write_text('<contentpackage gameversion="1.13.4.0" />')
    (env.game / "Barotrauma.dll").write_bytes(b"original client fixture")
    (env.game / "DedicatedServer.dll").write_bytes(b"original server fixture")
    (env.game / "config_player.xml").write_bytes(b"unrelated settings remain unchanged")
    (env.game / "LuaCsSetupConfig.xml").write_text(
        '<LuaCsSetupConfig EnableCsScripting="false" HideUserNames="false" />')
    original = fingerprint(env.game)
    cached = env.work / "luacs/downloads" / (info["sha256"] + ".zip")
    cached.parent.mkdir(parents=True)
    shutil.copy2(archive, cached)
    installer = LuaCsInstaller(env, process_guard=lambda: False, release_loader=lambda: info)
    expected = installer.payload(cached)
    installed = installer.install()
    assert installed["changed"]
    assert all((env.game / name).read_bytes() == data for name, data in expected.items())
    assert status(env).runtime and status(env).csharp
    assert b'Value="Enabled"' in (env.game / MODERN_SETTINGS).read_bytes()
    assert not installer.install()["changed"]
    installer.restore()
    assert fingerprint(env.game) == original
    report = {"ok": True, "isolated_game": True, "live_game_modified": False,
              "official_asset": info["url"], "official_sha256": info["sha256"],
              "official_patch_files_verified": len(expected), "game_version": "1.13.4.0",
              "permanent_csharp": True, "already_ready_noop": True, "restore_exact": True}
    atomic_json(project / "Research/integration-luacs.json", report)
    print(report)
