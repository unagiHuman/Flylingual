"""Bounded execution checkpoint with an external RSS watchdog; no Unity required."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not args.worker:
        limit = min(8 * 1024**3, psutil.virtual_memory().total // 2,
                    int(psutil.virtual_memory().available * 0.75))
        child = subprocess.Popen([sys.executable, __file__, '--worker', '--output', str(args.output)])
        process = psutil.Process(child.pid)
        peak = 0
        terminated = False
        started = time.monotonic()
        while child.poll() is None:
            try:
                peak = max(peak, process.memory_info().rss)
                if peak > limit or time.monotonic() - started > 300:
                    child.terminate()
                    terminated = True
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.05)
        try:
            code = child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            code = child.wait()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_suffix('.watchdog.json').write_text(json.dumps({
            'exitCode': code, 'terminated': terminated, 'rssLimitBytes': limit,
            'sampledPeakRssBytes': peak, 'sampleIntervalSeconds': 0.05
        }, indent=2) + '\n')
        raise SystemExit(code if code else int(terminated))

    from game_controller import MaleCNSGameController
    graph = root / 'artifacts/malecns_effective_csr'
    mapping = root / 'Brain/MaleCNS/config/game_mapping_exploratory_v1.json'
    trials = []
    for seed in (20260921, 20260922, 20260923):
        controller = MaleCNSGameController(graph, mapping, seed, 100, 0.1).initialize()
        frames = []
        for action in ('STOP', 'TURN_R', 'STOP'):
            controller.set_action(action)
            frames.append(controller.step())
        trials.append({'seed': seed, 'frames': frames,
                       'initializationMs': controller.brain.initialization_wall_ms})
    benchmarks = []
    for window in (25, 50, 100):
        controller = MaleCNSGameController(graph, mapping, 20260924, window, 0.1).initialize()
        first = controller.step()
        warm = []
        for action in ('STOP', 'FORWARD', 'STOP', 'TURN_R', 'STOP', 'TURN_L',
                       'STOP', 'FORWARD_R', 'STOP', 'FORWARD_L', 'STOP'):
            controller.set_action(action)
            warm.append(controller.step())
        times = np.array([f['performance']['stepWallTimeMs'] for f in warm])
        benchmarks.append({'windowMs': window, 'initializationMs': controller.brain.initialization_wall_ms,
                           'firstStep': first, 'warmFrames': warm, 'sampleCount': len(times),
                           'meanMs': float(times.mean()), 'medianMs': float(np.median(times)),
                           'p95Ms': float(np.percentile(times, 95)), 'maxMs': float(times.max()),
                           'simulatedToWallRatio': float(window / times.mean())})
    paths = [Path(__file__), root / 'Brain/MaleCNS/malecns_brain.py', mapping]
    payload = {'scope': 'Existing annotation-bodyid-v1 graph, including non-neuron annotations; not certified full-neuron CNS',
               'structuralManifest': json.loads((root / 'artifacts/malecns_structural_graph/manifest.json').read_text()),
               'effectiveManifest': json.loads((graph / 'manifest.json').read_text()),
               'datasetManifest': json.loads((root / 'Brain/MaleCNS/results/download_manifest.json').read_text()),
               'sourceHashes': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
               'trials': trials, 'benchmarks': benchmarks, 'acceptanceReady': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + '\n')


if __name__ == '__main__':
    main()
