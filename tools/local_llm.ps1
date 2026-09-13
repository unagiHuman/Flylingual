param(
    [ValidateSet('Install','Start','Prepare','Status','Pull','Stop')][string]$Action = 'Status',
    [string]$Model = 'qwen3.5:4b'
)
$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeDir = Join-Path $repoRoot 'artifacts/local-llm'
$version = '0.34.0'
$binaryDir = Join-Path $runtimeDir "ollama-v$version"
$binary = Join-Path $binaryDir 'ollama.exe'
$pidFile = Join-Path $runtimeDir 'server.json'
$origin = 'http://127.0.0.1:11435'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if ($Action -eq 'Prepare') {
    $python = Join-Path $repoRoot '.venv-bridge/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Prepare requires .venv-bridge with Runtime/Bridge/requirements.txt installed' }
    if (Test-Path -LiteralPath (Join-Path $runtimeDir 'llama-direct-owner.json')) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'local_llama.ps1') -Action Stop
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the owned direct llama test server' }
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Action Start
    if ($LASTEXITCODE -ne 0) { throw 'Local server startup failed' }
    & $python -B (Join-Path $PSScriptRoot 'prepare_local_intent.py') --model $Model
    exit $LASTEXITCODE
}

function Get-OwnedServer {
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    $record = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if ($null -ne $process -and $process.Path -eq $binary -and
        $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.startTicks) { return $process }
    return $null
}

