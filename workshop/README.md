# 工坊分发包

将 v0.5.0 的独立程序作为工坊内容包的附带文件分发。`filelist.xml` 为没有游戏资源条目的普通包，不注册可执行文件或脚本，不自动启动助手。用户手动运行安装入口，复制程序到个人目录并建立桌面快捷方式。

`description.bbcode.txt` 是 Steam 页面的中文简介，`description.en.bbcode.txt` 是英文简介，`FIRST_READ.txt` 是订阅后本机说明。实际编号为 `3812360206`，构建分发包时写入 filelist 的 `steamworkshopid`；发布记录在 `publication.json`。`cover.jpg` 为工坊封面，最终原图在 `assets/cover-final.png`；弃用的错误版本不纳入发布包。三张界面截图使用虚构示例清单，未公开个人模组列表。

2026-10-03 已通过 Steam 的语言设置分别保存并回读核验 `schinese` 和 `english` 标题与简介，保留作者修改后的中文标题和原有中文内容。项目已公开。英文页面提供安装、更新、功能、常见问题以及主要按钮的中英对照；v0.5.0 程序界面仍为中文，此次只更新页面说明，未修改程序、封面、分发包或可见性。

构建与上传操作记录放在忽略的 `.release-staging` / `Research`，不把本机路径、账号信息或玩家配置纳入发布包。上传清单严格列出允许的文件，不把整个项目目录作为工坊内容提交。GitHub 仓库目前保持私有，工坊安装无需访问 GitHub。

技术依据：游戏的 [内容包文档](https://regalis11.github.io/BaroModDoc/Intro/ContentPackages.html)、[安装目录复制逻辑](https://github.com/FakeFishGames/Barotrauma/blob/master/Barotrauma/BarotraumaShared/SharedSource/Steam/Workshop.cs) 和 Steam 的 [工坊接口](https://partner.steamgames.com/doc/api/ISteamUGC)。游戏复制包目录里的附带文件；内容加载仍由 filelist 中的资源条目决定。

封面提示词和生成方式见 [cover-prompt.md](cover-prompt.md)。使用内置 imagegen 生成，修正为右手持平板、左手扶腰，并调整标题避免遮挡。用于上传的 JPEG 仅转换格式压缩，保留原图尺寸和构图。
