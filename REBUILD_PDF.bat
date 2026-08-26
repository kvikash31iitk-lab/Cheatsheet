@echo off
title Cheatsheet AI - Markdown to PDF Converter
cd /d "%~dp0"

if "%~1"=="" (
    echo ================================================================
    echo    Cheatsheet AI - Drag-and-Drop Markdown to PDF Generator
    echo ================================================================
    echo.
    echo  HOW TO USE:
    echo  1. Drag and drop any .md file onto this batch file icon.
    echo  OR
    echo  2. Type the path to your .md file below:
    echo.
    set /p "MD_FILE=Enter markdown file path: "
) else (
    set "MD_FILE=%~1"
)

if "%MD_FILE%"=="" (
    echo No file specified. Exiting...
    pause
    exit /b 0
)

:: Strip surrounding quotes if present
set MD_FILE=%MD_FILE:"=%

if not exist "%MD_FILE%" (
    echo [ERROR] File not found: "%MD_FILE%"
    pause
    exit /b 1
)

:: Use virtual environment python if present
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXEC=%~dp0.venv\Scripts\python.exe"
) else (
    set "PY_EXEC=python"
)

echo.
echo [*] Converting Markdown to PDF: "%MD_FILE%"...
"%PY_EXEC%" "%~dp0scripts\rebuild_pdf.py" "%MD_FILE%"

echo.
echo ================================================================
echo  Done! Your PDF has been saved next to the markdown file.
echo ================================================================
pause
