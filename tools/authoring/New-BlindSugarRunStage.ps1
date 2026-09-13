[CmdletBinding()]
param(
    [switch]$Publish
)

# Author in a disposable project, so this never recompiles the shared gameplay project.
# Run only after the session using the shared Editor has released its validation window.
$ErrorActionPreference = 'Stop'
$repoPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$mainProjectPath = Join-Path $repoPath 'UnityProject'
$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runPath = Join-Path $repoPath "artifacts/blind-sugar-run-stage/authoring-$runId"
$authorProjectPath = Join-Path $runPath 'UnityProject'
$authorAssetsPath = Join-Path $authorProjectPath 'Assets'
$builderPath = Join-Path $PSScriptRoot 'BlindSugarRunStageBuilder.cs'
$destinationPath = Join-Path $mainProjectPath 'Assets/BlindSugarRunPrototype'
if (!(Test-Path -LiteralPath $builderPath)) { throw 'Stage builder source is missing.' }
if ($Publish -and (Test-Path -LiteralPath $destinationPath)) {
    throw 'The prototype already exists. Review the existing assets before replacing them.'
}

New-Item -ItemType Directory -Path (Join-Path $authorAssetsPath 'Editor') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $authorProjectPath 'Packages') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $authorProjectPath 'ProjectSettings') -Force | Out-Null
Copy-Item -LiteralPath $builderPath -Destination (Join-Path $authorAssetsPath 'Editor/BlindSugarRunStageBuilder.cs')
foreach ($settingsFile in @('ProjectVersion.txt', 'GraphicsSettings.asset', 'QualitySettings.asset')) {
    Copy-Item -LiteralPath (Join-Path $mainProjectPath "ProjectSettings/$settingsFile") -Destination (Join-Path $authorProjectPath "ProjectSettings/$settingsFile")
}
# Read-only copies of the same render-pipeline settings; never copied back to the main project.
Copy-Item -LiteralPath (Join-Path $mainProjectPath 'Assets/Settings') -Destination (Join-Path $authorAssetsPath 'Settings') -Recurse
Copy-Item -LiteralPath (Join-Path $mainProjectPath 'Assets/Settings.meta') -Destination (Join-Path $authorAssetsPath 'Settings.meta')
$mainManifest = Get-Content -LiteralPath (Join-Path $mainProjectPath 'Packages/manifest.json') -Raw | ConvertFrom-Json
$manifest = @{ dependencies = @{
    'com.unity.render-pipelines.universal' = $mainManifest.dependencies.'com.unity.render-pipelines.universal'
    'com.unity.modules.physics' = '1.0.0'
    'com.unity.modules.imageconversion' = '1.0.0'
} }
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $authorProjectPath 'Packages/manifest.json'), ($manifest | ConvertTo-Json -Depth 5), $utf8)
$versionText = Get-Content -LiteralPath (Join-Path $authorProjectPath 'ProjectSettings/ProjectVersion.txt') -Raw
$versionMatch = [regex]::Match($versionText, '(?m)^m_EditorVersion:\s*(\S+)')
if (!$versionMatch.Success) { throw 'Cannot read project Editor version.' }
$editorVersion = $versionMatch.Groups[1].Value
$logPath = Join-Path $runPath 'authoring.log'

Write-Output "Authoring project: $authorProjectPath"
& unity run $authorProjectPath --editor-version $editorVersion --timeout 300 -- -executeMethod BlindSugarRunStageBuilder.Create -stageReportPath $runPath -logFile $logPath
if ($LASTEXITCODE -ne 0) { throw "Unity stage generation failed. See $logPath" }

$generatedPath = Join-Path $authorAssetsPath 'BlindSugarRunPrototype'
$scenePath = Join-Path $generatedPath 'BlindSugarRunPrototype.unity'
if (!(Test-Path -LiteralPath $scenePath)) { throw 'Unity did not produce the expected stage scene.' }

if ($Publish) {
    # All generated assets use this new namespace. No shared scenes, scripts, settings or builds change.
    if (Test-Path -LiteralPath $destinationPath) { throw 'Destination appeared during authoring; refusing overwrite.' }
    Copy-Item -LiteralPath $generatedPath -Destination $destinationPath -Recurse
    Copy-Item -LiteralPath "$generatedPath.meta" -Destination "$destinationPath.meta"
    foreach ($generatedFile in Get-ChildItem -LiteralPath $generatedPath -Recurse -File) {
        $relativeName = [IO.Path]::GetRelativePath($generatedPath, $generatedFile.FullName)
        $publishedFile = Join-Path $destinationPath $relativeName
        if ((Get-FileHash -LiteralPath $generatedFile.FullName).Hash -ne (Get-FileHash -LiteralPath $publishedFile).Hash) {
            throw "Published asset differs: $relativeName"
        }
    }
    Write-Output "Published: $destinationPath"
}
Write-Output "Stage generated with Unity $editorVersion. No Fly, Brain, GPT or gameplay traversal was executed."
