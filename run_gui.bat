@echo off
setlocal

REM Change to the repository root (this script's folder)
cd /d "%~dp0"

REM Prefer virtual environment Python if present
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if exist "venv\Scripts\python.exe" set "PYTHON_EXE=venv\Scripts\python.exe"

if not defined PYTHON_EXE (
  REM Try the Windows Python launcher
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    set "PYTHON_EXE=py -3"
  ) else (
    REM Fallback to PATH python
    set "PYTHON_EXE=python"
  )
)

echo Launching WSApp GUI...
%PYTHON_EXE% gui.py %*
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% NEQ 0 (
  echo.
  echo The application exited with code %EXITCODE%.
  echo If this is the first run, ensure dependencies are installed:
  echo   pip install -r requirements_external.txt
)

endlocal
exit /b %EXITCODE%
