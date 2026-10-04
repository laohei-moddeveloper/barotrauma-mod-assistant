# BaroDock — access and privacy / 访问范围与隐私

Applies to **0.7.1** (renamed from BaroPy; access changes introduced in 0.7.0). BaroDock is an optional standalone Windows application, distributed through the Workshop; it is not loaded inside the game. It runs as the current user, without requesting administrator elevation. **It is not an operating-system sandbox.** These are limits implemented by our code, not a guarantee that Steam, LuaCs or other mods are isolated.

## What changed following community feedback

- Removed system-wide process enumeration, including the code that collected unrelated process names. There are no process-memory reads or process-termination operations.
- Removed automatic Steam subscribe/unsubscribe operations. Imported profiles require you to subscribe to missing items yourself in Steam.
- Startup and Refresh now inspect local files without connecting to Steam or requesting public item metadata. Online inspection and updates require an explicit action and an access explanation.
- LuaCs installation has its own confirmation explaining downloads, backups, client replacement and C# script execution.
- Local mod traversal rejects symbolic links and directory junctions rather than following them outside a mod folder.
- The application includes a bilingual Access & privacy report. Builds do not request elevated privileges; UPX packing is disabled.

The previous process inventory was broader than necessary. It should have been scoped and explained from the start. Thank you to the players who raised this concern. We found no wallet, browser-credential or firewall inspection in the application's production code; removing the unnecessary process inventory also removes visibility into unrelated application names.

## Reads and writes

| Operation | Purpose and scope |
| --- | --- |
| Find installation | Read Valve/Steam registry values and Steam library/game manifests to locate app 602960. No registry writes. A user-selected game folder takes precedence. |
| Local inspection | Read the selected Barotrauma folder, the current Windows user's Barotrauma mod/config folders, local Workshop manifests and BaroDock settings. Parse mod resources/scripts as text; do not execute them. |
| File availability | Probe only `Barotrauma.exe` and `DedicatedServer.exe` in the selected installation. Request a temporary existing-file handle with write access; **write no bytes**, create no file and change no content. Windows prevents this access to a running executable. Sharing conflicts or unknown access errors block modifications. This cannot identify the holder or detect another installation. |
| Online inspection/update | On request, use the game's official Steamworks DLL for Barotrauma subscriptions/download state. Public metadata requests send item IDs to Steam. Download only subscribed items; never subscribe automatically. Steam can show the game as running while connected. |
| Apply changes | User-requested changes to mods, enabled packages, load order or profiles, with backups. Preferences, analysis cache and task logs are stored in user folders. Reports/rules go to a user-selected export location. |
| LuaCs | After confirmation, fetch the official GitHub release and replace backed-up client files in the selected game folder; enable C# scripts. LuaCs and script mods run code within the game and have their own capabilities. |
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

写入包括用户请求的模组、启用配置、排序及备份，以及用户目录内的助手偏好、缓存和本地日志。导出仅保存到用户选择的位置，不自动上传。LuaCs 只在确认后从官方 GitHub 下载、备份替换客户端文件并开启 C#；脚本模组可以在游戏中运行代码。

不检查钱包、浏览器凭据或防火墙，不遥测、不枚举其他用户的进程，也不请求管理员提权。普通桌面程序仍拥有当前用户的系统权限，**本次改进不是操作系统沙箱**，无法隔离 Steam、LuaCs 或第三方模组。旧版进程名称收集范围过大，我们接受这个批评并已删除；感谢社区帮助指出问题。

## Sorting rules / 排序规则

Inspired by [RimPy's explicit-rule approach](https://github.com/rimpy-custom/RimPy/wiki/Autosorting), without copying RimWorld-specific ordering assumptions. BaroDock now uses identified resource dependencies and local before/after rules, preserves existing overlapping-definition precedence where possible, and does not guess order from categories or names. Review all reasons before saving. JSON rule import/export is local, executes no code, checks cycles and requires confirmation before replacing local rules. Import alone does not change the game order. 作者说明优先；不把自动排序当作兼容保证。
