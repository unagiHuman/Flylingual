@echo off
setlocal
pushd "%~dp0"
".venv-video\Scripts\python.exe" "tools\windows_local.py" up %*
set "FLY_STACK_EXIT=%ERRORLEVEL%"
popd
if not "%FLY_STACK_EXIT%"=="0" pause
exit /b %FLY_STACK_EXIT%
