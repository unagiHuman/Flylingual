"""Real LIF numerical tests for window batching and ordered CSR delivery."""
import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from test_malecns_compiled import CompiledLIFTest
from validate_malecns_compiled import ROOT, assert_exact, compare_simulations, load_implementations, save_report, sha256_file
from validate_malecns_window_compiled import load_snapshot, pack_events


class WindowCompiledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference, cls.candidate, _, cls.controller, _ = load_implementations()
        cls.snapshot, cls.snapshot_controller, _, _ = load_snapshot()

    def pair(self, n=5, ptr=None, post=(), weights=(), stimulated=(), baseline=None):
        ptr = np.zeros(n + 1, dtype=np.int64) if ptr is None else np.array(ptr, dtype=np.int64)
        post, weights = np.array(post, dtype=np.int64), np.array(weights, dtype=np.float64)
        return tuple(cls(n, ptr.copy(), post.copy(), weights.copy(), stimulated)
                     for cls in (baseline or self.reference, self.candidate))

    def compare_window(self, a, b, ticks, events=None, observed=None, buffers=None):
        events = {} if events is None else events
        observed = np.arange(len(a.v), dtype=np.int64) if observed is None else observed
        expected = np.zeros(len(a.v), dtype=np.int64) if buffers is None else buffers[0]
        sums = np.zeros((2, len(observed)), dtype=np.float64)
        offsets, indices = pack_events(a.tick, ticks, events)
        for _ in range(ticks):
            counts, _, _ = a.step(1, events, count_buffer=expected)
            self.assertIs(counts, expected)
            sums[0] += a.v[observed]
            sums[1] += a.g[observed]
        actual, actual_sums = b.step_window(ticks, offsets, indices, observed,
                                          count_buffer=None if buffers is None else buffers[1])
        assert_exact(expected, actual, "window counts")
        assert_exact(sums, actual_sums, "ordered observed sums")
        compare_simulations(a, b)
        if buffers is not None:
            self.assertIs(actual, buffers[1])
        return actual, actual_sums

    def test_threshold_refractory_same_tick_delivery_and_reset(self):
        a, b = self.pair(n=5, ptr=(0, 0, 0, 0, 0, 4), post=(0, 1, 2, 3), weights=(5., 6., 7., 8.), stimulated=(3,))
        c = (np.exp(-.1 / 20) - np.exp(-.1 / 5)) / 3
        for sim in (a, b):
            sim.tick = 22
            sim.last[:] = (0, 0, 1, 22, 0)
            sim.g[:] = (7 / c, 7 / c * (1 + 1e-12), -0., 8000., 0.)
            sim.pending[22 % 19] = [4]
        self.compare_window(a, b, 1, {22: [1, 3, 1]})
        self.assertEqual(a.v[0], -45.)
        assert_exact(a.g[2], -0.)
        assert_exact(a.v[[1, 3]], np.array([-52., -52.]))
        self.assertEqual(a.last[1], 22)
        assert_exact(b._active, np.array([True, True, False, True, True]))

    def test_ordered_duplicate_csr_pending_capacity_and_ring_wrap(self):
        a, b = self.pair(n=4, ptr=(0, 2, 2, 4, 4), post=(1, 1, 1, 1), weights=(1e16, 1., -1e16, 3.), stimulated=(0, 2))
        for sim in (a, b):
            sim.pending[0] = [0, 2]
            sim.pending[4] = [2, 0, 2] * 4  # deliberately exceeds n
        self.compare_window(a, b, 1)
        self.assertEqual(a.g[1], 3.)
        self.assertEqual(a.pending[4], [2, 0, 2] * 4)
        events = {tick: [0, 2, 0] for tick in (1, 19, 37, 55, 73)}
        for _ in range(80):
            self.compare_window(a, b, 1, events)

    def test_delay_exactly_eighteen_ticks(self):
        a, b = self.pair(n=3, ptr=(0, 1, 1, 1), post=(1,), weights=(10.,))
        a.v[0] = b.v[0] = 10.
        for tick in range(40):
            self.compare_window(a, b, 1)
            if tick < 18:
                self.assertEqual(a.g[1], 0.)
            if tick == 18:
                self.assertEqual(a.g[1], 10.)
                self.assertEqual(a.pending[18], [])

    def test_count_identity_accumulation_and_empty_observation(self):
        a, b = self.pair(n=3, stimulated=(0, 1))
        buffers = (np.arange(3, dtype=np.int64), np.arange(3, dtype=np.int64))
        for ticks in (0, 1, 18, 19, 22):
            start = a.tick
            events = {tick: [1, 0, 1] for tick in range(start, start + ticks, 2)}
            _, sums = self.compare_window(a, b, ticks, events, observed=np.empty(0, dtype=np.int64), buffers=buffers)
            self.assertEqual(sums.shape, (2, 0))

    def test_window_and_recorded_step_can_alternate(self):
        a, b = self.pair(n=6, ptr=(0, 2, 4, 4, 4, 4, 4), post=(3, 3, 4, 5), weights=(20., -8., 30., -5.), stimulated=(0, 1))
        events = {tick: [0, 1, 0] for tick in range(0, 160, 3)}
        for ticks, use_window in ((19, True), (7, False), (22, True), (20, False), (1, True), (77, True)):
            if use_window:
                self.compare_window(a, b, ticks, events)
            else:
                assert_exact(a.step(ticks, events, record=True), b.step(ticks, events, record=True), "record path")
                compare_simulations(a, b)

    def test_seeded_prefix_windows_and_observed_sum_order(self):
        n = 2048
        for seed in (20270101, 20270102, 20270103):
            rng = np.random.default_rng(seed)
            ptr = np.arange(0, 3 * (n + 1), 3, dtype=np.int64)
            post = rng.integers(0, n, n * 3, dtype=np.int64)
            weights = rng.uniform(-40., 40., n * 3)
            v, g = rng.uniform(-80., -44., n), rng.uniform(-80., 80., n)
            v[:4] = [-52., -52., -45., np.nextafter(-45., np.inf)]
            g[:4] = [-0., np.nextafter(0., 1.), 0., np.nextafter(0., -1.)]
            last = rng.integers(-40, 1, n, dtype=np.int64)
            events = {tick: rng.integers(0, n, 12).tolist() + [0, 1, 0] for tick in range(500)}
            # Duplicate and nonascending observation positions verify per-slot sums.
            observed = np.array([9, 2, 9, 0, 1, 1001], dtype=np.int64)
            for ticks in (0, 1, 18, 19, 22, 37, 77, 500):
                with self.subTest(seed=seed, ticks=ticks):
                    a, b = self.pair(n, ptr, post, weights, stimulated=tuple(range(0, n, 13)))
                    for sim in (a, b):
                        sim.v[:], sim.g[:], sim.last[:] = v, g, last
                        sim.pending[0], sim.pending[18] = [4, 2, 4], [9, 8, 9]
                    self.compare_window(a, b, ticks, events, observed)

    def test_native_boundary_rejects_invalid_input_without_state_changes(self):
        _, sim = self.pair()
        valid = {"ticks": 2, "event_offsets": np.array([0, 0, 0], dtype=np.int64),
                 "event_indices": np.empty(0, dtype=np.int64), "observed": np.array([0], dtype=np.int64)}
        invalid = [
            {"ticks": -1}, {"ticks": 1.5},
            {"event_offsets": np.array([0, 999, 0], dtype=np.int64)},
            {"event_offsets": np.array([0, -1, 0], dtype=np.int64)},
            {"event_offsets": np.array([0., 0., 0.])},
            {"event_offsets": np.array([[0, 0, 0]], dtype=np.int64)},
            {"event_offsets": np.array([0, 0, 1], dtype=np.int64), "event_indices": np.array([5], dtype=np.int64)},
            {"event_offsets": np.array([0, 0, 1], dtype=np.int64), "event_indices": np.array([-1], dtype=np.int64)},
            {"event_offsets": np.array([0, 0, 1], dtype=np.int64), "event_indices": np.array([0.])},
            {"event_indices": np.empty((0, 1), dtype=np.int64)},
            {"observed": np.array([5], dtype=np.int64)}, {"observed": np.array([-1], dtype=np.int64)},
            {"observed": np.array([0.])}, {"observed": np.array([[0]], dtype=np.int64)},
            {"count_buffer": np.zeros(4, dtype=np.int64)}, {"count_buffer": np.zeros(5)},
            {"count_buffer": np.zeros((1, 5), dtype=np.int64)},
        ]
        before = {key: copy.deepcopy(getattr(sim, key)) for key in ("v", "g", "last", "rfc", "pending", "tick")}
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises((ValueError, TypeError)):
                    sim.step_window(**{**valid, **changes})
                for name, expected in before.items():
                    assert_exact(expected, getattr(sim, name), "rejection." + name)
        for pre in (-1, 5, .5):
            sim.pending[0] = [pre]
            with self.subTest(invalid_pending=pre):
                with self.assertRaises((ValueError, TypeError)):
                    sim.step_window(**valid)
            sim.pending[0] = []

    def test_controller_random_consumption_and_event_order(self):
        # Small real CSR graph and both real controllers; captures only observe calls.
        with tempfile.TemporaryDirectory(prefix="malecns-window-test-") as temporary:
            graph = Path(temporary)
            for name, value in (("body_ids", np.arange(100, 108, dtype=np.int64)),
                ("indptr", np.array([0, 1, 2, 3, 3, 3, 3, 3, 3], dtype=np.int64)),
                ("targets", np.array([4, 5, 6], dtype=np.int64)), ("weights", np.full(3, 10., dtype=np.float64))):
                np.save(graph / name, value)
            config = {"stimulusRateHz": 100, "inputs": {"F": [100, 101], "R": [101, 102], "L": [102]},
                "readouts": {"DNp09_L_Hz": 103, "DNp09_R_Hz": 104, "DNa02_R_Hz": 105, "DNa02_L_Hz": 106},
                "populations": {axis: {side: {"test": [identifier]} for side, identifier in (("R", 103), ("L", 104))}
                    for axis in ("forward", "turn")}}
            a = self.snapshot_controller(graph, config, 20270101, 50.).initialize()
            b = self.controller(graph, config, 20270101, 50.).initialize()
            try:
                compare_simulations(a.sim, b.sim)
                assert_exact(a.rng.bit_generator.state, b.rng.bit_generator.state, "initialized RNG")
                original_step, original_window = a.sim.step, b.sim.step_window
                calls, packed = [], []
                def capture_step(ticks, events=None, **kwargs):
                    calls.append(list((events or {}).get(a.sim.tick, ())))
                    return original_step(ticks, events, **kwargs)
                def capture_window(ticks, offsets, indices, observed, **kwargs):
                    packed.extend(indices[offsets[t]:offsets[t + 1]].tolist() for t in range(ticks))
                    return original_window(ticks, offsets, indices, observed, **kwargs)
                a.sim.step, b.sim.step_window = capture_step, capture_window
                for action in ("STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L", "STOP"):
                    calls.clear()
                    packed.clear()
                    for controller in (a, b):
                        controller.set_action(action)
                    frames = [a.step(), b.step()]
                    for frame in frames:
                        frame.pop("performance")
                    self.assertEqual(len(calls), 500)
                    assert_exact(calls, packed, "tick-by-tick stimulus sequence")
                    assert_exact(a.rng.bit_generator.state, b.rng.bit_generator.state, "RNG state")
                    assert_exact(frames[0], frames[1], "controller frame")
                    compare_simulations(a.sim, b.sim)
            finally:
                for controller in (a, b):
                    for mapping in (controller.ids, controller.sim.indptr, controller.sim.post, controller.sim.weights):
                        mapping._mmap.close()

    def test_numba_cache_cross_entrypoint_in_both_directions(self):
        # Separate real interpreters exercise cache deserialization, not a module mock.
        child = r'''
import hashlib, importlib, json, pathlib, sys, time
import numpy as np
root = pathlib.Path(sys.argv[1]).resolve()
module = root / "Brain/MaleCNS"
forbidden = {str(root).casefold(), str(module).casefold()}
sys.path[:] = [p for p in sys.path if str(pathlib.Path(p).resolve()).casefold() not in forbidden]
mode = sys.argv[2]
sys.path.insert(0, str(root if mode == "package" else module))
kernel = importlib.import_module("Brain.MaleCNS.lif_kernels" if mode == "package" else "lif_kernels")
a, b = np.exp(-.1 / 20), np.exp(-.1 / 5)
c = (a - b) / 3
def arrays():
    return (np.array([-52., -44., -52.]), np.array([0., 0., -0.]),
            np.full(3, -1000000, dtype=np.int64), np.array([0, 22, 22], dtype=np.int64),
            np.empty(3, dtype=np.bool_), np.empty(3, dtype=np.int64))
v, g, last, rfc, active, fired = arrays()
start = time.perf_counter()
nf = kernel.update_state_and_extract_fired(v, g, last, rfc, 0, a, b, c, active, fired)
helper_ms = (time.perf_counter() - start) * 1000
helper = {"vBits": v.view(np.uint64).tolist(), "gBits": g.view(np.uint64).tolist(),
          "active": active.tolist(), "fired": fired[:nf].tolist()}
v, g, last, rfc, active, fired = arrays()
ptr = np.array([0, 2, 2, 2], dtype=np.int64)
post, weights = np.array([2, 2], dtype=np.int64), np.array([8., -3.])
ring, sizes = np.empty((19, 3), dtype=np.int64), np.zeros(19, dtype=np.int64)
ring[0, :2], sizes[0] = [0, 0], 2
offsets, events = [0], []
for tick in range(40):
    if tick % 5 == 0: events.extend([0, 0, 1])
    offsets.append(len(events))
counts, sums = np.zeros(3, dtype=np.int64), np.empty((2, 3), dtype=np.float64)
start = time.perf_counter()
kernel.run_window(v, g, last, rfc, ptr, post, weights, 0, 40, a, b, c, active, fired,
                  ring, sizes, np.array(offsets, dtype=np.int64), np.array(events, dtype=np.int64),
                  np.arange(3, dtype=np.int64), counts, sums)
window_ms = (time.perf_counter() - start) * 1000
state = {"helper": helper, "vBits": v.view(np.uint64).tolist(), "gBits": g.view(np.uint64).tolist(),
         "last": last.tolist(), "rfc": rfc.tolist(), "counts": counts.tolist(),
         "sumsBits": sums.view(np.uint64).tolist(), "pending": [ring[i, :sizes[i]].tolist() for i in range(19)]}
print(json.dumps({"mode": mode, "state": state, "helperMs": helper_ms, "windowMs": window_ms,
    "cache": {name: {"hits": sum(getattr(kernel, name)._cache_hits.values()),
                      "misses": sum(getattr(kernel, name)._cache_misses.values())}
              for name in ("update_state_and_extract_fired", "run_window")}}))
'''
        report = {"complete": False, "directions": [],
                  "sourceSha256": sha256_file(ROOT / "Brain/MaleCNS/lif_kernels.py"),
                  "notes": ["Separate subprocesses; each direction uses a fresh isolated NUMBA_CACHE_DIR.",
                            "Only one requested entry path is added before importing kernels.",
                            "Subprocess environment is allowlisted and excludes credentials/PYTHONPATH."]}
        output = ROOT / "artifacts/windows-malecns/window-compiled/cache-entrypoint-regression.json"
        save_report(output, report)
        allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA",
                   "USERPROFILE", "PATH", "PATHEXT"}
        for first, second in (("package", "standalone"), ("standalone", "package")):
            with tempfile.TemporaryDirectory(prefix="malecns-numba-cache-") as temporary:
                env = {name: value for name, value in os.environ.items() if name.upper() in allowed}
                env.update(NUMBA_CACHE_DIR=temporary, PYTHONNOUSERSITE="1")
                runs = []
                for mode in (first, second):
                    completed = subprocess.run([sys.executable, "-c", child, str(ROOT), mode], env=env,
                        cwd=temporary, text=True, capture_output=True, timeout=60)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    runs.append(json.loads(completed.stdout))
                assert_exact(runs[0]["state"], runs[1]["state"], "cross-entrypoint numerical state")
                for name in ("update_state_and_extract_fired", "run_window"):
                    self.assertGreaterEqual(runs[0]["cache"][name]["misses"], 1)
                    self.assertGreaterEqual(runs[1]["cache"][name]["hits"], 1)
                    self.assertEqual(runs[1]["cache"][name]["misses"], 0)
                report["directions"].append({"first": first, "second": second, "runs": runs, "exact": True})
                save_report(output, report)
        report["complete"] = True
        save_report(output, report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
