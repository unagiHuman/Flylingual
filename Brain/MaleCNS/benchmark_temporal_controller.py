"""Temporal controller window-cost benchmark; only50ms has semantic acceptance."""
import json
import resource
import numpy as np
from analog_controller import ROOT,MaleCNSAnalogController,ACTIONS


def main():
    reports=[]
    for window in (25,50,100):
        c=MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json',20270111,window).initialize()
        frames=[]
        for a in list(ACTIONS)*2:
            c.set_action(a); frames.append(c.step())
        times=[f['performance']['stepWallTimeMs'] for f in frames[1:]]
        reports.append({'windowMs':window,'initializationMs':c.initialization_ms,
          'firstStepMs':frames[0]['performance']['stepWallTimeMs'],'warmSamples':11,
          'meanMs':float(np.mean(times)),'medianMs':float(np.median(times)),
          'p95Ms':float(np.percentile(times,95)),'minMs':min(times),'maxMs':max(times),'frames':frames})
    (ROOT/'Docs/mac/checkpoints/temporal/window_benchmark.json').write_text(json.dumps({'reports':reports,
        'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'note':'Only cost at25/100ms; accepted action protocol uses50ms and400ms stimulus hold.'},indent=2)+'\n')
    print([(r['windowMs'],r['meanMs'],r['p95Ms']) for r in reports],flush=True)


if __name__=='__main__': main()
