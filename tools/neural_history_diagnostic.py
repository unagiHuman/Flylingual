"""Bounded Phase B preparation/runner. Never invoked by the game.

Prepare a manifest first; execute only after Phase A is accepted. Uses real LIF
with fixed cell/tick inputs, not replayed motor. No server or Unity connection.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (1701, 1702, 1703)
HOLDOUT = (2701, 2702, 2703)
CONDITIONS = ('A+', 'A0', 'B+', 'B0')
SOURCE_FILES = ('analog_controller.py', 'shiu_compatible.py', 'lif_kernels.py',
                'analog_motor_decoder.py', 'temporal_motor_decoder.py')
METHOD = {'conditions': list(CONDITIONS), 'dtMs': .1, 'baselineMs': 100,
          'historyMs': 500, 'testMs': 300, 'windowMs': 50, 'stimulusRateHz': 100,
          'seeds': list(SEEDS), 'holdoutSeeds': list(HOLDOUT),
          'stimulusMethod': 'independent_numpy_default_rng_bernoulli_p0.01',
          'forwardSeedOffset': 100000}


def validate_criteria(value):
    """Pre-register one axis/direction; all 3 metrics must exceed thresholds.

    schemaVersion=1, axis=forward|turn, direction=+1|-1,
    meanMv/integralMvMs/peakMv and motorMean/motorIntegralMs/motorPeak >0,
    calibrationEvidence nonempty. No automatic threshold or direction search.
    """
    if value is None:
        return None
    keys = {'schemaVersion', 'axis', 'direction', 'meanMv', 'integralMvMs', 'peakMv',
            'motorMean', 'motorIntegralMs', 'motorPeak', 'calibrationEvidence'}
    if (type(value) is not dict or set(value) != keys or type(value['schemaVersion']) is not int
            or value['schemaVersion'] != 1 or value['axis'] not in ('forward', 'turn')
            or type(value['direction']) is not int or value['direction'] not in (-1, 1)
            or type(value['calibrationEvidence']) is not str or not 1 <= len(value['calibrationEvidence']) <= 512):
        raise ValueError('invalid preregistered criteria')
    for key in ('meanMv', 'integralMvMs', 'peakMv', 'motorMean', 'motorIntegralMs', 'motorPeak'):
        if type(value[key]) not in (float, int) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ValueError('criteria thresholds must be positive finite calibrated numbers')
    return value


def registration_hash(manifest):
    fields = {k: manifest[k] for k in (*METHOD, 'criteria', 'configHash', 'sourceHashes', 'graphHashes')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fixed_events(cells, ticks, seed):
    """Same per-cell Bernoulli p=.01 at dt=.1ms as the 100Hz controller."""
    cells = np.unique(np.asarray(cells, dtype=np.int64))
    rng = np.random.default_rng(seed)
    offsets = np.zeros(ticks + 1, dtype=np.int64)
    batches = []
    for tick in range(ticks):
        batch = cells[rng.random(len(cells)) < .01]
        batches.append(batch)
        offsets[tick + 1] = offsets[tick] + len(batch)
    indices = np.concatenate(batches) if batches else np.empty(0, dtype=np.int64)
    return offsets, indices


def event_hash(events):
    digest = hashlib.sha256()
    for array in events:
        digest.update(np.asarray(array, dtype='<i8').tobytes())
    return digest.hexdigest()


def event_window(events, start, ticks=500):
    offsets, indices = events
    lo, hi = int(offsets[start]), int(offsets[start + ticks])
    return offsets[start:start + ticks + 1] - lo, indices[lo:hi]


def prepare(graph, config, output, commit, criteria=None, phase_a_evidence=None):
    validate_criteria(criteria)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'schemaVersion': 1, 'commitLabel': commit, 'phaseARequired': True,
                'seeds': list(SEEDS), 'holdoutSeeds': list(HOLDOUT),
                'conditions': list(CONDITIONS), 'dtMs': .1, 'baselineMs': 100,
                'historyMs': 500, 'testMs': 300, 'windowMs': 50,
                'stimulusRateHz': 100, 'graph': str(Path(graph).resolve()),
                'config': str(Path(config).resolve()), 'configHash': file_hash(config),
                'sourceHashes': {name: file_hash(ROOT / 'Brain/MaleCNS' / name) for name in SOURCE_FILES},
                'graphHashes': {name: file_hash(Path(graph) / name) for name in
                                ('body_ids.npy', 'indptr.npy', 'targets.npy', 'weights.npy')},
                'criteria': criteria, 'classification': 'INCONCLUSIVE',
                'criteriaNote': 'No calibrated meaningful-effect threshold; do not infer biological significance.'}
    manifest.update(METHOD)
    manifest['sourceHashes']['runner'] = file_hash(__file__)
    manifest['phaseAAcceptanceReference'] = ({'path': str(Path(phase_a_evidence).resolve()),
                                            'sha256': file_hash(phase_a_evidence)} if phase_a_evidence else None)
    manifest['registrationHash'] = registration_hash(manifest)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def summaries(curve):
    data = np.asarray(curve, dtype=float)
    return {'signedMeanMv': data.mean(axis=0).tolist(),
            'integralMvMs': (data.sum(axis=0) * 50).tolist(),
            'positivePeakMv': data.max(axis=0).tolist(), 'negativePeakMv': data.min(axis=0).tolist(),
            'onsetWindow': None, 'onsetNote': 'Uncalibrated detection threshold'}


def differences(curves):
    a, a0, b, b0 = [np.asarray(curves[k], dtype=float) for k in CONDITIONS]
    ia, ib = a - a0, b - b0
    result = {'D_total': b - a, 'I_A': ia, 'I_B': ib, 'D_increment': ib - ia}
    return {key: {'curveMv': value.tolist(), **summaries(value)} for key, value in result.items()}


def controlled(batch):
    t = {trial['condition']: trial for trial in batch}
    return (set(t) == set(CONDITIONS)
            and t['A+']['testEventHash'] == t['B+']['testEventHash']
            and t['A+']['historyEventHash'] == t['A0']['historyEventHash']
            and t['B+']['historyEventHash'] == t['B0']['historyEventHash']
            and t['A0']['testEventHash'] == t['B0']['testEventHash'])


def extract_curves(batch, decoder=None):
    return {t['condition']: [r['raw'] if decoder is None else
                            [r[decoder]['forward'], r[decoder]['turn']]
                            for r in t['rows'] if r['phase'] == 'test'] for t in batch}


def curve_metrics(curve, criteria):
    data = np.asarray(curve, dtype=float)
    if data.shape != (6, 2) or not np.isfinite(data).all():
        raise ValueError('invalid selected curve')
    values = data[:, 0 if criteria['axis'] == 'forward' else 1] * criteria['direction']
    return (float(values.mean()), float(values.sum() * 50), float(values.max()))


def meaningful(curve, criteria, noise, motor=False):
    keys = ('motorMean', 'motorIntegralMs', 'motorPeak') if motor else ('meanMv', 'integralMvMs', 'peakMv')
    limits = (noise, noise * 300, noise)
    return all(value > max(criteria[key], floor) for value, key, floor in
               zip(curve_metrics(curve, criteria), keys, limits))


def classify_batches(batches, criteria, raw_noise=0., motor_noise=0.):
    if not all(controlled(b) for b in batches):
        return 'STIMULUS_NOT_CONTROLLED'
    if criteria is None:
        return 'INCONCLUSIVE'
    validate_criteria(criteria)
    comparisons = [differences(extract_curves(b)) for b in batches]
    for key, classification in [('D_increment', 'SUPPORTED_INCREMENTAL_HISTORY_EFFECT'),
                                ('D_total', 'SUPPORTED_RESIDUAL_HISTORY_EFFECT')]:
        if all(meaningful(c[key]['curveMv'], criteria, raw_noise) for c in comparisons):
            return classification
    # Decoder-only requires small raw differences on BOTH axes at EVERY time,
    # small common-initial decoder difference, and consistent carry difference.
    raw_quiet = all(np.max(np.abs(c[key]['curveMv'])) <= max(raw_noise, min(criteria['meanMv'], criteria['peakMv']))
                    for c in comparisons for key in ('D_total', 'D_increment'))
    carry = [differences(extract_curves(b, 'decoderCarry')) for b in batches]
    common = [differences(extract_curves(b, 'decoderCommonInitial')) for b in batches]
    if (raw_quiet and all(np.max(np.abs(c['D_total']['curveMv'])) <= max(motor_noise, min(criteria['motorMean'], criteria['motorPeak'])) for c in common)
            and all(meaningful(c['D_total']['curveMv'], criteria, motor_noise, True) for c in carry)):
        return 'DECODER_ONLY_DIFFERENCE'
    return 'NO_MEANINGFUL_EFFECT'


def run_trial(graph, config, seed, condition, observe=None):
    # Imports are delayed so preparation/tests cannot initialize a production network.
    sys.path.insert(0, str(ROOT / 'Brain/MaleCNS'))
    from analog_controller import MaleCNSAnalogController
    from temporal_motor_decoder import TemporalMotorDecoder
    import psutil
    started = time.perf_counter()
    controller = MaleCNSAnalogController(graph, config, seed=seed, window_ms=50).initialize()
    history = fixed_events(controller.inputs['R'] if condition.startswith('B') else [], 5000, seed)
    test = fixed_events(controller.inputs['F'] if condition.endswith('+') else [], 3000, seed + 100000)
    common_decoder = TemporalMotorDecoder(controller.config['temporalDecoder'])
    rows = []
    rss = psutil.Process().memory_info().rss
    # No neural snapshots/resets: each condition reconstructs identical initial
    # state then carries v/g/last/rfc/pending/tick through the full history.
    for phase, events, windows in [('history', history, 10), ('test', test, 6)]:
        for index in range(windows):
            offsets, indices = event_window(events, index * 500)
            counts, sums = controller.sim.step_window(500, offsets, indices, controller.observed)
            delta = sums[0] / 500 - controller.baseline
            pop = {axis: {side: float(np.mean([delta[ix].mean() for ix in group.values()]))
                          for side, group in sides.items()} for axis, sides in controller.groups.items()}
            raw = [(pop['forward']['R'] + pop['forward']['L']) / 2,
                   pop['turn']['R'] - pop['turn']['L']]
            carry = controller.decoder.decode(raw, 50)
            row = {'phase': phase, 'endMs': (index + 1) * 50, 'raw': raw,
                   'populationDeltaMv': pop, 'decoderCarry': carry,
                   'selectedDnHz': {k: float(counts[i] * 20) for k, i in controller.dns.items()}}
            if phase == 'test':
                row['decoderCommonInitial'] = common_decoder.decode(raw, 50)
            if observe is not None:
                # Observer receives only a detached tiny JSON record, not state/RNG.
                observe(json.loads(json.dumps(row)))
            rows.append(row)
            rss = max(rss, psutil.Process().memory_info().rss)
    return {'seed': seed, 'condition': condition, 'historyEventHash': event_hash(history),
            'testEventHash': event_hash(test), 'historyEventCount': len(history[1]),
            'testEventCount': len(test[1]), 'rows': rows, 'wallSeconds': time.perf_counter() - started,
            'peakSampledRssBytes': rss, 'rssMethod': 'psutil sampled after every50ms window; mmap not pre-touched',
            'neurons': len(controller.ids), 'edges': len(controller.sim.post), 'finalTick': controller.sim.tick}


def execute(manifest_path, phase_a_accepted=False):
    if not phase_a_accepted:
        raise ValueError('Phase A acceptance is required; preparation does not authorize execution')
    manifest_path = Path(manifest_path)
    m = json.loads(manifest_path.read_text(encoding='utf-8'))
    result_path = manifest_path.parent / 'results.json'
    if result_path.exists(): raise ValueError('Do not overwrite an existing trial set')
    def save(result):
        result_path.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        return result
    try:
        validate_criteria(m.get('criteria'))
        if any(m.get(k) != v for k, v in METHOD.items()) or registration_hash(m) != m['registrationHash']:
            raise ValueError('preregistration changed')
        if set(m['sourceHashes']) != set(SOURCE_FILES) | {'runner'}: raise ValueError('source set changed')
        if set(m['graphHashes']) != {'body_ids.npy', 'indptr.npy', 'targets.npy', 'weights.npy'}: raise ValueError('graph set changed')
        for name, expected in m['sourceHashes'].items():
            if file_hash(__file__ if name == 'runner' else ROOT / 'Brain/MaleCNS' / name) != expected:
                raise ValueError('source hash changed')
        if file_hash(m['config']) != m['configHash']: raise ValueError('config hash changed')
        for name, expected in m['graphHashes'].items():
            if file_hash(Path(m['graph']) / name) != expected: raise ValueError('graph hash changed')
    except (ValueError, KeyError, TypeError, OSError) as error:
        return save({'classification': 'STIMULUS_NOT_CONTROLLED', 'reason': str(error), 'mainTrialCount': 0})
    batches, comparisons = [], []
    def run_batch(seed):
        batch = [run_trial(m['graph'], m['config'], seed, condition) for condition in CONDITIONS]
        batches.append(batch)
        comparisons.append({'seed': seed, **differences(extract_curves(batch))})
        return controlled(batch)
    for seed in SEEDS:
        if not run_batch(seed):
            return save({'classification': 'STIMULUS_NOT_CONTROLLED', 'reason': 'input event hash mismatch',
                         'trials': [t for b in batches for t in b], 'mainTrialCount': 4 * len(batches)})
    repeat = run_trial(m['graph'], m['config'], SEEDS[0], 'A+')
    original = batches[0][0]
    reproducible = repeat['rows'] == original['rows']
    if any(repeat[k] != original[k] for k in ('historyEventHash', 'testEventHash')):
        return save({'classification': 'STIMULUS_NOT_CONTROLLED', 'reason': 'repeat event hash mismatch', 'mainTrialCount': 12})
    raw_noise = float(np.max(np.abs(np.asarray([r['raw'] for r in repeat['rows']]) -
                                   np.asarray([r['raw'] for r in original['rows']]))))
    motor_noise = max(abs(r['decoderCarry'][axis] - s['decoderCarry'][axis])
                      for r, s in zip(repeat['rows'], original['rows']) for axis in ('forward', 'turn'))
    first = classify_batches(batches, m['criteria'], raw_noise, motor_noise)
    final, holdout = first, 'NOT_RUN'
    supported = ('SUPPORTED_INCREMENTAL_HISTORY_EFFECT', 'SUPPORTED_RESIDUAL_HISTORY_EFFECT', 'DECODER_ONLY_DIFFERENCE')
    # Exact deterministic replay is the conservative reproducibility gate. Noise
    # floors are also recorded; an unstable numerical run cannot earn support.
    if not reproducible:
        final = 'INCONCLUSIVE'
    elif first in supported:
        for seed in HOLDOUT:
            if not run_batch(seed):
                final = 'STIMULUS_NOT_CONTROLLED'
                break
        else:
            holdout = classify_batches(batches[3:], m['criteria'], raw_noise, motor_noise)
            final = first if holdout == first else 'INCONCLUSIVE'
    result = {'classification': final, 'initialClassification': first, 'holdoutClassification': holdout,
              'reason': 'Preregistered engineering thresholds only; no biological significance claim' if m['criteria'] else
                        'Meaningful-effect threshold not calibrated; no holdout',
              'mainTrialCount': 4 * len(batches), 'reproducibilityControlCount': 1,
              'reproducibilityExact': reproducible, 'rawNoiseMaxMv': raw_noise, 'motorNoiseMax': motor_noise,
              'trials': [t for b in batches for t in b],
              'reproducibilityControl': repeat, 'comparisons': comparisons,
              'noninterference': m.get('phaseAAcceptanceReference'),
              'provenance': 'Real fixed-event LIF numerical diagnostic, not Unity/physical validation'}
    return save(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--graph', required=True); prep.add_argument('--config', required=True)
    prep.add_argument('--output', required=True); prep.add_argument('--commit-label', required=True)
    prep.add_argument('--criteria-json', help='Optional independently calibrated preregistered threshold JSON')
    prep.add_argument('--phase-a-evidence', help='Optional completed noninterference report path; hashed as reference only')
    run = sub.add_parser('run'); run.add_argument('--manifest', required=True)
    run.add_argument('--phase-a-accepted', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.graph, args.config, args.output, args.commit_label,
        json.loads(Path(args.criteria_json).read_text(encoding='utf-8')) if args.criteria_json else None, args.phase_a_evidence)
    else: execute(args.manifest, args.phase_a_accepted)
