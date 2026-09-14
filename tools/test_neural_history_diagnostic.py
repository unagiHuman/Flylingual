"""Pure event/difference tests only: no Brain construction or execution."""
import unittest
import numpy as np
from tools.neural_history_diagnostic import (fixed_events, event_hash, event_window, differences, execute,
    validate_criteria, classify_batches, controlled, registration_hash, METHOD, SOURCE_FILES)
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

CRITERIA = {'schemaVersion': 1, 'axis': 'forward', 'direction': 1, 'meanMv': .1,
            'integralMvMs': 30., 'peakMv': .1, 'motorMean': .1, 'motorIntegralMs': 30.,
            'motorPeak': .1, 'calibrationEvidence': 'unit-fixture-only-not-biological-calibration'}


def fixture_batch(seed=1701, incremental=True, residual=False, decoder_only=False):
    batch = []
    for condition in ('A+', 'A0', 'B+', 'B0'):
        value = 1. if condition.endswith('+') else 0.
        if condition.startswith('B') and (residual or incremental and condition.endswith('+')): value += 2.
        rows = []
        for i in range(6):
            common = {'forward': 0., 'turn': 0.}
            carry = {'forward': .5 if decoder_only and condition.startswith('B') else 0., 'turn': 0.}
            rows.append({'phase': 'test', 'raw': [value, 0.],
                         'decoderCarry': carry, 'decoderCommonInitial': common})
        batch.append({'condition': condition, 'seed': seed, 'rows': rows,
                      'historyEventHash': 'history-' + condition[0], 'testEventHash': 'test-' + condition[1]})
    return batch


class HistoryPreparationTests(unittest.TestCase):
    def test_event_bytes_reproducible_and_cells_preserved(self):
        a = fixed_events([2, 8], 3000, 17)
        b = fixed_events([8, 2], 3000, 17)
        self.assertEqual(event_hash(a), event_hash(b))
        self.assertTrue(set(a[1]).issubset({2, 8}))
        self.assertEqual(len(a[0]), 3001)
        windows = [event_window(a, i * 500)[1] for i in range(6)]
        np.testing.assert_array_equal(np.concatenate(windows), a[1])

    def test_no_input_has_no_events(self):
        offsets, cells = fixed_events([], 5000, 17)
        self.assertEqual(offsets.sum(), 0)
        self.assertEqual(len(cells), 0)

    def test_residual_not_conflated_with_increment(self):
        curves = {'A+': [[3., 2.]] * 6, 'A0': [[1., 0.]] * 6,
                  'B+': [[7., 4.]] * 6, 'B0': [[5., 2.]] * 6}
        result = differences(curves)
        self.assertEqual(result['D_total']['signedMeanMv'], [4., 2.])
        self.assertEqual(result['D_increment']['signedMeanMv'], [0., 0.])

    def test_phase_a_gate_before_file_or_brain_access(self):
        with self.assertRaisesRegex(ValueError, 'Phase A'):
            execute('does-not-exist.json')

    def test_thresholds_require_calibration_and_strict_types(self):
        self.assertIsNone(validate_criteria(None))
        self.assertEqual(validate_criteria(CRITERIA), CRITERIA)
        for change in ({'direction': True}, {'meanMv': float('nan')}, {'peakMv': 0},
                       {'calibrationEvidence': ''}, {'extra': 1}, {'axis': 'best'}):
            with self.assertRaises(ValueError): validate_criteria({**CRITERIA, **change})

    def test_direction_noise_and_seed_consistency(self):
        batches = [fixture_batch(seed) for seed in (1701, 1702, 1703)]
        self.assertEqual(classify_batches(batches, CRITERIA), 'SUPPORTED_INCREMENTAL_HISTORY_EFFECT')
        self.assertEqual(classify_batches(batches, None), 'INCONCLUSIVE')
        self.assertEqual(classify_batches(batches, CRITERIA, raw_noise=3), 'NO_MEANINGFUL_EFFECT')
        self.assertEqual(classify_batches(batches, {**CRITERIA, 'direction': -1}), 'NO_MEANINGFUL_EFFECT')
        batches[-1] = fixture_batch(1703, incremental=False)
        self.assertEqual(classify_batches(batches, CRITERIA), 'NO_MEANINGFUL_EFFECT')

    def test_residual_and_decoder_separate(self):
        self.assertEqual(classify_batches([fixture_batch(residual=True)] * 3, CRITERIA),
                         'SUPPORTED_RESIDUAL_HISTORY_EFFECT')
        self.assertEqual(classify_batches([fixture_batch(incremental=False, decoder_only=True)] * 3, CRITERIA),
                         'DECODER_ONLY_DIFFERENCE')
        batch = fixture_batch(); batch[2]['testEventHash'] = 'changed'
        self.assertFalse(controlled(batch))
        self.assertEqual(classify_batches([batch], CRITERIA), 'STIMULUS_NOT_CONTROLLED')

    def test_execute_main_holdout_budget_without_lif(self):
        # Only orchestration fixtures; no graph, simulator, or network is loaded.
        for criteria, expected_count in ((None, 12), (CRITERIA, 24)):
            with tempfile.TemporaryDirectory() as directory:
                m = {**METHOD, 'criteria': criteria, 'sourceHashes': {k: 'h' for k in (*SOURCE_FILES, 'runner')},
                     'configHash': 'h', 'graphHashes': {k: 'h' for k in ('body_ids.npy', 'indptr.npy', 'targets.npy', 'weights.npy')},
                     'config': 'unused', 'graph': 'unused'}
                m['registrationHash'] = registration_hash(m)
                manifest = Path(directory) / 'manifest.json'; manifest.write_text(json.dumps(m))
                def trial(graph, config, seed, condition):
                    return next(t for t in fixture_batch(seed) if t['condition'] == condition)
                with patch('tools.neural_history_diagnostic.file_hash', return_value='h'), \
                     patch('tools.neural_history_diagnostic.run_trial', side_effect=trial) as mocked:
                    result = execute(manifest, True)
                self.assertEqual(result['mainTrialCount'], expected_count)
                self.assertEqual(mocked.call_count, expected_count + 1)
                self.assertEqual(result['classification'], 'INCONCLUSIVE' if criteria is None else 'SUPPORTED_INCREMENTAL_HISTORY_EFFECT')


if __name__ == '__main__': unittest.main()
