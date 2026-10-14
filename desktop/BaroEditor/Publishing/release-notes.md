BaroEditor|潜渊症通用事件编辑器【独立程序】 v0.2.2 预览版

- 声望/数据检查的比较方式与值直接显示在节点上，选择 gt/gte/eq/neq/lt/lte 并点击 ✓ 应用，保持原版 condition 格式。
- 拖入空白画布不再自动继承层级：生成独立悬空草稿，可编辑、连成链、保存工程、撤销。连接到事件后才进入事件 XML。
- XML 导出/复制/覆盖时提醒未连接草稿，确认后只输出已连接内容。保存工程保留所有草稿。带悬空节点的工程格式 2 需要 0.2.2 或更高版本，旧版工程仍可导入。
- GoTo 增加定位目标，查找同一事件中的同名 Label，缺失提示、重名选择。选中/悬停用边框高亮对应节点；连线可高亮两端。
- 阻止把事件组 EventSet 和脚本事件 ScriptedEvent/TraitorEvent 加入事件内部；导入的错误嵌套保持原文并警告，修正前阻止 XML 输出。

编译无警告，229 项独立版核心检查 + 671 项 XML 回归检查通过。未增加动画、扫描或权限；本次新增界面未做人工实测，复杂事件仍需游戏内验证。

Windows x64，需要 .NET 10 Windows Desktop Runtime；解压完整文件夹后双击 BaroEditor.exe。无需启动游戏、LuaCs 或管理员权限。

[独立程序工坊](https://steamcommunity.com/sharedfiles/filedetails/?id=3819572370) · [游戏内版工坊](https://steamcommunity.com/sharedfiles/filedetails/?id=3819517380)
