@echo off
title Cheatsheet AI - Local Desktop Engine
cd /d "%~dp0"

echo ================================================================
echo    Cheatsheet AI - 1-Click Desktop Launcher (Home PC Edition)
echo ================================================================
echo.

:: 1. Check Python installation
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in your system PATH!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo (Make sure to check "Add Python to PATH" during installation)
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

:: 3. Check / Create Virtual Environment
if not exist ".venv" (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    echo [*] Installing dependencies into .venv...
    .venv\Scripts\pip install -r requirements.txt
)

:: 4. Use virtual environment python if present
if exist ".venv\Scripts\python.exe" (
    set "PY_EXEC=.venv\Scripts\python.exe"
) else (
    set "PY_EXEC=python"
)

:: 5. Launch Desktop Engine
echo [*] Starting Cheatsheet Local Engine...
%PY_EXEC% scripts\launch_desktop_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [*] If dependencies are missing, run SETUP_DEPENDENCIES.bat
    pause
)
