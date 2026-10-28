@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment not found. Run Install.bat first.
  pause
  exit /b 1
)
start "KoeSub" ".venv\Scripts\pythonw.exe" -m studio
