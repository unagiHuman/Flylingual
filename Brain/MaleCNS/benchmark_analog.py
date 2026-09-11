"""Observed local step cost; does not certify action semantics at other windows."""
import json
import resource
import numpy as np
from analog_controller import MaleCNSAnalogController,ROOT


def main():
    records=[]
    for window in (25,50,100):
        c=MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_backend_v1.json',20261201,window).initialize()
        frames=[]
        for a in ['STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L']*2:
            c.set_action(a); frames.append(c.step())
        times=[f['performance']['stepWallTimeMs'] for f in frames[1:]]
        records.append({'windowMs':window,'initializationMs':c.initialization_ms,'firstStepMs':frames[0]['performance']['stepWallTimeMs'],
            'warmSamples':len(times),'meanMs':float(np.mean(times)),'medianMs':float(np.median(times)),
            'p95Ms':float(np.percentile(times,95)),'minMs':min(times),'maxMs':max(times),'frames':frames})
    output=ROOT/'Docs/mac/checkpoints/six-action/window_benchmark.json'
    output.write_text(json.dumps({'records':records,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         'limitation':'Cost only; 25/50ms action semantics not independently calibrated or accepted.'},indent=2)+'\n')
    print([(r['windowMs'],r['meanMs'],r['p95Ms']) for r in records])


if __name__=='__main__': main()
