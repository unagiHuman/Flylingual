"""Extended diagnostic equivalence and optional candidate-only localhost server."""
import pathlib,sys,inspect,json,time,argparse,asyncio
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Brain/MaleCNS'))
from malecns_reference import reference_ac as ac
from malecns_reference import Original
# Reuse precisely the candidate generation block without running the earlier test.
text=(ROOT/'tools/probe_malecns_buffers.py').read_text(encoding='utf-8-sig')
block=text[text.index('source=inspect.getsource(Original)'):text.index("(out/'candidate.py').write_text(source)")]
ns={'np':np,'inspect':inspect,'Original':Original};exec(block,ns);Candidate=ns['Candidate']
parser=argparse.ArgumentParser();parser.add_argument('--server',action='store_true');args=parser.parse_args()
if args.server:
 ac.MaleCNSShiuCompatibleLIF=Candidate
 import brain_server_analog as server_module
 server_module.MaleCNSAnalogController=ac.MaleCNSAnalogController
 from brain_server_analog import AnalogServer
 from types import SimpleNamespace
 asyncio.run(AnalogServer(SimpleNamespace(graph=ROOT/'artifacts/neuron_checkpoint',config=ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',host='127.0.0.1',port=18766,seed=20270101,window_ms=50)).run())
 sys.exit()
out=ROOT/'artifacts/windows-malecns/buffer-extended';out.mkdir(parents=True,exist_ok=True)
report={'completed':False,'rows':[],'seeds':[20270102,20270103]}
def save(): (out/'equivalence.json').write_text(json.dumps(report,indent=2))
for seed in report['seeds']:
 def make(cls):
  ac.MaleCNSShiuCompatibleLIF=cls
  return ac.MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',seed,50).initialize()
 a=make(Original);b=make(Candidate)
 for action,n in [('STOP',4),('FORWARD',8),('TURN_R',8),('TURN_L',8),('FORWARD_R',8),('FORWARD_L',8),('STOP',16)]:
  a.set_action(action);b.set_action(action)
  for i in range(n):
   frames={};times={}
   for label,c in ([('original',a),('candidate',b)] if i%2==0 else [('candidate',b),('original',a)]):
    t=time.perf_counter();f=c.step();times[label]=(time.perf_counter()-t)*1000;f.pop('performance');frames[label]=f
   assert frames['original']==frames['candidate'],'frame mismatch'
   for key in ['v','g','last','rfc']:assert np.array_equal(getattr(a.sim,key),getattr(b.sim,key)),key
   assert a.sim.pending==b.sim.pending and a.sim.tick==b.sim.tick
   assert a.rng.bit_generator.state==b.rng.bit_generator.state
   report['rows'].append({'seed':seed,'action':action,'index':i,'exact':True,'motor':frames['original']['motor'],**times});save()
  print(seed,action,n,'exact',flush=True)
report['completed']=True;save()
