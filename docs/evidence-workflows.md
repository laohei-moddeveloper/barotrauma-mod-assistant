# 0.10.0: order evidence, save matching and specific conflict investigation

Version 0.10.0 was approved for release on 2026-10-06. No new runtime dependency is required.

## Supported tasks

| User task | Concrete result | Verification boundary |
| --- | --- | --- |
| Keep a reviewed order rule useful after updates | A local rule can record its reason, source, date, game version and both installed mod versions. An out-of-scope or unreadable version suspends it with an explanation. | Exact declared versions, not proof of identical files or successful gameplay. Author/test records are supplied by the user, not automatically certified. |
| Continue an old campaign | Import accepts a selected `.save`, reads its real `gamesession.xml` entry, lists missing/ambiguous names and compares recorded order with saved presets. | A save records synced package names/order, not all client mods, Workshop IDs or historical files. Old formats without names are rejected with a usable alternative. |
| Prepare a reviewable preset | The user confirms ambiguous candidates, previews the core and regular order, and chooses whether to retain extra enabled items. Saving creates native ModLists XML. | No subscription or enabled-list changes. A separate local association records the save digest and filename; editing XML can invalidate this provenance without making the native list unusable. |
| See what two XML definitions actually declare | Field paths, left/right values, original baseline, source files, differing changes and repeated-child ambiguity. | Literal declarations are not runtime values. Only a small, reviewed set of Item fields has functional descriptions; unknown fields are not given invented meanings. |
| Identify an Item registration conflict | In the bounded 1.13.4.0 Item model, ordinary duplicates are identified and a whole-definition Override selection is shown in enabled order. | No Clear, inheritance, incomplete scan, multiple definitions per provider, custom core or unreviewed type/version is silently simulated. Constructor validation, assets and scripts are outside this model. |
| Locate a reported failure after playing | The selected/local game log's explicit duplicate message is connected to current matching XML files, identifiers and source paths. Logged source-line locations are distinguished from cause attribution. | Current XML may differ from the crash-time files. A path mention is not proof of sole responsibility; absent evidence is not filled in by a guessed mod name. |

## Where to use it

