@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\local_llm.ps1 Prepare
if errorlevel 1 goto failed
".venv-bridge\Scripts\python.exe" -B tools\local_intent_console.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Local intent test could not start. See the message above.
pause
exit /b 1
