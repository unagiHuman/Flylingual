param([ValidateSet('Goal','Fall','Steering','Frames')][string]$Test='Goal')
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$exe=Join-Path $repo 'artifacts/windows/demo/FlyAscent.exe'
if(!(Test-Path -LiteralPath $exe)){throw 'Build the demo first.'}
$batch=Join-Path $repo ('artifacts/windows/check-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
$cases=switch($Test){'Goal'{@('goal-1','goal-2','goal-3')};'Fall'{@('fall')};'Steering'{@('FORWARD_L','FORWARD_R')};'Frames'{@('frames')}}
foreach($case in $cases){
    $out=Join-Path $batch $case
    New-Item -ItemType Directory -Force $out|Out-Null
    $arguments=@('-screen-fullscreen','0','-screen-width','1440','-screen-height','900','-demoOutput',('"'+$out+'"'),'-logFile',('"'+(Join-Path $out 'Player.log')+'"'))
    switch($Test){
        'Goal'{$arguments+=@('-courseTrial','goal','-demoQuitAfter','120')}
        'Fall'{$arguments+=@('-courseTrial','fall','-demoQuitAfter','120')}
        'Steering'{$arguments+=@('-demoAction','STOP','-steeringTrial',$case,'-steeringGain','1.5','-signedSteering','-trialAdhesion','-demoQuitAfter','14')}
        'Frames'{$arguments+=@('-demoAction','ALL','-demoCapture','-demoQuitAfter','30')}
    }
    # Visible Player is intentional for game/visual acceptance.
    $process=Start-Process -FilePath $exe -ArgumentList $arguments -PassThru
    Write-Output "$case PID $($process.Id): $out"
    if(!$process.WaitForExit(180000)){$process.Kill();throw "Timed out: $case"}
    $log=Get-Content (Join-Path $out 'Player.log') -Raw
    if($log -match '\w+Exception:'){throw "Player exception: $out"}
    if($Test -eq 'Goal' -and $log -notmatch 'COURSE_RESULT state=Goal'){throw "Goal not reached: $out"}
    if($Test -eq 'Fall' -and ($log -notmatch 'COURSE_RESULT state=Fallen' -or $log -notmatch 'COURSE_RESTART_PASS')){throw "Fall/restart incomplete: $out"}
}
Write-Output "Evidence: $batch"
Write-Output 'Inspect steering CSV signs and frame summaries; process exit alone is not their pass criterion.'
