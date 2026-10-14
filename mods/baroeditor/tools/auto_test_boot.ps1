param([Parameter(Mandatory=$true)][string]$Runtime)
$ErrorActionPreference='Stop'
$bdRuntime=[IO.Path]::GetFullPath($Runtime)
if (!(Test-Path -LiteralPath (Join-Path $bdRuntime 'LocalMods/BaroEditor/CSharp/Client/GameValidation.cs'))) {
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
# The new LuaCs backend can require a reload after initial package discovery.
# Request it once after the copied client reaches the main menu. This is a
# development bootstrap, not input injection or a permission-policy change.
$bdUpdate=$bdGame.Methods | Where-Object { $_.Name -eq 'Update' -and $_.HasBody -and $_.Parameters.Count -eq 1 }
if (@($bdUpdate).Count -ne 1) { throw 'Unrecognized update routine; no patch made' }
$bdMenu=$bdGame.Fields | Where-Object Name -eq 'MainMenuScreen'
$bdScreen=$bdModule.Types | Where-Object Name -eq 'Screen'
$bdSelected=$bdScreen.Methods | Where-Object Name -eq 'get_Selected'
$bdConsole=$bdModule.Types | Where-Object Name -eq 'DebugConsole'
$bdExecute=$bdConsole.Methods | Where-Object { $_.Name -eq 'ExecuteCommand' -and $_.Parameters.Count -eq 1 }
$bdFrames=[Mono.Cecil.FieldDefinition]::new('BaroEditorTestBootFrames',([Mono.Cecil.FieldAttributes]::Private -bor [Mono.Cecil.FieldAttributes]::Static),$bdModule.TypeSystem.Int32)
$bdGame.Fields.Add($bdFrames)
$bdUpdateIL=$bdUpdate.Body.GetILProcessor()
$bdOriginalStart=$bdUpdate.Body.Instructions[0]
$bdBoot=@(
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldsfld,$bdMenu)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Brfalse,$bdOriginalStart)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Call,$bdSelected)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldsfld,$bdMenu)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Bne_Un,$bdOriginalStart)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldsfld,$bdFrames)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldc_I4_1)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Add)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Stsfld,$bdFrames)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldsfld,$bdFrames)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldc_I4,60)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Bne_Un,$bdOriginalStart)
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldstr,'cl_reloadluacs')
    [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Call,$bdExecute)
)
foreach ($bdInstruction in $bdBoot) { $bdUpdateIL.InsertBefore($bdOriginalStart,$bdInstruction) }
$bdModule.Write($bdFile);$bdModule.Dispose()
[pscustomobject]@{isolatedRuntime=$bdRuntime;autoEnterMainMenu=$true;oneTestLuaCsReload=$true;realGameUntouched=$true} | ConvertTo-Json
