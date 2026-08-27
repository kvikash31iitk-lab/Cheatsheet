@echo off
title Cheatsheet AI - 1-Click Auto Updater
cd /d "%~dp0"

echo ================================================================
echo    Cheatsheet AI - 1-Click Desktop Updater
echo ================================================================
echo.

:: 1. Check if git is available for instant sync
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    if exist ".git" (
        echo [*] Git repository detected. Pulling latest updates from GitHub...
        git pull origin main
        goto :UPDATE_DEPENDENCIES
    )
)

:: 2. Standalone Plug-and-Play Home PC Update (via Cloud Release)
echo [*] Standalone desktop installation detected.
echo [*] Downloading latest verified engine from cheetsheet.tech...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri 'https://cheetsheet.tech/downloads/Cheatsheet_Desktop_Latest.zip' -OutFile '%TEMP%\cheatsheet_latest.zip' -UseBasicParsing; Expand-Archive -Path '%TEMP%\cheatsheet_latest.zip' -DestinationPath '%TEMP%\cheatsheet_extracted' -Force; Copy-Item -Path '%TEMP%\cheatsheet_extracted\Cheatsheet_Desktop_*\scripts\*' -Destination '%~dp0scripts\' -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item -Path '%TEMP%\cheatsheet_extracted\Cheatsheet_Desktop_*\bot\*' -Destination '%~dp0bot\' -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item -Path '%TEMP%\cheatsheet_extracted\Cheatsheet_Desktop_*\api\*' -Destination '%~dp0api\' -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item -Path '%TEMP%\cheatsheet_extracted\Cheatsheet_Desktop_*\web\*' -Destination '%~dp0web\' -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item -Path '%TEMP%\cheatsheet_extracted\Cheatsheet_Desktop_*\version.json' -Destination '%~dp0version.json' -Force -ErrorAction SilentlyContinue; Remove-Item -Path '%TEMP%\cheatsheet_extracted', '%TEMP%\cheatsheet_latest.zip' -Recurse -Force -ErrorAction SilentlyContinue; Write-Host '[OK] Successfully updated engine to latest release!' -ForegroundColor Green } catch { Write-Host '[!] Cloud update error: ' $_.Exception.Message -ForegroundColor Red }"

:UPDATE_DEPENDENCIES
:: 3. Update python dependencies if .venv exists
if exist "%~dp0.venv\Scripts\pip.exe" (
    echo [*] Checking Python dependencies...
    "%~dp0.venv\Scripts\pip.exe" install -q -r "%~dp0requirements.txt"
)

echo.
echo ================================================================
echo  [SUCCESS] Cheatsheet Desktop is up to date!
echo  Double-click START_CHEATSHEET.bat to launch.
echo ================================================================
echo.
pause
