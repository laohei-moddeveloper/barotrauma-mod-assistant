# Barotrauma Mod Assistant

Version **0.6.1** is a standalone mod manager for the Steam version of Barotrauma on **64-bit Windows**, with **English and Simplified Chinese** interfaces.

[Download](https://github.com/laohei-moddeveloper/barotrauma-mod-assistant/releases/latest) · [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3812360206&l=english) · [中文说明](使用说明.md)

## Install and choose a language

From GitHub: download the Windows ZIP, extract it, and run **BarotraumaModAssistant.exe**. Python is not required.

From the Workshop: subscribe and wait for Steam to download the item. If needed, open Barotrauma to its main menu to install Workshop content, then exit. Press Win+R and open:

```text
%LOCALAPPDATA%\Daedalic Entertainment GmbH\Barotrauma\WorkshopMods\Installed\3812360206
```

Run **Install-to-desktop.cmd** to create an English desktop shortcut, or copy **BarotraumaModAssistant.exe** to your own folder and run the copy. If the installed folder is missing, check `steamapps\workshop\content\602960\3812360206` in the Steam library where this item downloaded. The copied desktop program is in `%LOCALAPPDATA%\BarotraumaModAssistant\WorkshopProgram`.

The Workshop package delivers files. Do not enable it as a gameplay mod or require it on your server; it does not run automatically.

Use the **中文 / English** selector at the top of the window. Language changes apply immediately and are saved, including open dialogs, reports, and future messages. New users get Chinese on Chinese systems and English otherwise. Switching languages does not change mod names, enabled mods, load order, running tasks, or your current selection.

## Everyday use

1. Keep Steam signed in. Close the game and dedicated server before changing files, enabled mods, profiles, order, or LuaCs.
2. Wait for scanning. **Update** selects a mod for the task; **Enabled** controls whether the game loads it next time. These are separate choices.
3. Click **Update mods**. Defaults: 4 concurrent Workshop requests and 3 installations. Adjust these in **Settings & appearance**.
4. Open **Load order** for drag-and-drop, **Auto-sort**, before/after rules, and locked positions. Click **Save load order** to apply it on the next game launch.
5. Click **Launch game** when finished.

Use **Mods** for filtering, search, enabled state, order, and profiles. Use **Tools & scripts** for LuaCs, logs, cache installation, and exports. **Settings & appearance** has themes, colors, font size, list spacing, and update settings.

## Profiles, snapshots, and scripts

Profiles save the core package, enabled regular mods, order, installed versions, and available verified fingerprints. Review differences before applying. **Download & apply** can subscribe to missing Workshop items from a friend's list. Install local mods separately. Steam provides current versions, not historical versions from a shared list. Differences block switching by default unless you explicitly allow current local versions/files.

Snapshots keep independent copies of saved mod files and enabled configuration, using disk space. They restore only previously saved files and do not restore Steam subscriptions, original Steam cache, or the LuaCs client patch. LuaCs has its own pre-installation backup and restore action.

**Install LuaCs + enable C#** obtains a matching official Windows client patch, verifies it, backs up replaced files, and enables persistent C# scripting. This changes only your local client; other computers and dedicated servers need separate setup. Use trusted script mods and follow the post-install checklist. File checks do not confirm scripts work in game.

## Understand the results

Compatibility ratings and auto-sort are static analysis suggestions. They compare resource IDs, XML Overrides, readable Lua hooks, and C# method patches, but cannot fully predict compiled code, dynamic scripts, or runtime interactions. Follow mod authors' instructions and test in game. **Impact** means the scope of changes, not mod quality. The assistant does not repair mod code conflicts.

Steam controls actual downloads. Parallel requests, installations, and cache reuse cannot bypass Steam's queue, server limits, or your bandwidth. Accepted downloads may continue after stopping the assistant. Steam may show Barotrauma as running while the assistant uses its Workshop interface, without opening a game window.

While playing, light scanning uses cached analysis and defers deep scanning. Refresh after closing the game for current results. Process checks and installation protections stay active in both languages. Mod names, file paths, identifiers, and original third-party log excerpts retain their original language.

## Updates and feedback

Version 0.6.1 adds **Getting started & environment** in Settings and **LuaCs restore help** in Tools. Missing or damaged backups disable Restore and explain why. An existing LuaCs installation may have no assistant backup; reinstalling an already working runtime cannot recreate original files. A settings-only backup restores settings, not the pre-existing runtime. To remove the client patch, close the game and assistant, remove any auto-install command from Steam Launch Options, and verify game files in Steam. This restores original game files rather than the assistant's prior state. See the [LuaCs author's instructions](https://steamcommunity.com/sharedfiles/filedetails/?id=2559634234).

New users should launch the game to its main menu and exit once before scanning. An empty list with no subscribed mods is normal. Moved Steam installations are detected again when a saved game path is no longer valid. Invalid operation settings fall back to defaults or valid limits; malformed settings files are preserved separately before replacement. If preferences cannot be saved, the interface keeps working for the session and shows the storage status. Unwritable analysis caches keep the current results usable.

The mod list now updates changed rows instead of rewriting every row during progress. Scans avoid unnecessary texture file checks while retaining code/resource change detection. Repeated translations use a bounded cache. Temporary public-metadata failures reuse saved data with a one-minute retry delay; **Full reanalysis** refreshes metadata as well as local analysis when the service is available. These changes do not bypass Steam download limits.

After a Workshop update, close the assistant and rerun the desktop installer or replace the copied executable. Steam updates Workshop files, not the separate desktop copy. Unsubscribing does not remove your desktop copy or preferences. Use supplied SHA-256 checksums to verify downloaded release files.

When reporting a problem, include the version, reproduction steps, and exact error. Remove personal information from exported reports before sharing them. This community tool includes no base-game files, third-party mods, or credentials. The original cover was made with AI assistance.

## Development

Python 3.12; runtime uses the standard library. Run `python -m unittest discover -s tests -v`. Install `requirements-build.txt` into `.build-tools`, then run `build.ps1`. English copy lives in `mod_assistant/i18n_catalog.py`. Localization affects presentation; game configuration and mod identity remain unchanged.
