import pathlib,subprocess,json,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];base=ROOT/'artifacts/windows-malecns/coxa-check';base.mkdir(parents=True,exist_ok=True)
initial=ROOT.parent/'Flytest/artifacts/windows/physics-diagnostic/controlled-initial.json'
for name,amp in [('baseline',None),('bounded','35.135')]:
 out=base/name;out.mkdir(exist_ok=True)
 args=[str(ROOT/'artifacts/windows/m1/player/FlyAscent.exe'),'-physicsDiagnostic','-diagnosticBatch','steering','-diagnosticInitial',str(initial),'-fixedFixtures',str(ROOT/'Docs/windows/physics-diagnostic/fixtures'),'-demoOutput',str(out),'-screen-fullscreen','0','-screen-width','800','-screen-height','600','-logFile',str(out/'Player.log')]
 if amp:args+=['-diagnosticCoxaAmplitude',amp]
 p=subprocess.Popen(args,cwd=ROOT)
 try:code=p.wait(180)
 finally:
  if p.poll() is None:p.terminate();p.wait(10)
 print(name,'exit',code,flush=True)
 subprocess.run([sys.executable,str(ROOT/'tools/analyze_fixed_physics.py'),str(out)],check=True,cwd=ROOT)
