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

:: 2. If not a git repo, check if main project workspace exists
set "MAIN_WS=C:\Users\Vikash PC\OneDrive\Desktop\claude projects\cheetsheet"
if exist "%MAIN_WS%\scripts\build_cheatsheet.py" (
    echo [*] Syncing latest engine files from workspace...
    xcopy /Y /E /I "%MAIN_WS%\scripts\*.py" "%~dp0scripts\" >nul
    xcopy /Y /E /I "%MAIN_WS%\api\*.py" "%~dp0api\" >nul
    xcopy /Y /E /I "%MAIN_WS%\bot\*.py" "%~dp0bot\" >nul
    copy /Y "%MAIN_WS%\version.json" "%~dp0version.json" >nul
    copy /Y "%MAIN_WS%\requirements.txt" "%~dp0requirements.txt" >nul
    echo [OK] Engine files updated to latest version!
    goto :UPDATE_DEPENDENCIES
)

:UPDATE_DEPENDENCIES
:: 3. Update python dependencies if .venv exists
if exist "%~dp0.venv\Scripts\pip.exe" (
    echo [*] Checking and updating Python dependencies...
    "%~dp0.venv\Scripts\pip.exe" install -q -r "%~dp0requirements.txt"
)

echo.
echo ================================================================
echo  [SUCCESS] Cheatsheet Desktop has been updated to the latest version!
echo  Double-click START_CHEATSHEET.bat to launch.
echo ================================================================
echo.
pause
