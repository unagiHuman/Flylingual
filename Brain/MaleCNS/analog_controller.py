"""Persistent experimental MaleCNS controller, compatible nested BrainFrame."""
import copy
import json
import time
from pathlib import Path
import numpy as np
from shiu_compatible import MaleCNSShiuCompatibleLIF
from analog_motor_decoder import AnalogMotorDecoder
from temporal_motor_decoder import TemporalMotorDecoder

ROOT=Path(__file__).resolve().parents[2]
ACTIONS={'STOP':(), 'FORWARD':('F',), 'TURN_R':('R',), 'TURN_L':('L',),
         'FORWARD_R':('F','R'), 'FORWARD_L':('F','L')}


class MaleCNSAnalogController:
    def __init__(self,graph,config,seed=20261101,window_ms=100):
        self.graph=Path(graph); self.config=json.loads(Path(config).read_text()) if isinstance(config,(str,Path)) else config
        self.seed=seed; self.window_ms=float(window_ms); self.sequence=0; self.action='STOP'
        self.network_rebuild_count=0; self.state_reset_count=0; self.frame=None
        self.decoder=AnalogMotorDecoder(self.config['decoder']) if self.config.get('decoder') else None
        self.temporal=bool(self.config.get('temporalDecoder'))
        if self.temporal: self.decoder=TemporalMotorDecoder(self.config['temporalDecoder'])
        if self.config.get('stimulusRateHz') != 100:
            raise ValueError('This checkpoint fixes stimulation at 100 Hz')
        if window_ms<=0 or not np.isclose(window_ms/.1,round(window_ms/.1)):
            raise ValueError('window must be positive multiple of .1 ms')

    def initialize(self):
        if self.network_rebuild_count: raise RuntimeError('Already initialized')
        t=time.perf_counter()
        self.ids,ptr,post,w=[np.load(self.graph/n,mmap_mode='r') for n in ('body_ids.npy','indptr.npy','targets.npy','weights.npy')]
        def indices(values):
            values=np.array(values,dtype=np.int64); ix=np.searchsorted(self.ids,values)
            if np.any(ix>=len(self.ids)) or not np.array_equal(self.ids[ix],values): raise ValueError('Unknown MaleCNS ID')
            return ix
        self.inputs={g:indices(v) for g,v in self.config['inputs'].items()}
        self.dns={k:indices([v])[0] for k,v in self.config['readouts'].items()}
        full={axis:{s:{typ:indices(values) for typ,values in g.items()} for s,g in p.items()} for axis,p in self.config['populations'].items()}
        self.observed=np.unique(np.concatenate([ix for p in full.values() for g in p.values() for ix in g.values()]))
        pos={int(i):j for j,i in enumerate(self.observed)}
        self.groups={axis:{s:{typ:np.array([pos[int(i)] for i in ix]) for typ,ix in g.items()} for s,g in p.items()} for axis,p in full.items()}
        stim=np.unique(np.concatenate(list(self.inputs.values())))
        if np.intersect1d(stim,self.observed).size: raise ValueError('Input/readout overlap')
        self.sim=MaleCNSShiuCompatibleLIF(len(self.ids),ptr,post,w,stim)
        self.rng=np.random.default_rng(self.seed)
        # Explicit initial no-input baseline; no subsequent resets.
        self.sim.step(1000)
        self.baseline=self.sim.v[self.observed].copy()
        self.network_rebuild_count=1
        self.initialization_ms=(time.perf_counter()-t)*1000
        return self

    def set_action(self,action):
        value=str(getattr(action,'value',action))
        if value not in ACTIONS: raise ValueError('Unknown action: '+value)
        self.action=value

    def step(self):
        if not self.network_rebuild_count: raise RuntimeError('Initialize first')
        t=time.perf_counter(); ticks=round(self.window_ms/.1)
        groups= ACTIONS[self.action]
        stim=np.unique(np.concatenate([self.inputs[g] for g in groups])) if groups else np.array([],dtype=int)
        sums=np.zeros((2,len(self.observed))); counts=np.zeros(len(self.ids),dtype=np.int64)
        for _ in range(ticks):
            events={self.sim.tick:list(stim[self.rng.random(len(stim))<.01])} if len(stim) else {}
            c,_,_=self.sim.step(1,events); counts+=c
            sums[0]+=self.sim.v[self.observed]; sums[1]+=self.sim.g[self.observed]
        mean=sums/ticks; delta=mean[0]-self.baseline
        response={axis:{s:float(np.mean([delta[ix].mean() for ix in g.values()])) for s,g in p.items()} for axis,p in self.groups.items()}
        raw=[(response['forward']['R']+response['forward']['L'])/2,response['turn']['R']-response['turn']['L']]
        brain={k:float(counts[i]*1000/self.window_ms) for k,i in self.dns.items()}
        brain['DNp09_Hz']=(brain['DNp09_L_Hz']+brain['DNp09_R_Hz'])/2
        brain['DNa02Difference_Hz']=brain['DNa02_R_Hz']-brain['DNa02_L_Hz']
        decoded=(self.decoder.decode(raw,self.window_ms) if self.temporal else self.decoder.decode(raw)) if self.decoder else {'forward':0.,'turn':0.}
        self.frame={'type':'brain_frame','sequence':self.sequence,'requestedAction':self.action,
            'brainTimeMs':self.sim.tick*.1,'windowMs':self.window_ms,
            'appliedRequestId':None,'appliedClientTimeMs':None,
            'motor':{k:decoded[k] for k in ('forward','turn')},'brain':brain,
            'raw':{'forward_raw':raw[0],'turn_raw':raw[1],'populationDeltaMv':response,
                   'bodyIds':self.ids[self.observed].tolist(),'deltaV':delta.tolist(),'meanG':mean[1].tolist()},
            'performance':{'windowMs':self.window_ms,'stepWallTimeMs':(time.perf_counter()-t)*1000},
            'diagnostics':{'networkRebuildCount':self.network_rebuild_count,'stateResetCount':self.state_reset_count},
            'metadata':{'backendId':'MALECNS_EXPERIMENTAL','datasetId':'male-cns:v1.0',
                        'model':'MaleCNS + Shiu-compatible LIF','motor_readout':'VNC_ANALOG_POPULATION',
                        'mode':'LIVE','ready':False,'calibrationApplied':self.decoder is not None}}
        self.frame['metadata']['sixActionValidationPassed']=bool(self.config.get('sixActionValidationPassed',False))
        if self.temporal:
            self.frame['raw']['filteredRaw']=decoded['filteredRaw']
            self.frame['metadata']['motor_readout']='VNC_ANALOG_POPULATION'
            self.frame['metadata']['temporalDecoder']=self.config['temporalDecoder']['mode']
            self.frame['metadata']['sixActionValidationPassed'] &= self.window_ms==50
        self.sequence+=1
        return self.get_frame()

    def get_frame(self):
        return copy.deepcopy(self.frame)
