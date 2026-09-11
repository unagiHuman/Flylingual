"""Fixed anatomical selection, R/L characterization, held-out persistent validation."""
import hashlib
import json
import resource
import time
from pathlib import Path
import numpy as np
import pandas as pd
import psutil
from shiu_compatible import MaleCNSShiuCompatibleLIF
from analog_steering import AnalogSteering

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Docs/mac/checkpoints/analog-steering'
GRAPH=ROOT/'artifacts/neuron_checkpoint'


def main():
    start=time.perf_counter(); OUT.mkdir(parents=True,exist_ok=True)
    ids,ptr,post,w=[np.load(GRAPH/n,mmap_mode='r') for n in ('body_ids.npy','indptr.npy','targets.npy','weights.npy')]
    a=pd.read_feather(ROOT.parent/'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather').set_index('bodyId').loc[ids]
    mapping=json.loads((ROOT/'Brain/MaleCNS/config/game_mapping_exploratory_v1.json').read_text())
    dns={s:int(np.searchsorted(ids,int(mapping['readouts']['DNa02_'+s]))) for s in ('R','L')}
    groups={}; direct={}
    for side,d in dns.items():
        row=a.iloc[d]; assert row['type']=='DNa02' and row.somaSide==side and row.instance=='DNa02_'+side
        lo,hi=ptr[d:d+2]; targets=post[lo:hi]; weights=w[lo:hi]
        direct[side]=targets[a.iloc[targets].superclass.str.startswith('vnc_',na=False).to_numpy()]
        selected=targets[(weights>0)&a.iloc[targets].superclass.eq('vnc_motor').to_numpy()&a.iloc[targets].somaSide.eq(side).to_numpy()&a.iloc[targets]['type'].notna().to_numpy()]
        groups[side]={t:selected[a.iloc[selected]['type'].eq(t).to_numpy()] for t in sorted(a.iloc[selected]['type'].unique())}
    common=sorted(set(groups['R'])&set(groups['L'])); assert common
    groups={s:{t:g[t] for t in common} for s,g in groups.items()}
    observed=np.unique(np.concatenate(list(direct.values())))
    position={int(i):j for j,i in enumerate(observed)}
    local_groups={s:{t:np.array([position[int(i)] for i in ix]) for t,ix in g.items()} for s,g in groups.items()}
    inputs={s:np.searchsorted(ids,np.array(mapping['groups'][s],dtype=np.int64)) for s in ('R','L')}
    for s,x in inputs.items():
        assert np.array_equal(ids[x],np.array(mapping['groups'][s],dtype=np.int64))
        assert not np.intersect1d(x,observed).size
    raw_decoder=AnalogSteering(local_groups,1,0)
    def trial(seed,sequence):
        sim=MaleCNSShiuCompatibleLIF(len(ids),ptr,post,w,np.unique(np.concatenate(list(inputs.values()))))
        rng=np.random.default_rng(seed); frames=[]; baseline=None
        for action in sequence:
            sums=np.zeros((2,len(observed))); vmax=np.full(len(observed),-np.inf); vmin=np.full(len(observed),np.inf)
            counts=np.zeros(len(ids),dtype=np.int64); t=time.perf_counter()
            for _ in range(1000):
                event={} if action=='STOP' else {sim.tick:list(inputs[action][rng.random(len(inputs[action]))<.01])}
                c,_,_=sim.step(1,event); counts+=c
                sums[0]+=sim.v[observed]; sums[1]+=sim.g[observed]
                vmax=np.maximum(vmax,sim.v[observed]); vmin=np.minimum(vmin,sim.v[observed])
            mean=sums/1000
            if baseline is None:
                assert action=='STOP'; baseline=mean[0].copy()
            dv=mean[0]-baseline
            frame={'action':action,'wallMs':(time.perf_counter()-t)*1000,
                   'DNa02Hz':{s:int(counts[i])*10 for s,i in dns.items()},
                   'meanV':mean[0].tolist(),'maxV':vmax.tolist(),'minV':vmin.tolist(),
                   'meanG':mean[1].tolist(),'deltaMeanV':dv.tolist(),
                   'maxDeltaV':(vmax-baseline).tolist(),
                   'populationMeanG':{s:float(np.mean([mean[1][ix].mean() for ix in g.values()])) for s,g in local_groups.items()},
                   'cellTypeResponse':{s:{typ:float(dv[ix].mean()) for typ,ix in g.items()} for s,g in local_groups.items()},
                   **raw_decoder.decode(dv)}
            frames.append(frame)
        return {'seed':seed,'frames':frames}
    calibration=[]
    for side in ('R','L'):
        for seed in (20260921,20260922,20260923):
            r=trial(seed,['STOP',side,'STOP','STOP']); calibration.append(r)
            print(side,seed,[(f['action'],round(f['rawTurnMv'],6)) for f in r['frames']],flush=True)
    signal=[abs(r['frames'][1]['rawTurnMv']) for r in calibration]
    recovery=[abs(r['frames'][-1]['rawTurnMv']) for r in calibration]
    reference=float(np.percentile(signal,95)); deadzone=max(max(recovery)*1.1,.02*reference)
    assert all(r['frames'][1]['rawTurnMv']*(1 if r['frames'][1]['action']=='R' else -1)>0 for r in calibration)
    decoder=AnalogSteering(local_groups,reference,deadzone)
    validation=[trial(s,['STOP','R','STOP','STOP','L','STOP','STOP']) for s in (20260931,20260932,20260933)]
    for r in calibration+validation:
        for f in r['frames']:
            f.update(decoder.decode(np.array(f['deltaMeanV'])))
    checks=[{'seed':r['seed'],'rightPositive':r['frames'][1]['turn']>0,
             'leftNegative':r['frames'][4]['turn']<0,
             'recoveredStopZero':all(r['frames'][i]['turn']==0 for i in (0,3,6))} for r in validation]
    config={'motor_readout':'VNC_SUBTHRESHOLD_POPULATION','ready':False,
        'selection':'Positive direct ipsilateral DNa02 targets annotated vnc_motor; retain types represented on both sides; equal type then neuron weights; no response-fitted signs.',
        'populations':{s:{t:ids[ix].tolist() for t,ix in g.items()} for s,g in groups.items()},
        'formula':'response=type-balanced mean(window mean v - initial baseline mean v); raw=R-L; turn=sign(raw)*clip((abs(raw)-deadzone)/(reference-deadzone),0,1)',
        'referenceMv':reference,'deadzoneMv':deadzone,'normalization':'p95 absolute calibration STIM raw; deadzone=max(1.1*max recovered STOP raw, .02*reference)',
        'model':'MaleCNS + Shiu-compatible LIF','windowMs':100,'dtMs':.1,
        'stimulusMapping':mapping,'baselinePolicy':'Initial100ms only; never reset membrane or force STOP output',
        'populationAnnotation':json.loads(a.loc[np.unique(np.concatenate([ids[ix] for g in groups.values() for ix in g.values()]))][['type','instance','superclass','somaSide','somaNeuromere']].reset_index().to_json(orient='records'))}
    (OUT/'calibration.json').write_text(json.dumps(config,indent=2)+'\n')
    result={'ready':False,'turnValidationPassed':all(all(v for k,v in c.items() if k!='seed') for c in checks),
       'checks':checks,'observedIds':ids[observed].tolist(),'calibrationExperiments':calibration,'heldOutValidation':validation,
       'runtimeSeconds':time.perf_counter()-start,'rssBytes':psutil.Process().memory_info().rss,
       'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
       'graphProvenance':json.loads((GRAPH/'provenance.json').read_text()),
       'sourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('analog_steering.py'),Path(__file__).with_name('shiu_compatible.py')]}}
    (OUT/'results.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({'passed':result['turnValidationPassed'],'checks':checks,'types':common,'reference':reference,'deadzone':deadzone,'runtime':result['runtimeSeconds']}),flush=True)


if __name__=='__main__':
    main()
