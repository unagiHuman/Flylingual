"""Owns and cleans up one diagnostic localhost candidate server."""
import pathlib,subprocess,sys,time,json,asyncio
ROOT=pathlib.Path(__file__).resolve().parents[1]
folder=ROOT/'artifacts/windows-malecns/buffer-extended';folder.mkdir(parents=True,exist_ok=True)
log=(folder/'candidate-server.log').open('w')
p=subprocess.Popen([sys.executable,str(ROOT/'tools/validate_malecns_buffers_extended.py'),'--server'],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
try:
 for _ in range(120):
  if p.poll() is not None:raise RuntimeError('Candidate server exited')
  if 'READY at' in (folder/'candidate-server.log').read_text():break
  time.sleep(.25)
 else:raise TimeoutError('Startup timeout')
 # Same probe, longer final/initial STOP observation only. Explicitly recorded in report.
 source=(ROOT/'tools/probe_malecns_live.py').read_text(encoding='utf-8-sig')
 source=source.replace("while len(sample['frames'])<8:","while len(sample['frames'])<(16 if action=='STOP' else 8):")
 ns={'__name__':'diagnostic_probe'};exec(compile(source,'<candidate-tcp-probe>','exec'),ns)
 from types import SimpleNamespace
 code=asyncio.run(ns['run'](SimpleNamespace(host='127.0.0.1',port=18766,output=str(folder/'tcp.json'))))
 print('PROBE_EXIT',code,flush=True)
 async def reconnect():
  r,w=await asyncio.open_connection('127.0.0.1',18766,limit=4*1024*1024)
  msgs=[]
  try:
   for _ in range(4):msgs.append(json.loads(await asyncio.wait_for(r.readline(),15)))
  finally:w.close();await w.wait_closed()
  (folder/'reconnect.json').write_text(json.dumps({'messages':msgs,'disconnect':True},indent=2))
 asyncio.run(reconnect())
finally:
 p.terminate()
 try:p.wait(10)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 log.close()