if ($Action -eq 'Install') {
    if (Test-Path -LiteralPath $binary) { Write-Output "Already installed: $binary"; exit 0 }
    $downloads = Join-Path $runtimeDir 'downloads'
    New-Item -ItemType Directory -Force -Path $downloads | Out-Null
    $archive = Join-Path $downloads "ollama-windows-amd64-v$version.zip"
    if (-not (Test-Path -LiteralPath $archive)) {
        & curl.exe -L --fail --retry 2 --silent --show-error -o $archive "https://github.com/ollama/ollama/releases/download/v$version/ollama-windows-amd64.zip"
        if ($LASTEXITCODE -ne 0) { throw 'Official Ollama download failed' }
    }
    $expected = 'a7dd1b174f39d3d1b8a25d4cbc86045d0e190b17187bfdcbe2f2ee3b5a11470e'
    if ((Get-FileHash -LiteralPath $archive).Hash.ToLowerInvariant() -ne $expected) { throw 'Ollama archive SHA-256 mismatch' }
    Expand-Archive -LiteralPath $archive -DestinationPath $binaryDir
    Write-Output "Installed official Ollama $version (SHA-256 verified)"
    exit 0
}
if ($Action -eq 'Status') {
    $owned = Get-OwnedServer
    Write-Output ('Owned server running: ' + ($null -ne $owned))
    try {
        Invoke-RestMethod "$origin/api/version" -TimeoutSec 3 | ConvertTo-Json
        Invoke-RestMethod "$origin/api/ps" -TimeoutSec 3 | ConvertTo-Json -Depth 6
    } catch { Write-Output 'Local intent endpoint unavailable'; exit 1 }
    exit 0
}
if ($Action -eq 'Stop') {
    $owned = Get-OwnedServer
    if ($null -eq $owned) { throw 'No matching owned Ollama process; nothing stopped' }
    $parentId = $owned.Id
    $parentTicks = $owned.StartTime.ToUniversalTime().Ticks
    $runnerPath = [IO.Path]::GetFullPath((Join-Path $binaryDir 'lib/ollama/llama-server.exe'))
    $children = @()
    # Resolve every direct child's identity before stopping the parent. Failure
    # to inspect is not permission to kill a process by name or adopt a runner.
    $directChildren = @(Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId = $parentId" -ErrorAction Stop)
    foreach ($child in $directChildren) {
        if ([string]::IsNullOrEmpty($child.ExecutablePath)) { throw 'Cannot inspect a direct child executable; nothing stopped' }
        if ([IO.Path]::GetFullPath($child.ExecutablePath) -ne $runnerPath) { continue }
        $runner = Get-Process -Id ([int]$child.ProcessId) -ErrorAction Stop
        $runnerTicks = $runner.StartTime.ToUniversalTime().Ticks
        if ([string]::IsNullOrEmpty($runner.Path) -or $null -eq $child.CreationDate) {
            throw 'Cannot inspect runner identity; nothing stopped'
        }
        # CIM timestamps have microsecond precision; Process creation ticks may
        # have one further digit. Reject a recycled PID between the two reads.
        $cimTicks = $child.CreationDate.ToUniversalTime().Ticks
        if ($runner.Path -ne $runnerPath -or $runnerTicks -lt $parentTicks -or
            [Math]::Abs($runnerTicks - $cimTicks) -gt 10) {
            throw 'Direct runner identity changed or predates the parent; nothing stopped'
        }
        $children += [pscustomobject]@{ processId = $runner.Id; startTicks = $runnerTicks; path = $runnerPath }
    }
    $confirmedParent = Get-OwnedServer
    if ($null -eq $confirmedParent -or $confirmedParent.Id -ne $parentId -or
        $confirmedParent.StartTime.ToUniversalTime().Ticks -ne $parentTicks) {
        throw 'Parent ownership changed during child inspection; nothing stopped'
    }
    Stop-Process -InputObject $confirmedParent -ErrorAction Stop
    if (-not $confirmedParent.WaitForExit(10000)) { throw 'Owned Ollama parent did not exit within 10 seconds' }
    foreach ($record in $children) {
        $remaining = Get-Process -Id $record.processId -ErrorAction SilentlyContinue
        if ($null -eq $remaining) { continue }
        if ($remaining.Path -ne $record.path -or $remaining.StartTime.ToUniversalTime().Ticks -ne $record.startTicks) {
            throw 'Recorded child identity changed; refusing to stop the replacement process'
        }
        Stop-Process -InputObject $remaining -ErrorAction Stop
        if (-not $remaining.WaitForExit(10000)) { throw 'Owned llama runner did not exit within 10 seconds' }
    }
    Remove-Item -LiteralPath $pidFile
    Write-Output 'Stopped this test environment server and its verified direct llama runners'
    exit 0
}
if (-not (Test-Path -LiteralPath $binary)) { throw 'Run local_llm.ps1 -Action Install first' }
if ($Action -eq 'Start') {
    if ($null -ne (Get-OwnedServer)) { Write-Output 'Owned Ollama server already running'; exit 0 }
    $endpointExists = $false
    try { $null = Invoke-RestMethod "$origin/api/version" -TimeoutSec 2; $endpointExists = $true } catch { }
    if ($endpointExists) { throw 'Port 11435 is already serving another Ollama; not adopting it' }
}
$settings = @{
    OLLAMA_HOST='127.0.0.1:11435'; OLLAMA_MODELS=(Join-Path $runtimeDir 'models');
    OLLAMA_CONTEXT_LENGTH='8192'; OLLAMA_NUM_PARALLEL='1'; OLLAMA_MAX_LOADED_MODELS='1';
    OLLAMA_KEEP_ALIVE='10m'; OLLAMA_NO_CLOUD='1'
}
$previous = @{}
try {
    foreach ($name in $settings.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
    }
    if ($Action -eq 'Pull') {
        if ($null -eq (Get-OwnedServer)) { throw 'Start this environment before pulling its model' }
        if ($Model -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._:/-]+$' -or $Model -match 'cloud') { throw 'Use a local model tag' }
        & $binary pull $Model
        if ($LASTEXITCODE -ne 0) { throw 'Model pull failed' }
    } else {
        $server = Start-Process -FilePath $binary -ArgumentList 'serve' -WorkingDirectory $runtimeDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $runtimeDir 'server.out.log') -RedirectStandardError (Join-Path $runtimeDir 'server.err.log')
        [pscustomobject]@{pid=$server.Id;startTicks=$server.StartTime.ToUniversalTime().Ticks.ToString();binary=$binary;origin=$origin;version=$version} |
            ConvertTo-Json | Set-Content -LiteralPath $pidFile
        for ($i = 0; $i -lt 30; $i++) {
            if ($server.HasExited) { throw 'Owned Ollama server exited; see artifacts/local-llm/server.err.log' }
            try { $null = Invoke-RestMethod "$origin/api/version" -TimeoutSec 1; Write-Output "Local intent server ready: $origin"; exit 0 } catch { }
            Start-Sleep -Milliseconds 200
        }
        throw 'Ollama startup did not become ready; see artifacts/local-llm/server.err.log'
    }
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
