@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\local_llama.ps1 Prepare
if errorlevel 1 goto failed
".venv-bridge\Scripts\python.exe" -B tools\local_intent_console.py --provider llama_cpp --local-format label
if errorlevel 1 goto failed
exit /b 0
:failed
echo Local label test could not start. See the message above.
pause
exit /b 1
