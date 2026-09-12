"""Compare production with a direct spike-count accumulation candidate."""
import pathlib,sys,json,time,inspect
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'Brain/MaleCNS'))
import analog_controller as ac
from shiu_compatible import MaleCNSShiuCompatibleLIF as LIF
out=ROOT/'artifacts/windows-malecns/count-buffer';out.mkdir(parents=True,exist_ok=True)
a_src=inspect.getsource(LIF).replace('record=False, count_buffer=None):','record=False):').replace('count = np.zeros(len(self.v), dtype=np.int64) if count_buffer is None else count_buffer','count = np.zeros(len(self.v), dtype=np.int64)');b_src=a_src.replace('record=False):','record=False, count_buffer=None):').replace('count = np.zeros(len(self.v), dtype=np.int64)','count = np.zeros(len(self.v), dtype=np.int64) if count_buffer is None else count_buffer')
c_src=inspect.getsource(ac.MaleCNSAnalogController).replace('self.sim.step(1,events,count_buffer=counts)','c,_,_=self.sim.step(1,events); counts+=c');d_src=c_src.replace('c,_,_=self.sim.step(1,events); counts+=c','self.sim.step(1,events,count_buffer=counts)');assert d_src!=c_src
(out/'lif-before.py').write_text(a_src);(out/'controller-before.py').write_text(c_src)
ns={'np':np};exec(b_src,ns);OptimizedLIF=ns['MaleCNSShiuCompatibleLIF']
ns=dict(ac.__dict__);ns['MaleCNSShiuCompatibleLIF']=OptimizedLIF;exec(d_src,ns);OptimizedController=ns['MaleCNSAnalogController']
ns0={'np':np};exec(a_src,ns0);baseline_ns=dict(ac.__dict__);baseline_ns['MaleCNSShiuCompatibleLIF']=ns0['MaleCNSShiuCompatibleLIF'];exec(c_src,baseline_ns);BaselineController=baseline_ns['MaleCNSAnalogController']
rows=[]
for seed in [20270101,20270102,20270103]:
 a=BaselineController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',seed,50).initialize()
 b=OptimizedController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',seed,50).initialize()
 for action in ['STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L','STOP']:
  a.set_action(action);b.set_action(action)
  for i in range(8):
   t=time.perf_counter();f=a.step();ta=time.perf_counter()-t;t=time.perf_counter();g=b.step();tb=time.perf_counter()-t
   f.pop('performance');g.pop('performance');assert f==g
   for key in ['v','g','last','rfc']:assert np.array_equal(getattr(a.sim,key),getattr(b.sim,key)),key
   assert a.sim.pending==b.sim.pending and a.rng.bit_generator.state==b.rng.bit_generator.state
   rows.append({'seed':seed,'action':action,'baselineMs':ta*1000,'candidateMs':tb*1000,'exact':True})
  print(seed,action,'exact',flush=True)
  (out/'results.json').write_text(json.dumps({'complete':False,'rows':rows},indent=2))
(out/'results.json').write_text(json.dumps({'complete':True,'rows':rows},indent=2))
