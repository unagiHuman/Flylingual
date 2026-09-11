param([switch]$Baseline, [switch]$RecreateScene, [string]$EditorPath)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repo 'UnityProject'
$logs = Join-Path $repo 'artifacts/windows'
New-Item -ItemType Directory -Force $logs | Out-Null
$method = if ($Baseline) { 'WindowsDemoBuilder.BuildBaseline' } elseif ($RecreateScene) { 'WindowsDemoBuilder.CreateAndBuild' } else { 'WindowsDemoBuilder.BuildDemo' }
$log = Join-Path $logs ('build-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$editorArgs = @('--editor-version','6000.5.5f1')
if ($EditorPath) { $editorArgs += @('--editor-path',$EditorPath) }
& unity run $project @editorArgs --timeout 1800 -- -executeMethod $method -buildTarget Win64 -logFile $log
if ($LASTEXITCODE -ne 0) { throw "Unity build failed. See $log" }
Write-Output "Build completed. Log: $log"
