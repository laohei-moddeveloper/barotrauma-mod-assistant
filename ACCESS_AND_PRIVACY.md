# BaroDock — access and privacy / 访问范围与隐私

Applies to **0.10.0** (access changes introduced in 0.7.0). BaroDock is an optional standalone Windows application, distributed through the Workshop; it is not loaded inside the game. It runs as the current user, without requesting administrator elevation. **It is not an operating-system sandbox.** These are limits implemented by our code, not a guarantee that Steam, LuaCs or other mods are isolated.

## What changed following community feedback

- Removed system-wide process enumeration, including the code that collected unrelated process names. There are no process-memory reads or process-termination operations.
- Removed automatic Steam subscribe/unsubscribe operations. Imported profiles require you to subscribe to missing items yourself in Steam.
- Startup and Refresh now inspect local files without connecting to Steam or requesting public item metadata. Online inspection and updates require an explicit action and an access explanation.
- LuaCs installation has its own confirmation explaining downloads, backups, client replacement while preserving C#; C# has a separate confirmation explaining unsandboxed script execution.
- Local mod traversal rejects symbolic links and directory junctions rather than following them outside a mod folder.
- The application includes a bilingual Access & privacy report. Builds do not request elevated privileges; UPX packing is disabled.

The previous process inventory was broader than necessary. It should have been scoped and explained from the start. Thank you to the players who raised this concern. We found no wallet, browser-credential or firewall inspection in the application's production code; removing the unnecessary process inventory also removes visibility into unrelated application names.

## Reads and writes

| Operation | Purpose and scope |
| --- | --- |
| Find installation | Read Valve/Steam registry values and Steam library/game manifests to locate app 602960. No registry writes. A user-selected game folder takes precedence. |
| Local inspection | Read the selected Barotrauma folder, the current Windows user's Barotrauma mod/config folders, local Workshop manifests and BaroDock settings. Parse XML definitions and explicit dependency declarations; count script files without reading script source for compatibility scoring. Do not execute mod code. |
| File availability | Probe only `Barotrauma.exe` and `DedicatedServer.exe` in the selected installation. Request a temporary existing-file handle with write access; **write no bytes**, create no file and change no content. Windows prevents this access to a running executable. Sharing conflicts or unknown access errors block modifications. This cannot identify the holder or detect another installation. |
| Online inspection/update | On request, use the game's official Steamworks DLL for Barotrauma subscriptions/download state. Public metadata requests send item IDs to Steam. Download only subscribed items; never subscribe automatically. Steam can show the game as running while connected. |
| Apply changes | User-requested changes to mods, enabled packages, load order or profiles, with backups. Preferences, analysis cache, task logs and the latest update checkpoint are stored in user folders. The checkpoint stores the selected game path, target/completed item IDs, online choice and timestamps; it cannot start a task automatically. Reports/rules go to a user-selected export location. |
| LuaCs | After confirmation, fetch the official GitHub release and replace backed-up client files in the selected game folder; preserve the current C# setting. A separate action enables/disables C# or restores its settings backup. LuaCs and script mods run code within the game and have their own capabilities. |
| Copy selected mods | Only on Ctrl+C in the mod list or an explicit menu action, write selected mod names/IDs to the clipboard. Never read clipboard contents. |
| Logs | Inspect game/LuaCs logs in the selected game and current user's game folders, or a log file you explicitly select. No automatic uploads. |

No telemetry, wallet checks, browser-credential access, firewall inspection, automatic report uploads, or collection of other users' processes. A Windows kernel API is still used for file handles and the application's own single-instance mutex. Calling a Windows API is not itself process inspection; the purpose and target matter.

