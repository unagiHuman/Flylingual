"""Read-only model use: fixed R stimulus, whole VNC activity audit."""
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

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT/'artifacts/neuron_checkpoint'
OUT = ROOT/'Docs/mac/checkpoints/vnc-r'


def main():
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    ids, ptr, post, weight = [np.load(GRAPH/name, mmap_mode='r') for name in
                            ('body_ids.npy','indptr.npy','targets.npy','weights.npy')]
    annotation = pd.read_feather(ROOT.parent/'Data/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather').set_index('bodyId').loc[ids]
    selected = annotation.superclass.str.startswith('vnc_', na=False).to_numpy()
    ix = np.flatnonzero(selected)
    mapping = json.loads((ROOT/'Brain/MaleCNS/config/game_mapping_exploratory_v1.json').read_text())
    source_ids = np.array(mapping['groups']['R'], dtype=np.int64)
    sources = np.searchsorted(ids, source_ids)
    dn = int(np.searchsorted(ids,10360))
    assert ids[dn] == 10360 and dn not in sources and np.array_equal(ids[sources], source_ids)
    trials = []
    all_counts = []
    for seed in (20260921,20260922,20260923):
        sim = MaleCNSShiuCompatibleLIF(len(ids),ptr,post,weight,sources)
        rng = np.random.default_rng(seed)
        frames = []
        counts = []
        for phase in ('baseline','stimulation','recovery1','recovery2'):
            events = {sim.tick+k:list(sources[rng.random(len(sources))<.01]) for k in range(1000)} if phase == 'stimulation' else {}
            t = time.perf_counter()
            count,_,_ = sim.step(1000,events)
            counts.append(count)
            frames.append({'phase':phase,'wallMs':(time.perf_counter()-t)*1000,
                           'allSpikes':int(count.sum()),'vncSpikes':int(count[ix].sum()),'DNa02_R_Hz':int(count[dn])*10})
        all_counts.append(counts)
        trials.append({'seed':seed,'frames':frames})
    rates = np.array(all_counts)*10.
    delta = rates[:,1]-rates[:,0]
    # Effective directed reachability is structural evidence, not causal mediation.
    graph = csr_matrix((np.ones(len(post),dtype=np.int8),post,ptr),shape=(len(ids),len(ids)))
    order, predecessors = breadth_first_order(graph,dn,directed=True,return_predecessors=True)
    distance = np.full(len(ids),-1,dtype=np.int32); distance[dn] = 0
    for v in order[1:]:
        distance[v] = distance[predecessors[v]]+1
    columns = ['type','instance','superclass','subclass','class','somaSide','rootSide','somaNeuromere','entryNerve','exitNerve','mancType']
    annotations = json.loads(annotation[columns].reset_index().to_json(orient='records'))
    def candidate(i):
        lo,hi = ptr[dn:dn+2]
        direct = weight[lo:hi][post[lo:hi] == i]
        return {'bodyId':int(ids[i]),'annotation':annotations[i],
                'motorClassification':'annotated motor' if annotation.iloc[i].superclass == 'vnc_motor' else 'not established',
                'premotorClassification':None,'legAssociation':None,
                'baselineHz':rates[:,0,i].tolist(),'stimulationHz':rates[:,1,i].tolist(),
                'deltaHz':delta[:,i].tolist(),'deltaMeanHz':float(delta[:,i].mean()),
                'deltaStdHz':float(delta[:,i].std(ddof=1)),
                'recoveryHz':rates[:,2:,i].tolist(),
                'recoveryMeanHz':float(rates[:,2:,i].mean()),
                'baselineMeanHz':float(rates[:,0,i].mean()),
                'stimulationMeanHz':float(rates[:,1,i].mean()),
                'effectiveHopCount':int(distance[i]) if distance[i]>=0 else None,
                'directEffectiveWeightMv':float(direct.sum()) if len(direct) else None}
    activated = sorted([i for i in ix if delta[:,i].mean()>0],key=lambda i:-delta[:,i].mean())
    suppressed = sorted([i for i in ix if delta[:,i].mean()<0],key=lambda i:delta[:,i].mean())
    stable = [i for i in activated if np.all(delta[:,i]>0)]
    paths = []
    for i in stable[:50]:
        if distance[i]<0:
            continue
        nodes = [int(i)]
        while nodes[-1] != dn:
            nodes.append(int(predecessors[nodes[-1]]))
        nodes.reverse()
        edges = []
        for u,v in zip(nodes,nodes[1:]):
            lo,hi = ptr[u:u+2]; w = float(weight[lo:hi][post[lo:hi]==v].sum())
            edges.append({'pre':int(ids[u]),'post':int(ids[v]),'effectiveWeightMv':w,
                          'sign':int(np.sign(w)),'nt':'ACh' if w>0 else 'GABA',
                          'synapseCount':int(round(abs(w)/.0275))})
        paths.append({'target':int(ids[i]),'hops':len(edges),'nodes':[annotations[n] for n in nodes],
                      'edges':edges,'caveat':'Shortest effective directed path; activity mediation not proven; intermediates need not be VNC.'})
    laterality = {}
    for side in ('R','L'):
        si = np.flatnonzero(selected & annotation.somaSide.eq(side).to_numpy())
        laterality[side] = {'neurons':len(si),'summedRateBySeedPhase':rates[:,:,si].sum(axis=2).tolist(),
                            'meanPerNeuronRateBySeedPhase':rates[:,:,si].mean(axis=2).tolist()}
    result = {'ready':False,'modelUnchanged':True,'seeds':[20260921,20260922,20260923],
              'populationDefinition':'Retained neuron-only IDs with annotation superclass startswith vnc_; excludes projecting non-vnc classes; not every neuron with VNC arbor.',
              'annotationSource':'body-annotations-male-cns-v1.0-minconf-0.5.feather',
              'vncCount':len(ix),'stimulusIds':source_ids.tolist(),'stimulusHz':100,'dtMs':.1,
              'phaseMs':[100,100,100,100],'trials':trials,
              'activatedCount':len(activated),'suppressedCount':len(suppressed),'stableActivatedCount':len(stable),
              'structuralDiagnostics':{'effectiveReachableVnc':int(np.sum(distance[ix]>=0)),
                  'directEffectiveVnc':int(np.sum(distance[ix]==1)),
                  'reachableAnnotatedMotor':int(np.sum((distance>=0) & annotation.superclass.eq('vnc_motor').to_numpy())),
                  'DNa02EffectiveOutEdges':int(ptr[dn+1]-ptr[dn]),
                  'note':'Reachability does not imply firing or DNa02-mediated causal response.'},
              'top50Activated':[candidate(i) for i in activated[:50]],
              'top50Suppressed':[candidate(i) for i in suppressed[:50]],
              'annotatedMotorCandidates':[candidate(i) for i in stable if annotation.iloc[i].superclass=='vnc_motor'],
              'paths':paths,'laterality':laterality,
              'suppressionCaveat':'Zero baseline cannot demonstrate suppression. Empty rankings are not padded.',
              'leftExperiment':'Not run; requires promising R motor-related candidate and review of evidence.',
              'runtimeSeconds':time.perf_counter()-started,'rssBytes':psutil.Process().memory_info().rss,
              'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'sourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('shiu_compatible.py')]},
              'graphProvenance':json.loads((GRAPH/'provenance.json').read_text()),
              'datasetManifest':json.loads((GRAPH/'graph_audit.json').read_text())['datasetManifest']}
    (OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'all_vnc_activity.json').write_text(json.dumps([candidate(i) for i in ix],separators=(',',':'))+'\n')
    print(json.dumps({k:result[k] for k in ('vncCount','activatedCount','suppressedCount','stableActivatedCount','trials','runtimeSeconds','peakRssBytes')}))


if __name__ == '__main__':
    main()
