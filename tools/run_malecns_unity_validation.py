"""Bounded production brain plus actual Windows Unity Player integration run."""
import pathlib,sys,subprocess,time,json
ROOT=pathlib.Path(__file__).resolve().parents[1];out=ROOT/'artifacts/windows-malecns/unity-stop-timer-fixed';out.mkdir(parents=True,exist_ok=True)
log=(out/'brain-server.log').open('w');player=None
server=subprocess.Popen([sys.executable,'-u',str(ROOT/'Brain/MaleCNS/brain_server_analog.py'),'--host','127.0.0.1','--port','18766'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
try:
 for _ in range(120):
  if server.poll() is not None:raise RuntimeError('Brain exited')
  if 'READY at' in (out/'brain-server.log').read_text():break
  time.sleep(.25)
 else:raise TimeoutError('Brain init timeout')
 player=subprocess.Popen([str(ROOT/'artifacts/windows/m1/player/FlyAscent.exe'),'-demoAction','ALL','-demoLive','-liveTrial','-brainHost','127.0.0.1','-brainPort','18766','-demoOutput',str(out),'-screen-fullscreen','0','-screen-width','1280','-screen-height','720','-logFile',str(out/'Player.log')],cwd=ROOT)
 print('UNITY_PID',player.pid,'BRAIN_PID',server.pid,flush=True)
 result={'playerExit':player.wait(timeout=180),'endpoint':'127.0.0.1:18766'}
 (out/'process-result.json').write_text(json.dumps(result));print(result,flush=True)
finally:
 if player and player.poll() is None:player.terminate();player.wait(10)
 server.terminate();server.wait(10);log.close()
