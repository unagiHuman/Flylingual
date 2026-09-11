"""Record unchanged neural trajectories before any temporal decoding."""
import argparse
import gzip
import hashlib
import json
import resource
import sys
import time
import platform
import psutil
from analog_controller import MaleCNSAnalogController,ROOT

OUT=ROOT/'Docs/mac/checkpoints/temporal'
SEEDS={'calibration':(20261211,20261212,20261213),'validation':(20261221,20261222,20261223,20261224,20261225)}
SEEDS['validation_hysteresis']=(20261231,20261232,20261233,20261234,20261235)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=SEEDS,required=True)
    args=parser.parse_args(); OUT.mkdir(parents=True,exist_ok=True)
    for seed in SEEDS[args.phase]:
        start=time.perf_counter()
        c=MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',ROOT/'Brain/MaleCNS/config/analog_backend_v1.json',seed,50).initialize()
        frames=[]; blocks=[('STOP',6)]
        for action in ('FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L'):
            blocks.extend([(action,8),('STOP',6)])
        for block,(action,n) in enumerate(blocks):
            c.set_action(action)
            for k in range(n):
                f=c.step(); f['experiment']={'block':block,'windowInBlock':k,'blockWindowCount':n}
                frames.append(f)
            print(args.phase,seed,action,'complete',flush=True)
        files=[__file__,str(ROOT/'Brain/MaleCNS/analog_controller.py'),str(ROOT/'Brain/MaleCNS/shiu_compatible.py'),str(ROOT/'Brain/MaleCNS/config/analog_backend_v1.json')]
        payload={'seed':seed,'phase':args.phase,'windowMs':50,'frames':frames,'ready':False,
            'initializationMs':c.initialization_ms,'runtimeSeconds':time.perf_counter()-start,
            'rssBytes':psutil.Process().memory_info().rss,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'python':sys.version,'numpy':__import__('numpy').__version__,'platform':platform.platform(),
            'sourceHashes':{str(__import__('pathlib').Path(p).relative_to(ROOT)):hashlib.sha256(__import__('pathlib').Path(p).read_bytes()).hexdigest() for p in files},
            'graphProvenance':json.loads((ROOT/'artifacts/neuron_checkpoint/provenance.json').read_text())}
        with gzip.open(OUT/(args.phase+'_'+str(seed)+'.json.gz'),'wt',encoding='utf-8') as stream:
            json.dump(payload,stream,separators=(',',':'))


if __name__=='__main__': main()
