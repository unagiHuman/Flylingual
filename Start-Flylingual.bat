@echo off
setlocal
call "%~dp0Start-UnityConversation.cmd" %*
set "LAUNCH_EXIT_CODE=%errorlevel%"
if not "%LAUNCH_EXIT_CODE%"=="0" (
  echo.
  echo Flylingual exited with code %LAUNCH_EXIT_CODE%.
  pause
)
exit /b %LAUNCH_EXIT_CODE%
