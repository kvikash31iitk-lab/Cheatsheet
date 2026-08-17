@echo off
set "PROJECT_ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%Generate-YTSummary.ps1" %*
echo.
pause
