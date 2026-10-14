param([Parameter(Mandatory=$true)][string]$GameRoot,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
[Reflection.Assembly]::LoadFrom((Join-Path $GameRoot 'Mono.Cecil.dll')) | Out-Null
$beResolver=[Mono.Cecil.DefaultAssemblyResolver]::new()
$beResolver.AddSearchDirectory([IO.Path]::GetFullPath($GameRoot))
$beOptions=[Mono.Cecil.ReaderParameters]::new(); $beOptions.AssemblyResolver=$beResolver
$beModule=[Mono.Cecil.ModuleDefinition]::ReadModule((Join-Path $GameRoot 'Barotrauma.dll'),$beOptions)
$beActions=foreach($beType in $beModule.Types) {
    if($beType.IsAbstract) {continue}
    $beChain=[Collections.Generic.List[object]]::new(); $beParent=$beType; $beIsAction=$false
    while($null -ne $beParent) { $beChain.Add($beParent); if($beParent.FullName -eq 'Barotrauma.EventAction') {$beIsAction=$true;break}; if($null -eq $beParent.BaseType) {break}; try {$beParent=$beParent.BaseType.Resolve()} catch {break} }
    if(!$beIsAction) {continue}
    $beProps=foreach($beProperty in $beChain | ForEach-Object Properties) {
        $beAttribute=$beProperty.CustomAttributes | Where-Object {$_.AttributeType.FullName -eq 'Barotrauma.Serialize'} | Select-Object -First 1
        if(!$beAttribute) {continue}
        $beValue=$beAttribute.ConstructorArguments[0].Value
        while($beValue -is [Mono.Cecil.CustomAttributeArgument]) {$beValue=$beValue.Value}
        $beDefault=if($beValue -is [bool]) {$beValue.ToString().ToLowerInvariant()} else {[Convert]::ToString($beValue,[Globalization.CultureInfo]::InvariantCulture)}
        $beChoices=@(); try {$beResolved=$beProperty.PropertyType.Resolve(); if($beResolved.IsEnum) {$beChoices=@($beResolved.Fields | Where-Object IsLiteral | ForEach-Object Name); $beEnum=$beResolved.Fields | Where-Object {$_.IsLiteral -and $_.Constant -eq $beValue} | Select-Object -First 1; if($beEnum) {$beDefault=$beEnum.Name} }} catch {}
        [pscustomobject]@{name=$beProperty.Name.ToLowerInvariant();type=$beProperty.PropertyType.Name;default=$beDefault;choices=$beChoices}
    }
    [pscustomobject]@{name=$beType.Name;properties=@($beProps | Sort-Object name -Unique)}
}
$beResult=[pscustomobject]@{gameVersion=$beModule.Assembly.Name.Version.ToString();actions=@($beActions | Sort-Object name)}
[IO.Directory]::CreateDirectory((Split-Path ([IO.Path]::GetFullPath($Output)) -Parent)) | Out-Null
[IO.File]::WriteAllText([IO.Path]::GetFullPath($Output),($beResult | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
$beResult.actions.Count
$beModule.Dispose();$beResolver.Dispose()
