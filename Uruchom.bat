@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Brak srodowiska. Uruchom najpierw Instaluj.bat.
  pause
  exit /b 1
)
start "KoeSub" ".venv\Scripts\pythonw.exe" -m studio
