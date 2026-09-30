@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "report_python=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%report_python%" set "report_python=python"
"%report_python%" -m pip install -r requirements.txt
pause
endlocal
