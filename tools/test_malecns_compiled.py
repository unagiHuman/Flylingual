"""Tick-level numerical tests of real LIF dynamics against commit add0364.

Small synthetic CSR inputs exercise the production simulator directly. These
are numerical unit tests, not Unity replay/mock or physical integration tests.
"""
import hashlib
import importlib
import json
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from validate_malecns_compiled import assert_exact, compare_simulations, load_implementations


class CompiledLIFTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference, cls.candidate, _, _, _ = load_implementations()

    def pair(self, n=5, ptr=None, post=(), weights=(), stimulated=()):
        ptr = np.zeros(n + 1, dtype=np.int64) if ptr is None else np.array(ptr, dtype=np.int64)
        post = np.array(post, dtype=np.int64)
        weights = np.array(weights, dtype=np.float64)
        a, b = (cls(n, ptr.copy(), post.copy(), weights.copy(), stimulated) for cls in (self.reference, self.candidate))
        compare_simulations(a, b)
        for name in ("indptr", "post", "weights"):
            assert_exact(getattr(a, name), getattr(b, name), name)
        return a, b

    def same_step(self, a, b, ticks=1, events=None, record=True, buffers=None):
        ra = a.step(ticks, events, record, None if buffers is None else buffers[0])
        rb = b.step(ticks, events, record, None if buffers is None else buffers[1])
        assert_exact(ra, rb, "step return")
        compare_simulations(a, b)
        if buffers is not None:
            self.assertIs(ra[0], buffers[0])
            self.assertIs(rb[0], buffers[1])
        return ra, rb

    def test_bit_comparison_rejects_signed_zero_and_nonfinite(self):
        for left, right in ((np.array([0.]), np.array([-0.])), (0., -0.),
                            (np.array([np.nan]), np.array([np.nan])), (float("inf"), float("inf"))):
            with self.assertRaises(AssertionError):
                assert_exact(left, right)

    def test_initialization_dt_and_zero_ticks(self):
        a, b = self.pair(stimulated=(0, 3))
        assert_exact(a.rfc, np.array([0, 22, 22, 0, 22], dtype=np.int64))
        buffers = (np.arange(5, dtype=np.int64), np.arange(5, dtype=np.int64))
        result, _ = self.same_step(a, b, ticks=0, buffers=buffers)
        self.assertEqual(result[1:], ([], []))
        for cls in (self.reference, self.candidate):
            with self.assertRaises(ValueError):
                cls(1, np.zeros(2, dtype=np.int64), np.empty(0, dtype=np.int64), np.empty(0), dt=.2)

    def test_strict_threshold_and_refractory_boundary(self):
        a, b = self.pair(n=4, stimulated=(3,))
        coefficient = (np.exp(-.1 / 20) - np.exp(-.1 / 5)) / 3
        for sim in (a, b):
            sim.tick = 22
            sim.last[:] = (0, 0, 1, 22)
            sim.g[:] = (7 / coefficient, 7 / coefficient * (1 + 1e-12), 8000, 8000)
        result, _ = self.same_step(a, b)
        self.assertEqual(result[1], [(1, 22), (3, 22)])
        self.assertEqual(a.v[0], -45.)  # equality itself does not fire
        self.assertEqual(a.g[2], 8000.)  # tick-last == 21 is still refractory
        self.assertEqual(a.last[1], 22)  # tick-last == 22 is active

    def test_delay_eighteen_ticks_and_ring_wrap(self):
        a, b = self.pair(n=3, ptr=(0, 1, 1, 1), post=(1,), weights=(10.,), stimulated=(0,))
        for sim in (a, b):
            sim.v[0] = 10.
        for tick in range(60):
            result, _ = self.same_step(a, b, events={19: [0], 38: [0]})
            if tick == 0:
                self.assertEqual(result[1], [(0, 0)])
                self.assertEqual(a.pending[18], [0])
            if tick < 18:
                self.assertEqual(a.g[1], 0.)
            if tick == 18:
                self.assertEqual(a.g[1], 10.)
                self.assertEqual(a.pending[18], [])
            if tick in (20, 39):
                self.assertIn((0, tick), result[1])
        self.assertEqual(a.tick, 60)

    def test_duplicate_targets_cancellation_and_pending_order(self):
        a, b = self.pair(n=4, ptr=(0, 2, 2, 4, 4), post=(1, 1, 1, 1),
                         weights=(1e16, 1., -1e16, 3.))
        for sim in (a, b):
            sim.pending[0] = [0, 2]
            sim.pending[4] = [2, 0, 2]  # future order and repeats must remain unchanged
        self.same_step(a, b)
        self.assertEqual(a.g[1], 3.)
        self.assertEqual(a.pending[4], [2, 0, 2])
        for _ in range(25):
            self.same_step(a, b)

    def test_active_frozen_before_last_update_and_inactive_g_frozen(self):
        a, b = self.pair(n=4, ptr=(0, 0, 0, 0, 3), post=(0, 1, 2), weights=(5., 6., 7.))
        for sim in (a, b):
            sim.tick = 22
            sim.v[:] = (10., -52., -52., -52.)
            sim.last[:] = (0, 1, 0, 0)
            sim.g[:] = (0., -0., 0., 0.)
            sim.pending[22 % 19] = [3]
        self.same_step(a, b)
        assert_exact(b._active, np.array([True, False, True, True]))
        self.assertEqual(a.last[0], 22)
        self.assertEqual(a.g[0], 0.)  # reset follows incoming delivery
        assert_exact(a.g[1], -0.)  # neither decay nor incoming delivery while inactive
        self.assertEqual(a.g[2], 7.)

    def test_external_duplicate_events_reset_and_count_identity(self):
        a, b = self.pair(n=3, stimulated=(0, 1))
        buffers = (np.array([4, 5, 6], dtype=np.int64), np.array([4, 5, 6], dtype=np.int64))
        events = {0: [1, 0, 1, 0, 1], 1: [0, 1, 0], 2: [1, 1]}
        result, _ = self.same_step(a, b, events=events, buffers=buffers)
        self.assertEqual(result[1], [])  # events arrive after threshold
        assert_exact(a.v, np.array([85.5, 154.25, -52.]))
        result, _ = self.same_step(a, b, events=events, buffers=buffers)
        self.assertEqual(result[1], [(0, 1), (1, 1)])
        assert_exact(result[0], np.array([5, 6, 6], dtype=np.int64))
        assert_exact(a.v, np.full(3, -52.))  # fired reset wins over same-tick events
        self.same_step(a, b, events=events, buffers=buffers)
        self.same_step(a, b, events=events, buffers=buffers)
        assert_exact(buffers[0], np.array([5, 7, 6], dtype=np.int64))

    def test_record_modes_snapshots_and_multitick_equivalence(self):
        events = {tick: [0, 0, 1] for tick in range(0, 85, 3)}
        for record in (False, True):
            a, b = self.pair(n=3, ptr=(0, 2, 3, 3), post=(2, 2, 2), weights=(8., -3., 4.), stimulated=(0, 1))
            one_a, one_b = self.pair(n=3, ptr=(0, 2, 3, 3), post=(2, 2, 2), weights=(8., -3., 4.), stimulated=(0, 1))
            batch, _ = self.same_step(a, b, ticks=85, events=events, record=record)
            buffers = (np.zeros(3, dtype=np.int64), np.zeros(3, dtype=np.int64))
            spikes, states = [], []
            for _ in range(85):
                result, _ = self.same_step(one_a, one_b, events=events, record=record, buffers=buffers)
                spikes.extend(result[1])
                states.extend(result[2])
            assert_exact(batch, (buffers[0], spikes, states))
            compare_simulations(a, one_a)
            compare_simulations(b, one_b)
            if record:
                self.assertFalse(np.shares_memory(batch[2][0][0], a.v))
                self.assertFalse(np.shares_memory(batch[2][0][0], batch[2][1][0]))
            else:
                self.assertEqual(batch[1:], ([], []))

    def test_seeded_4096_neurons_every_tick(self):
        n = 4096
        for seed in (20270101, 20270102, 20270103):
            rng = np.random.default_rng(seed)
            ptr = np.arange(0, (n + 1) * 4, 4, dtype=np.int64)
            post = rng.integers(0, n, size=n * 4, dtype=np.int64)
            weights = rng.uniform(-25., 25., size=n * 4)
            v, g = rng.uniform(-90., -44., size=n), rng.uniform(-100., 100., size=n)
            last = rng.integers(-50, 1, size=n, dtype=np.int64)
            v[:6] = [-45., np.nextafter(-45., -np.inf), np.nextafter(-45., np.inf), -52., -0., 0.]
            g[:6] = [0., -0., np.nextafter(0., 1.), np.nextafter(0., -1.), -0., 0.]
            for record in (False, True):
                a, b = self.pair(n, ptr, post, weights, stimulated=tuple(range(0, n, 11)))
                for sim in (a, b):
                    sim.v[:], sim.g[:], sim.last[:] = v, g, last
                    sim.pending[0] = [9, 1, 9, 300]
                event_rng = np.random.default_rng(seed + 100)
                buffers = (np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64))
                for tick in range(77):
                    events = {tick: event_rng.integers(0, n, 100).tolist() + [3, 3, 2, 3]}
                    with self.subTest(seed=seed, record=record, tick=tick):
                        self.same_step(a, b, events=events, record=record, buffers=buffers)

    def test_current_controller_optional_visualization(self):
        # Both arms use the current optional atlas code; only LIF differs.
        controller_module = importlib.import_module("analog_controller")
        selection_module = importlib.import_module("neural_visualization")
        with tempfile.TemporaryDirectory(prefix="malecns-compiled-test-") as temporary:
            graph = Path(temporary)
            ids = np.arange(100, 108, dtype=np.int64)
            for name, value in (("body_ids", ids), ("indptr", np.array([0, 2, 4, 6, 6, 6, 6, 6, 6], dtype=np.int64)),
                                ("targets", np.array([3, 4, 5, 6, 6, 7], dtype=np.int64)),
                                ("weights", np.full(6, 12., dtype=np.float64))):
                np.save(graph / name, value)
            atlas = {"schemaVersion": 1, "datasetId": "male-cns:v1.0", "coordinateSpace": "test",
                     "sourceSha256": "0" * 64, "graphIdsSha256": hashlib.sha256((graph / "body_ids.npy").read_bytes()).hexdigest(),
                     "totalGraphNeurons": 8, "omittedCoordinateCount": 0,
                     "neurons": [{"id": str(i), "x": 0., "y": 0., "z": 0.} for i in (107, 100, 104)]}
            atlas["atlasId"] = selection_module._canonical_atlas_id(atlas)
            atlas_path = graph / "atlas.json"
            atlas_path.write_text(json.dumps(atlas), encoding="utf-8")
            config = {"stimulusRateHz": 100, "inputs": {"F": [100], "R": [101], "L": [102]},
                      "readouts": {"DNp09_L_Hz": 103, "DNp09_R_Hz": 104, "DNa02_R_Hz": 105, "DNa02_L_Hz": 106},
                      "populations": {axis: {side: {"test": [identifier]} for side, identifier in (("R", 103), ("L", 104))}
                                      for axis in ("forward", "turn")}}
            controllers = []
            for lif in (self.reference, self.candidate):
                namespace = dict(controller_module.__dict__)
                namespace["MaleCNSShiuCompatibleLIF"] = lif
                initializer = types.FunctionType(controller_module.MaleCNSAnalogController.initialize.__code__, namespace)
                controller_type = type("IsolatedController", (controller_module.MaleCNSAnalogController,), {"initialize": initializer})
                controllers.append(controller_type(graph, config, 20270101, 2., visualization_atlas=atlas_path).initialize())
            try:
                for action in ("STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L", "STOP"):
                    frames = []
                    for controller in controllers:
                        controller.set_action(action)
                        frame = controller.step()
                        frame.pop("performance")
                        frames.append(frame)
                    assert_exact(frames[0], frames[1], "visualization frame")
                    self.assertEqual(frames[0]["visualization"]["bodyIds"], ["107", "100", "104"])
                    compare_simulations(controllers[0].sim, controllers[1].sim)
            finally:
                # Windows cannot unlink live mmap files at TemporaryDirectory exit.
                for controller in controllers:
                    for mapping in (controller.ids, controller.sim.indptr, controller.sim.post, controller.sim.weights):
                        mapping._mmap.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
