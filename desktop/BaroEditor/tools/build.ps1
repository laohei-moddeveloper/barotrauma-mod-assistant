param([Parameter(Mandatory=$true)][string]$Output,[string]$RoslynDirectory='D:/steam/steamapps/common/Barotrauma',[string]$RuntimeRoot='C:/Program Files/dotnet',[switch]$Validation,[switch]$Interaction,[switch]$Tests)
$ErrorActionPreference='Stop'
$beRoot=[IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent)); $beOutput=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $beOutput) {throw 'Use a new output directory.'}
[IO.Directory]::CreateDirectory($beOutput) | Out-Null
foreach($beDll in @('Microsoft.CodeAnalysis.dll','Microsoft.CodeAnalysis.CSharp.dll')) {[Reflection.Assembly]::LoadFrom((Join-Path $RoslynDirectory $beDll)) | Out-Null}
$beCore=Get-ChildItem -LiteralPath (Join-Path $RuntimeRoot 'shared/Microsoft.NETCore.App') -Directory | Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1
$beDesktop=Get-Item -LiteralPath (Join-Path $RuntimeRoot ('shared/Microsoft.WindowsDesktop.App/'+$beCore.Name))
$beRefs=[Collections.Generic.List[Microsoft.CodeAnalysis.MetadataReference]]::new()
foreach($beDll in @(Get-ChildItem -LiteralPath $beCore.FullName -Filter '*.dll')+@(Get-ChildItem -LiteralPath $beDesktop.FullName -Filter '*.dll')) {
    try {[Reflection.AssemblyName]::GetAssemblyName($beDll.FullName) | Out-Null} catch {continue}
    $beRefs.Add([Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($beDll.FullName))
}
$beSymbols=if($Interaction) {[string[]]@('VALIDATION','INTERACTION')} elseif($Validation) {[string[]]@('VALIDATION')} else {[string[]]@()}
$beParse=[Microsoft.CodeAnalysis.CSharp.CSharpParseOptions]::Default.WithPreprocessorSymbols([string[]]$beSymbols)
function Emit-BE($Name,$Files,$References,$Kind) {
    $beTrees=[Collections.Generic.List[Microsoft.CodeAnalysis.SyntaxTree]]::new()
    foreach($beFile in $Files) {$beTrees.Add([Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText([IO.File]::ReadAllText($beFile),$beParse,$beFile))}
    $beOptions=[Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new($Kind).WithOptimizationLevel([Microsoft.CodeAnalysis.OptimizationLevel]::Release)
    if($Name -eq 'BaroEditor.Desktop.Tests') {$beOptions=$beOptions.WithMainTypeName('StandaloneTests')}
    $beCompilation=[Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create($Name,$beTrees.ToArray(),[Microsoft.CodeAnalysis.MetadataReference[]]$References,$beOptions)
    $beStream=[IO.MemoryStream]::new();$beResource=$null;$beManifest=$null
    if($Name -eq 'BaroEditor') {$beManifest=[IO.File]::OpenRead((Join-Path $beRoot 'app.manifest')); $beResource=$beCompilation.CreateDefaultWin32Resources($true,$false,$beManifest,$null)}
    $beEmit=$beCompilation.Emit($beStream,$null,$null,$beResource)
    if($beResource) {$beResource.Dispose()}; if($beManifest) {$beManifest.Dispose()}
    $beDiagnostics=@($beEmit.Diagnostics | Where-Object {$_.Severity -ne [Microsoft.CodeAnalysis.DiagnosticSeverity]::Hidden} | ForEach-Object ToString)
    if(!$beEmit.Success) {$beStream.Dispose(); throw ($beDiagnostics -join "`n")}
    $beExtension=if($Name -eq 'BaroEditor') {'.exe'} else {'.dll'}
    [IO.File]::WriteAllBytes((Join-Path $beOutput ($Name+$beExtension)),$beStream.ToArray());$beStream.Dispose()
    [pscustomobject]@{name=$Name;success=$true;diagnostics=$beDiagnostics}
}
$beSources=@(Get-ChildItem -LiteralPath $beRoot -Filter '*.cs' | ForEach-Object FullName)+@(Get-ChildItem -LiteralPath (Join-Path $beRoot 'Core') -Filter '*.cs' | ForEach-Object FullName)
$beResults=@(Emit-BE 'BaroEditor.Desktop' $beSources ($beRefs.ToArray()) ([Microsoft.CodeAnalysis.OutputKind]::WindowsApplication))
$beFramework='C:/Windows/Microsoft.NET/Framework64/v4.0.30319'
$beLauncherRefs=@('mscorlib.dll','System.dll','System.Core.dll','System.Windows.Forms.dll') | ForEach-Object {[Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile((Join-Path $beFramework $_))}
$beResults+=Emit-BE 'BaroEditor' @((Join-Path $beRoot 'Launcher.cs.source')) $beLauncherRefs ([Microsoft.CodeAnalysis.OutputKind]::WindowsApplication)
$beRuntime=@{runtimeOptions=@{tfm='net10.0';frameworks=@(@{name='Microsoft.NETCore.App';version=$beCore.Name},@{name='Microsoft.WindowsDesktop.App';version=$beCore.Name});rollForward='LatestPatch'}}
[IO.File]::WriteAllText((Join-Path $beOutput 'BaroEditor.Desktop.runtimeconfig.json'),($beRuntime | ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $beRoot 'Assets') -Destination $beOutput -Recurse
if(Test-Path -LiteralPath (Join-Path $beRoot 'README.md')) {Copy-Item -LiteralPath (Join-Path $beRoot 'README.md') -Destination $beOutput}
Copy-Item -LiteralPath (Join-Path $beRoot 'LICENSE') -Destination $beOutput
if($Tests) {
    $beTestFiles=@(Get-ChildItem -LiteralPath (Join-Path $beRoot 'Core') -Filter '*.cs' | ForEach-Object FullName)+@(Get-ChildItem -LiteralPath (Join-Path $beRoot 'tests') -Filter '*.cs' | ForEach-Object FullName)
    $beResults+=Emit-BE 'BaroEditor.Desktop.Tests' $beTestFiles ($beRefs.ToArray()) ([Microsoft.CodeAnalysis.OutputKind]::ConsoleApplication)
    [IO.File]::WriteAllText((Join-Path $beOutput 'BaroEditor.Desktop.Tests.runtimeconfig.json'),($beRuntime | ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
}
$beResults | ConvertTo-Json -Depth 5
