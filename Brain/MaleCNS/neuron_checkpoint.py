"""Build neuron-only graph, compare deterministic Brian2 reference, then smoke.

Run from Parallel with the dedicated flybrain-malecns Python environment.
"""
import json
import time
import resource
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import psutil
from shiu_compatible import MaleCNSShiuCompatibleLIF

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/neuron_checkpoint'
OUT.mkdir(parents=True, exist_ok=True)


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2)+'\n')


def provenance():
    import brian2
    def digest(path):
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8*1024*1024), b''):
                h.update(chunk)
        return h.hexdigest()
    files = [Path(__file__), Path(__file__).with_name('shiu_compatible.py'),
             ROOT/'Brain/ShiuBaseline/model.py',
             ROOT/'Brain/MaleCNS/config/game_mapping_exploratory_v1.json',
             ROOT/'Brain/MaleCNS/config/nt_policy_exploratory_lif_v1.json']
    save('provenance.json', {'utc':datetime.now(timezone.utc).isoformat(),
         'python':sys.version,'numpy':np.__version__,'brian2':brian2.__version__,
         'platform':platform.platform(),'machine':platform.machine(),
         'ramBytes':psutil.virtual_memory().total,
         'sourceHashes':{str(p.relative_to(ROOT)):digest(p) for p in files},
         'arrayFiles':{p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in OUT.glob('*.npy')}})


def parity():
    import brian2 as br
    br.start_scope()
    br.prefs.codegen.target = 'numpy'
    br.defaultclock.dt = 0.1 * br.ms
    pre = np.array([0, 0, 1, 2, 3])
    post = np.array([1, 2, 3, 3, 4])
    weights = np.array([30., -30., 40., -40., 30.])
    ptr = np.r_[0, np.cumsum(np.bincount(pre, minlength=10))]
    events = {k: [0] for k in [0, 10, 20, 21, 40, 80, 160, 200]}
    custom = MaleCNSShiuCompatibleLIF(10, ptr, post, weights, [0])
    custom.v[2] = -44
    counts, spikes, states = custom.step(400, events, True)
    namespace = {'v_0': -52*br.mV, 'v_rst': -52*br.mV,
                 'v_th': -45*br.mV, 't_mbr':20*br.ms, 'tau':5*br.ms}
    g = br.NeuronGroup(10, 'dv/dt=(v_0-v+g)/t_mbr : volt (unless refractory)\ndg/dt=-g/tau : volt (unless refractory)\nrfc : second',
                      threshold='v>v_th', reset='v=v_rst; w=0; g=0*mV', refractory='rfc', method='linear', namespace=namespace)
    g.v = -52*br.mV
    g.v[2] = -44*br.mV
    g.rfc = 2.2*br.ms
    g.rfc[0] = 0*br.ms
    s = br.Synapses(g,g,'w:volt',on_pre='g_post+=w',delay=1.8*br.ms)
    s.connect(i=pre,j=post); s.w=weights*br.mV
    source = br.SpikeGeneratorGroup(1, np.zeros(len(events),dtype=int), np.array(list(events))*0.1*br.ms)
    external = br.Synapses(source,g,on_pre='v_post+=68.75*mV')
    external.connect(i=[0],j=[0])
    sm=br.SpikeMonitor(g); vm=br.StateMonitor(g,['v','g'],record=True,when='end')
    br.Network(g,s,source,external,sm,vm).run(40*br.ms)
    reference = sorted(zip(map(int,sm.i[:]),map(int,np.rint(sm.t[:]/br.ms/0.1))))
    v=np.array([x[0] for x in states]).T
    syn=np.array([x[1] for x in states]).T
    report={'spikesEqual':sorted(spikes)==reference, 'customSpikes':spikes,'referenceSpikes':reference,
            'maxVoltageErrorMv':float(np.max(abs(v-vm.v[:]/br.mV))),
            'maxSynapticErrorMv':float(np.max(abs(syn-vm.g[:]/br.mV))),
            'resetNote':'Exact Shiu reset string; w=0 is a local reset temporary, not a synaptic weight mutation.',
            'customSpikeCount':int(counts.sum()), 'referenceSpikeCount':int(sm.num_spikes),
            'dtMs':0.1,'neurons':10}
    report['passed']=report['spikesEqual'] and report['maxVoltageErrorMv']<1e-8 and report['maxSynapticErrorMv']<1e-8
    save('parity.json',report)
    if not report['passed']:
        raise RuntimeError('Brian2 parity failed; full graph simulation prohibited')


