param([Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$bdRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$bdOutput = [IO.Path]::GetFullPath($Output)
if ($bdOutput.StartsWith($bdRoot.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -or $bdOutput -eq $bdRoot) { throw 'Package output must be outside the source directory.' }
if (Test-Path -LiteralPath $bdOutput) { throw 'Use a new release directory; existing files will not be overwritten.' }
[IO.Directory]::CreateDirectory($bdOutput) | Out-Null
$bdWorkshop = Join-Path $bdOutput 'workshop/BaroEditor'
[IO.Directory]::CreateDirectory($bdWorkshop) | Out-Null
$bdRuntimeFiles = @('CSharp/Shared/EventDocument.cs','CSharp/Client/Plugin.cs','CSharp/Client/Editor.cs','ModConfig.xml','filelist.xml','README.md','LICENSE','docs/ACCESS.md','publishing/cover.png')
foreach ($bdRelative in $bdRuntimeFiles) {
    $bdTarget = Join-Path $bdWorkshop $bdRelative
    [IO.Directory]::CreateDirectory((Split-Path $bdTarget -Parent)) | Out-Null
    Copy-Item -LiteralPath (Join-Path $bdRoot $bdRelative) -Destination $bdTarget
}
$bdSource = Join-Path $bdOutput 'source/BaroEditor'
[IO.Directory]::CreateDirectory($bdSource) | Out-Null
$bdSourceFiles = @($bdRuntimeFiles + @('CHANGELOG.md','.gitignore','docs/VALIDATION.md','tests/CoreTests.cs','tests/CoreTests.csproj','tools/verify_compile.ps1','tools/verify_catalog.ps1','tools/prepare_game_test.ps1','tools/auto_test_boot.ps1','tools/GameValidation.cs','tools/package.ps1','publishing/steam-zh.txt','publishing/steam-en.txt','publishing/release-notes.md','publishing/batch.png'))
foreach ($bdRelative in $bdSourceFiles) {
    $bdTarget = Join-Path $bdSource $bdRelative
    [IO.Directory]::CreateDirectory((Split-Path $bdTarget -Parent)) | Out-Null
    Copy-Item -LiteralPath (Join-Path $bdRoot $bdRelative) -Destination $bdTarget
}
$bdActual = @(Get-ChildItem -LiteralPath $bdWorkshop -File -Recurse)
if ($bdActual.Count -ne $bdRuntimeFiles.Count -or @($bdActual | Where-Object { $_.Extension -eq '.dll' -or $_.Name -eq 'GameValidation.cs' }).Count -gt 0) { throw 'Runtime allowlist validation failed.' }
Compress-Archive -LiteralPath $bdWorkshop -DestinationPath (Join-Path $bdOutput 'BaroEditor-0.1.0.zip')
Compress-Archive -LiteralPath $bdSource -DestinationPath (Join-Path $bdOutput 'BaroEditor-0.1.0-source.zip')
$bdManifest = foreach ($bdFile in $bdActual) {
    [pscustomobject]@{path=$bdFile.FullName.Substring($bdWorkshop.Length+1).Replace('\','/');bytes=$bdFile.Length;sha256=(Get-FileHash -LiteralPath $bdFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$bdArchives = @(Get-ChildItem -LiteralPath $bdOutput -Filter '*.zip' | ForEach-Object { [pscustomobject]@{name=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()} })
[pscustomobject]@{version='0.1.0';releaseChannel='preview';inGameAcceptance='basic-ui-and-metadata';runtime=$bdManifest;archives=$bdArchives} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $bdOutput 'manifest.json') -Encoding utf8
[pscustomobject]@{output=$bdOutput;runtimeFiles=$bdActual.Count;runtimeBytes=($bdActual | Measure-Object Length -Sum).Sum;archives=$bdArchives} | ConvertTo-Json -Depth 5
