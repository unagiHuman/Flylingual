param(
    [string]$Destination = "artifacts/judge-python/portable"
)
$ErrorActionPreference = "Stop"
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$portableRoot = [IO.Path]::GetFullPath((Join-Path $repository $Destination))
if (Test-Path -LiteralPath $portableRoot) { throw "Destination must be fresh: $portableRoot" }
$uvCommand = Get-Command uv -ErrorAction Stop
$parentDirectory = Split-Path -Parent $portableRoot
New-Item -ItemType Directory -Path $parentDirectory -Force | Out-Null
$archive = Join-Path $parentDirectory ("python-3.11.9-embed-amd64-" + [Guid]::NewGuid().ToString("N") + ".zip")
$downloadUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
Invoke-WebRequest -Uri $downloadUrl -OutFile $archive
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Expand-Archive -LiteralPath $archive -DestinationPath $portableRoot
$pathFile = Join-Path $portableRoot "python311._pth"
Add-Content -LiteralPath $pathFile -Value "`nLib/site-packages`nimport site"
$pythonExecutable = Join-Path $portableRoot "python.exe"
$sitePackages = Join-Path $portableRoot "Lib/site-packages"
$requirements = @("numpy==1.24.3", "numba==0.61.2", "llvmlite==0.44.0", "psutil==7.2.2", "aiohttp==3.14.3")
& $uvCommand.Source pip install --python $pythonExecutable --target $sitePackages @requirements
if ($LASTEXITCODE -ne 0) { throw "Portable Python dependency installation failed; preserve output for diagnosis." }
$dependencyJson = & $pythonExecutable -I -c 'import importlib.metadata as m,json; import numpy,numba,llvmlite,psutil,aiohttp; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()},sort_keys=True))'
if ($LASTEXITCODE -ne 0) { throw "Portable dependency import check failed." }
$report = [ordered]@{
    schemaVersion = 1
    pythonVersion = "3.11.9"
    platform = "windows-amd64"
    archiveUrl = $downloadUrl
    archiveSha256 = $archiveHash
    requestedDependencies = $requirements
    installedDependencies = ($dependencyJson | ConvertFrom-Json)
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $portableRoot "distribution-manifest.json") -Encoding utf8
Write-Output "Portable runtime prepared: $portableRoot"
Write-Output "Archive SHA256: $archiveHash"