def build():
    a=pd.read_feather(ROOT.parent/'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather')
    keep=a.superclass.notna() & a.status.ne('Glia')
    ids=np.sort(a.loc[keep,'bodyId'].to_numpy(dtype=np.int64))
    old=ROOT/'artifacts/malecns_structural_graph'
    oldids=np.load(old/'body_ids.npy',mmap_mode='r')
    mapping=np.full(len(oldids),-1,dtype=np.int32)
    mapping[np.searchsorted(oldids,ids)]=np.arange(len(ids))
    pre=np.load(old/'pre_index.npy',mmap_mode='r'); post=np.load(old/'post_index.npy',mmap_mode='r')
    count=np.load(old/'synapse_count.npy',mmap_mode='r')
    sign=np.load(ROOT/'artifacts/malecns_signed_graph/sign.npy',mmap_mode='r')
    mask=(mapping[pre]>=0)&(mapping[post]>=0)
    np.save(OUT/'body_ids.npy',ids)
    np.save(OUT/'pre.npy',mapping[pre[mask]])
    np.save(OUT/'post.npy',mapping[post[mask]])
    np.save(OUT/'count.npy',count[mask]);np.save(OUT/'sign.npy',sign[mask])
    active=mask & (sign!=0)
    order=np.argsort(mapping[pre[active]],kind='stable')
    pp=mapping[pre[active]][order]
    np.save(OUT/'indptr.npy',np.r_[0,np.cumsum(np.bincount(pp,minlength=len(ids)))])
    np.save(OUT/'targets.npy',mapping[post[active]][order])
    np.save(OUT/'weights.npy',(count[active]*sign[active]*0.275*0.1)[order])
    incident=np.unique(np.r_[mapping[pre[mask]],mapping[post[mask]]])
    report={'entities_before':len(a),'neurons_after':len(ids),'glia_excluded':int(a.status.eq('Glia').sum()),
            'other_excluded':int((~keep & ~a.status.eq('Glia')).sum()),'other_exclusionReason':'unclassified superclass, not asserted non-neuronal',
            'includedSuperclasses':sorted(a.loc[keep,'superclass'].unique()),
            'edges_before':len(pre),'edges_after':int(mask.sum()),'removed_edges':int((~mask).sum()),
            'effective_edges':int(active.sum()),'isolated_neurons':len(ids)-len(incident),
            'datasetManifest':json.loads((ROOT/'Brain/MaleCNS/results/download_manifest.json').read_text()),
            'rssBytes':psutil.Process().memory_info().rss,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    save('graph_audit.json',report)


def runs():
    arrays=[np.load(OUT/name,mmap_mode='r') for name in ['body_ids.npy','indptr.npy','targets.npy','weights.npy']]
    ids,ptr,post,weights=arrays
    before=resource.getrusage(resource.RUSAGE_SELF)
    touched=[float(x.sum()) for x in arrays]
    after=resource.getrusage(resource.RUSAGE_SELF)
    mapping=json.loads((ROOT/'Brain/MaleCNS/config/game_mapping_exploratory_v1.json').read_text())
    sources=np.searchsorted(ids,np.array(mapping['groups']['R'],dtype=np.int64))
    target=int(np.searchsorted(ids,10360))
    assert ids[target] == 10360 and target not in sources
    assert np.array_equal(ids[sources], np.array(mapping['groups']['R'], dtype=np.int64))
    def trial(seed,window,repeats):
        started=time.perf_counter(); sim=MaleCNSShiuCompatibleLIF(len(ids),ptr,post,weights,sources)
        init=(time.perf_counter()-started)*1000
        rng=np.random.default_rng(seed); frames=[]
        for on in ([False,True,False,False] if repeats == 1 else [False,True,False]*repeats):
            ticks=int(window/0.1)
            events={sim.tick+k:list(sources[rng.random(len(sources))<0.01]) for k in range(ticks)} if on else {}
            start=time.perf_counter(); counts,_,_=sim.step(ticks,events)
            frames.append({'stimulated':on,'readoutHz':float(counts[target]*1000/window),'spikes':int(counts.sum()),'wallMs':(time.perf_counter()-start)*1000})
        return {'seed':seed,'windowMs':window,'initializationMs':init,'frames':frames}
    trials=[trial(s,100,1) for s in (20260921,20260922,20260923)]
    benchmarks=[]
    for window in (25,50,100):
        result=trial(20260924,window,4); times=[f['wallMs'] for f in result['frames'][1:]]
        result.update({'firstStepMs':result['frames'][0]['wallMs'],'warmSamples':len(times),'meanMs':float(np.mean(times)),
                       'medianMs':float(np.median(times)),'p95Ms':float(np.percentile(times,95)), 'simulatedWallRatio':window/float(np.mean(times))})
        benchmarks.append(result)
    save('execution.json',{'model':'Shiu-compatible LIF dynamics applied to the MaleCNS connectome','ready':False,
         'recurrentScale':0.1,'trials':trials,'benchmarks':benchmarks,'mappedBytes':sum(x.nbytes for x in arrays),
         'fileBytes':sum((OUT/n).stat().st_size for n in ['body_ids.npy','indptr.npy','targets.npy','weights.npy']),
         'warmTouchChecksums':touched,'warmTouchMinorFaults':after.ru_minflt-before.ru_minflt,'warmTouchMajorFaults':after.ru_majflt-before.ru_majflt,
         'rssBytes':psutil.Process().memory_info().rss,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})


if __name__=='__main__':
    parity()
    build()
    runs()
    provenance()
