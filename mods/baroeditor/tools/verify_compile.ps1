param([Parameter(Mandatory=$true)][string]$GameRoot,[Parameter(Mandatory=$true)][string]$Scratch,[switch]$IncludeValidationHarness)
$ErrorActionPreference = 'Stop'
$bdRoot = Split-Path $PSScriptRoot -Parent
$bdScratch = [IO.Path]::GetFullPath($Scratch)
[IO.Directory]::CreateDirectory($bdScratch) | Out-Null
foreach ($bdDll in @('Mono.Cecil.dll','Microsoft.CodeAnalysis.dll','Microsoft.CodeAnalysis.CSharp.dll')) {
    [Reflection.Assembly]::LoadFrom((Join-Path $GameRoot $bdDll)) | Out-Null
}
function Set-BdPublicType($Type) {
    if ($Type.IsNested) { $Type.IsNestedPublic = $true } else { $Type.IsPublic = $true }
    foreach ($bdMethod in $Type.Methods) { $bdMethod.IsPublic = $true }
    foreach ($bdField in $Type.Fields) { $bdField.IsPublic = $true }
    foreach ($bdNested in $Type.NestedTypes) { Set-BdPublicType $bdNested }
}
$bdReferences = [Collections.Generic.List[Microsoft.CodeAnalysis.MetadataReference]]::new()
foreach ($bdFile in Get-ChildItem -LiteralPath $GameRoot -Filter '*.dll') {
    if ($bdFile.Name -eq 'DedicatedServer.dll') { continue }
    try { [Reflection.AssemblyName]::GetAssemblyName($bdFile.FullName) | Out-Null } catch { continue }
    $bdReference = $bdFile.FullName
    if ($bdFile.Name -in @('Barotrauma.dll','BarotraumaCore.dll')) {
        $bdResolver = [Mono.Cecil.DefaultAssemblyResolver]::new()
        $bdResolver.AddSearchDirectory([IO.Path]::GetFullPath($GameRoot))
        $bdOptions = [Mono.Cecil.ReaderParameters]::new(); $bdOptions.AssemblyResolver = $bdResolver
        $bdModule = [Mono.Cecil.ModuleDefinition]::ReadModule($bdFile.FullName, $bdOptions)
        foreach ($bdType in $bdModule.Types) { Set-BdPublicType $bdType }
        $bdReference = Join-Path $bdScratch $bdFile.Name
        $bdModule.Write($bdReference); $bdModule.Dispose()
    }
    $bdReferences.Add([Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($bdReference))
}
$bdParse = [Microsoft.CodeAnalysis.CSharp.CSharpParseOptions]::Default.WithPreprocessorSymbols([string[]]@('CLIENT'))
function Compile-Bd($Name, $Files, $Kind) {
    $bdTrees = [Collections.Generic.List[Microsoft.CodeAnalysis.SyntaxTree]]::new()
    foreach ($bdSource in $Files) { $bdTrees.Add([Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText([IO.File]::ReadAllText($bdSource), $bdParse, $bdSource)) }
    $bdCompileOptions = [Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new($Kind)
    $bdCompilation = [Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create($Name, $bdTrees.ToArray(), $bdReferences.ToArray(), $bdCompileOptions)
    $bdStream = [IO.MemoryStream]::new(); $bdEmit = $bdCompilation.Emit($bdStream)
    $bdDiagnostics = @($bdEmit.Diagnostics | ForEach-Object { $_.ToString() })
    if (!$bdEmit.Success) { $bdStream.Dispose(); throw ($bdDiagnostics -join "`n") }
    [IO.File]::WriteAllBytes((Join-Path $bdScratch ($Name + '.dll')), $bdStream.ToArray()); $bdStream.Dispose()
    [pscustomobject]@{name=$Name;success=$bdEmit.Success;diagnostics=$bdDiagnostics}
}
$bdShared = @(Get-ChildItem -LiteralPath (Join-Path $bdRoot 'CSharp/Shared') -Filter '*.cs' | ForEach-Object FullName)
$bdClient = @(Get-ChildItem -LiteralPath (Join-Path $bdRoot 'CSharp/Client') -Filter '*.cs' | ForEach-Object FullName)
$bdResults = @(
    Compile-Bd 'BaroEditor.Client' ($bdShared + $bdClient) ([Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary)
    Compile-Bd 'BaroEditor.Tests' ($bdShared + @(Join-Path $bdRoot 'tests/CoreTests.cs')) ([Microsoft.CodeAnalysis.OutputKind]::ConsoleApplication)
)
if ($IncludeValidationHarness) {
    $bdResults += Compile-Bd 'BaroEditor.Validation' ($bdShared + $bdClient + @(Join-Path $PSScriptRoot 'GameValidation.cs')) ([Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary)
}
'{"runtimeOptions":{"tfm":"net8.0","framework":{"name":"Microsoft.NETCore.App","version":"8.0.0"}}}' | Set-Content -LiteralPath (Join-Path $bdScratch 'BaroEditor.Tests.runtimeconfig.json') -Encoding utf8
$bdResults | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $bdScratch 'compile-results.json') -Encoding utf8
$bdResults | ConvertTo-Json -Depth 6
