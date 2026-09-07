@echo off
setlocal
if "%~1"=="" (
  echo Usage: %~nx0 path\to\deployment-profile.json 1>&2
  exit /b 2
)
if not exist "%~f1" (
  echo Deployment profile not found: %~f1 1>&2
  exit /b 2
)
set "FLOORTERMINAL_PROJECT_PROFILE_FILE=%~f1"
call "%~dp0build_windows.bat"
exit /b %errorlevel%
