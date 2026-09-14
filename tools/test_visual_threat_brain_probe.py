"""Pure schedule, stimulus and aggregation tests; no LIF or TCP execution."""
import unittest
import numpy as np
from tools.visual_threat_brain_probe import schedule, phase, stimulus, summarize


class VisualThreatProbeTests(unittest.TestCase):
    def test_fixed_schedule(self):
        self.assertEqual(len(schedule()), 12)
        self.assertEqual([phase(i) for i in range(40)].count('baseline'), 10)
        self.assertEqual([phase(i) for i in range(40)].count('on'), 10)
        self.assertEqual([phase(i) for i in range(40)].count('off'), 20)

    def test_common_random_draws_and_mask(self):
        indices = np.arange(311, dtype=np.int64)
        types = ['LC4'] * 126 + ['LPLC2'] * 185
        outputs, states = {}, []
        for condition in ('SHAM', 'LC4', 'LPLC2', 'BOTH'):
            rng = np.random.default_rng(1701)
            offsets, events = stimulus(rng, indices, types, condition, True)
            ticks = np.repeat(np.arange(500), np.diff(offsets))
            outputs[condition] = set(zip(ticks.tolist(), events.tolist()))
            states.append(rng.bit_generator.state)
        self.assertEqual(outputs['SHAM'], set())
        self.assertEqual(outputs['LC4'], {pair for pair in outputs['BOTH'] if pair[1] < 126})
        self.assertEqual(outputs['LPLC2'], {pair for pair in outputs['BOTH'] if pair[1] >= 126})
        self.assertTrue(all(state == states[0] for state in states))
        _, off = stimulus(np.random.default_rng(1701), indices, types, 'BOTH', False)
        self.assertEqual(len(off), 0)

    def test_off_tail_and_sham_counts_are_separate(self):
        frames = []
        for condition in ('SHAM', 'LC4'):
            for window in range(40):
                count = 2 if condition == 'LC4' and window >= 10 else 0
                frames.append({'seed': 1701, 'condition': condition, 'phase': phase(window),
                    'brainTimeMs': (window + 1) * 50,
                    'DNp01': {'10001': {'spikes': count, 'hz': count * 20, 'meanV': -52., 'meanG': 0.}}})
        rows = summarize(frames)
        tail = next(row for row in rows if row['condition'] == 'LC4' and row['phase'] == 'lastOff500')
        self.assertEqual(tail['windows'], 10)
        self.assertEqual(tail['spikeCount'], 20)
        self.assertEqual(tail['deltaSpikeCountSHAM'], 20)
        self.assertEqual(tail['deltaSpikeCountBaseline'], 20)


if __name__ == '__main__':
    unittest.main()
