"""Read-only, bounded Windows MaleCNS CPU profiling; no TCP or parameter edits."""
import sys,pathlib,time,json,cProfile,pstats,io,platform
import numpy as np,psutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Brain/MaleCNS'))
from analog_controller import MaleCNSAnalogController
out=ROOT/'artifacts/windows-malecns/profile';out.mkdir(parents=True,exist_ok=True)
p=psutil.Process(); psutil.cpu_percent(None,percpu=True)
meta={'platform':platform.platform(),'processor':platform.processor(),'affinity':p.cpu_affinity(),'battery':str(psutil.sensors_battery()),'numpy':np.__version__,'seed':20270101,'windowMs':50,'dtMs':.1}
buf=io.StringIO()
from contextlib import redirect_stdout
with redirect_stdout(buf): np.show_config()
meta['numpyConfig']=buf.getvalue()
c=MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',20270101,50)
t=time.perf_counter();c.initialize();meta['initializeSeconds']=time.perf_counter()-t
rows=[]
for action in ['STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L','STOP']:
 c.set_action(action)
 for i in range(2):
  t=time.perf_counter();ct=time.process_time();f=c.step();elapsed=time.perf_counter()-t
  rows.append({'action':action,'wallMs':elapsed*1000,'cpuMs':(time.process_time()-ct)*1000,'frame':f})
 print(action,round(elapsed*1000),flush=True)
prof=cProfile.Profile();prof.enable();c.step();prof.disable();prof.dump_stats(str(out/'step.prof'))
buf=io.StringIO();pstats.Stats(prof,stream=buf).strip_dirs().sort_stats('tottime').print_stats(25)
(out/'profile.txt').write_text(buf.getvalue());meta.update(rss=p.memory_info().rss,cpuPercentPerCore=psutil.cpu_percent(None,percpu=True),cpuFrequency=str(psutil.cpu_freq()),rows=rows)
(out/'direct.json').write_text(json.dumps(meta,indent=2));print(buf.getvalue(),flush=True)
