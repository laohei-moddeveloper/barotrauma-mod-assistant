param([Parameter(Mandatory=$true)][string]$GameRoot,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
[Reflection.Assembly]::LoadFrom((Join-Path $GameRoot 'Mono.Cecil.dll')) | Out-Null
$bdResolver = [Mono.Cecil.DefaultAssemblyResolver]::new()
$bdResolver.AddSearchDirectory([IO.Path]::GetFullPath($GameRoot))
$bdOptions = [Mono.Cecil.ReaderParameters]::new(); $bdOptions.AssemblyResolver = $bdResolver
$bdModule = [Mono.Cecil.ModuleDefinition]::ReadModule((Join-Path $GameRoot 'Barotrauma.dll'), $bdOptions)
function Get-BdTypes($Types) {
    foreach ($bdType in $Types) { $bdType; if ($bdType.HasNestedTypes) { Get-BdTypes $bdType.NestedTypes } }
}
$bdActions = foreach ($bdType in Get-BdTypes $bdModule.Types) {
    if ($bdType.IsAbstract) { continue }
    $bdChain = [Collections.Generic.List[object]]::new()
    $bdParent = $bdType
    $bdIsAction = $false
    while ($null -ne $bdParent) {
        $bdChain.Add($bdParent)
        if ($bdParent.FullName -eq 'Barotrauma.EventAction') { $bdIsAction = $true; break }
        if ($null -eq $bdParent.BaseType) { break }
        try { $bdParent = $bdParent.BaseType.Resolve() } catch { break }
    }
    if (!$bdIsAction) { continue }
    $bdHints = @($bdChain | ForEach-Object { $_.Properties } | Where-Object { @($_.CustomAttributes | Where-Object { $_.AttributeType.FullName -eq 'Barotrauma.Serialize' }).Count -gt 0 } | ForEach-Object { $_.Name.ToLowerInvariant() } | Sort-Object -Unique)
    [pscustomobject]@{name=$bdType.Name;properties=$bdHints}
}
$bdActions = @($bdActions | Sort-Object name)
if (@($bdActions | Group-Object name | Where-Object Count -gt 1).Count -gt 0) { throw 'Duplicate vanilla Action names.' }
foreach ($bdRequired in @('ConversationAction','TagAction','WaitAction','GoTo','Label','StatusEffectAction')) {
    if ($bdRequired -notin $bdActions.name) { throw "Missing vanilla action: $bdRequired" }
}
$bdResult = [pscustomobject]@{gameVersion=$bdModule.Assembly.Name.Version.ToString();actionCount=$bdActions.Count;serializedPropertyCount=@($bdActions | ForEach-Object properties).Count;actions=$bdActions}
if ($bdResult.serializedPropertyCount -lt 100 -or 'targettag' -notin ($bdActions | Where-Object name -eq ConversationAction).properties) { throw 'Vanilla serialized properties were not discovered.' }
$bdResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Output -Encoding utf8
$bdResult | Select-Object gameVersion,actionCount,serializedPropertyCount | ConvertTo-Json
$bdModule.Dispose(); $bdResolver.Dispose()
