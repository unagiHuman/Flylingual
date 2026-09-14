@echo off
setlocal
pushd "%~dp0" || exit /b 1
echo Flylingual Judge / Cloud submission packager
echo Default edition: GPT Live voice. Build the Unity Player before packaging.
echo.
set "PACKAGE_PYTHON=%~dp0.venv-bridge\Scripts\python.exe"
if not exist "%PACKAGE_PYTHON%" set "PACKAGE_PYTHON=python"
"%PACKAGE_PYTHON%" tools\package_submission.py %*
set "PACKAGE_EXIT_CODE=%errorlevel%"
popd
echo.
if not "%PACKAGE_EXIT_CODE%"=="0" echo Packaging failed. See the error above.
if not "%FLYLINGUAL_PACKAGE_NO_PAUSE%"=="1" pause
exit /b %PACKAGE_EXIT_CODE%
