param([Parameter(Mandatory=$true)][string]$GameRoot,[Parameter(Mandatory=$true)][string]$LuaCsPackage,[Parameter(Mandatory=$true)][string]$Scratch)
$ErrorActionPreference = 'Stop'
$bdRoot = Split-Path $PSScriptRoot -Parent
$bdRuntime = [IO.Path]::GetFullPath($Scratch)
if (!(Test-Path -LiteralPath (Join-Path $LuaCsPackage 'filelist.xml')) -or !(Test-Path -LiteralPath (Join-Path $LuaCsPackage 'Config/SettingsShared.xml'))) { throw 'Supply the installed official LuaCs package directory.' }
if (Test-Path -LiteralPath $bdRuntime) { throw 'Use a new isolated runtime directory; existing data will not be overwritten.' }
[IO.Directory]::CreateDirectory($bdRuntime) | Out-Null
# All copies are private to this test. Content is a read-only reference in practice;
# the test code never edits game assets or the real game's config.
foreach ($bdFile in Get-ChildItem -LiteralPath $GameRoot -File) {
    if ($bdFile.Extension -in @('.dll','.exe','.json') -and $bdFile.Name -notmatch 'DedicatedServer|createdump') {
        Copy-Item -LiteralPath $bdFile.FullName -Destination $bdRuntime
    }
}
foreach ($bdDirectory in @('Content','DLC','Lua','Publicized','x64')) {
    $bdSource = Join-Path $GameRoot $bdDirectory
    if (Test-Path -LiteralPath $bdSource) {
        if ($bdDirectory -in @('Publicized','x64')) { Copy-Item -LiteralPath $bdSource -Destination $bdRuntime -Recurse }
        else { New-Item -ItemType Junction -Path (Join-Path $bdRuntime $bdDirectory) -Target $bdSource | Out-Null }
    }
}
$bdPackage = Join-Path $bdRuntime 'LocalMods/BaroEditor'
[IO.Directory]::CreateDirectory($bdPackage) | Out-Null
Copy-Item -LiteralPath (Join-Path $bdRoot 'CSharp') -Destination $bdPackage -Recurse
Copy-Item -LiteralPath (Join-Path $bdRoot 'filelist.xml') -Destination $bdPackage
Copy-Item -LiteralPath (Join-Path $bdRoot 'ModConfig.xml') -Destination $bdPackage
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'GameValidation.cs') -Destination (Join-Path $bdPackage 'CSharp/Client/GameValidation.cs')
$bdLuaCs = Join-Path $bdRuntime 'LocalMods/LuaCsForBarotrauma'
Copy-Item -LiteralPath $LuaCsPackage -Destination $bdLuaCs -Recurse
# This policy applies only to the throwaway copy, never the user's LuaCs settings.
$bdLuaCsSettings = [xml][IO.File]::ReadAllText((Join-Path $bdLuaCs 'Config/SettingsShared.xml'))
$bdPolicy = $bdLuaCsSettings.SelectSingleNode('/Configuration/Settings/Setting[@Name="CsRunPolicy"]')
if ($null -eq $bdPolicy) { throw 'The supplied LuaCs package has no supported C# policy setting.' }
$bdPolicy.SetAttribute('Value','Enabled')
$bdLuaCsSettings.Save((Join-Path $bdLuaCs 'Config/SettingsShared.xml'))
$bdConfig = [xml]'<config language="Simplified Chinese" verboselogging="true" savedebugconsolelogs="true"><graphicssettings display="0" width="1280" height="900" displaymode="Windowed" vsync="true" framelimit="60" textscale="1" hudscale="1"/><contentpackages><corepackage path="Content/ContentPackages/Vanilla.xml"/><regularpackages/></contentpackages></config>'
$bdConfig.config.SetAttribute('savepath', (Join-Path $bdRuntime 'Saves'))
$bdConfig.config.SetAttribute('savedebugconsolelogs','true')
$bdConfig.config.SetAttribute('splashscreens','false')
$bdRegular = $bdConfig.SelectSingleNode('/config/contentpackages/regularpackages')
$bdRegular.RemoveAll()
$bdEnableLuaCs = $bdConfig.CreateElement('package')
$bdEnableLuaCs.SetAttribute('path','LocalMods/LuaCsForBarotrauma/filelist.xml')
[void]$bdRegular.AppendChild($bdEnableLuaCs)
$bdEnable = $bdConfig.CreateElement('package')
$bdEnable.SetAttribute('path','LocalMods/BaroEditor/filelist.xml')
[void]$bdRegular.AppendChild($bdEnable)
$bdConfig.Save((Join-Path $bdRuntime 'config_player.xml'))
'<LuaCsSetupConfig EnableCsScripting="true" TreatForcedModsAsNormal="true" PreferToUseWorkshopLuaSetup="false" DisableErrorGUIOverlay="true" HideUserNames="true" />' | Set-Content -LiteralPath (Join-Path $bdRuntime 'LuaCsSetupConfig.xml') -Encoding utf8
[pscustomobject]@{runtime=$bdRuntime;package=$bdPackage;realConfigUntouched=$true;testOnlyValidationSource=$true} | ConvertTo-Json
