@echo off
setlocal
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PLAYER=%ROOT%\artifacts\windows-native-conversation\unity\FlylingualConversation.exe"
if not exist "%PLAYER%" (
  echo Unity Player was not found: %PLAYER%
  echo Build the Windows Player first, or edit PLAYER in this launcher.
  exit /b 2
)
if exist "%ROOT%\Runtime\Config\windows-native.local.json" goto config_ok
if exist "%ROOT%\Runtime\Config\windows-stack.local.json" goto config_ok
  echo Missing Runtime\Config\windows-native.local.json or windows-stack.local.json.
  echo Copy Runtime\Config\windows-native.example.json and set local paths without committing it.
  exit /b 2
:config_ok
"%PLAYER%" -flyConversation -flyRepoRoot "%ROOT%" -demoLive -brainHost 127.0.0.1 -brainPort 18770 -screen-fullscreen 0 %*
exit /b %errorlevel%
