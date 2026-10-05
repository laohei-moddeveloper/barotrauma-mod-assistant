# 0.9.0 reliability design / 可靠性修订

The detailed [Issue #1 report](https://github.com/laohei-moddeveloper/barotrauma-mod-assistant/issues/1), its supplied screenshots, the BMT repository, and the discussion text supplied by the project owner were reviewed. The goal is a small tool that makes ordinary mod-management work easier and makes failures understandable. A functional-looking button or a compatibility score is not evidence that it works.

## Seven areas and concrete behavior

| Area | Result | Boundary |
| --- | --- | --- |
| Configuration | Structural identification of core/regular sections; preserve other configuration bytes, comments and BOM. Native ModLists XML import/export and discovery; legacy JSON retained. Aliases, missing entries and ambiguous names checked. | No automatic preset application. Native XML has no version/hash history. Multiple custom cores are rejected rather than silently picking one. |
| Analysis | XML definition/Override and explicit dependency evidence. Read-only side-by-side definition view and text diff, with source filenames. | No Lua/C# regex compatibility grading or source execution. Script behavior stays unknown. A textual diff is not a semantic proof of the game's final result or a malware detector. |
| Backups | Shorter default root, recognizable payload names, open/copy/location controls, legacy discovery. Capture failure retains visible copies; restore validates hashes, all target locations and free space before changing live directories. | Incomplete or malformed manifests cannot restore automatically. Moving/editing payloads can invalidate verification. Backups consume real space and do not restore subscriptions or LuaCs. |
| Errors | Operation, version, error ID, actionable cause and local redacted traceback; per-item update errors accessible. Logs retain source, UTC modification time, encoding and byte offset; excerpt lines are labeled honestly. | No automatic upload. Redaction is limited to known paths/common fields; review arbitrary third-party text before sharing. Keyword matches are clues, not a crash root cause. |
| Permissions | A production Steam binding allowlist; centralized content-package edits and target-scoped transaction paths. Separate settings/runtime receipts. | No process enumeration/memory inspection, subscription changes, account credential handling, elevation or telemetry. A desktop program is not an OS sandbox. |
| LuaCs | Official patch download, SHA-256/size/game-version/location checks, backups, recovery, post-write verification. Installation preserves C#; enabling/disabling/restoring C# settings is separate. | No silent game launch or launch-option edits. C# mods have no sandbox. Files later changed by another writer block rollback/restore rather than being overwritten. |
| Sorting/UI | Main-toolbar preview, background calculation/cancel, changes and reasons, actual cycle chain, stable order and aliases. Focused comparison view and consistent control grids in both languages. | Preview is not applied automatically. Missing mods are not enabled/subscribed. Author rules and verified game behavior take precedence over assumptions. |

Implementation entry points: `game_config.py`, `native_profiles.py`, `profiles.py`, `mod_analysis.py`, `xml_compare.py`, `snapshots.py`, `operation_errors.py`, `diagnostics.py`, `steam.py`, `luacs.py`, `mod_order.py` and `author_rules.py`. Tests exercise behavior on fictional mod files rather than requiring Steam credentials.

## Learning from BMT without repeating its tradeoffs

[BMT's documented metadata format](https://github.com/themanyfaceddemon/Barotrauma_Modding_Tool/blob/1b581228f9a6014d8f7696f0b15ef3ae54958033/examples/metadata.xml/README.md) provides explicit dependency/patch/conflict declarations. The supplied discussion also describes parallel parsing, localized errors, path regressions and slow whole-drive discovery. Its later users specifically wanted to pinpoint overrides and compare the definitions for companion patches. Those are useful workflow lessons; old bug reports do not prove the current archived version has every defect.

BaroDock independently implements a **read-only subset**, without copying GPL source: `metadata/dependencies/{patch,requirement,requiredAnyOrder,conflict}`, identified by decimal `steamID` or unique name/alias. Following the documented format, `patch` is above its target and `requirement` is below; `requiredAnyOrder` checks presence without inventing priority. Conditions support `ifhas('name or ID')`, `&`, `|` and parentheses. Unknown conditions and ambiguous names are reported, not evaluated as Python or guessed. These declarations may be outdated, so reports identify their local source and ask users to verify versions.

This is **not full BMT compatibility**. Settings processing and `modparts.xml` are not implemented; mod source files are not rewritten. There is no whole-drive scan, automatic activation of dependencies, bundled code console, browser or authoring suite. Existing explicit rules, current override precedence where possible, locks and manual dragging remain reviewable. The definition comparison solves a concrete investigation task inside the existing analysis workflow.

## Official LuaCs updater decision

We reviewed the [official Luatrauma.AutoUpdater project](https://github.com/Luatrauma/Luatrauma.AutoUpdater), its published release and the inspected `Updater.cs`/`Program.cs`. It selects the official platform patch, compares DLL versions and copies extracted files into the current directory. In that inspected implementation, no complete pre-install backup/rollback transaction is provided, and some failures are logged before returning. Program completion alone would therefore not establish successful installation. It also supports launching a program after updating.

The decision for this release is to **keep a bounded BaroDock installer using the official patch**, rather than bundle and silently run the updater. The installer now preserves C# by default (including migration of an existing legacy runtime's explicit choice to the new setting format), requires a matching game version and official asset digest/size, rejects unreviewed file locations, keeps separate runtime/settings recovery records and verifies written hashes. This avoids another bundled runtime/executable while retaining the backup and failure behavior players need. The consent text identifies who supplies the patch and who implements the installer. No updater process, automatic game command or Steam launch option is installed. Users can use the official updater independently if they prefer.

This is an engineering tradeoff, not a criticism of trust or a claim our installer is universally safer. A changed official archive layout stops installation until reviewed. C# policy remains an informed separate choice, consistent with [LuaCs's unsandboxed C# documentation](https://luatrauma.github.io/Luatrauma.Docs/cs/introduction/). Security software must not be disabled to make an installation proceed.

## Format and recovery verification

[Barotrauma's ModListPreset reader/writer](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaClient/ClientSource/Steam/WorkshopMenu/Mutable/ModListPreset.cs) uses `<mods name>`, `Vanilla`, `Workshop id/name` and `Local name`. Tests independently inspect those fields, including core-first export, and apply imported order while retaining other game settings. Local names include the game's alternate-name concept. Missing core entries are reclassified from their installed content package when they later become available. Unlike the game reader's skip behavior, BaroDock preserves missing entries for pre-apply review.

Actual Windows C/D tests used disposable fictional game/mod folders: a game-local mod on D, a Workshop install on C, and backup roots separately on C and D. Restoration and interruption rollback passed. Staging, retained originals and discarded replacements use a target-local transaction directory; no directory rename crosses volumes. Deep Windows paths are handled without changing system settings. Malformed/failed manifests remain visible, old snapshot schemas stay discoverable, and unchanged ready snapshots may be reused.

Configuration changes have pre-change backups and concurrent-change checks. Transaction rollback verifies known hashes before overwriting; an unknown later modification blocks automatic recovery and retains evidence. This reduces damage but does not make concurrent external edits impossible. Close the game/server and avoid other tools changing the same files during a task.

The release does not claim actual in-game preset loading, script execution, multiplayer compatibility, or comprehensive hardware/environment coverage. Download speed remains controlled by Steam. The validation document and release manifest distinguish isolated checks, real multi-volume file operations, packaged UI checks and untested gameplay.

## 中文说明

本次七项改进不是仅换按钮或删除功能：原生清单互通、具体 XML 差异、可追溯的备份与恢复、能定位的错误、可审查的权限边界、保留 C# 选择的 LuaCs 安装以及可解释/可取消的排序均有对应实现和检查。

学习 BMT 的明确作者声明、覆盖定位、翻译校验和并行处理；避免全盘查找、偷偷启用前置、改写模组片段和无法解释的结论。不把“未发现 XML 重叠”当作脚本兼容证明，也不把截图中的旧主题错误当成已经解决其他故障的理由。感谢反馈者提供长文、链接和图片；仍请继续报告可复现的问题，尤其是我们没有覆盖的使用环境。
