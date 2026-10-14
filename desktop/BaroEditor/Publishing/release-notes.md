BaroEditor|潜渊症通用事件编辑器【独立程序】 v0.2.1 预览版

- 画布空白处直接拖动平移，也支持中键、空格+拖动；Ctrl+滚轮围绕鼠标缩放。
- 全图按节点实际范围适配，缩放最低 0.1%；“定位”恢复 100% 阅读比例。超过 400 节点的事件仍需选择事件或搜索缩小显示范围。
- 点击连线或 › 跳转点定位下一节点，导航不修改事件 XML。
- 导入原版或模组 infotexts 本地化 XML，切换语言；卡片、搜索、试播及属性预览显示译文。支持静态 Text/Replace，运行时变量保留。工程内保存词条，编辑与导出保留原标签。后台导入，不扫描目录。
- 新增深蓝声呐与事件节点图标，应用于 EXE、窗口和 SDK 构建。

188 项独立版检查 + 671 项 XML 回归检查通过；100 节点全图边界、连线跳转、本地化与工程恢复的实际 WPF 回调/渲染验证通过。原版简中 8,675 词条测试导入约 23 ms。真实鼠标拖动、全部设备与分辨率尚未完整验证。

Windows x64，需 .NET 10 Windows Desktop Runtime。解压完整文件夹后双击 BaroEditor.exe；无需启动游戏、LuaCs 或管理员权限。工坊订阅不会自动运行程序。旧版工程可继续导入，原文件保持不变。

[独立程序工坊](https://steamcommunity.com/sharedfiles/filedetails/?id=3819572370) · [游戏内版工坊](https://steamcommunity.com/sharedfiles/filedetails/?id=3819517380) · [游戏内版下载](https://github.com/laohei-moddeveloper/baroeditor/releases/tag/v0.1.1)
