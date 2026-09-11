"""Diagnostic-only state observation; production simulator and arrays untouched."""
import hashlib
import json
import resource
import time
from pathlib import Path
import numpy as np
import pandas as pd
import psutil
from shiu_compatible import MaleCNSShiuCompatibleLIF

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'Docs/mac/checkpoints/subthreshold'
GRAPH = ROOT/'artifacts/neuron_checkpoint'


def main():
    start = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    ids,ptr,post,weights = [np.load(GRAPH/n,mmap_mode='r') for n in
                          ('body_ids.npy','indptr.npy','targets.npy','weights.npy')]
    a = pd.read_feather(ROOT.parent/'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather').set_index('bodyId').loc[ids]
    vnc = a.superclass.str.startswith('vnc_',na=False).to_numpy()
    dn = int(np.searchsorted(ids,10360)); assert ids[dn]==10360
    lo,hi = map(int,ptr[dn:dn+2])
    edge_indices = np.arange(lo,hi)[vnc[post[lo:hi]]]
    targets = post[edge_indices]; assert len(targets)==371 and len(np.unique(targets))==371
    edge_weights = weights[edge_indices]
    mapping = json.loads((ROOT/'Brain/MaleCNS/config/game_mapping_exploratory_v1.json').read_text())
    upstream = np.searchsorted(ids,np.array(mapping['groups']['R'],dtype=np.int64))
    assert np.array_equal(ids[upstream],np.array(mapping['groups']['R'],dtype=np.int64))
    def annotation(i):
        return json.loads(a.iloc[i][['type','instance','superclass','subclass','somaSide','somaNeuromere','mancType']].to_json())
    def experiment(label, seed=20260921, gain=1, driven=None):
        t = time.perf_counter()
        w = weights if gain==1 else weights.copy()
        if gain!=1:
            w[lo:hi] *= gain
        sim = MaleCNSShiuCompatibleLIF(len(ids),ptr,post,w,upstream if driven is None else ())
        rng = np.random.default_rng(seed)
        # Aggregate every end-of-tick state, never store full CNS state histories.
        extrema = np.zeros((4,4,len(targets)))
        extrema[:,0:2,:] = np.inf
        extrema[:,2:4,:] = -np.inf
        phase_counts = np.zeros((4,len(ids)),dtype=np.int64)
        received = np.zeros(len(targets),dtype=np.int64)
        scheduled = []
        observed_spikes = []
        driven_spikes = {int(i):[] for i in driven} if driven is not None else {}
        delivery_ticks = []
        delivery_error = []
        trace = []
        strongest = int(np.argmax(abs(edge_weights)))
        for k in range(4000):
            phase = k//1000
            events = {}
            if driven is None and phase==1:
                events[k] = list(upstream[rng.random(len(upstream))<.01])
            if driven is not None and 1000<=k<2000 and (k-1000)%100==0:
                # Diagnostic voltage pulse before update; ordinary threshold/reset/
                # refractory/delay remain untouched. Exact train verified below.
                sim.v[driven] = -44.
                scheduled.append(k)
            due = dn in sim.pending[k%19]
            before_g = sim.g[targets].copy() if due else None
            active = ((k-sim.last[targets])>=sim.rfc[targets]) if due else None
            count,_,_ = sim.step(1,events)
            phase_counts[phase] += count
            if count[dn]:
                observed_spikes.append(k)
            for i in driven_spikes:
                if count[i]:
                    driven_spikes[i].append(k)
            if due:
                received += active.astype(np.int64)
                delivery_ticks.append(k)
                # Residual includes any other same-tick synapses; direct-only
                # control isolates this check until recurrent responses occur.
                expected = before_g.copy()
                expected[active] *= np.exp(-.1/5)
                expected[active] += edge_weights[active]*gain
                valid = count[targets]==0
                delivery_error.append(float(np.max(abs(sim.g[targets][valid]-expected[valid]))) if valid.any() else None)
            v,g = sim.v[targets],sim.g[targets]
            extrema[phase,0] = np.minimum(extrema[phase,0],v)
            extrema[phase,1] = np.minimum(extrema[phase,1],g)
            extrema[phase,2] = np.maximum(extrema[phase,2],v)
            extrema[phase,3] = np.maximum(extrema[phase,3],g)
            if k%10==0 or due:
                trace.append([k,float(v[strongest]),float(g[strongest])])
        summaries = []
        for j,i in enumerate(targets):
            summaries.append({'bodyId':int(ids[i]),'internalIndex':int(i),'annotation':annotation(int(i)),
              'weightMv':float(edge_weights[j]),'sign':int(np.sign(edge_weights[j])),
              'transmitter':'ACh' if edge_weights[j]>0 else 'GABA','baselineV':extrema[0,[0,2],j].tolist(),
              'stimMinV':float(extrema[1,0,j]),'stimMaxV':float(extrema[1,2,j]),
              'stimMinG':float(extrema[1,1,j]),'stimMaxG':float(extrema[1,3,j]),
              'thresholdMarginMv':float(-45-extrema[1,2,j]),
              'receivedDNa02Events':int(received[j]),'spikesByPhase':phase_counts[:,i].tolist(),
              'recoveryExtremaMinVMinGMaxVMaxG':extrema[2:,:,j].tolist(),
              'finalV':float(sim.v[i]),'finalG':float(sim.g[i])})
        margin = -45-extrema[1,2]
        report = {'label':label,'seed':seed,'diagnosticGain':gain,'drivenIds':None if driven is None else ids[driven].tolist(),
            'DNa02SpikeTicks':observed_spikes,'scheduledPulseTicks':scheduled,
            'allDrivenSpikeTicks':{str(int(ids[i])):ticks for i,ticks in driven_spikes.items()},
            'exactTenVerified':None if driven is None else observed_spikes==scheduled and len(scheduled)==10,
            'deliveryTicks':delivery_ticks,'deliveryResidualMaxMv':delivery_error,
            'delayVerified':delivery_ticks==[k+18 for k in observed_spikes if k+18<4000],
            'sanity':{'gChanged':int(np.sum(np.max(abs(extrema[1,[1,3]]),axis=0)>1e-10)),
                      'vChanged':int(np.sum(np.max(abs(extrema[1,[0,2]]+52),axis=0)>1e-10)),
                      'depolarized':int(np.sum(extrema[1,2]>-52+1e-10)),
                      'hyperpolarized':int(np.sum(extrema[1,0]<-52-1e-10)),
                      'within1mV':int(np.sum(margin<=1)), 'within3mV':int(np.sum(margin<=3)),
                      'within5mV':int(np.sum(margin<=5))},
            'spikingVncIds':ids[np.flatnonzero(vnc & (phase_counts.sum(axis=0)>0))].tolist(),
            'vncSpikesByPhase':phase_counts[:,vnc].sum(axis=1).tolist(),
            'closest50':sorted(summaries,key=lambda r:r['thresholdMarginMv'])[:50],
            'targets':summaries,'traceBodyId':int(ids[targets[strongest]]),'traceTickVMvGMv':trace,
            'runtimeSeconds':time.perf_counter()-t}
        if driven is not None and not report['exactTenVerified']:
            raise RuntimeError('Diagnostic source train not exact; cannot interpret sweep')
        if any(ticks!=scheduled for ticks in driven_spikes.values()):
            raise RuntimeError('Co-DN train not exact')
        (OUT/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        print(label,report['sanity'],len(report['spikingVncIds']),flush=True)
        return report
    trials = [experiment('upstream_'+str(s),seed=s) for s in (20260921,20260922,20260923)]
    if any(r['sanity']['gChanged']==0 for r in trials):
        raise RuntimeError('No g propagation: stop downstream diagnostics')
    direct = experiment('direct_gain1',driven=[dn])
    sweeps = [direct]+[experiment('direct_gain'+str(g),gain=g,driven=[dn]) for g in (2,4,8)]
    # Only scan descending rows, selecting existing effective inputs to top50.
    closest_ids = [r['bodyId'] for r in direct['closest50']]
    closest_indices = np.searchsorted(ids,closest_ids)
    dn_indices = np.flatnonzero(a.superclass.str.startswith('descending_neuron',na=False).to_numpy())
    convergent = []
    for d in dn_indices:
        if d==dn:
            continue
        left,right = map(int,ptr[d:d+2])
        hits = np.flatnonzero(np.isin(post[left:right],closest_indices))
        for h in hits:
            e = left+int(h); w = float(weights[e])
            convergent.append({'dnId':int(ids[d]),'targetId':int(ids[post[e]]),'weightMv':w,
                'sign':int(np.sign(w)),'transmitter':'ACh' if w>0 else 'GABA','annotation':annotation(int(d))})
    convergent.sort(key=lambda r:-abs(r['weightMv']))
    # Bound coactivation to strongest positive convergent inputs to closest target.
    positive = [r for r in convergent if r['weightMv']>0 and r['targetId']==closest_ids[0]]
    codns = list(dict.fromkeys(r['dnId'] for r in positive))[:2]
    co = [experiment('coactivation_'+str(n),driven=[dn]+list(np.searchsorted(ids,codns[:n]))) for n in range(1,len(codns)+1)]
    dist = {k:float(f(edge_weights)) for k,f in {'min':np.min,'median':np.median,'mean':np.mean,'p90':lambda x:np.percentile(x,90),'p95':lambda x:np.percentile(x,95),'max':np.max}.items()}
    structural_pre = np.load(GRAPH/'pre.npy',mmap_mode='r')
    structural_post = np.load(GRAPH/'post.npy',mmap_mode='r')
    structural_count = np.load(GRAPH/'count.npy',mmap_mode='r')
    structural_sign = np.load(GRAPH/'sign.npy',mmap_mode='r')
    row = np.flatnonzero(structural_pre==dn)
    row = row[vnc[structural_post[row]] & (structural_sign[row]!=0)]
    expected = {int(structural_post[e]):float(structural_count[e]*structural_sign[e]*.275*.1) for e in row}
    audit_pass = len(expected)==371 and all(np.isclose(expected[int(i)],w) for i,w in zip(targets,edge_weights))
    assert audit_pass
    summary = {'ready':False,'classification':'SUBTHRESHOLD_SINGLE_DN' if not direct['spikingVncIds'] else 'UNRESOLVED',
       'sourceIndex':dn,'sourceBodyId':10360,'targetCount':len(targets),'modelUnchanged':True,
       'structuralToDynamicAudit':{'passed':bool(audit_pass),'conversion':'synapse_count * sign * 0.275 * 0.1 mV','matchedTargets':len(expected)},
       'observation':'end-of-tick v/g; voltage maxima in spiking cases omit pre-reset peak; use spike counts for threshold crossing',
       'diagnosticMode':'pre-update voltage pulse; source exact10 ticks verified; ordinary simulator unchanged',
       'gainScope':'diagnostic sensitivity analysis, only DNa02 outgoing row, in-memory copy',
       'edgeDistributionMv':dist,'signCounts':{str(s):int(np.sum(np.sign(edge_weights)==s)) for s in (-1,0,1)},
       'weightTop50':sorted(direct['targets'],key=lambda r:-abs(r['weightMv']))[:50],
       'upstreamSanity':[r['sanity'] for r in trials],
       'directSanity':direct['sanity'],'closest':direct['closest50'][0],
       'sweep':[{'gain':r['diagnosticGain'],'spikingVncIds':r['spikingVncIds'],'vncSpikesByPhase':r['vncSpikesByPhase']} for r in sweeps],
       'firstSpikeGain':next((r['diagnosticGain'] for r in sweeps if r['spikingVncIds']),None),
       'convergentDnRanking':convergent,'coactivationTarget':closest_ids[0],
       'coactivation':[{'drivenIds':r['drivenIds'],'spikingVncIds':r['spikingVncIds'],'closest':r['closest50'][0]} for r in co],
       'baselineLimitation':'Zero baseline spikes cannot show rate suppression; g/v can show subthreshold responses.',
       'runtimeSeconds':time.perf_counter()-start,'rssBytes':psutil.Process().memory_info().rss,
       'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
       'provenance':json.loads((GRAPH/'provenance.json').read_text()),
       'sourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('shiu_compatible.py')]}}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('classification','edgeDistributionMv','firstSpikeGain','runtimeSeconds','peakRssBytes')}),flush=True)


if __name__=='__main__':
    main()
