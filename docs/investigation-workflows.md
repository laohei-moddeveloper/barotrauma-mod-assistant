# 排查工作流 / Investigation workflows

1.0.0 正式版。本页说明功能的使用、实现依据和实际验证边界。

## 玩家希望省掉哪些麻烦

用户需要的是少翻资料、少重复操作、明确的解决路径和可撤回的修改。以下是对实际建议的归纳，而非对所有玩家的调查结论。

| 已阅读的建议或机制 | 玩家实际诉求 | 本次落实 |
| --- | --- | --- |
| [RimSort #2417](https://github.com/RimSort/RimSort/issues/2417)：重建清单时逐项寻找某模组的补丁和附属项目很费时 | 点一个框架就能找到谁需要它，包括当前未启用的项目 | 主列表右键“谁需要或关联此模组”；列出作者要求、补丁、冲突和工坊依赖，显示条件、启用状态和出处 |
| [Irony #606](https://github.com/bcssov/IronyModManager/issues/606)：大清单组织、作者标签不一致 | 自己整理清单，不依赖作者恰好使用正确标签 | 本地标记进入搜索与筛选，保存在助手设置；不改变真实加载顺序 |
| [CKAN #4510](https://github.com/KSP-CKAN/CKAN/issues/4510)：建议条目会受输入顺序及冲突影响而隐藏；该问题已关闭并关联修复 | 即使某项有冲突，也要看见它及其原因，不让程序默默删掉选项 | 依赖查询保留未成立、未知和同名条件；排序、修复候选仍需审核，覆盖输入重排的回归样本 |
| [Vortex 用户讨论](https://forums.nexusmods.com/topic/6357941-how-to-solve-mod-rules-contain-cycles/)：看到一长串名字却不知道哪条规则有问题 | 错误应指向具体关系和下一步，而不是只给警告 | 保留现有循环链和每条关系的来源；新排查流程指向 XML 标识、文件与具体变化。该历史讨论不代表 Vortex 当前仍有同一缺陷 |
| [Vortex 的文件冲突说明](https://github.com/Nexus-Mods/Vortex/wiki/MODDINGWIKI-Users-General-Managing-File-Conflicts)与 [xEdit 的记录对照](https://tes5edit.github.io/docs/5-conflict-detection-and-resolution.html) | 看清究竟保留了谁的修改，选择希望得到的结果 | Item 定义来源、继承后的字段、未进入结果的修改，以及明确选择字段的兼容草稿。潜渊症优先级单独核对，不套用其他游戏的后加载优先 |
| [RimSort #2431](https://github.com/RimSort/RimSort/issues/2431)：特定访问环境下外部工坊浏览失败 | 网络失败时仍可管理本地清单；避免工具偷偷增加代理或账号操作 | 本地证据、对照、标记和草稿无需联网。沿用已有公开资料缓存与退避；没有增加代理、账号登录或访问限制绕过 |

这次优先复用现有主列表、XML 对照和日志窗口，没有增加云服务、账号管理或强制后台服务。

## 代码与界面的取舍

参考 [SMAPI 的 LogParser](https://github.com/Pathoschild/SMAPI/blob/develop/src/SMAPI.Web/Framework/LogParsing/LogParser.cs)及 [LogMessageBuilder](https://github.com/Pathoschild/SMAPI/blob/develop/src/SMAPI.Web/Framework/LogParsing/LogMessageBuilder.cs)，值得借鉴的是把完整消息、延续行和重复计数组织好，让解析器返回结构化事实，显示层再组织说明。它解析的是已知日志协议，不能拿来支持用正则判断 C# 源码兼容。本次将调用栈作为异常块的一部分：相同标题但不同调用位置分别保留，不把栈帧里的关键词再次计成独立异常；签名方法变化时，旧记录不能据此判定故障消失。

参考 [LOOT 的排序流程](https://loot.readthedocs.io/en/latest/app/sorting.html)，稳定处理已有顺序、明确关系优先、检查循环的组织方式适合保留；按游戏插件类别建立多图、按覆盖数量猜顺序等具体策略不移植。BaroDock 在没有新依据时尽量减少无关移动，预览与写入分开。

参考 [Irony 的定义层次](https://github.com/bcssov/IronyModManager/wiki/Conflicted-Objects)和 [LOOT 主界面](https://loot.readthedocs.io/en/latest/app/usage/main.html)，复杂信息应在选中具体问题后展开，重要状态同时用文字说明，结果需要明确审核入口。本次保留三个主页面；XML 窗口分为定义、文本差异和语义来源，日志窗口分为日志、文件清单和修复复查。高级草稿与诊断在菜单中，不把所有按钮堆在首屏。按钮可见性以两种语言、850×640 小窗口和 12 号字体实际检查，不能只看控件是否创建成功。

后端将字节证据、现场记录、Item 合成、资源引用、游戏观察及草稿生成拆成小模块，界面通过既有任务队列接收结果。读取边界、取消、变化检查和格式验证分别可测试。用清晰的责任边界降低重复与维护成本，比引入新的大型 GUI 框架或插件体系更适合当前规模。这些是架构思路的借鉴，没有复制其他项目的游戏加载规则或整套功能。

进一步阅读了 [RimSort 的后台工作单元](https://github.com/RimSort/RimSort/blob/1e0085d58b2687a04ed86a2b0af06769c42c4708/app/utils/github/worker.py)：工作单元按操作分开，通过进度、完成、错误通知界面，版本切换有备份和失败恢复。可学习任务边界与反馈，但不移植 Git 账号、SQLAlchemy 或 PySide6 依赖。本次现场捕获通过既有队列显示“第几项文件证据”和核心内容阶段，保留停止入口。

也核对了 [libloot 的错误结构](https://github.com/loot/libloot/blob/38610e7b0a61cf407ae0a30e35ba57a344a66e69/src/sorting/error.rs)及 [排序前验证](https://github.com/loot/libloot/blob/38610e7b0a61cf407ae0a30e35ba57a344a66e69/src/sorting/validate.rs)：循环不仅是一段字符串，还带具体节点与关系；数据读取失败与约束冲突分别表达。BaroDock 当前已有循环链、来源与本地错误记录，后续维护应保留这些可解释信息，避免用一个“排序失败”覆盖全部原因。其他游戏硬编码插件组规则不套用到潜渊症。

## 1. 更新后旧排序依据是否还适用

在排序规则窗口记录来源和适用范围。新文件依据实际读取 XML、Lua、C# 和 DLL 字节并保存 SHA-256；可同时绑定核心内容及游戏程序集、脚本设置。版本号没变但这些文件改变时，旧规则暂停并解释。

声明版本相同、文件证据相同、成功加载和运行正常是不同的事实。旧手工规则仍可使用，但不会升级为已实测结论。只改变音量、界面或启用顺序，不会因为配置文件整体变化就让核心文件依据过期。超出读取上限或文件在读取中变化，不能生成有效的完整摘要。

## 2. 哪个修改没有生效

主列表选中模组 → 查看完整分析 → 查看 XML 覆盖对照 → 比较定义 → 字段变化与定义来源。

已审阅的 Item 模型处理普通重复注册、整份 Override 选取、同包多个 Override、Clear、inherit/variantof、循环或缺失父项、位置对应的子节点替换与部分数值运算。组件的 identifier 不再混入物品注册集合。自定义核心包作为该场景的字段基线。

例如原版为耐久 100 / 堆叠 1，A 为 200 / 1，B 为 100 / 10：若选择 A 的整份定义，不能声称结果为 200 / 10。界面列出 B 的堆叠修改没有进入结果。已知来源包的其他注册错误、继承来源包错误或失败 Clear 包会阻止虚假的完整加载结果。

纹理检查说明具体资源根、文件存在性和同名歧义。不同 ModDir 下的同名文件不是共享文件冲突。配方引用区分有候选、在模型范围内未找到和目标不可用；不模拟配方执行或脚本生成的资源。

## 3. 保存现场、修复草稿与复查

工具与脚本 → 日志诊断。

1. 选择日志，保存测试前记录并填写需要重复的具体操作。记录保存在助手数据目录的 investigations 中。
2. “比较当前文件”列出启用顺序、版本、相关文件、核心内容、程序集和脚本设置变化。旧日志不能重建当时未保存的文件。
3. 明确的重复普通 Item 注册可生成逐项停用候选。必要依赖按明确声明连带处理；未能完整读取或不支持的条件列为待核对项目。
4. 选择候选，保存新的游戏原生 ModLists XML。原启用清单保持不变，另到配置窗口审核应用。
5. 在独立测试会话重复记录的操作，不覆盖原战役存档，然后“测试后读取新日志”。

日志读取最多 16 MiB，较大文件读取头尾并标出缺口。最多保留最早 80 种异常并归并重复次数和调用栈。完整追加日志只有在旧前缀字节完全匹配且边界为完整行时，才只分析本次追加部分。新错误、仍然出现和本次未复现分别显示；片段缺口、错误种类超限、截断调用栈、不稳定读取或旧日志不用于确认消失。

“本次未复现”只描述本次已执行的操作。它不是所有功能修复，也不是唯一根因或模组安全证明。没有稳定复现的复杂组合不能自动二分确定唯一责任方。

## 4. 明确选择字段的兼容草稿

完成 Item 对照后 → 更多分析 → 导出所选字段兼容草稿。选择希望保留的属性来源值，可多选；同一字段只能保留一个来源。

草稿保存在助手数据目录 patch-drafts，附带 README、字段选择记录、filelist.xml、Item Override 和明确依赖。不会覆盖工坊文件，不会复制到 LocalMods，也不会自动启用。原 ModDir 路径绑定到对应来源包。同名来源或不能明确定位的子节点不进入自动属性编辑。

审核后自行安装并测试。草稿需要排在竞争的普通 Override 包之前；核心包自身的 Override 可能阻止它胜出。它不消除多个普通注册，不修复 C#/Lua，也不处理其他类型的构造行为。源文件改变后应重新对照和生成草稿。

## 5. 可选游戏内观察

XML 对照 → 更多分析 → 生成可选游戏内诊断模块。助手在 LocalMods 创建独立目录，用户需要自行启用，并使用已经正常运行的 LuaCs。不会安装 LuaCs、开启 C# 或启动游戏。脚本使用 Autorun，不使用 ForcedAutorun。

在独立测试回合的 roundStart，通过游戏 API 获取实际加载内容包和所选 Item 的提供者、Health、MaxStackSize；只写自身目录 barodock-runtime-state.json。完成后在 XML 对照里导入该文件。对照配置启用清单、实际包、提供者及已审阅属性值；单个 API 读取失败保留具体错误，不把它说成“物品不存在”。

Health 默认值、上限及 MaxStackSize 默认值、1–63 范围按公开源码核对；只有已支持的有限数值格式进入属性值比较。导入文件的路径只作为匹配标签，绝不据此打开其他目录。导入观察不证明文件由何程序生成，也不重建历史模组。结束后自行停用或移除该模块。

## 权限与验证边界

新功能限于已选游戏/模组、用户选定日志或记录，以及助手自身数据。没有新增进程枚举、账户数据读取、系统扫描、联网上传、提权、构建脚本执行或生产依赖。导出记录中的复现步骤是用户原文，分享前自行检查隐私；路径和已识别日志字段的脱敏不是通用敏感数据检测器。

加载规则来自 [公开游戏源码快照](https://github.com/FakeFishGames/Barotrauma/tree/e6e95da83b1b5ca8b55ec52653c7cf6b40e30247)；公开快照不证明与某个已安装二进制完全相同。模型作为针对当前审核范围的检查使用，不能认证整个游戏启动或所有模组兼容。非 ASCII / 旧式自动生成 Item 标识、未覆盖数值格式、医疗/状态等其他加载类型不套用 Item 的确定结果。

10 个继承最小样本与公开源码中的 C# XML 合成函数结果一致；Lua 5.2 在隔离 API 适配器下执行并验证输出；中英文小窗口、实际字节哈希、修复草稿和复查流程有隔离验证。可选诊断模块已在本机真实 LuaCs 客户端的潜艇编辑器试玩回合验证：27 个内容包与配置顺序匹配，原版 wrench 的提供者及 Health / MaxStackSize 成功读取，测试后原清单与原版潜艇哈希保持一致。修复了真实环境 os.time() 返回小数导致导入失败的问题。其他真实电脑、构造行为和真实联机组合仍未完全实测，不作完整认证。

## English quick guide

These workflows apply to the 1.0.0 release.

- Right-click an installed mod and choose **Mods that require or reference this mod**. Explicit declarations include inactive and conditional entries; absence of declarations does not prove independence.
- Open **XML override comparison**, compare a shared Item definition and inspect the selected provider, inherited fields and lost changes. Normal overrides are distinct from duplicate ordinary registration.
- Open **Log diagnosis**, save a before-test record with exact steps, compare current inputs and generate a repair draft when a duplicate is located. Drafts are native ModLists files and require separate review/application. Run an independent test session, then recheck its new log.
- **More analysis → Export selected fields as a companion draft** exports only explicitly selected, unambiguous attributes. Review its README and dependencies before installing it. Competing regular Override packages must come after the draft; a core Override can still prevent it from winning.
- **More analysis → Create optional in-game diagnostic module** creates an unenabled local Lua observer. Enable it yourself with a working LuaCs client, start a separate test round, then import its JSON output. The observer reads game APIs and writes only its own file. It does not enable C#, launch the game, inspect other processes or upload data.
- Records hash actual XML/Lua/C#/DLL bytes, core inputs and selected runtime settings. Same version numbers do not conceal changed files. Large/partial/unsteady logs do not certify error disappearance; an appended log requires exact prefix verification.

The reviewed model covers Item registration/XML composition and a small set of property setters, not scripts, prefab constructors or universal compatibility. The Lua observer passed a real LuaCs client test round on this machine, including package order and selected Item fields; other machines and complete mod combinations remain unverified. Exported reproduction notes remain user text: review them before sharing.
