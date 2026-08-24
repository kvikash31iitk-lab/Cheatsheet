@echo off
title Cheatsheet AI - Dependency Setup
cd /d "%~dp0"

echo ================================================================
echo    Cheatsheet AI - 1-Click Dependency Installer
echo ================================================================
echo.

:: 1. Setup Python Virtualenv & install requirements
echo [1/2] Setting up Python dependencies...
if not exist ".venv" (
    python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt

:: 2. Setup Web Frontend if node is present
where npm >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [2/2] Setting up Web Frontend (Node.js)...
    cd web
    call npm install
    call npm run build
    cd ..
) else (
    echo.
    echo [2/2] Node.js not found in PATH (optional). The app will run in local backend mode.
)

echo.
echo ================================================================
echo  Setup complete! Double-click START_CHEATSHEET.bat to launch!
echo ================================================================
pause
