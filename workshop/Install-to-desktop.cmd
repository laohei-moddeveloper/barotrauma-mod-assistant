@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "ASSISTANT_INSTALL_LANGUAGE=en"
call "%~dp0安装到桌面.cmd"
exit /b %errorlevel%
