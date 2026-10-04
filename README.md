# BaroDock｜潜渊症模组管理

面向 Windows 64 位 Steam 版《潜渊症》（Barotrauma）的独立模组管理工具。当前版本 **0.7.1**。

[English guide](README_EN.md) · 程序右上角可在「中文 / English」之间实时切换，自动保存语言选择。

## 下载和使用

在本仓库的 [Releases](https://github.com/laohei-moddeveloper/barotrauma-mod-assistant/releases) 下载对应版本的 Windows 压缩包，解压后双击 `BarotraumaModAssistant.exe`（历史版本为「潜渊症模组更新助手.exe」）。无需安装 Python。保持 Steam 已登录，更新、切换启用状态、保存顺序及安装 LuaCs 前请关闭游戏和专用服务器。详细操作见 [使用说明](使用说明.md)。

也可通过 [Steam 创意工坊](https://steamcommunity.com/sharedfiles/filedetails/?id=3812360206) 订阅分发包，按照页面步骤运行「安装到桌面.cmd」。这是独立工具，无需在游戏中启用分发包；桌面版在工坊下载新版后需手动重新复制。工坊介绍和封面见 [workshop](workshop)。

## 功能

- 三页导航：模组管理、工具与脚本、设置与外观；固定常用更新按钮，右键及「更多操作」集中处理低频操作。
- 深海蓝、石墨灰和明亮主题，自选强调色、字号与列表疏密；实时换肤，自动保存显示列、记录展开状态、窗口大小与列宽。
- 按启用状态或待处理项目筛选，搜索模组名称/编号；Ctrl+F 搜索、F5 检测、Ctrl+U 更新，任务记录可折叠。
- 同时向 Steam 提交多个工坊更新请求，并行安装已完成的缓存；校验、复用未变化文件、失败重试及备份恢复。
- 单独控制工坊和本地模组的启用状态；分析模组类型、影响范围及资源和 Lua/C# 源码的兼容风险。
- 展示实际启用模组顺序，支持拖动、上下移动和自动排序建议；保存前预览，并备份游戏配置。
- 一键安装官方 LuaCs Windows 客户端补丁并永久开启 C#；检查补丁哈希、游戏版本及运行状态，支持恢复安装前文件。
- 导出更新报告、静态兼容分析和包含加载顺序的联机清单。
- 保存多套配置，整体切换核心包、启用列表和顺序；导入朋友清单，核实项目所属游戏后手动在 Steam 订阅，再下载缺失模组并应用。
- 增量分析缓存；游玩时默认轻量检测并推迟深度扫描，显示资料是否待刷新。
- 区分明确 XML Override 和普通重复定义，展示文件位置、预计覆盖优先项及处理建议；自定义前后排序规则和锁定位置。
- 更新前独立保存整套模组及启用配置快照，支持整套恢复、失败回滚和中断恢复；读取游戏/LuaCs 日志并提供验证指引。

Steam 负责实际下载调度，助手不能保证突破客户端队列或带宽限制。兼容风险及自动排序属于静态分析建议，作者说明和游戏内测试优先。开启 C# 后请使用可信来源的脚本模组。

## 版本

| 版本 | 主要变化 | 验证 |
| --- | --- | --- |
| 0.1.0 | 并行请求与安装、缓存复用、校验、备份恢复 | 22 项测试 |
| 0.2.0 | 启用开关、类型与重要程度、资源和脚本兼容分析 | 34 项测试 |
| 0.3.0 | 自动/拖动排序、LuaCs 与永久 C# 一键设置、游戏运行时检测提示 | 47 项测试 |
| 0.4.0 | 多套配置、分析缓存、兼容证据、排序规则、日志诊断、整套快照、联机配齐、LuaCs 验证指引 | 81 项测试 |
| 0.5.0 | 实时外观定制、三页导航、筛选与快捷键、显示列和窗口记忆 | 89 项测试 |
| 0.6.0 | 中文/English 实时切换、双语提示与报告、英文说明与安装入口 | 96 项测试 |
| 0.6.1 | 新用户环境指引、LuaCs 备份状态、设置容错、界面和扫描效率改进 | 123 项测试 |
| 0.7.0 | 访问范围收紧、本地检测默认、解释排序及规则导入导出、BaroPy 品牌 | 133 项测试 |
| 0.7.1 | 更名 BaroDock，统一程序、工坊、封面及桌面入口 | 133 项测试 |

版本变化见 [CHANGELOG](CHANGELOG.md)，发布及重建说明见 [releases](releases)，验证范围见 [docs/validation.md](docs/validation.md)。0.1.0 与 0.2.0 的安装包从对应历史源码重新构建，发布记录会明确标注。

## 开发

使用 Python 3.12，应用运行代码仅依赖标准库。测试：

```powershell
python -m unittest discover -s tests -v
```

构建独立程序：

```powershell
py -3.12 -m venv .build-tools
.\.build-tools\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1
```

入口为 `run_assistant.py`，源码在 `mod_assistant`，构建输出在 `dist`。界面截图开发工具额外需要 Pillow。原始环境调查、个人配置、游戏内容、第三方参考源码、缓存、日志和本机工具目录不纳入 Git。

## 依据

使用本机游戏自带的 Steam 接口库，接口依据 [ISteamUGC 官方文档](https://partner.steamgames.com/doc/api/ISteamUGC)。LuaCs 补丁来自 [官方发布](https://github.com/evilfactory/LuaCsForBarotrauma/releases/tag/latest)，安装方式依据 [官方手动安装文档](https://github.com/evilfactory/LuaCsForBarotrauma/blob/master/luacs-docs/lua/manual/installing-lua-for-barotrauma-manually.md)。本仓库和下载包不分发原版游戏文件或第三方工坊模组。

## 0.7.0 访问与排序改进

启动和重新检测默认仅检查本地资料。需要下载状态和公开工坊资料时，主动选择「联网检测」；联网更新也会说明访问范围。不遍历系统进程，不自动订阅或取消订阅。完整说明见 [访问范围与隐私](ACCESS_AND_PRIVACY.md)。普通桌面程序并非系统沙箱。

自动排序不再按类型或名称猜测优先级，依据资源依赖、前后规则及现有覆盖顺序。可查看全部排序依据、导入导出本地 JSON 规则；导入不会修改游戏顺序，需要另行预览与保存。参考 RimPy 的明确规则思路，未复制 RimWorld 的加载规则。
