param(
    [ValidateSet('ALL','STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L')][string]$Action,
    [ValidateSet('perspective','front','side','top')][string]$View = 'perspective',
    [switch]$Capture,
    [switch]$HideVisual,
    [int]$QuitAfter = 0
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo 'artifacts/windows/demo/FlyAscent.exe'
if (!(Test-Path -LiteralPath $exe)) { throw 'Build the Windows demo first with tools/Build-WindowsDemo.ps1 -RecreateScene.' }
$output = Join-Path $repo ('artifacts/windows/runs/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Force $output | Out-Null
$arguments = @('-screen-fullscreen','0','-screen-width','1440','-screen-height','900','-demoView',$View,'-demoOutput',('"' + $output + '"'),'-logFile',('"' + (Join-Path $output 'Player.log') + '"'))
if ($Action) { $arguments += @('-demoAction',$Action) }
if ($Capture) { $arguments += '-demoCapture' }
if ($HideVisual) { $arguments += '-demoHideVisual' }
if ($QuitAfter -gt 0) { $arguments += @('-demoQuitAfter', [string]$QuitAfter) }
# This is the interactive Player requested by the user, so its window is visible.
$process = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru
@{ pid = $process.Id; output = $output; mode = 'REPLAY (Shiu recording)' } | ConvertTo-Json | Write-Output
