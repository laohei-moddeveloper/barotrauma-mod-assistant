$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$buildPython = Join-Path $projectRoot '.build-tools\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    throw '请先用 Python 3.12 创建 .build-tools 虚拟环境并安装 PyInstaller 6。'
}
Push-Location -LiteralPath $projectRoot
try {
    & $buildPython -m PyInstaller --noconfirm BarotraumaModAssistant.spec
    if ($LASTEXITCODE -ne 0) { throw '打包失败' }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'dist\BarotraumaModAssistant.exe') -Destination (Join-Path $projectRoot 'dist\潜渊症模组更新助手.exe') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot '使用说明.md') -Destination (Join-Path $projectRoot 'dist\使用说明.md') -Force
} finally {
    Pop-Location
}
