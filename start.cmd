@echo off
rem Starts PS5 Agent Remote and opens the page. Close this window to stop it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Not installed yet. Follow docs\01-install.md first.
  pause
  exit /b 1
)
if not exist "native\ps5bridge.dll" (
  echo native\ps5bridge.dll is missing. Download it from the GitHub release or build it. See docs\01-install.md.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8765
where varlock >nul 2>nul
if %errorlevel%==0 (
  varlock run -- ".venv\Scripts\python.exe" server.py
) else (
  ".venv\Scripts\python.exe" server.py
)
