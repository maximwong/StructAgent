@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "report_python=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%report_python%" set "report_python=python"
"%report_python%" desktop_verify.py > desktop_run.log 2>&1
type desktop_run.log
pause
