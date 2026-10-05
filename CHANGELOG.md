# 版本记录

## 0.9.0

This revision follows the detailed report in [Issue #1](https://github.com/laohei-moddeveloper/barotrauma-mod-assistant/issues/1) and the BMT workflow discussion.

- Read/write game-native ModLists XML; retain legacy JSON, missing entries and ambiguous-name warnings. Handle valid empty/self-closing configuration without rewriting unrelated settings.
- Remove Lua/C# regex compatibility scoring. Keep XML and explicit dependency evidence; scripts remain unverified. Add read-only XML definition comparison and text differences.
- Make failed backups visible, with navigable names, open/copy/custom-location controls and legacy backup discovery. Stage restores on each target volume, check integrity/space, retain pre-restore files and recover incomplete transactions.
- Add local error ID, operation, version, cause and redacted traceback; preserve log source/time/encoding and honest excerpt line numbers. No automatic upload.
- Restrict production Steam bindings to the required read/download interfaces. No process inventory, subscription changes, elevation or new runtime dependency.
- Separate LuaCs installation/update from C# permission and settings recovery. Preserve C# by default; verify official patch hashes, size, version, file locations and post-write hashes. The official AutoUpdater was reviewed; see [decision and limits](docs/reliability-design.md).
- Put Auto-sort preview in the main toolbar; background computation/cancel, position changes/reasons, actual cycle chains, aliases and ambiguity checks. Support a bounded read-only subset of BMT metadata.xml declarations. Never auto-enable missing dependencies or edit mod parts.

验证：205 项单元/隔离检查通过；实际 C/D 跨盘备份恢复、失败回滚及两种备份磁盘位置通过。中英文、三种主题、打包界面及全新状态检查另记录在发布清单。

Limitations: static findings are not gameplay compatibility or malware detection. No real in-game preset loading, multiplayer session or broad hardware test was completed. Steam controls downloads. This ordinary desktop application is not an OS sandbox; C# mods are not sandboxed. Read the included guides and access document before changing files.

中文：七项修订落实原生清单、证据分析、备份可追溯、错误定位、权限边界、LuaCs/C# 分离与排序预览。具体用法见使用说明；感谢社区认真指出缺陷。

## 0.8.1

Selecting a theme from the actual dropdown could show `can't read "PY_VAR11": no such variable`. The dropdown callback executes within a Tcl procedure, while Tkinter's control variables are global. Localization now reads those variables from global scope, so theme, font and density selections complete normally.

The regression check invokes the same Tcl selection procedure as the UI, in Chinese and English, across all three themes and the font/density dropdowns. It checks saved preferences and confirms that game configuration bytes stay unchanged. Packaged self-checks now exercise the real theme dropdown callbacks without saving temporary diagnostic choices.

The access scope and runtime dependencies remain unchanged. The Workshop introduction is more concise in both languages, with installation and access explanations near the top. A free, local, bilingual demonstration uses fictional data and explicitly edited steps; it is not a download benchmark or a compatibility guarantee.

After the Workshop update, close the old tool and rerun the desktop installer, or replace your copied executable. Existing settings remain compatible.

中文：修复从主题下拉菜单切换时出现的变量报错。新增真实下拉回调检查，覆盖中英文、三种主题、字号和列表密度，并确认偏好保存及游戏配置不变；打包自检也检查实际下拉回调。权限范围和运行依赖不变。更新后请退出旧助手，重新运行桌面安装入口。

## 0.8.0

Updates can be interrupted, first-time users may have no game configuration, and editing several enabled mods used to require separate saves. This release makes the local list available before analysis, preserves unfinished update targets and adds one reviewable enabled-list/order draft.

- **Browse earlier:** read each Workshop manifest once; fill types progressively and compare only potentially overlapping mods. Missing/invalid game configuration allows read-only browsing, with Enabled shown as Unknown.
- **Explicit resume:** More actions → Resume unfinished updates continues remaining items from one local checkpoint, explaining online access again. No automatic task/network restart.
- **Configuration draft:** add installed regular mods, disable selected entries, drag or auto-sort, undo/redo and Apply draft. Back up and save once; refuse application if the game starts or the configuration changes. Core package is preserved; rules/locks are saved separately.
- **Everyday controls:** multiword search and Ctrl+C to copy selected mod names/IDs. No clipboard reads.
- **Honest compatibility:** no-overlap results still need testing. Affliction Overrides do not infer a winner from list position alone; ordinary duplicate warnings are retained.
- **Lean and scoped:** no added runtime dependencies, process enumeration, subscription changes, telemetry or administrator requests. Local task storage and explicit clipboard writes are documented in ACCESS_AND_PRIVACY.md.

Validation: 155 unit/isolated checks, packaged Chinese/English and three-theme self-checks, isolated screenshot/layout checks and both desktop installers. A clean Windows CI job runs the same isolated checks without Steam, the game or user accounts. See docs/validation.md for recorded results and limits. Static findings are not proof of gameplay or multiplayer compatibility, and local speed improvements do not bypass Steam download scheduling.

After a Workshop update, close the tool and rerun the desktop installer or replace your copied EXE. The executable/settings paths, repository URL and existing rule schema remain compatible. No base-game files or third-party mods are distributed.

中文：提前显示清单，未生成有效游戏配置也可只读浏览；中断后从「更多操作」明确继续未完成更新；加载顺序增加配置草稿、添加/禁用及撤销重做，确认后一次保存。支持多关键词搜索和 Ctrl+C 复制名称/编号，兼容提示更谨慎。保留访问范围限制，无新增运行依赖。工坊下载完成后请退出旧助手，重新运行桌面安装入口。


## 0.7.1

BaroPy is now **BaroDock**, with matching Chinese/English Workshop titles, application headings, access reports, guides, desktop shortcuts, screenshots and animated cover. This is the same standalone Barotrauma mod manager. The access restrictions and sorting improvements released in 0.7.0 remain in place.

The executable name, preferences directory, repository URL and existing JSON rule schema are retained for upgrade compatibility. Existing exported rules continue to work. The desktop installer renames an old BaroPy shortcut only if it points to this tool and the new shortcut does not already exist; unrelated shortcuts are retained.

After Steam downloads the update, close the old tool and run the desktop installer again. Chinese and English guides, access notes and SHA-256 checksums are included. Validation: 133 existing unit/isolated checks, packaged bilingual and three-theme checks, screenshot/layout checks and both desktop installers. This branding update does not add broader access or gameplay changes.

中文：BaroPy 正式更名为 BaroDock，统一程序、工坊双语标题、指南、桌面入口和动态封面。保留程序文件名、设置目录、仓库链接及规则格式，老用户升级无需重新配置。访问范围限制和排序改进沿用 0.7.0。


## 0.7.0

Community feedback identified unnecessary system access. This release removes system-wide process enumeration and automatic subscription operations, makes startup/Refresh local by default, explains online/LuaCs access before actions, and includes a bilingual access report and document. Ordinary desktop application; not an OS sandbox.

Sorting now preserves existing order where possible instead of guessing from categories/names. Added full sorting reasons and validated local JSON rule import/export. Inspired by RimPy's explicit-rule approach; no RimWorld-specific rules copied.

New BaroPy branding, bilingual short Workshop titles and a functional animated English cover. Existing executable/settings paths are retained for upgrade compatibility. Re-run the Workshop desktop installer after Steam downloads the update.

Validation: 133 unit/isolated tests; packaged bilingual UI and three-theme checks; fictional screenshots; scoped Windows file-probe verification without changing bytes. No claim of testing every computer, mod combination or actual multiplayer gameplay.

中文：删除系统进程遍历与自动订阅，默认本地检测，说明联网及脚本安装访问范围；显示排序依据并支持本地规则导入导出。感谢社区反馈。详见 ACCESS_AND_PRIVACY.md。


## 0.6.1

- 新增首次使用与环境检查、LuaCs 恢复说明；区分完整安装、仅设置、已恢复及缺失/损坏备份，不可恢复时禁用按钮。
- 容错处理运行参数和设置文件；损坏原文件另存，权限受限时保留会话界面并明确说明无法保存偏好。
- 游戏搬盘后重新定位，兼容旧版 Steam 库记录；未生成游戏配置、空模组列表与 Steam 接口问题提供处理指引。
- 界面只刷新变化行、翻译有限缓存、减少纹理文件的无关检查；扫描可取消，缓存不能保存时仍可使用结果。
- 公开资料失败保留已有数据并短暂退避，完整分析可刷新资料；恢复期间重检游戏运行状态并响应停止。

## 0.6.0

- 中文 / English 实时切换，自动保存语言偏好；新用户按系统语言初始化，非中文环境默认英文。
- 主界面、菜单、筛选、排序与规则、配置/联机/快照、LuaCs、兼容分析、日志说明和错误提示提供英文；已打开的窗口与报告同步更新。
- 语言切换只影响显示，保留模组名称、编号、路径、启用状态、筛选、排序预览和运行中的任务；导出报告按当前语言显示说明，不改变配置清单结构。
- 新增英文使用说明及工坊英文桌面安装入口，工坊简介顶部提供公开 GitHub 源码和下载链接。
- 检查双语界面、小窗口大字号、语言偏好、事件消息和游戏配置不变；延续原有更新、LuaCs、排序与快照测试。真实玩家联机兼容仍需游戏内测试。

## 0.5.0

- 界面重新划分为「模组管理」「工具与脚本」「设置与外观」，更新、检测和启动游戏固定在上方；导出、恢复和分析集中到「更多操作」及工具页。
- 深海蓝、石墨灰、明亮三种主题，自选强调色与六种预设色；字号 10/11/12、舒适/紧凑列表。主界面、已打开的排序/管理/报告窗口实时同步，无需重新检测模组。
- 自动保存外观、显示列和任务记录展开状态；退出时记录窗口大小、列宽。恢复默认外观保留更新参数和游戏目录。
- 启用/未启用/需要处理筛选，名称或编号搜索，右键快捷操作和键盘快捷键；隐藏记录不清空内容，保留关键「更新」「启用」「模组」列。
- 自选颜色自动调整按钮文字和强调文字对比度；小窗口使用横向滚动及工具/设置页滚动，避免大字号挤出主要按钮。
- 89 项测试通过，独立 EXE 自检通过三种主题、排序及管理窗口；实际 51 项清单的界面预览确认游戏启用配置未变。原有更新、Steam 关联、排序、LuaCs 与快照逻辑沿用 0.4.0。

## 0.4.0

- 多套命名配置，保存实际已安装版本、核心内容包、启用清单及顺序；一次写入整体应用，保留其他游戏设置。
- 分析缓存按文件状态和工坊资料复用；游玩时默认不遍历资源、不读取脚本、不查询 Steam 和网络资料，深度分析延后并标记待刷新。
- 兼容报告区分普通重复定义与显式 Override，显示相关文件、预计 XML 优先项、证据状态和建议；脚本与 XML 多重线索一起计入风险。
- 自动/拖动排序增加自定义前后规则与位置锁定，拒绝矛盾规则或违反锁定的移动。
- 游戏、LuaCs 与服务器日志尾部诊断，错误分类、可能关联模组和敏感字段遮盖；LuaCs 安装后验证指引区分磁盘检测与游戏内实测。
- 更新前整套独立文件快照，覆盖启用模组和更新目标；按游戏版本校验后恢复文件和启用顺序，事务备份、失败回滚及下次操作时中断恢复。
- 导入朋友清单并订阅下载缺失/不同版本的工坊项目；所属游戏核实、下载失败或版本不一致时保留原启用配置。Steam 不能按清单取得历史版本，本地模组需自行安装。
- 保留只有游戏副本、已无 Steam 缓存的工坊模组；支持旧版联机清单导入。
- 81 项测试通过；实际 51 个模组的游玩中轻量检测和打包自检通过，实际启用配置未修改。新增订阅与整套恢复通过模拟/隔离验证，未自动订阅真实账号或替换真实模组。

## 0.3.0

- 实际加载顺序读取、排序建议预览、拖动及上下移动，保存时备份配置并检查游戏进程。
- 根据资源引用生成顺序建议；重复定义保留现有相对优先级；检测循环并提示手动调整。
- 官方 LuaCs 客户端补丁一键安装，SHA-256 和游戏版本检查、安装失败恢复及中断恢复。
- 新旧配置兼容，永久开启 C#；检测已就绪时跳过，支持恢复助手安装前的文件。
- 联机清单导出和对比增加实际加载顺序。
- 游戏运行时的只读检测进度提示；47 项测试通过，官方真实补丁隔离安装与恢复通过。

## 0.2.0

- 工坊与 LocalMods 模组逐项启用/禁用，配置备份和核心内容包切换。
- 模组类型、内容影响范围及兼容风险分析，读取 XML 标识、Lua 钩子、方法补丁和部分全局写入。
- 已启用与未启用模组的重叠区分，完整分析展示与导出。
- 34 项测试通过。

## 0.1.0

- Steam 工坊并行更新请求、缓存完成通知与并行安装。
- 逐文件校验、缓存复用、未变化安装跳过、超时和错误重试。
- 安装备份、失败恢复、中断恢复、游戏进程保护。
- 更新报告及联机清单导出/对比；22 项测试通过。

## 历史版本归档说明

0.1.0 和 0.2.0 对应程序未独立保留，现从对应开发记录恢复源码并重新构建。0.1.0 的五个主要源码文件与原发布记录 SHA-256 完全一致；0.2.0 恢复自当时发布构建前的源码节点。各自测试与重新构建的独立程序自检均通过。重建程序的二进制校验值以本次发布清单为准，可能与原始构建不同。使用说明和发布文档按版本重新整理。
