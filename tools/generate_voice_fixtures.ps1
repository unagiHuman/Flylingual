[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [string]$Voice = 'Microsoft Haruka Desktop',
    [int]$Rate = 0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$out = [IO.Path]::GetFullPath($OutputDir)
$manifestPath = Join-Path $out 'manifest.json'
$scenarios = @(
    @{ id='stop'; utterance='止まって'; expectedAction='STOP'; expectedKind='action'; expectedPlan=$null },
    @{ id='forward8'; utterance='8秒間前に進んで'; expectedAction='FORWARD'; expectedKind='action'; expectedPlan=$null },
    @{ id='right8'; utterance='8秒間右に曲がって'; expectedAction='TURN_R'; expectedKind='action'; expectedPlan=$null },
    @{ id='left8'; utterance='8秒間左に曲がって'; expectedAction='TURN_L'; expectedKind='action'; expectedPlan=$null },
    @{ id='forward_right8'; utterance='8秒間右前に進んで'; expectedAction='FORWARD_R'; expectedKind='action'; expectedPlan=$null },
    @{ id='forward_left8'; utterance='8秒間左前に進んで'; expectedAction='FORWARD_L'; expectedKind='action'; expectedPlan=$null },
    @{ id='ambiguous_forward'; utterance='もう少し前に進んで'; expectedAction='FORWARD'; expectedKind='action'; expectedPlan=$null },
    @{ id='ambiguous_right'; utterance='軽く右を向いて'; expectedAction='TURN_R'; expectedKind='action'; expectedPlan=$null },
    @{ id='plan_nudge_right'; utterance='ちょっと右'; expectedAction=$null; expectedKind='plan'; expectedPlan='nudge_right' },
    @{ id='plan_right_then_forward'; utterance='右側に進んで'; expectedAction=$null; expectedKind='plan'; expectedPlan='right_then_forward' },
    @{ id='plan_forward_concern'; utterance='前に進んで、違和感があったら止まれ'; expectedAction=$null; expectedKind='plan'; expectedPlan='forward_until_concern' }
)

function Get-FileHashHex([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Get-Manifest([string]$Path) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json } catch { return $null }
}
function Get-WavDurationSeconds([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 12 -or [Text.Encoding]::ASCII.GetString($bytes,0,4) -ne 'RIFF') { throw "Generated WAV is not RIFF: $Path" }
    $pos = 12; $dataBytes = 0
    while ($pos + 8 -le $bytes.Length) {
        $size = [BitConverter]::ToUInt32($bytes, $pos + 4)
        if ([uint64]$pos + 8 + $size -gt [uint64]$bytes.Length) { throw "Generated WAV chunk is truncated: $Path" }
        if ([Text.Encoding]::ASCII.GetString($bytes, $pos, 4) -eq 'data') { $dataBytes = [int64]$size; break }
        $pos += 8 + [int]$size + ([int]$size % 2)
    }
    if ($dataBytes -le 0) { throw "Generated WAV has no data chunk: $Path" }
    return [math]::Round($dataBytes / 48000.0, 6)
}

if (Test-Path -LiteralPath $out) {
    $old = Get-Manifest $manifestPath
    $valid = $null -ne $old -and $old.schemaVersion -eq 1 -and @($old.fixtures).Count -eq $scenarios.Count
    $valid = $valid -and $old.voice -eq $Voice -and [int]$old.rate -eq $Rate -and [int]$old.sampleRate -eq 24000 -and [int]$old.channels -eq 1 -and [int]$old.bitsPerSample -eq 16
    if ($valid) {
        for ($i=0; $i -lt $scenarios.Count; $i++) {
            $item = @($old.fixtures)[$i]; $scenario = $scenarios[$i]
            foreach ($field in @('id','utterance','expectedAction','expectedKind','expectedPlan')) {
                $left = [string]$item.$field; $right = [string]$scenario[$field]
                if ($left -ne $right) { $valid = $false; break }
            }
            if (!$valid) { break }
            $file = Join-Path $out ([string]$item.file)
            if (!(Test-Path -LiteralPath $file -PathType Leaf) -or (Get-FileHashHex $file) -ne ([string]$item.sha256).ToLowerInvariant()) { $valid = $false; break }
        }
    }
    if ($valid) { Write-Output "Existing matching fixture manifest reused: $manifestPath"; exit 0 }
    throw "Output directory already exists and is not a matching fixture set; choose a new directory: $out"
}

$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voiceNames = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
    if ($voiceNames -notcontains $Voice) { throw "Requested voice was not installed: $Voice" }
    if ($Rate -lt -10 -or $Rate -gt 10) { throw "Rate must be between -10 and 10" }
    New-Item -ItemType Directory -Path $out | Out-Null
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SelectVoice($Voice); $synth.Rate = $Rate; $synth.Volume = 100
    $items = @()
    foreach ($scenario in $scenarios) {
        $name = "$($scenario.id).wav"; $path = Join-Path $out $name
        $synth.SetOutputToWaveFile($path, $format)
        $synth.Speak([string]$scenario.utterance)
        $synth.SetOutputToNull()
        $wav = Get-Item -LiteralPath $path
        $items += [ordered]@{ id=$scenario.id; file=$name; sha256=(Get-FileHashHex $path); expectedAction=$scenario.expectedAction; expectedKind=$scenario.expectedKind; expectedPlan=$scenario.expectedPlan; utterance=$scenario.utterance; durationSeconds=(Get-WavDurationSeconds $path) }
    }
    [ordered]@{ schemaVersion=1; voice=$Voice; rate=$Rate; sampleRate=24000; channels=1; bitsPerSample=16; format='PCM16LE'; fixtures=$items } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
} finally { $synth.Dispose() }
Write-Output "Generated voice fixture manifest: $manifestPath"
