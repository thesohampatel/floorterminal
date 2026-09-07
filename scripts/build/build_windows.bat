@echo off
setlocal
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0build.py"
  exit /b %errorlevel%
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0build.py"
  exit /b %errorlevel%
)
echo BUILD FAILED: Python 3.11 or newer is not installed or is not on PATH. 1>&2
exit /b 1
endlocal
