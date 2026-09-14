"""Fixed, opt-in real MaleCNS LIF diagnostic over owned localhost TCP.

No production Brain, decoder, motor or Unity endpoint is modified.
Without --execute, only the preregistered schedule is printed.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import queue
import socket
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (1701, 1702, 1703)
CONDITIONS = ('SHAM', 'LC4', 'LPLC2', 'BOTH')
LIMIT = 300


def schedule():
    return [{'seed': seed, 'condition': condition} for seed in SEEDS for condition in CONDITIONS]


def phase(window):
    return 'baseline' if window < 10 else 'on' if window < 20 else 'off'


def stimulus(rng, candidate_indices, candidate_types, condition, active):
    """Identical random draws in every condition, including SHAM and OFF."""
    offsets = np.zeros(501, dtype=np.int64)
    batches = []
    mask = np.array([active and (condition == 'BOTH' or condition == typ) for typ in candidate_types])
    for tick in range(500):
        selected = candidate_indices[(rng.random(len(candidate_indices)) < .01) & mask]
        batches.append(selected)
        offsets[tick + 1] = offsets[tick] + len(selected)
    events = np.concatenate(batches).astype(np.int64, copy=False)
    return offsets, events


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def emit(connection, value):
    connection.sendall((json.dumps(value, allow_nan=False) + '\n').encode())


def trials(connection, started):
    import pyarrow
    import pyarrow.feather as feather
    import psutil
    import numba
    import llvmlite
    sys.path.insert(0, str(ROOT / 'Brain/MaleCNS'))
    from shiu_compatible import MaleCNSShiuCompatibleLIF
    manifest = json.loads((ROOT / 'Brain/MaleCNS/results/download_manifest.json').read_text())
    paths = {key: ROOT / 'Data/malecns/v1.0' / manifest['files'][key]['filename']
             for key in ('annotations', 'neurotransmitters')}
    for key, path in paths.items():
        if sha(path) != manifest['files'][key]['sha256']:
            raise ValueError(key + ' manifest SHA mismatch')
    rows = feather.read_table(paths['annotations'], columns=['bodyId', 'type', 'somaSide']).to_pylist()
    selected = sorted((row for row in rows if row['type'] in ('LC4', 'LPLC2')), key=lambda row: row['bodyId'])
    readouts = sorted(row['bodyId'] for row in rows if row['type'] == 'DNp01')
    if readouts != [10001, 10010] or sum(row['type'] == 'LC4' for row in selected) != 126 or len(selected) != 311:
        raise ValueError('preregistered annotation selection changed')
    graph = ROOT / 'artifacts/neuron_checkpoint'
    arrays = {name: np.load(graph / (name + '.npy'), mmap_mode='r', allow_pickle=False)
              for name in ('body_ids', 'indptr', 'targets', 'weights')}
    ids, ptr, targets, weights = [arrays[name] for name in ('body_ids', 'indptr', 'targets', 'weights')]
    if np.any(ids[1:] <= ids[:-1]) or len(ptr) != len(ids) + 1 or ptr[0] != 0 or ptr[-1] != len(weights) or len(targets) != len(weights):
        raise ValueError('invalid graph dimensions or IDs')
    if np.any(ptr[1:] < ptr[:-1]):
        raise ValueError('non-monotonic graph indptr')
    for start in range(0, len(targets), 1_000_000):
        block = targets[start:start + 1_000_000]
        if np.any(block < 0) or np.any(block >= len(ids)):
            raise ValueError('graph target outside neuron bounds')
        if not np.all(np.isfinite(weights[start:start + 1_000_000])):
            raise ValueError('non-finite graph weights')
    def indices(values):
        at = np.searchsorted(ids, values)
        if np.any(at >= len(ids)) or not np.array_equal(ids[at], values):
            raise ValueError('missing graph ID')
        return at.astype(np.int64)
    candidate_ids = np.array([row['bodyId'] for row in selected], dtype=np.int64)
    candidate_indices = indices(candidate_ids)
    candidate_types = [row['type'] for row in selected]
    dn_indices = indices(np.array(readouts, dtype=np.int64))
    config_path = ROOT / 'Brain/MaleCNS/config/analog_temporal_v1.json'
    config = json.loads(config_path.read_text())
    common_ids = np.unique(np.r_[candidate_ids, [int(v) for group in config['inputs'].values() for v in group]])
    common_indices = indices(common_ids)
    observed = np.r_[candidate_indices, dn_indices].astype(np.int64)
    source_paths = [Path(__file__), ROOT / 'Brain/MaleCNS/shiu_compatible.py', ROOT / 'Brain/MaleCNS/lif_kernels.py', config_path]
    graph_hashes = {name + '.npy': sha(graph / (name + '.npy')) for name in arrays}
    graph_sha = hashlib.sha256(json.dumps(graph_hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    emit(connection, {'type': 'manifest', 'diagnosticOnly': True, 'ready': False, 'productReady': False,
        'backend': 'MALECNS_EXPERIMENTAL', 'mode': 'LIVE', 'schedule': schedule(),
        'windowMs': 50, 'dtMs': .1, 'baselineMs': 500, 'onMs': 500, 'offMs': 1000,
        'stimulusRateHz': 100, 'tickProbability': .01, 'externalJumpMv': 68.75,
        'commonCandidateRandomDraws': True, 'candidateInputs': selected, 'readoutBodyIds': readouts,
        'refractory': {'zeroTickBodyIds': common_ids.tolist(), 'otherTicks': 22,
                       'note': 'diagnostic candidate rfc=0 differs from production; identical across all trials'},
        'annotationSha256': sha(paths['annotations']), 'ntSha256': sha(paths['neurotransmitters']),
        'graphHashes': graph_hashes, 'graphSha256': graph_sha,
        'serverKind': 'fixed_schedule_real_kernel_diagnostic_not_production_six_action_server',
        'sourceHashes': {str(path.relative_to(ROOT)): sha(path) for path in source_paths},
        'dependencies': {'python': platform.python_version(), 'numpy': np.__version__, 'pyarrow': pyarrow.__version__,
                         'numba': numba.__version__, 'llvmlite': llvmlite.__version__, 'psutil': psutil.__version__},
        'neuronCount': len(ids), 'storedEdgeCount': len(weights),
        'limitations': ['Artificial diagnostic stimulation, not natural visual calibration.',
                       'No motor output, avoidance success, emotion or reward claim.']})
    process = psutil.Process()
    sequence = 0
    for trial in schedule():
        if time.monotonic() - started >= LIMIT:
            raise TimeoutError('300-second wall budget')
        trial_start = time.monotonic()
        sim = MaleCNSShiuCompatibleLIF(len(ids), ptr, targets, weights, common_indices)
        sim.step_window(0, np.zeros(1, dtype=np.int64), np.empty(0, dtype=np.int64), observed)
        rng = np.random.default_rng(trial['seed'])
        for window in range(40):
            if time.monotonic() - started >= LIMIT:
                raise TimeoutError('300-second wall budget')
            kind = phase(window)
            offsets, events = stimulus(rng, candidate_indices, candidate_types, trial['condition'], kind == 'on')
            event_hash = hashlib.sha256(offsets.astype('<i8').tobytes() + ids[events].astype('<i8').tobytes()).hexdigest()
            before = time.monotonic()
            counts, sums = sim.step_window(500, offsets, events, observed)
            sequence += 1
            emit(connection, {'type': 'frame', **trial, 'sequence': sequence, 'trialSequence': window,
                'phase': kind, 'brainTimeMs': sim.tick * .1, 'windowMs': 50,
                'DNp01': {str(body): {'spikes': int(counts[index]), 'hz': float(counts[index] * 20),
                    'meanV': float(sums[0, 311 + n] / 500), 'meanG': float(sums[1, 311 + n] / 500)}
                    for n, (body, index) in enumerate(zip(readouts, dn_indices))},
                'inputGroupSpikes': {name: int(counts[candidate_indices[np.array(candidate_types) == name]].sum())
                                    for name in ('LC4', 'LPLC2')},
                'stimulusEvents': {'count': len(events), 'sha256': event_hash,
                    'hashEncoding': 'little-endian int64 offsets then body IDs',
                    'groupCounts': {name: int(np.count_nonzero(np.isin(events, candidate_indices[np.array(candidate_types) == name])))
                                    for name in ('LC4', 'LPLC2')}},
                'wholeGraphSpikes': int(counts.sum()), 'rssBytes': process.memory_info().rss,
                'stepWallSeconds': time.monotonic() - before, 'trialWallSeconds': time.monotonic() - trial_start,
                'wallSeconds': time.monotonic() - started, 'ready': False})
        del sim
    emit(connection, {'type': 'completed', 'frames': sequence, 'wallSeconds': time.monotonic() - started})


def serve():
    started = time.monotonic()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        print(json.dumps({'port': listener.getsockname()[1]}), flush=True)
        with listener.accept()[0] as connection:
            connection.settimeout(10)
            # The only accepted command starts the immutable schedule.
            command = b''
            while not command.endswith(b'\n') and len(command) < 64:
                chunk = connection.recv(64 - len(command))
                if not chunk:
                    break
                command += chunk
            if command != b'RUN_FIXED_VISUAL_THREAT_V1\n':
                raise ValueError('invalid fixed-trial command')
            try:
                trials(connection, started)
            except Exception as error:
                emit(connection, {'type': 'failed', 'error': type(error).__name__ + ': ' + str(error)})
                raise


def summarize(frames):
    buckets = defaultdict(list)
    for frame in frames:
        bucket = frame['phase']
        for body, values in frame['DNp01'].items():
            buckets[(frame['seed'], frame['condition'], body, bucket)].append(values)
            if frame['brainTimeMs'] > 1500:
                buckets[(frame['seed'], frame['condition'], body, 'lastOff500')].append(values)
    means = {key: {metric: float(np.mean([row[metric] for row in rows])) for metric in ('hz', 'meanV', 'meanG')}
             for key, rows in buckets.items()}
    result = []
    for (seed, condition, body, phase_name), mean in means.items():
        baseline = means.get((seed, condition, body, 'baseline'))
        sham = means.get((seed, 'SHAM', body, phase_name))
        spike_count = sum(row['spikes'] for row in buckets[(seed, condition, body, phase_name)])
        sham_rows = buckets.get((seed, 'SHAM', body, phase_name))
        baseline_rows = buckets.get((seed, condition, body, 'baseline'))
        result.append({'seed': seed, 'condition': condition, 'bodyId': int(body), 'phase': phase_name,
                       'windows': len(buckets[(seed, condition, body, phase_name)]), 'means': mean,
                       'spikeCount': spike_count,
                       'deltaSpikeCountSHAM': spike_count - sum(row['spikes'] for row in sham_rows) if sham_rows and len(sham_rows) == len(buckets[(seed, condition, body, phase_name)]) else None,
                       'deltaSpikeCountBaseline': spike_count - sum(row['spikes'] for row in baseline_rows)
                           if baseline_rows and len(baseline_rows) == len(buckets[(seed, condition, body, phase_name)]) else None,
                       'deltaBaseline': {key: mean[key] - baseline[key] for key in mean} if baseline else None,
                       'deltaSHAM': {key: mean[key] - sham[key] for key in mean} if sham else None})
    return result


def execute(output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); frames = []; completed = False; failure = None; child = None
    endpoint = None; received_manifest = None
    with (output / 'server.stderr.log').open('w', encoding='utf-8') as stderr, (output / 'events.ndjson').open('w', encoding='utf-8') as events:
        try:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve'],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=stderr, text=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            handshake = queue.Queue()
            threading.Thread(target=lambda: handshake.put(child.stdout.readline()), daemon=True).start()
            port = json.loads(handshake.get(timeout=10))['port']
            endpoint = '127.0.0.1:' + str(port)
            with socket.create_connection(('127.0.0.1', port), timeout=10) as connection:
                connection.settimeout(1); connection.sendall(b'RUN_FIXED_VISUAL_THREAT_V1\n'); buffer = b''
                while time.monotonic() - started < LIMIT:
                    try:
                        data = connection.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    buffer += data
                    if len(buffer) > 2 * 1024 * 1024:
                        raise ValueError('oversized TCP record')
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        record = json.loads(line); events.write(line.decode() + '\n'); events.flush()
                        if record['type'] == 'manifest':
                            received_manifest = record
                        elif record['type'] == 'frame':
                            if record['sequence'] != len(frames) + 1:
                                raise ValueError('TCP sequence discontinuity')
                            frames.append(record)
                        elif record['type'] == 'completed':
                            completed = record['frames'] == 480 and len(frames) == 480
                        elif record['type'] == 'failed':
                            failure = record['error']
                if not completed and failure is None:
                    failure = 'wall_budget_or_incomplete_stream'
        except Exception as error:
            failure = type(error).__name__ + ': ' + str(error)
        finally:
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=5)
            completed = completed and failure is None
            report = {'endpoint': endpoint, 'ownedChildPid': child.pid if child else None,
                'manifest': received_manifest, 'completed': completed, 'error': failure, 'framesReceived': len(frames),
                'wallSeconds': time.monotonic() - started, 'maxSampledRssBytes': max((f['rssBytes'] for f in frames), default=None),
                'phaseSummary': summarize(frames), 'ready': False, 'productReady': False,
                'interpretation': 'Observed diagnostic downstream values only; no physiological, emotional or avoidance-success claim.',
                'capturedAtUtc': datetime.now(timezone.utc).isoformat()}
            (output / 'summary.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'completed': completed, 'error': failure, 'output': str(output)}))
    return 0 if completed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/neural-feedback/visual-threat-brain-probe')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve(); return 0
    if args.execute:
        return execute(args.output.resolve())
    print(json.dumps({'schedule': schedule(), 'windowsPerTrial': 40, 'wallLimitSeconds': LIMIT,
                      'instruction': 'Use --execute only after checking ownership of Windows Brain resources.'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
