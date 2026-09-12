import pathlib,subprocess,sys,argparse,hashlib,json,datetime
parser=argparse.ArgumentParser();parser.add_argument('--output',default='artifacts/windows-malecns/contact-timing');options=parser.parse_args()
ROOT=pathlib.Path(__file__).resolve().parents[1];out=(ROOT/options.output).resolve();
if out.exists():raise SystemExit('Output exists; choose a new output directory to preserve evidence')
out.mkdir(parents=True)
args=[str(ROOT/'artifacts/windows/m1/player/FlyAscent.exe'),'-physicsDiagnostic','-diagnosticBatch','steering','-diagnosticInitial',str(ROOT.parent/'Flytest/artifacts/windows/physics-diagnostic/controlled-initial.json'),'-fixedFixtures',str(ROOT/'Docs/windows/physics-diagnostic/fixtures'),'-demoOutput',str(out),'-screen-fullscreen','0','-screen-width','800','-screen-height','600','-logFile',str(out/'Player.log')]
files=[ROOT/'UnityProject/Assets/FlyLocomotion/FlyLocomotionController.cs',ROOT/'UnityProject/Assets/FlyLocomotion/FlyFootAdhesion.cs',ROOT/'UnityProject/Assets/VisualDemo/FixedPhysicsDiagnostic.cs',pathlib.Path(args[0]),ROOT/'artifacts/windows/m1/player/FlyAscent_Data/Managed/Assembly-CSharp.dll']
(out/'run-manifest.json').write_text(json.dumps(dict(startedUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),command=args,sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}),indent=2))
p=subprocess.Popen(args,cwd=ROOT)
try:
 code=p.wait(180);print('exit',code,flush=True)
 if code:raise SystemExit(code)
finally:
 if p.poll() is None:p.terminate();p.wait(10)
subprocess.run([sys.executable,str(ROOT/'tools/analyze_fixed_physics.py'),str(out)],check=True,cwd=ROOT)
