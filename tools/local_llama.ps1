[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Start', 'Prepare', 'Status', 'Stop')]
    [string]$Action,
    [ValidateRange(1, 120)]
    [int]$ReadyTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$localRoot = Join-Path $repoRoot 'artifacts/local-llm'
$installRoot = Join-Path $localRoot 'ollama-v0.34.0/lib/ollama'
$serverPath = Join-Path $installRoot 'llama-server.exe'
$modelPath = Join-Path $localRoot 'models/blobs/sha256-81fb60c7daa80fc1123380b98970b320ae233409f0f71a72ed7b9b0d62f40490'
$ownerPath = Join-Path $localRoot 'llama-direct-owner.json'
$healthUrl = 'http://127.0.0.1:11436/health'

function Read-Ownership {
    if (-not (Test-Path -LiteralPath $ownerPath -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $ownerPath -Raw | ConvertFrom-Json }
    catch { throw 'Invalid llama ownership record; no process was adopted or stopped.' }
}

function Get-OwnedProcess($record) {
    if ($null -eq $record) { return $null }
    try {
        if ([string]$record.path -ne $serverPath -or [long]$record.startTicks -le 0 -or [int]$record.processId -le 0) { return $null }
        $candidate = Get-Process -Id ([int]$record.processId) -ErrorAction SilentlyContinue
        if ($null -eq $candidate) { return $null }
        if ($candidate.Path -ne $serverPath -or $candidate.StartTime.ToUniversalTime().Ticks -ne [long]$record.startTicks) { return $null }
        return $candidate
    } catch { return $null }
}

function Get-PortListeners {
    # Preserve an empty array through PowerShell's pipeline under StrictMode.
    return ,@(Get-NetTCPConnection -LocalPort 11436 -State Listen -ErrorAction SilentlyContinue)
}

function Test-Health {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 1 -MaximumRedirection 0
        return $null -ne $response -and $response.status -eq 'ok'
    } catch { return $false }
}

function Stop-OwnedServer {
    $record = Read-Ownership
    $owned = Get-OwnedProcess $record
    if ($null -eq $owned) {
        Write-Output 'No matching owned llama process. Other processes remain untouched.'
        return
    }
    # Re-check PID + executable path + creation time immediately before termination.
    $confirmed = Get-OwnedProcess $record
    if ($null -eq $confirmed) { throw 'Ownership changed before stop; refusing termination.' }
    Stop-Process -InputObject $confirmed -ErrorAction Stop
    $confirmed.WaitForExit(10000) | Out-Null
    if (-not $confirmed.HasExited) { throw 'Owned llama process did not exit within 10 seconds.' }
    Remove-Item -LiteralPath $ownerPath -ErrorAction Stop
    Write-Output 'Owned llama server stopped.'
}

function Install-Server {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'local_llm.ps1') -Action Install
    if ($LASTEXITCODE -ne 0) { throw 'Pinned Ollama runtime installation failed' }
    if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) { throw 'Bundled llama-server.exe is missing' }
    Write-Output 'Using the verified Ollama 0.34.0 bundled llama.cpp runtime with its matching GGUF.'
}

