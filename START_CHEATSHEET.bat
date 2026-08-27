@echo off
title Cheatsheet AI - Local Desktop Engine
cd /d "%~dp0"

echo ================================================================
echo    Cheatsheet AI - 1-Click Desktop Launcher
echo ================================================================
echo.

:: 1. Detect Python executable
set "PY_EXEC="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXEC=%~dp0.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% EQU 0 set "PY_EXEC=python"
    if not defined PY_EXEC if exist "C:\Python314\python.exe" set "PY_EXEC=C:\Python314\python.exe"
    if not defined PY_EXEC if exist "C:\Python312\python.exe" set "PY_EXEC=C:\Python312\python.exe"
    if not defined PY_EXEC if exist "C:\Python311\python.exe" set "PY_EXEC=C:\Python311\python.exe"
    if not defined PY_EXEC if exist "C:\Python310\python.exe" set "PY_EXEC=C:\Python310\python.exe"
)

if not defined PY_EXEC (
    echo [ERROR] Python was not found on this system!
    echo Please install Python 3.10+ and make sure to check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: 2. Check for .env file, copy from .env.example if missing
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Initializing .env configuration from .env.example...
        copy ".env.example" ".env" >nul
    )
)

:: 3. Launch Desktop Engine
echo [*] Starting Cheatsheet Local Engine...
"%PY_EXEC%" "%~dp0scripts\launch_desktop_app.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Cheatsheet desktop process stopped.
    pause
)
