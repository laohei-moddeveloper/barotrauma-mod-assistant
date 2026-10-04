"""User-facing access contract; no system inventory or telemetry."""

NETWORK_NOTICE = ('联网操作将使用游戏自带的官方 Steam 接口，读取潜渊症订阅与下载状态；'
                  '联网检测还会向 Steam 查询模组编号对应的公开资料。更新只请求已订阅项目，'
                  '不会代你订阅或取消订阅，也不上传日志和报告。Steam 可能显示游戏正在运行。是否继续？')

LUACS_NOTICE = ('此操作会从 LuaCs 官方 GitHub 发布下载补丁，备份并替换所选游戏目录的客户端文件，'
                '并启用 C# 脚本。启用后，游戏中的脚本模组具有运行代码的能力，请只使用可信模组。'
                '该功能只在你主动选择时运行，不需要管理员权限。是否继续？')

def access_report(env=None, language='zh'):
    game = str(env.game) if env else ('Not detected' if language == 'en' else '尚未检测')
    player = str(env.player) if env else ('Not detected' if language == 'en' else '尚未检测')
    if language == 'en':
        return '\n'.join([
            'BaroDock: access & privacy', '',
            'Default: local inspection. Startup and Refresh do not connect to Steam or fetch public metadata.',
            'Reads: the selected Barotrauma folder, this Windows user\'s Barotrauma mod folder, '
            'Steam installation/library manifests for app 602960, and BaroDock settings.',
            'Steam installation discovery reads only Valve/Steam registry values. No registry writes.',
            'Game folder: '+game, 'Player folder: '+player, '',
            'Before changing files, only Barotrauma.exe and DedicatedServer.exe in the selected folder '
            'are checked. Windows is asked to open an existing-file handle with write access; '
            'no bytes are written. A sharing conflict blocks changes. Access errors keep changes blocked.',
            'No process enumeration, process memory reads, or process termination. '
            'This cannot identify which program holds a file or detect a game running from another installation.',
            'Online check/update: requested by you, using the installed official Steamworks DLL for '
            'Barotrauma. Item IDs are sent to Steam for public metadata. Steam may show the game as running.',
            'The program does not contain automatic subscribe/unsubscribe calls. Subscribe in Steam yourself.',
            'Writes: selected mod/config changes and backups after your actions; assistant preferences/cache/logs '
            'in your user folders; exports only to the location you choose.',
            'LuaCs: only on explicit confirmation, downloads an official GitHub release, backs up/replaces '
            'client files, and enables C# scripting. Script mods can run code in the game.',
            'No wallet/browser credential/firewall inspection, telemetry, or automatic log/report uploads.',
            'No administrator elevation request. This is an ordinary desktop application, not an OS sandbox. '
            'Its code limits access; it cannot sandbox Steam, LuaCs, or other game mods.',
            'Details and limitations: ACCESS_AND_PRIVACY.md in the release and public source repository.'
        ])
    return '\n'.join([
        'BaroDock：访问范围与隐私', '',
        '默认仅本地检测；启动和重新检测不连接 Steam，也不获取公开模组资料。',
        '读取范围：所选潜渊症目录、当前 Windows 用户的游戏模组目录、Steam 的游戏 602960 '
        '安装/工坊清单，以及助手设置。定位 Steam 仅读取 Valve/Steam 注册表值，不写注册表。',
        '游戏目录：'+game, '玩家目录：'+player, '',
        '修改前只检查所选目录的 Barotrauma.exe 与 DedicatedServer.exe。向 Windows 请求打开已有'
        '文件的临时写入访问句柄，不写入任何字节；文件占用或无法确认时阻止更改。',
        '不枚举系统进程、不读取进程内存、不终止程序。此检测不能识别占用者，也不能判断其他游戏安装目录的运行状态。',
        '联网检测/更新由你主动选择，使用游戏自带的官方 Steamworks 接口，只针对潜渊症；'
        '公开资料查询会将模组编号发给 Steam，Steam 可能显示游戏正在运行。',
        '程序不包含自动订阅或取消订阅的调用；需要你在 Steam 手动订阅。',
        '写入范围：你选择的模组/启用配置及备份；用户目录内的助手设置、缓存和本地日志；'
        '导出文件仅保存到你选择的位置。',
        'LuaCs 仅在明确确认后下载官方 GitHub 补丁、备份替换客户端文件并启用 C#。脚本模组可以在游戏中运行代码。',
        '不检查钱包、浏览器凭据、防火墙，不遥测，也不自动上传日志或报告。',
        '不请求管理员提权。这是普通桌面程序，并非操作系统沙箱；代码限制自身访问范围，不能替 Steam、LuaCs 或其他模组隔离权限。',
        '详细说明和限制见发布包及公开源码中的 ACCESS_AND_PRIVACY.md。'
    ])
