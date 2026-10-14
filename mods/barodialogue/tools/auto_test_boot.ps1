param([Parameter(Mandatory=$true)][string]$Runtime)
$ErrorActionPreference='Stop'
$bdRuntime=[IO.Path]::GetFullPath($Runtime)
if (!(Test-Path -LiteralPath (Join-Path $bdRuntime 'LocalMods/BaroDialogue/CSharp/Client/GameValidation.cs'))) {
    throw 'Only an isolated runtime containing the development validation harness may be changed.'
}
$bdConfig=[xml](Get-Content -LiteralPath (Join-Path $bdRuntime 'config_player.xml') -Raw)
if ($bdConfig.config.savepath -ne (Join-Path $bdRuntime 'Saves')) { throw 'Not an isolated test config' }
[Reflection.Assembly]::LoadFrom((Join-Path $bdRuntime 'Mono.Cecil.dll')) | Out-Null
$bdFile=Join-Path $bdRuntime 'Barotrauma.dll'
$bdOriginal=$bdFile+'.test-original'
if (!(Test-Path -LiteralPath $bdOriginal)) { Copy-Item -LiteralPath $bdFile -Destination $bdOriginal }
$bdResolver=[Mono.Cecil.DefaultAssemblyResolver]::new()
$bdResolver.AddSearchDirectory($bdRuntime)
$bdRead=[Mono.Cecil.ReaderParameters]::new();$bdRead.AssemblyResolver=$bdResolver
$bdModule=[Mono.Cecil.ModuleDefinition]::ReadModule($bdOriginal,$bdRead)
$bdGame=$bdModule.Types | Where-Object Name -eq 'GameMain'
$bdLoad=$bdGame.Methods | Where-Object { $_.Name -eq 'Load' -and $_.HasBody }
$bdAnchor=@($bdLoad.Body.Instructions | Where-Object { $_.OpCode.Code -eq [Mono.Cecil.Cil.Code]::Ldsfld -and $_.Operand.Name -eq 'MainMenuScreen' })
if ($bdAnchor.Count -ne 1) { throw 'Unrecognized loading routine; no patch made' }
$bdField=$bdGame.Fields | Where-Object Name -eq 'loadingScreenOpen'
$bdProcessor=$bdLoad.Body.GetILProcessor()
# Test fixture only: complete the loading screen immediately before normal
# MainMenu.Select(). No action, networking, permission, or editor logic changes.
$bdProcessor.InsertBefore($bdAnchor[0],[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldarg_0))
$bdProcessor.InsertBefore($bdAnchor[0],[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldc_I4_0))
$bdProcessor.InsertBefore($bdAnchor[0],[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Stfld,$bdField))
$bdModule.Write($bdFile);$bdModule.Dispose()
[pscustomobject]@{isolatedRuntime=$bdRuntime;autoEnterMainMenu=$true;realGameUntouched=$true} | ConvertTo-Json
