[CmdletBinding()]
param(
    [ValidateSet('doctor', 'up')]
    [string]$Action = 'doctor',
    [string]$Config = 'Runtime/Config/windows-stack.local.json',
    [string]$KeyFile,
    [ValidateRange(1, 86400)]
    [int]$Duration,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv-video\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing .venv-video Python runtime.' }

$launcherArgs = @((Join-Path $repo 'tools\windows_local.py'), $Action, '--config', $Config)
if ($KeyFile) { $launcherArgs += @('--key-file', $KeyFile) }
if ($PSBoundParameters.ContainsKey('Duration')) { $launcherArgs += @('--duration', $Duration) }
if ($NoBrowser) { $launcherArgs += '--no-browser' }
& $python @launcherArgs
exit $LASTEXITCODE
