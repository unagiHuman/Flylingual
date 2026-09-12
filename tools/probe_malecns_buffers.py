"""Diagnostic-only buffer reuse candidate; production files are never modified."""
import pathlib,sys,time,json,inspect,collections
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Brain/MaleCNS'))
from malecns_reference import reference_ac as ac
from malecns_reference import Original
out=ROOT/'artifacts/windows-malecns/buffer-probe';out.mkdir(parents=True,exist_ok=True)
source=inspect.getsource(Original)
old='''            self.v[active] = -52 + (self.v[active]+52)*a + self.g[active]*c
            self.g[active] *= b'''
new='''            np.add(self.v, 52, out=self._scratch_v)
            np.multiply(self._scratch_v, a, out=self._scratch_v)
            np.add(-52, self._scratch_v, out=self._scratch_v)
            np.multiply(self.g, c, out=self._scratch_g)
            np.add(self._scratch_v, self._scratch_g, out=self._scratch_v)
            np.copyto(self.v, self._scratch_v, where=active)
            np.multiply(self.g, b, out=self.g, where=active)'''
assert source.count(old)==1
source=source.replace('class MaleCNSShiuCompatibleLIF:', 'class Candidate:').replace(old,new).replace('        self.tick = 0','        self._scratch_v = np.empty(n, dtype=np.float64)\n        self._scratch_g = np.empty(n, dtype=np.float64)\n        self.tick = 0')
ns={'np':np};exec(compile(source,'<diagnostic-buffer-candidate>','exec'),ns);Candidate=ns['Candidate']
(out/'candidate.py').write_text(source)
def make(cls):
 ac.MaleCNSShiuCompatibleLIF=cls
 return ac.MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',20270101,50).initialize()
a=make(Original); b=make(Candidate)
def equal_state():
 for key in ['v','g','last','rfc']:
  assert np.array_equal(getattr(a.sim,key),getattr(b.sim,key)),key
 assert a.sim.tick==b.sim.tick and a.sim.pending==b.sim.pending
 assert a.rng.bit_generator.state==b.rng.bit_generator.state
equal_state()
# Attribute time between Python line events to the preceding line. Instrumented timing only.
totals=collections.defaultdict(float);previous=[None,None]
def trace(frame,event,arg):
 if frame.f_code is Original.step.__code__ and event in ('line','return'):
  now=time.perf_counter()
  if previous[0] is not None:totals[previous[0]]+=now-previous[1]
  previous[:]=[frame.f_lineno,now] if event=='line' else [None,None]
 return trace
sys.settrace(trace)
a.step()
sys.settrace(None)
b.step();equal_state()
(out/'line-times.json').write_text(json.dumps([{'line':k,'seconds':v} for k,v in sorted(totals.items())],indent=2))
rows=[]
for action in ['STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L','STOP']:
 a.set_action(action);b.set_action(action)
 for i in range(4):
  times={};frames={}
  for name,c in ([('original',a),('candidate',b)] if i%2==0 else [('candidate',b),('original',a)]):
   t=time.perf_counter();f=c.step();times[name]=(time.perf_counter()-t)*1000
   f.pop('performance');frames[name]=f
  assert frames['original']==frames['candidate'], 'BrainFrame mismatch'
  equal_state();rows.append({'action':action,'trial':i,**times,'exactStateAndFrame':True})
 print(action,round(np.mean([r['original'] for r in rows[-4:]])),round(np.mean([r['candidate'] for r in rows[-4:]])),flush=True)
 (out/'comparison.json').write_text(json.dumps({'seed':20270101,'rows':rows,'completed':False},indent=2))
(out/'comparison.json').write_text(json.dumps({'seed':20270101,'rows':rows,'completed':True,'scope':'28 windows; exact arrays at window boundaries, RNG, pending spikes and BrainFrame excluding timing; not every tick or multiple seeds'},indent=2))