1. **Load order → Before/after rules → Record rule evidence**: select a relation, record its source and optional exact version scope. Preview shows scope status, reasons and unchecked items. Legacy JSON rules still work and are explicitly labeled manual. New export uses `barodock-order-rules-v2`.
   A directory macro is not a load-order edge or proof that its package must be enabled. The [game's ContentPath resolver](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/ContentManagement/ContentPath.cs) looks up all packages and substitutes their directories. This release corrects the previous inference, accepts own Workshop-ID macros, and invalidates the old analysis cache (schema 4).
2. **Profiles/multiplayer → Import list**: choose XML, JSON or a campaign `.save`. Save matching does not apply a preset. Review the generated list and use the existing native-list application workflow afterward.
3. **Mod analysis → XML comparison → Field changes and definition sources**: inspect exact declarations, Vanilla paths and enabled providers. Medical and other unmodeled content retain structural comparison rather than a guessed winner.
4. **Log diagnosis**: inspect a log from the session that reproduced the failure. Findings include original excerpt positions, matched current files and follow-up steps. A repeated-registration repair must remove/disable the ordinary duplicate or use an author solution that does so. Adding an extra Override while keeping both ordinary registrations does not solve it.

## Side effects and access

- Rule recording writes only local assistant rule data. Importing rules never applies game order.
- Save inspection streams the user-selected archive, hashes the compressed bytes actually read, validates the archive through EOF/CRC, and retains only its session XML. No archive entry is extracted to disk; names, expansion, entries, depth and node counts are bounded. Reading can be cancelled.
- Saving a reviewed result writes a new native XML file under the selected game's `ModLists`, plus association metadata under assistant state. It does not edit the campaign, existing presets, subscriptions or `config_player.xml`.
- XML investigation reads selected mod resources and the selected game's Vanilla content. Reads reject document types/entities and mod links; all definitions have size/structure limits. A report caches trees only within that operation.
- Log inspection reads at most the existing 4 MiB tail and does not execute log text or upload it. File/identifier matches are bounded local lookups, not C# source analysis.
- No administrator request, process enumeration, memory inspection, wallet/firewall checks, account keys, background sync or automatic game launch is added. These are code boundaries, not an OS sandbox.

## Loading model basis

The Item model was checked against `GenericPrefabFile`, `PrefabSelector` and `ItemFile`. `PrefabSelector` has a single ordinary base, a separate Override list sorted by package index, and selects one whole prefab. That does not merge the field edits of separate Overrides.

- [PrefabSelector snapshot](https://github.com/FakeFishGames/Barotrauma/blob/1fd2a51bbb1b44bac9ff3606f697bfa96142e7af/Barotrauma/BarotraumaShared/SharedSource/Prefabs/PrefabSelector.cs)
- [GenericPrefabFile](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/ContentManagement/ContentFile/GenericPrefabFile.cs)
- [Item field reading](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/Items/ItemPrefab.cs)
- [Campaign archive format](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/Utils/SaveUtil.cs)
- [Recorded package names](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/GameSession/GameSession.cs)

Functional descriptions currently cover Item health, maximum stack size, extra-cargo permission, tags and a single Price/baseprice declaration. They describe what the source reads, not complete economy, AI or combat behavior. Repeated unkeyed children are not treated as a reliable semantic correspondence.

## Issue #1 reread

The complete issue, its current comment and three original screenshots were reread on 2026-10-06. This review did not merely focus on the script-regex paragraph.

| Feedback concern | Current response and remaining boundary |
| --- | --- |
| Do what users do manually, more conveniently | Save matching finishes in a normal ModLists file. Existing preset and backup workflows remain; no extra main-window feature row. |
| Backup folders must be findable and useful | 0.9.0 already added visible locations, open/copy controls, shorter roots, failed copies and journaled restoration. Original sandbox/path failure is not claimed retested on the author's machine. Modified/missing manifests still require manual inspection; all folder edits cannot be promised automatically recoverable. |
| Use native ModLists | New save-based output defaults to native XML. JSON remains for older users and optional version evidence, not a replacement of the game's format. |
| Stop analysis the program cannot perform | Script execution/compatibility and maliciousness are not inferred from code regex. XML field facts and a specifically scoped registration model have explicit sources. Roslyn alone would not certify all dynamic behavior or safety, and is not added. |
| Optimize actual setup and conflict tasks | The preview connects rule expiry, campaign matching, concrete XML fields and a current logged identifier to the next actionable step. Tests use these workflows, not only button existence. |
| Logs should help explain real failures | Numeric occurrences are not assigned to mod IDs. Explicit errors can locate current files; missing information gets a request for the actual exception/stack and reproduction, not a fabricated culprit. |
| Mod analysis should identify dangerous mods | There is no malware certification. Static XML consistency, file verification and permissions documentation are separate from security review. The program does not execute scripts to investigate them. |
| Steam and file changes should be isolated/readable | Existing production Steam allowlist, central configuration commit and target-scoped transactions remain. New readers are separate modules; their writes are limited to reviewed presets and assistant evidence. |
| Official LuaCs updater should be assessed | The documented 0.9.0 official-patch/transaction tradeoff remains. This release changes status wording, not installer authority. Prompt/unreadable policy is no longer displayed as a confirmed disabled session. |
| Fix actions/errors before appearance | No new theme or branding system. Existing six-action manager layout is retained; nested bilingual dialogs and raw XML values are checked. |

## Validation meaning

`--evidence-check <report.json>` runs an explicit diagnostic with disposable fictional game/mod/save files and isolated assistant settings. It exercises packaged worker callbacks, version expiry, native save-associated export, field comparison and logged-identifier lookup in both languages. It does not connect Steam or launch a real game.

Unit/isolated checks and packaged checks do not establish successful real gameplay, all popular mod combinations, script compatibility or malware detection. Genuine game validation must record game/mod versions, starting preset, operation, observed result and the fresh log. Common-combination rules must not be labeled verified until that evidence exists.

## 中文说明

本版本改进排序依据、战役存档关联、具体 XML 字段与来源，并让运行日志能核对当前模组文件。它不会替用户运行被分析的脚本，也不会把静态模型包装成“全部兼容”或安全认证。

存档从原有“导入清单”入口打开；确认同名项目、预览核心包和顺序后，保存到游戏原生 ModLists。关联记录与文件摘要分开保存；存档和当前启用列表不变。

对已核实版本的普通 Item 重复定义，能明确指出注册冲突、文件和标识符；多个 Override 的模型选取的是整份定义，不会自动融合双方不同字段。清单顺序、实际构造与脚本运行是不同层次。日志里明确报告的同标识问题，会核对当前文件并提供可执行的处理及复现步骤。

0.10.0 已获所有者发布批准；测试结果与尚未验证的实际游戏场景分别记录。
