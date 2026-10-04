# Community feedback and design decisions / 社区反馈与设计依据

Reviewed on 2026-10-04. These are primary project documents and firsthand user reports, not a claim that another tool still has every reported problem. BaroDock borrows workflow ideas, not code or RimWorld-specific loading rules. We do not execute downloads or instructions embedded in feedback.

| Source | Useful observation | BaroDock response |
| --- | --- | --- |
| [RimSort user report #406](https://github.com/RimSort/RimSort/issues/406), June 2024 | Lost download queues, overly exact search, missing Ctrl+C and startup warnings interrupt daily use. | 0.8.0: explicit resumable queue, multiword search, selected-name/ID copying and earlier local list. Missing configuration allows browsing instead of a blocking error. |
| [RimSort basic usage](https://rimsort.github.io/RimSort/user-guide/basic-usage) | Review active/inactive setups before saving and share mod lists. | 0.8.0 extends the existing order window with enabled-list drafts and undo/redo; existing profile import/export is retained. No additional main page. |
| [RimSort rule editor](https://rimsort.github.io/RimSort/user-guide/rule-editor) | Author, community and user rules have distinct origins and annotations. | Existing local rules are explainable and importable. A shared curated database is deferred until there are verified Barotrauma rules, provenance and version coverage. No empty service or automatic database downloads. |
| [RimPy autosorting](https://github.com/rimpy-custom/RimPy/wiki/Autosorting) and [rule-creation guidance](https://github.com/rimpy-custom/RimPy/wiki/How-To-Create-Load-Order-Rules-%28read-this-before-any-rules-creation%21%29) | Explicit rules require reproducible tests rather than assumptions about categories. | Preserve manual rules, current overlapping-definition order and author instructions. Future shared rules need game/mod versions, evidence and a reviewable source. |
| [Barotrauma Mod loader Workshop comments](https://steamcommunity.com/sharedfiles/filedetails/?id=3361544538), January 2025 | A player reported companion patches being sorted in an unexpected order; the author discussed gaps in metadata and manual sorting. | Do not infer patch precedence from names or broad types. Keep drag editing, locks, explicit before/after rules and a full explanation of suggestions. This report is not a verified rule for those current mod versions. |
| [Mod loader author's guide](https://steamcommunity.com/sharedfiles/filedetails/?id=3360663065) | Author-supplied dependency/patch/conflict metadata is preferable to guesses; platform installation difficulties also appear in comments. | Author metadata support remains a candidate, pending validation of IDs, semantics and version coverage. No automatic execution of metadata, new Python installation requirement or unsupported Linux promise. |
| [Barotrauma discussion #15753](https://github.com/FakeFishGames/Barotrauma/discussions/15753), initially game 1.7.7.0 | Affliction overrides have loading considerations that may differ from item overrides. | 0.8.0 suppresses the generic predicted winner for affliction overlaps and requests author/current-version checking. Mixed ordinary duplicates retain their stronger warning. This old-version discussion is not proof of a universal current loading rule. |
| [BaroBaro repository](https://github.com/Whth/BaroBaro) | Its README lists profiles, offline management and file differences as design ideas. | Use local-first browsing and current profiles. Unchecked README items are not treated as verified implemented features. No framework rewrite for feature parity. |
| [Valve ISteamUGC DownloadItem](https://partner.steamgames.com/doc/api/ISteamUGC#DownloadItem) | Steam owns scheduling; the high-priority option may pause other downloads, and download completion must be confirmed before using files. | Keep ordinary-priority requests and verified staging. Improved local preparation/installation is not a claimed network throughput improvement. |

## What is deliberately deferred

A community rule database, author metadata import and guided conflict testing could be useful, but need verified data and a compact workflow. They are not included in 0.8.0. Cross-platform packaging also needs separate testing. Embedded login browsers, SteamCMD management, cloud log upload, system watchers and texture conversion are outside this small release; the current access limits still apply.

This is development research, not an added background monitor. Future changes should be prioritized by reproducible reports from BaroDock users, with permission scope, UI cost, rollback behavior and meaningful regression checks considered before implementation. No promise to automatically reply to third-party comments.

## 中文说明

不只参考宣传功能，也读玩家实际遇到的问题：任务中断丢失、搜索太精确、提示挡住操作、配套补丁排序不正确及新用户安装困难。0.8.0 落实了任务记录与手动恢复、多关键词搜索、显式复制、提前显示清单和配置草稿。草稿仍用现有排序窗口，确认后一次保存，并支持撤销重做。

其他工具的评论是线索，不能直接当作当前潜渊症模组的可靠排序规则。社区数据库和作者元数据需要来源、版本及实测证据，因此暂不增加空壳功能或自动联网服务。保留用户要求的访问范围，不新增进程遍历、自动订阅、账号登录管理、遥测或管理员权限。
