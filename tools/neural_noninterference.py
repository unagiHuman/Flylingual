"""Opt-in real LIF OFF/ON comparison; no server, Unity, or model mutation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Brain/MaleCNS'))


def execute(graph, config, output):
    import numpy as np
    import psutil
    from analog_controller import MaleCNSAnalogController
    from Runtime.Bridge.neural_response import NeuralResponseAnalyzer
    from Runtime.Bridge.neural_feedback import compact_summary
    from tools.neural_history_diagnostic import file_hash, SOURCE_FILES
    identity = {'instanceId': 'offline-real-lif', 'sessionId': 'noninterference-1701',
                'backendId': 'MALECNS_EXPERIMENTAL', 'datasetId': 'male-cns:v1.0',
                'sourceHash': hashlib.sha256(''.join(file_hash(ROOT/'Brain/MaleCNS'/n) for n in SOURCE_FILES).encode()).hexdigest(),
                'graphHash': hashlib.sha256(''.join(file_hash(Path(graph)/n) for n in ('body_ids.npy','indptr.npy','targets.npy','weights.npy')).encode()).hexdigest(),
                'configHash': file_hash(config)}
    results = []
    for enabled in (False, True):
        started = time.perf_counter()
        controller = MaleCNSAnalogController(graph, config, seed=1701, window_ms=50).initialize()
        analyzer = NeuralResponseAnalyzer({'enabled': enabled})
        rows, costs, steps, rng, rss = [], [], [], [], []
        for request, action in enumerate(('STOP', 'FORWARD', 'STOP'), 1):
            controller.set_action(action)
            for index in range(10):
                frame = controller.step()
                frame['appliedRequestId'] = request if index == 0 else None
                original = json.dumps(frame, sort_keys=True, allow_nan=False)
                now = time.monotonic()*1000
                begin = time.perf_counter()
                event = analyzer.observe(frame, identity=identity, epoch=1, generation=1,
                    received_ms=now, age_ms=0, request={'requestId':request,'action':action})
                if event:
                    snapshot = analyzer.snapshot(now, 0, 1, 1)
                    compact_summary(snapshot)
                costs.append((time.perf_counter()-begin)*1000)
                assert json.dumps(frame, sort_keys=True, allow_nan=False) == original
                rows.append({k: frame[k] for k in ('sequence','requestedAction','brainTimeMs','raw','motor','brain')})
                rng.append(hashlib.sha256(json.dumps(controller.rng.bit_generator.state, sort_keys=True).encode()).hexdigest())
                steps.append(frame['performance']['stepWallTimeMs'])
                rss.append(psutil.Process().memory_info().rss)
        results.append({'enabled':enabled,'rows':rows,'rngHashes':rng,'analysisMs':costs,'stepWallMs':steps,
                        'sampledPeakRssBytes':max(rss),'wallSeconds':time.perf_counter()-started,
                        'rawMotorHash':hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()})
        del controller
    equal = results[0]['rows'] == results[1]['rows'] and results[0]['rngHashes'] == results[1]['rngHashes']
    result = {'result':'PASS' if equal else 'FAIL','identity':identity,'seed':1701,'framesPerCondition':30,
              'stimulus':'production 100Hz cell/tick generation; independent identical seeded controllers',
              'analyzerP95Ms':float(np.percentile(results[1]['analysisMs'],95)),
              'python':sys.version,'numpy':np.__version__,'runs':results}
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('runs','identity')}))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('graph','config','output'): parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    execute(args.graph,args.config,args.output)
