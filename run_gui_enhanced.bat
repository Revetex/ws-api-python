@echo off
setlocal
set AI_ENHANCED=1
call "%~dp0\run_gui.bat" %*
set EXITCODE=%ERRORLEVEL%
endlocal
exit /b %EXITCODE%
