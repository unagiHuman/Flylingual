"""Actual Windows MaleCNS -> Unity; one owned server and one client per trial."""
import argparse,datetime,hashlib,json,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--predictive-goal',action='store_true');parser.add_argument('--goals',nargs='+',choices=['front','left','right','back']);parser.add_argument('--capture',action='store_true');parser.add_argument('--join-seconds',type=float,default=0);parser.add_argument('--actions',nargs='+',choices=['FORWARD_L','FORWARD_R'],default=['FORWARD_L']);parser.add_argument('--conditions',nargs='+',choices=['NONE','LM','RF','RM'],default=['NONE','LM','RF','RM']);parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--output',default='artifacts/windows-malecns/live-tibia')
opt=parser.parse_args();base=(ROOT/opt.output).resolve();base.mkdir(parents=True,exist_ok=True)
for n in range(opt.repeats):
 for action,condition,goal in [(a,c,g) for a in opt.actions for c in opt.conditions for g in (opt.goals or [None])]:
  out=base/f'{goal or action}-{condition}-{n}';out.mkdir()
  args=[str(ROOT/'artifacts/windows/m1/player/FlyAscent.exe'),'-physicsDiagnostic','-diagnosticWindowsLive','-diagnosticJoinSeconds',str(opt.join_seconds),'-diagnosticLiveAction',action,'-diagnosticIgnoreTibia',condition,'-diagnosticInitial',str(ROOT/'artifacts/windows-malecns/live-tibia-initial.json'),'-demoAction','ALL','-demoOutput',str(out),'-screen-fullscreen','0','-screen-width','800','-screen-height','600','-logFile',str(out/'Player.log')]
  if opt.predictive_goal:args.append('-diagnosticPredictiveGoal')
  if goal:args.extend(['-diagnosticGoal',goal])
  if opt.capture:args.append('-diagnosticCapture')
  brain=[sys.executable,'-u',str(ROOT/'Brain/MaleCNS/brain_server_analog.py'),'--host','127.0.0.1','--port','18766','--seed','20270101']
  sources=[ROOT/'UnityProject/Assets/VisualDemo/FixedPhysicsDiagnostic.cs',ROOT/'UnityProject/Assets/FlyLocomotion/FlyLocomotionController.cs',ROOT/'UnityProject/Assets/FlyLocomotion/FlyFootAdhesion.cs',ROOT/'artifacts/windows/m1/player/FlyAscent_Data/Managed/Assembly-CSharp.dll',ROOT/'artifacts/windows-malecns/live-tibia-initial.json']
  (out/'manifest.json').write_text(json.dumps(dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),condition=condition,action=action,joinSeconds=opt.join_seconds,goal=goal,predictiveGoal=opt.predictive_goal,player=args,brain=brain,sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}),indent=2))
  player=None
  with (out/'brain-server.log').open('w') as log:
   server=subprocess.Popen(brain,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
   try:
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
     if server.poll() is not None:raise RuntimeError('Brain exited; no fallback')
     if 'READY at' in (out/'brain-server.log').read_text():break
     time.sleep(.25)
    else:raise TimeoutError('Brain initialization')
    player=subprocess.Popen(args,cwd=ROOT);print('START',out.name,'Unity',player.pid,'Brain',server.pid,flush=True)
    code=player.wait(110 if goal else 90)
    (out/'process-result.json').write_text(json.dumps(dict(playerExit=code,endpoint='127.0.0.1:18766')))
    if code:raise RuntimeError(f'Unity exited {code}')
   finally:
    if player is not None and player.poll() is None:player.terminate();player.wait(10)
    if server.poll() is None:server.terminate();server.wait(10)
  subprocess.run([sys.executable,str(ROOT/'tools/analyze_fixed_physics.py'),str(out)],check=True,cwd=ROOT)
  print('DONE',out.name,flush=True)
