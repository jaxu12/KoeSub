@echo off
cd /d "%~dp0"
echo Lokalny model tlumaczenia z D:\models.
echo Zamknij ten serwer przed kolejnym zadaniem ASR, aby zwolnic VRAM.
".venv\Scripts\python.exe" -m tools.serve_test_model
pause
