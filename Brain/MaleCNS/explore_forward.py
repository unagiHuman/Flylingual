"""Three literature/annotation-grounded candidates; held-out persistent gate."""
import hashlib
import json
import resource
import time
from pathlib import Path
import numpy as np
import pandas as pd
import psutil
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order
from shiu_compatible import MaleCNSShiuCompatibleLIF
from analog_steering import AnalogSteering
from analog_forward import AnalogForward

ROOT=Path(__file__).resolve().parents[2]
GRAPH=ROOT/'artifacts/neuron_checkpoint'
OUT=ROOT/'Docs/mac/checkpoints/forward'


def main():
    started=time.perf_counter(); OUT.mkdir(parents=True,exist_ok=True)
    ids,ptr,post,w=[np.load(GRAPH/n,mmap_mode='r') for n in ('body_ids.npy','indptr.npy','targets.npy','weights.npy')]
    a=pd.read_feather(ROOT.parent/'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather').set_index('bodyId').loc[ids]
    annotation_columns=['type','instance','superclass','somaSide','somaNeuromere','synonyms']
    def ann(i):
        return {'bodyId':int(ids[i]),**json.loads(a.iloc[i][annotation_columns].to_json())}
    vnc=a.superclass.str.startswith('vnc_',na=False).to_numpy()
    motor=a.superclass.eq('vnc_motor').to_numpy()
    # Restrict to explicit leg-related motor type names, not unknown MN types.
    leg=motor & a['type'].str.contains(r'^(Fe |Ti |Ta )|trochanter|coxa|remotor|rotator|adductor|promotor',case=False,na=False).to_numpy()
    observed=np.flatnonzero(vnc); loc={int(i):j for j,i in enumerate(observed)}
    tc=json.loads((ROOT/'Docs/mac/checkpoints/analog-steering/calibration.json').read_text())
    def localize(g):
        return {s:{t:np.array([loc[int(i)] for i in ix]) for t,ix in groups.items()} for s,groups in g.items()}
    tg={s:{t:np.searchsorted(ids,values) for t,values in g.items()} for s,g in tc['populations'].items()}
    turn=AnalogSteering(localize(tg),tc['referenceMv'],tc['deadzoneMv'])
    inputs={s:np.searchsorted(ids,np.array(tc['stimulusMapping']['groups'][s],dtype=np.int64)) for s in ('R','L')}
    candidate_table=[]; populations={}; dn_map={}
    graph=csr_matrix((np.ones(len(post),dtype=np.int8),post,ptr),shape=(len(ids),len(ids)))
    for typ in ('DNp09','DNg97','DNg100'):
        neurons=np.flatnonzero(a['type'].eq(typ).to_numpy() & a.superclass.eq('descending_neuron').to_numpy())
        assert len(neurons)==2 and set(a.iloc[neurons].somaSide)=={'R','L'}
        inputs[typ]=neurons; dn_map[typ]=neurons
        reachable2=set(); details=[]
        for i in neurons:
            lo,hi=map(int,ptr[i:i+2]); direct=post[lo:hi]; weights=w[lo:hi]
            positive=direct[weights>0]; reachable2.update(map(int,positive))
            for j in positive:
                l,h=map(int,ptr[j:j+2]); reachable2.update(map(int,post[l:h][w[l:h]>0]))
            reachable=breadth_first_order(graph,int(i),directed=True,return_predecessors=False)
            details.append({**ann(int(i)), 'directVncCount':int(vnc[direct].sum()),
                 'reachableMotorCount':int(motor[reachable].sum()),'premotorStatus':'not inferred',
                 'effectiveOutWeightSumMv':float(weights.sum()),
                 'directVncEdges':[{'target':int(ids[j]),'weightMv':float(ww),'annotation':ann(int(j))} for j,ww in zip(direct,weights) if vnc[j]]})
        pool=np.array(sorted(i for i in reachable2 if leg[i]),dtype=int)
        byside={s:{t:pool[a.iloc[pool]['type'].eq(t).to_numpy() & a.iloc[pool].somaSide.eq(s).to_numpy()] for t in a.iloc[pool]['type'].unique()} for s in ('R','L')}
        common=sorted(t for t in byside['R'] if len(byside['R'][t]) and len(byside['L'][t]))
        populations[typ]={s:{t:byside[s][t] for t in common} for s in ('R','L')}
        candidate_table.append({'type':typ,'neurons':details,'anatomicalTypes':common,
            'rationale':'MaleCNS type/side plus literature; bilateral pair, positive <=2-hop paths to explicitly named leg motor types. Connectivity is not physiological forward proof.'})
    del graph
    stimulated=np.unique(np.concatenate(list(inputs.values())))
    assert not np.intersect1d(stimulated,observed).size
    def trial(seed,sequence):
        sim=MaleCNSShiuCompatibleLIF(len(ids),ptr,post,w,stimulated)
        rng=np.random.default_rng(seed); baseline=None; frames=[]
        for action in sequence:
            t=time.perf_counter(); sums=np.zeros((2,len(observed))); count=np.zeros(len(ids),dtype=np.int64)
            for _ in range(1000):
                event={} if action=='STOP' else {sim.tick:list(inputs[action][rng.random(len(inputs[action]))<.01])}
                c,_,_=sim.step(1,event); count+=c
                sums[0]+=sim.v[observed]; sums[1]+=sim.g[observed]
            mean=sums/1000
            if baseline is None:
                assert action=='STOP'; baseline=mean[0].copy()
            dv=mean[0]-baseline
            frames.append({'action':action,'wallMs':(time.perf_counter()-t)*1000,
                'candidateHz':{typ:{str(int(ids[i])):int(count[i])*10 for i in ns} for typ,ns in dn_map.items()},
                'vncSpikeCount':int(count[observed].sum()),'motorSpikeCount':int(count[motor].sum()),
                'deltaV':dv.tolist(),'meanG':mean[1].tolist(),'baselineV':baseline.tolist(),
                **turn.decode(dv)})
        return {'seed':seed,'frames':frames}
    trials=[]
    for action in ('DNp09','DNg97','DNg100','R','L'):
        for seed in (20261001,20261002,20261003):
            r=trial(seed,['STOP',action,'STOP','STOP']); trials.append(r)
        print('characterized',action,flush=True)
    # Functional selection only on calibration seeds, whole cell types, no signs.
    # Require each side positive on every candidate trial and >=2x any TURN raw.
    selection=[]
    for typ,g in populations.items():
        passing=[]; scores=[]
        for celltype in g['R']:
            single={s:{celltype:g[s][celltype]} for s in ('R','L')}
            read=AnalogForward(localize(single),1,0)
            f=[read.decode(np.array(r['frames'][1]['deltaV'])) for r in trials if r['frames'][1]['action']==typ]
            controls=[read.decode(np.array(r['frames'][1]['deltaV']))['forwardRawMv'] for r in trials if r['frames'][1]['action'] in ('R','L')]
            minimum=min(x['forwardRawMv'] for x in f); maximum=max(controls)
            ok=all(min(x['bilateralDeltaMv'].values())>0 for x in f) and minimum>max(.001,2*maximum)
            if ok: passing.append(celltype)
            scores.append({'type':celltype,'minimumForwardRawMv':minimum,'maximumTurnRawMv':maximum,'accepted':ok})
        selected={s:{t:g[s][t] for t in passing} for s in ('R','L')}
        score=0
        if passing:
            read=AnalogForward(localize(selected),1,0)
            score=float(np.mean([read.decode(np.array(r['frames'][1]['deltaV']))['forwardRawMv'] for r in trials if r['frames'][1]['action']==typ]))
        selection.append({'candidate':typ,'acceptedTypes':passing,'scores':scores,'scoreMeanForwardMv':score})
    best=max(selection,key=lambda x:x['scoreMeanForwardMv'])
    validation=[]; calibration=None; checks=[]
    if best['acceptedTypes']:
        chosen=best['candidate']; groups={s:{t:populations[chosen][s][t] for t in best['acceptedTypes']} for s in ('R','L')}
        local=localize(groups); read=AnalogForward(local,1,0)
        active=[read.decode(np.array(r['frames'][1]['deltaV']))['forwardRawMv'] for r in trials if r['frames'][1]['action']==chosen]
        recovered=[read.decode(np.array(r['frames'][-1]['deltaV']))['forwardRawMv'] for r in trials]
        reference=float(np.percentile(active,95)); deadzone=max(.02*reference,1.1*max(recovered))
        decoder=AnalogForward(local,reference,deadzone)
        validation=[trial(s,['STOP',chosen,'STOP','STOP','R','STOP','STOP','L','STOP','STOP']) for s in (20261011,20261012,20261013)]
        for r in trials+validation:
            for f in r['frames']:
                f.update(decoder.decode(np.array(f['deltaV'])))
                f['forwardPopulationG']={s:float(np.mean([np.array(f['meanG'])[ix].mean() for ix in g.values()])) for s,g in local.items()}
        checks=[{'seed':r['seed'],'forwardPositive':r['frames'][1]['forward']>0,
                 'turnForwardLessThanHalf':max(r['frames'][i]['forwardRawMv'] for i in (4,7))<.5*r['frames'][1]['forwardRawMv'],
                 'turnSigns':r['frames'][4]['turn']>0 and r['frames'][7]['turn']<0,
                 'recoveredStopZero':all(r['frames'][i]['forward']==0 and r['frames'][i]['turn']==0 for i in (0,3,6,9))} for r in validation]
        population_ids={s:{t:ids[ix].tolist() for t,ix in g.items()} for s,g in groups.items()}
        turn_ids=set(v for g in tc['populations'].values() for vs in g.values() for v in vs)
        forward_ids=set(v for g in population_ids.values() for vs in g.values() for v in vs)
        calibration={'candidate':chosen,'populations':population_ids,'referenceMv':reference,'deadzoneMv':deadzone,
             'formula':'equal sides, equal cell types, equal neurons: bilateral mean(initial-baseline-subtracted window mean v); clip((raw-deadzone)/(reference-deadzone),0,1)',
             'selection':best,'overlapWithTurnCells':len(turn_ids & forward_ids),
             'inputIds':ids[inputs[chosen]].tolist(),'stimulusHzPerCell':100,'mode':'direct paired DN Poisson voltage input; no forced spikes',
             'turnCalibrationUnchanged':tc,'ready':False}
    result={'ready':False,'passed':bool(checks) and all(all(v for k,v in c.items() if k!='seed') for c in checks),
        'checks':checks,'candidateTable':candidate_table,'selection':selection,'calibration':calibration,
        'populationPolicy':'Named leg vnc_motor types with positive <=2-hop candidate connectivity; both sides; calibration-only 2x discrimination, equal type weights.',
        'keywordScan':'No descending type/instance/synonyms/matchingNotes matches walking|locomot|forward|leg motor|premotor; use literature aliases verified in annotation.',
        'sourceUrls':['https://pubmed.ncbi.nlm.nih.gov/32822613/','https://www.nature.com/articles/s41586-024-07854-7','https://www.nature.com/articles/s41586-026-10735-w'],
        'observedVncIds':ids[observed].tolist(),'trials':trials,'validation':validation,
        'runtimeSeconds':time.perf_counter()-started,'rssBytes':psutil.Process().memory_info().rss,
        'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'graphProvenance':json.loads((GRAPH/'provenance.json').read_text()),
        'sourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('analog_forward.py'),Path(__file__).with_name('shiu_compatible.py')]}}
    (OUT/'results.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    (OUT/'selection.json').write_text(json.dumps({'selection':selection,'calibration':calibration,'checks':checks},indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'best':best,'checks':checks,'runtime':result['runtimeSeconds'],'peak':result['peakRssBytes']}),flush=True)


if __name__=='__main__':
    main()
