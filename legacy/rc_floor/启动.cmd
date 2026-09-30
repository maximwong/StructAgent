@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "report_python=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%report_python%" goto found
set "report_python=python"
:found
"%report_python%" -c "import docx, PIL, tkinter" >nul 2>&1
if errorlevel 1 (
 echo 未找到可用的 Python 或依赖。请先安装 Python 3.10+，并运行 安装依赖.cmd。
 pause
 exit /b 1
)
"%report_python%" app.py
if errorlevel 1 pause
endlocal