function Start-Server {
    if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) { throw 'Run Install first: pinned llama-server.exe is missing.' }
    if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) { throw 'The existing pinned model blob is missing.' }
    $record = Read-Ownership
    if ($null -ne (Get-OwnedProcess $record)) { throw 'Owned llama server is already running; use Status.' }
    if ((Get-PortListeners).Count -gt 0) { throw 'Port 11436 is already occupied; existing servers are never adopted.' }
    $logRoot = Join-Path $localRoot 'logs'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')
    $stdout = Join-Path $logRoot ('llama-' + $stamp + '.stdout.log')
    $stderr = Join-Path $logRoot ('llama-' + $stamp + '.stderr.log')
    $arguments = '-m "' + $modelPath + '" -ngl all --device CUDA0 -c 8192 -np 1 -b 1024 -ub 1024 --host 127.0.0.1 --port 11436 --reasoning off --ctx-checkpoints 32 --checkpoint-min-step 0 --cache-ram 512 --no-webui --offline --cors-origins http://127.0.0.1:11436 --no-cors-credentials'
    $previousBackend = [Environment]::GetEnvironmentVariable('GGML_BACKEND_PATH', 'Process')
    $previousSearchPath = [Environment]::GetEnvironmentVariable('PATH', 'Process')
    try {
        $cudaRoot = Join-Path $installRoot 'cuda_v13'
        $env:GGML_BACKEND_PATH = Join-Path $cudaRoot 'ggml-cuda.dll'
        $env:PATH = $cudaRoot + ';' + $previousSearchPath
        $launched = Start-Process -FilePath $serverPath -ArgumentList $arguments -WorkingDirectory $installRoot `
            -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    } finally {
        [Environment]::SetEnvironmentVariable('GGML_BACKEND_PATH', $previousBackend, 'Process')
        [Environment]::SetEnvironmentVariable('PATH', $previousSearchPath, 'Process')
    }
    $record = [ordered]@{ processId = $launched.Id; startTicks = $launched.StartTime.ToUniversalTime().Ticks; path = $serverPath }
    try {
        $record | ConvertTo-Json | Set-Content -LiteralPath $ownerPath -Encoding UTF8
        $watch = [Diagnostics.Stopwatch]::StartNew()
        do {
            $owned = Get-OwnedProcess $record
            if ($null -eq $owned) { throw 'Owned llama server exited before readiness. Inspect its local logs.' }
            $listeners = Get-PortListeners
            if ($listeners.Count -gt 0) {
                if (@($listeners | Where-Object { $_.OwningProcess -ne $launched.Id }).Count -gt 0) {
                    throw 'Another process acquired port 11436; it will not be adopted.'
                }
                if ($watch.Elapsed.TotalSeconds -le ($ReadyTimeoutSeconds - 1) -and (Test-Health)) {
                    Write-Output ('Owned llama server ready: ' + $healthUrl + ' pid=' + $launched.Id)
                    return
                }
            }
            if ($watch.Elapsed.TotalSeconds -ge ($ReadyTimeoutSeconds - .2)) { break }
            Start-Sleep -Milliseconds 200
        } while ($watch.Elapsed.TotalSeconds -lt $ReadyTimeoutSeconds)
        throw 'Owned llama server readiness timed out (maximum 120 seconds).'
    } catch {
        # Failed startup may stop only the exact child created by this invocation.
        $failure = $_
        $owned = Get-OwnedProcess $record
        if ($null -ne $owned) { Stop-Process -InputObject $owned -ErrorAction SilentlyContinue }
        throw $failure
    }
}

switch ($Action) {
    'Prepare' {
        # Free only this test environment's owned Ollama before loading the same model.
        if (Test-Path -LiteralPath (Join-Path $localRoot 'server.json')) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'local_llm.ps1') -Action Stop
            if ($LASTEXITCODE -ne 0) { throw 'Could not stop the owned Ollama test server' }
        }
        if ($null -eq (Get-OwnedProcess (Read-Ownership))) { Start-Server }
        if (-not (Test-Health)) { throw 'Local llama endpoint is not ready' }
        $python = Join-Path $repoRoot '.venv-bridge/Scripts/python.exe'
        & $python -B (Join-Path $PSScriptRoot 'prepare_local_intent.py') --provider llama_cpp --local-format label
        if ($LASTEXITCODE -ne 0) { throw 'Local label warmup failed' }
    }
    'Install' { Install-Server }
    'Start' { Start-Server }
    'Stop' { Stop-OwnedServer }
    'Status' {
        $owned = Get-OwnedProcess (Read-Ownership)
        $listeners = Get-PortListeners
        $ownedPort = $null -ne $owned -and $listeners.Count -gt 0 -and @($listeners | Where-Object { $_.OwningProcess -ne $owned.Id }).Count -eq 0
        [ordered]@{ owned = ($null -ne $owned); processId = $(if ($null -ne $owned) { $owned.Id } else { $null });
            port = 11436; occupied = ($listeners.Count -gt 0); ready = ($ownedPort -and (Test-Health));
            executable = $serverPath } | ConvertTo-Json
    }
}
