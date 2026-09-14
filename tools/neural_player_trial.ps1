param(
    [Parameter(Mandatory=$true)][string]$Name,
    [ValidateSet('ja','en')][string]$Language = 'ja',
    [ValidateRange(0,3)][int]$Question = 0,
    [switch]$ObservationOff,
    [switch]$RenderScreenshot,
    [switch]$EnvironmentFeedback,
    [switch]$VisualThreat,
    [switch]$ConnectionStability,
    [switch]$NativePlayer
)
$ErrorActionPreference = 'Stop'
$trialRoot = Split-Path $PSScriptRoot -Parent
$trialOutput = Join-Path $trialRoot 'artifacts/neural-feedback'
if ($Name -notmatch '^[a-z0-9-]+$') { throw 'Use a simple trial name' }
$trialConfig = Join-Path $trialRoot 'Runtime/Config/local.json'
$trialExe = Join-Path $trialRoot $(if ($NativePlayer) { 'artifacts/windows-native-conversation/unity/FlylingualConversation.exe' } else { 'artifacts/hayeringual-builds/Dev-Local/FlylingualConversation.exe' })
if (Get-Process FlylingualConversation -ErrorAction SilentlyContinue) { throw 'A Player is already running; do not interrupt it' }
$originalBytes = [IO.File]::ReadAllBytes($trialConfig)
$trialProcess = $null
try {
    $settings = [Text.Encoding]::UTF8.GetString($originalBytes) | ConvertFrom-Json
    $settings.conversation.language = $Language
    $settings.conversation.persona = $(if ($Language -eq 'en') {'deadpan_skeptic'} else {'hiroyuki_like'})
    # The diagnostic uses only the checked-in preset, never terminal-local free text.
    $settings.conversation | Add-Member -Force -NotePropertyName personaText -NotePropertyValue ''
    $settings | Add-Member -Force -NotePropertyName neuralFeedback -NotePropertyValue @{enabled = (-not $ObservationOff.IsPresent)}
    $settings | Add-Member -Force -NotePropertyName logPath -NotePropertyValue (Join-Path $trialOutput ($Name + '-bridge.jsonl'))
    [IO.File]::WriteAllText($trialConfig, ($settings | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
    [IO.Directory]::CreateDirectory($trialOutput) | Out-Null
    $resultPath = Join-Path $trialOutput ($Name + '.json')
    if (Test-Path -LiteralPath $resultPath) { throw 'Do not overwrite an existing trial' }
    $launchArguments = @('-batchmode','-neuralFeedbackProbe',$resultPath,'-neuralFeedbackQuestion',"$Question",'-flyConversationNoMicrophone','-logFile',(Join-Path $trialOutput ($Name + '-player.log')))
    if ($RenderScreenshot) { $launchArguments = @($launchArguments | Where-Object { $_ -ne '-batchmode' }) }
    if ($Language -eq 'en') { $launchArguments += '-neuralFeedbackEnglish' }
    if ($EnvironmentFeedback) { $launchArguments += '-environmentFeedbackProbe' }
    if ($VisualThreat) { $launchArguments += '-visualThreatProbe' }
    if ($ConnectionStability) { $launchArguments += '-connectionStabilityProbe' }
    $trialProcess = Start-Process -FilePath $trialExe -WorkingDirectory (Split-Path $trialExe) -WindowStyle Hidden -ArgumentList $launchArguments -PassThru
    $trialProcess | Select-Object Id,StartTime,Path | ConvertTo-Json | Set-Content (Join-Path $trialOutput ($Name + '-process.json'))
    $deadline = [DateTime]::UtcNow.AddSeconds(180)
    $peak = 0L
    $ownedTree = @{}
    $ownedTree[([string]$trialProcess.Id)] = @{name='Player'; peakRssBytes=0L}
    $sampleTick = 0
    while (-not $trialProcess.WaitForExit(1000)) {
        $trialProcess.Refresh()
        $peak = [Math]::Max($peak, $trialProcess.WorkingSet64)
        if (($sampleTick++ % 5) -eq 0) {
            $processInventory = @(Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId,Name -ErrorAction SilentlyContinue)
            for ($depth=0; $depth -lt 8; $depth++) {
                $added = $false
                foreach ($child in $processInventory) {
                    if ($ownedTree.ContainsKey([string]$child.ParentProcessId) -and -not $ownedTree.ContainsKey([string]$child.ProcessId)) {
                        $ownedTree[[string]$child.ProcessId] = @{name=$child.Name; peakRssBytes=0L}
                        $added = $true
                    }
                }
                if (-not $added) { break }
            }
            foreach ($processKey in @($ownedTree.Keys)) {
                $sampled = Get-Process -Id $processKey -ErrorAction SilentlyContinue
                if ($null -ne $sampled) { $ownedTree[$processKey].peakRssBytes = [Math]::Max($ownedTree[$processKey].peakRssBytes, $sampled.WorkingSet64) }
            }
        }
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Owned trial exceeded 180 seconds' }
    }
    @{sampledPlayerPeakRssBytes=$peak; ownedProcessTree=$ownedTree; rssSamplingSeconds=5; exitCode=$trialProcess.ExitCode; language=$Language; observationEnabled=(-not $ObservationOff.IsPresent)} |
        ConvertTo-Json -Depth 5 | Set-Content (Join-Path $trialOutput ($Name + '-metrics.json'))
    Get-Content -LiteralPath $resultPath -Encoding UTF8
}
finally {
    [IO.File]::WriteAllBytes($trialConfig, $originalBytes)
    if ($null -ne $trialProcess -and -not $trialProcess.HasExited) {
        $owned = Get-Process -Id $trialProcess.Id -ErrorAction SilentlyContinue
        if ($null -ne $owned -and $owned.Path -eq $trialExe -and $owned.StartTime -eq $trialProcess.StartTime) {
            Stop-Process -Id $owned.Id
        }
    }
}
