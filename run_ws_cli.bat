@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if exist "venv\Scripts\python.exe" set "PYTHON_EXE=venv\Scripts\python.exe"
if not defined PYTHON_EXE (
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    set "PYTHON_EXE=py -3"
  ) else (
    set "PYTHON_EXE=python"
  )
)

echo WS API CLI
%PYTHON_EXE% run_ws.py %*
set EXITCODE=%ERRORLEVEL%
endlocal
exit /b %EXITCODE%
