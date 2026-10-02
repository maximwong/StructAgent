@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv-demo\Scripts\pythonw.exe" (
  echo Please create the demo environment first. See docs/demo-deployment.md.
  pause
  exit /b 1
)
start "" "%~dp0.venv-demo\Scripts\pythonw.exe" "%~dp0app.py"
