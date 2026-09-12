import pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];out=ROOT/'artifacts/windows-malecns/onset-smoothing';out.mkdir(parents=True,exist_ok=True)
args=[str(ROOT/'artifacts/windows/m1/player/FlyAscent.exe'),'-physicsDiagnostic','-diagnosticBatch','steering','-diagnosticInitial',str(ROOT.parent/'Flytest/artifacts/windows/physics-diagnostic/controlled-initial.json'),'-fixedFixtures',str(ROOT/'Docs/windows/physics-diagnostic/fixtures'),'-diagnosticMotorSmoothing','0.35','-demoOutput',str(out),'-screen-fullscreen','0','-screen-width','800','-screen-height','600','-logFile',str(out/'Player.log')]
p=subprocess.Popen(args,cwd=ROOT)
try:print('exit',p.wait(180),flush=True)
finally:
 if p.poll() is None:p.terminate();p.wait(10)
subprocess.run([sys.executable,str(ROOT/'tools/analyze_fixed_physics.py'),str(out)],check=True,cwd=ROOT)
