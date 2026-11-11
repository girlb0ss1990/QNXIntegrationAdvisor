@echo off
rem QNX Integration Advisor - double-click launcher for Windows.
rem First run: creates a private Python environment in .venv and installs the tool (needs internet).
rem Every run: starts the local web UI and opens it in your browser. Close this window to stop it.
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title QNX Integration Advisor
if not defined PORT set "PORT=8765"

echo.
echo   QNX Integration Advisor
echo   -----------------------

rem ---- 1. Python environment (first run only)
if not exist ".venv\Scripts\python.exe" (
    set "PY="
    for %%v in (3.13 3.12 3.14 3.11) do (
        if not defined PY (
            py -%%v -c "import sys" >nul 2>&1 && set "PY=py -%%v"
        )
    )
    if not defined PY (
        python -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] else 1)" >nul 2>&1 && set "PY=python"
    )
    if not defined PY goto :nopython
    echo   First run: creating a Python environment with !PY! ...
    !PY! -m venv .venv || goto :fail
)

rem ---- 2. Install or update the tool when pyproject.toml has changed
set "HASH="
for /f "delims=" %%h in ('certutil -hashfile pyproject.toml SHA256 ^| findstr /v ":"') do if not defined HASH set "HASH=%%h"
set "OLD="
if exist ".venv\.installed" set /p OLD=<".venv\.installed"
if not "!HASH!+llm"=="!OLD!" (
    echo   Installing the tool and its dependencies - this takes a minute the first time ...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip >nul 2>&1
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -e ".[llm]" || goto :fail
    > ".venv\.installed" echo !HASH!+llm
)

rem ---- 3. Web UI (shipped pre-built in advisor\static; rebuilt only if missing and Node is present)
if not exist "advisor\static\index.html" (
    where npm >nul 2>&1 || goto :noui
    echo   Building the web UI ...
    pushd web
    call npm ci --silent && call npm run build --silent
    popd
    if not exist "advisor\static\index.html" goto :fail
)

rem ---- 4. Run
echo   Starting on http://127.0.0.1:%PORT% - your browser will open shortly.
echo   Keep this window open while you use the tool. Close it to stop.
echo.
".venv\Scripts\python.exe" -m advisor.cli serve --port %PORT% --open
echo.
echo   The advisor has stopped.
pause
exit /b 0

:nopython
echo.
echo   Python 3.11 or newer is required and was not found.
echo   Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo   then double-click start.bat again.
echo.
pause
exit /b 1

:noui
echo.
echo   The web UI files (advisor\static) are missing and Node.js is not installed to rebuild them.
echo   Re-download the project, or install Node.js 20 from https://nodejs.org/ and try again.
echo.
pause
exit /b 1

:fail
echo.
echo   Setup failed - see the messages above. Check your internet connection and try again.
echo   To start completely fresh, delete the .venv folder and double-click start.bat.
echo.
pause
exit /b 1
