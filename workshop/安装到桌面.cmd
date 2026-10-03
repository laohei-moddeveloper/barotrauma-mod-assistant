@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "ASSISTANT_WORKSHOP_PACKAGE=%~dp0"
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; try { function Hash-File([string]$path) { $hasher=[Security.Cryptography.SHA256]::Create(); try { ([BitConverter]::ToString($hasher.ComputeHash([IO.File]::ReadAllBytes($path)))).Replace('-','') } finally { $hasher.Dispose() } }; $source=Join-Path $env:ASSISTANT_WORKSHOP_PACKAGE 'BarotraumaModAssistant.exe'; $hashFile=Join-Path $env:ASSISTANT_WORKSHOP_PACKAGE 'SHA256SUMS.txt'; if (!(Test-Path -LiteralPath $source) -or !(Test-Path -LiteralPath $hashFile)) { throw '工坊下载尚未完成，缺少程序或校验文件。' }; $line=@(Get-Content -LiteralPath $hashFile -Encoding UTF8 | Where-Object { $_ -match '^[a-f0-9]{64}  BarotraumaModAssistant\.exe$' }); if ($line.Count -ne 1) { throw '程序校验记录不正确。' }; $expected=$line[0].Substring(0,64); if ((Hash-File $source) -ine $expected) { throw '程序校验失败，请重新下载工坊项目。' }; $program=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'BarotraumaModAssistant\WorkshopProgram'; $target=Join-Path $program 'BarotraumaModAssistant.exe'; if (Get-Process -Name BarotraumaModAssistant -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $target }) { throw '请先退出正在运行的工坊版助手，再更新桌面版。' }; New-Item -ItemType Directory -Path $program -Force | Out-Null; Copy-Item -LiteralPath $source -Destination $target -Force; if ((Hash-File $target) -ine $expected) { throw '复制后的程序校验失败。' }; $shell=New-Object -ComObject WScript.Shell; $link=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '潜渊症模组更新助手（工坊版）.lnk')); $link.TargetPath=$target; $link.WorkingDirectory=$program; $link.IconLocation=$target; $link.Description='潜渊症模组更新助手 v0.5.0 - 工坊分发版'; $link.Save(); Write-Host '已创建桌面入口：潜渊症模组更新助手（工坊版）'; Write-Host '个人设置已保留；以后从桌面启动助手即可。'; exit 0; } catch { Write-Host ('创建失败：'+$_.Exception.Message); exit 1 }"
if errorlevel 1 (
  pause
  exit /b 1
)
pause
exit /b 0
