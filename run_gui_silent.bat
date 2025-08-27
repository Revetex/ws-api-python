@echo off
setlocal

REM Launch GUI without a console window using pythonw if available.
cd /d "%~dp0"

set "PYW_EXE="
if exist ".venv\Scripts\pythonw.exe" set "PYW_EXE=.venv\Scripts\pythonw.exe"
if exist "venv\Scripts\pythonw.exe" set "PYW_EXE=venv\Scripts\pythonw.exe"

if not defined PYW_EXE (
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    for /f "usebackq tokens=*" %%i in (`py -3 -c "import sys,shutil;print(shutil.which('pythonw') or '')"`) do set "PYW_EXE=%%i"
  )
)

if not defined PYW_EXE (
  REM Fallback to vbs if pythonw is not found
  cscript //nologo "%~dp0\run_gui_silent.vbs"
  goto :eof
)

start "WSApp" "%PYW_EXE%" gui.py %*
endlocal