Steamworks uses native functions and callbacks. Python `ctypes` pointers here marshal arguments/results for the official interface loaded into the assistant's own process; they do not inspect another process's memory. See [Valve's ISteamUGC documentation](https://partner.steamgames.com/doc/api/ISteamUGC) and [Microsoft's CreateFile documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

## Reviewable source and limits

Relevant files: `mod_assistant/core.py` (scoped file probe and paths), `steam.py` (native Steam interface), `app.py` and `access.py` (explicit actions/notices), `friends.py` (manual-subscription requirement), and `BarotraumaModAssistant.spec` (build privileges). [Public source](https://github.com/laohei-moddeveloper/barotrauma-mod-assistant).

This release does not remove every native call: reliable Workshop downloads still use the official Steam interface. It does not reduce permissions granted by Windows to all desktop programs, sandbox third-party mods, or prove all mod combinations safe. Static compatibility analysis is a warning system; it cannot prove runtime compatibility. File availability checks also have a race between checking and changing files. Close the game/server before modifications and keep backups. No administrator elevation is requested to bypass protected-folder failures.

## 中文说明

BaroDock 是通过工坊分发的独立 Windows 工具，不是在游戏中加载的模组。0.7.0 删除了遍历系统进程名称的代码及自动订阅功能；启动和重新检测默认只读取本地资料。联网检测、更新以及 LuaCs 安装由用户主动选择，操作前说明具体访问内容。

读取范围是所选游戏目录、当前用户的游戏模组与配置、Steam 安装和工坊清单及助手设置。定位 Steam 仅读取 Valve/Steam 注册表值，不写注册表。不执行被分析的模组代码，不跟随模组内的符号链接或目录联接。

修改前仅检查所选安装目录的游戏和服务器程序是否被占用：请求打开已有文件的临时写入访问句柄，但不写字节、不创建文件、不改变内容。占用或无法确认时阻止更改；不能识别占用者，也不能检查另一份游戏安装。此功能无需读取系统进程列表或其他程序内存。

联网操作通过游戏自带的官方 Steam 接口读取潜渊症订阅/下载状态，公开资料查询将模组编号发送给 Steam。缺失订阅需要用户在 Steam 手动完成。Python 指针用于自身进程内的官方接口调用与结果转换，不读取其他进程内存。连接时 Steam 仍可能显示游戏正在运行。

写入包括用户请求的模组、启用配置、排序及备份，以及用户目录内的助手偏好、缓存、本地日志及最近一次更新记录。更新记录只含所选游戏路径、目标/完成编号、联网选择和时间，不会自动执行任务。导出仅保存到用户选择的位置，不自动上传。仅按列表 Ctrl+C 或明确菜单操作将所选模组名称/编号写入剪贴板，不读取剪贴板。LuaCs 只在确认后从官方 GitHub 下载、备份替换客户端文件并保留 C# 选择；C# 开关和设置恢复由独立确认处理，C# 模组没有沙箱；脚本模组可以在游戏中运行代码。

不检查钱包、浏览器凭据或防火墙，不遥测、不枚举其他用户的进程，也不请求管理员提权。普通桌面程序仍拥有当前用户的系统权限，**本次改进不是操作系统沙箱**，无法隔离 Steam、LuaCs 或第三方模组。旧版进程名称收集范围过大，我们接受这个批评并已删除；感谢社区帮助指出问题。

## Sorting rules / 排序规则

Inspired by [RimPy's explicit-rule approach](https://github.com/rimpy-custom/RimPy/wiki/Autosorting), without copying RimWorld-specific ordering assumptions. BaroDock now uses identified resource dependencies and local before/after rules, preserves existing overlapping-definition precedence where possible, and does not guess order from categories or names. Review all reasons before saving. JSON rule import/export is local, executes no code, checks cycles and requires confirmation before replacing local rules. Import alone does not change the game order. 作者说明优先；不把自动排序当作兼容保证。

## 0.9.0 boundaries

Production `steam.py` has an explicit binding allowlist for initialization, subscription/download status, download requests and callbacks. Workshop publisher tools used by the owner during development are excluded from the released application. Author metadata is parsed as bounded XML and a limited Boolean grammar, without eval or mod-part writes. XML comparison is read-only. Backups can use a user-selected folder; restore staging and retained originals stay inside target mod-library roots on the appropriate volumes. Original-game content is not distributed.

Local logs may contain personal details. The error viewer redacts known game/user paths, common credential fields and Steam IDs; it cannot guarantee removal of every personal detail in arbitrary third-party log text. Inspect before sharing. No automatic sharing occurs.

An existing legacy LuaCs runtime's explicit C# choice may be migrated to the modern configuration while updating. This migration is backed up with the runtime transaction. A fresh installation or a stale legacy setting in a vanilla game does not grant C# permission.

## 0.10.0 read-only evidence additions

Explicitly selected campaign saves are streamed with archive/size/XML limits; nothing is extracted or executed. Saving an approved match creates a new native ModLists XML and local association metadata; the save, enabled list and subscriptions stay unchanged. XML comparisons also read selected-game Vanilla resources and report specific fields and a bounded registration model. Log matches can locate current XML, but do not execute or upload text. Rule provenance and exact-version scopes are local; recorded source URLs are not fetched automatically. No runtime dependency, process scanning, credentials, elevation or telemetry is added.

0.10.0：用户选定存档后有界只读检查；保存核对结果仅创建原生清单及助手关联记录，不改存档、启用列表或订阅。XML 对照读取所选游戏的原版资源，日志可以对应当前文件；都不执行第三方代码、不自动上传。规则来源/版本记录保持本地，不自动访问填写的网址。权限边界延续。
