@echo off
setlocal ENABLEDELAYEDEXPANSION
title Zerochan Watch - Setup & Run

REM --- 1) Go to this script's directory
cd /d "%~dp0"

echo.
echo ==== Zerochan Watch: Setup & Run ====
echo Working folder: %CD%
echo.

REM --- 2) Find Python (prefer py launcher)
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py"
if "%PY_CMD%"=="" (
  where python >nul 2>&1 && set "PY_CMD=python"
)

if "%PY_CMD%"=="" (
  echo [ERROR] Python not found on PATH.
  echo Please install Python 3.10+ from:
  echo   https://www.python.org/downloads/windows/
  echo (Make sure to tick "Add Python to PATH" during setup.)
  start "" "https://www.python.org/downloads/windows/"
  echo.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%V in (`%PY_CMD% -c "import sys;print(sys.version)"`) do set PY_VER=%%V
echo [OK] Python detected via "%PY_CMD%"  (version: %PY_VER%)
echo.

REM --- 3) Create/Use virtualenv
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [SETUP] Creating virtual environment: .venv
  %PY_CMD% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
) else (
  echo [OK] Found existing virtual environment.
)

set "PYEXE=%VENV_PY%"
if not exist "%PYEXE%" (
  echo [WARN] venv python missing; falling back to system "%PY_CMD%"
  set "PYEXE=%PY_CMD%"
)

echo.
echo [PIP] Upgrading pip...
"%PYEXE%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [WARN] pip upgrade returned a non-zero exit code; continuing...
)

REM --- 4) Install requirements
echo.
if exist "requirements.txt" (
  echo [PIP] Installing from requirements.txt...
  "%PYEXE%" -m pip install -r requirements.txt
) else (
  echo [PIP] requirements.txt not found; installing core packages...
  "%PYEXE%" -m pip install requests beautifulsoup4 lxml playwright
)
if errorlevel 1 (
  echo [ERROR] Dependency install failed.
  pause
  exit /b 1
)

REM --- 5) Install Playwright browser (Chromium)
echo.
echo [PW ] Installing Playwright Chromium (browser binaries)...
"%PYEXE%" -m playwright install chromium
if errorlevel 1 (
  echo [WARN] Playwright chromium install failed or skipped. If you use the browser fallback, run:
  echo        "%PYEXE%" -m playwright install chromium
)

REM --- 6) Sanity check for subscriptions.txt
echo.
if not exist "subscriptions.txt" (
  echo [WARN] subscriptions.txt not found in %CD%
  echo        Create it with one tag per line (e.g., Artoria+Caster).
  echo.
)

REM --- 7) Run the scraper
if exist "zerochan_watch.py" (
  echo [RUN] Starting zerochan_watch.py ...
  "%PYEXE%" "%CD%\zerochan_watch.py"
) else (
  echo [ERROR] zerochan_watch.py not found in %CD%
)

echo.
echo ==== Done ====
pause
endlocal
