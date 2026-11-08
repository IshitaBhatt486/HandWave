@echo off
setlocal
cd /d "%~dp0"
echo === HandWave release build ===
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1" %*
exit /b %errorlevel%
