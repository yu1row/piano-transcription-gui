@echo off
setlocal
cd /d "%~dp0"
set "PATH=%ProgramFiles%\GitHub CLI;%PATH%"
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\release.ps1" %*
endlocal
