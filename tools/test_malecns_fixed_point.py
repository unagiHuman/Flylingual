"""Bit-exact boundary tests for preserving subnormal fixed points, not zeroing.

Run directly with the MaleCNS Python environment. No performance assertions or
full graph/Unity/TCP work. The rounding test uses its own credential-free process.
"""
import importlib
import json
import os
import subprocess
import sys
import unittest

import numpy as np

from validate_malecns_compiled import ROOT, assert_exact, compare_simulations, load_implementations
from validate_malecns_window_compiled import pack_events


def boundary_g_values():
    magnitudes = list(range(27)) + [27, 31, 50, 51, 1 << 51, (1 << 52) - 1, 1 << 52, (1 << 52) + 1]
    return np.array([magnitude | sign for sign in (0, 1 << 63) for magnitude in magnitudes],
                    dtype=np.uint64).view(np.float64)


def numpy_state_update(v, g, last, rfc, tick, a, b, c):
    """Independent NumPy ufunc oracle preserving the pinned update's order."""
    v, g = v.copy(), g.copy()
    active = (tick - last) >= rfc
    temporary = np.add(v, 52)
    np.multiply(temporary, a, out=temporary)
    np.add(-52, temporary, out=temporary)
    product = np.multiply(g, c)
    np.add(temporary, product, out=temporary)
    np.copyto(v, temporary, where=active)
    np.multiply(g, b, out=g, where=active)
    return v, g, active, np.flatnonzero(active & (v > -45))


class FixedPointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference, cls.candidate, _, _, _ = load_implementations()
        cls.kernels = importlib.import_module("lif_kernels")
        cls.a, cls.b = np.exp(-.1 / 20), np.exp(-.1 / 5)
        cls.c = (cls.a - cls.b) / 3

    def pair(self, g, v=None, stimulated=(), ptr=None, post=(), weights=()):
        n = len(g)
        ptr = np.zeros(n + 1, dtype=np.int64) if ptr is None else np.asarray(ptr, dtype=np.int64)
        post, weights = np.asarray(post, dtype=np.int64), np.asarray(weights, dtype=np.float64)
        a, b = (cls(n, ptr.copy(), post.copy(), weights.copy(), stimulated) for cls in (self.reference, self.candidate))
        for sim in (a, b):
            sim.g[:] = g
            if v is not None:
                sim.v[:] = v
        return a, b

    def compare_window(self, a, b, ticks, events=None, buffers=None):
        events = events or {}
        observed = np.arange(len(a.v), dtype=np.int64)
        expected = np.zeros(len(a.v), dtype=np.int64) if buffers is None else buffers[0]
        sums = np.zeros((2, len(observed)), dtype=np.float64)
        offsets, indices = pack_events(a.tick, ticks, events)
        for _ in range(ticks):
            a.step(1, events, count_buffer=expected)
            sums[0] += a.v[observed]
            sums[1] += a.g[observed]
        actual, actual_sums = b.step_window(ticks, offsets, indices, observed,
            count_buffer=None if buffers is None else buffers[1])
        assert_exact(expected, actual, "count")
        assert_exact(sums, actual_sums, "observed sums")
        compare_simulations(a, b)
        if buffers is not None:
            self.assertIs(actual, buffers[1])

    def test_guard_accepts_nominal_and_signed_zero_products(self):
        guard = self.kernels._fixed_point_updates_enabled
        for c in (self.c, -self.c, 0., -0.):
            self.assertTrue(guard(self.a, self.b, c))
        self.assertTrue(guard(1., 1., -0.))

    def test_guard_rejects_incompatible_coefficients(self):
        guard = self.kernels._fixed_point_updates_enabled
        for a, b, c in ((self.a, .9, self.c), (self.a, -self.b, self.c),
                        (self.a, self.b, 1e308), (self.a, self.b, -1e308),
                        (np.inf, self.b, self.c), (-np.inf, self.b, self.c),
                        (np.nan, self.b, self.c), (self.a, np.nan, self.c), (self.a, self.b, np.nan)):
            with self.subTest(a=a, b=b, c=c):
                self.assertFalse(guard(a, b, c))

    def test_all_signed_fixed_point_and_normal_boundaries_through_step(self):
        g = boundary_g_values()
        a, b = self.pair(g)
        for tick in range(30):
            left, right = a.step(1, record=True), b.step(1, record=True)
            assert_exact(left, right, "recorded step")
            compare_simulations(a, b)
            if tick == 0:
                magnitude = g.view(np.uint64) & np.uint64(0x7fffffffffffffff)
                fixed = magnitude <= 25
                assert_exact(b.g[fixed], g[fixed], "preserved signed fixed-point bits")
                changed = magnitude == 26
                self.assertTrue(np.all(b.g[changed].view(np.uint64) != g[changed].view(np.uint64)))

    def test_voltage_neighbors_and_long_prefix_windows(self):
        base_g = boundary_g_values()
        voltages = np.array([-52., np.nextafter(-52., -np.inf), np.nextafter(-52., np.inf),
                             -52. + 100 * np.spacing(52.), -52. - 100 * np.spacing(52.), -44.])
        g = np.tile(base_g, len(voltages))
        v = np.repeat(voltages, len(base_g))
        for ticks in (0, 1, 18, 19, 22, 77, 500):
            with self.subTest(ticks=ticks):
                a, b = self.pair(g, v)
                self.compare_window(a, b, ticks)

    def test_direct_kernels_preserve_fallback_and_signed_product_results(self):
        base_g = boundary_g_values()
        voltages = np.array([-52., np.nextafter(-52., -np.inf), np.nextafter(-52., np.inf), -0., 0., -44.])
        initial_g = np.tile(base_g, len(voltages))
        initial_v = np.repeat(voltages, len(base_g))
        n = len(initial_g)
        last = np.full(n, -1000000, dtype=np.int64)
        rfc = np.full(n, 22, dtype=np.int64)
        for a, b, c in ((self.a, self.b, self.c), (self.a, self.b, -self.c),
                        (1., 1., 0.), (1., 1., -0.), (self.a, .9, self.c),
                        (self.a, self.b, 1e308), (self.a, self.b, -1e308)):
            with self.subTest(a=a, b=b, c=c):
                expected_v, expected_g, expected_active, expected_fired = numpy_state_update(
                    initial_v, initial_g, last, rfc, 0, a, b, c)
                v, g = initial_v.copy(), initial_g.copy()
                active, fired = np.empty(n, dtype=np.bool_), np.empty(n, dtype=np.int64)
                count = self.kernels.update_state_and_extract_fired(v, g, last, rfc, 0, a, b, c, active, fired)
                for left, right, name in ((v, expected_v, "helper.v"), (g, expected_g, "helper.g"),
                    (active, expected_active, "helper.active"), (fired[:count], expected_fired, "helper.fired")):
                    assert_exact(left, right, name)
                # Exercise the same coefficient fallback in the complete window kernel.
                v, g, window_last = initial_v.copy(), initial_g.copy(), last.copy()
                ring = np.empty((19, n), dtype=np.int64)
                ring_sizes = np.zeros(19, dtype=np.int64)
                counts, sums = np.zeros(n, dtype=np.int64), np.empty((2, n))
                self.kernels.run_window(v, g, window_last, rfc, np.zeros(n + 1, dtype=np.int64),
                    np.empty(0, dtype=np.int64), np.empty(0), 0, 1, a, b, c, active, fired,
                    ring, ring_sizes, np.zeros(2, dtype=np.int64), np.empty(0, dtype=np.int64),
                    np.arange(n, dtype=np.int64), counts, sums)
                expected_v[expected_fired], expected_g[expected_fired] = -52., 0.
                expected_last, expected_counts = last.copy(), np.zeros(n, dtype=np.int64)
                expected_last[expected_fired], expected_counts[expected_fired] = 0, 1
                assert_exact(v, expected_v, "window.v")
                assert_exact(g, expected_g, "window.g")
                assert_exact(window_last, expected_last, "window.last")
                assert_exact(counts, expected_counts, "window.count")
                assert_exact(sums, np.stack((np.zeros(n) + expected_v, np.zeros(n) + expected_g)), "window.sums")
                assert_exact(ring[18, :ring_sizes[18]], expected_fired, "window.pending")

    def test_refractory_and_delivery_resume_from_preserved_values(self):
        g = np.array([25, (1 << 63) | 25, 0, 0], dtype=np.uint64).view(np.float64)
        a, b = self.pair(g, stimulated=(0,), ptr=(0, 0, 0, 0, 4), post=(0, 0, 1, 2), weights=(8., -3., 4., 7.))
        for sim in (a, b):
            sim.tick = 22
            sim.last[:] = (22, 1, 0, 0)
            sim.pending[22 % 19] = [3]
        self.compare_window(a, b, 1, {22: [0, 0, 2]})
        assert_exact(b._active, np.array([True, False, True, True]))
        self.assertEqual(b.g[0], 5.)
        assert_exact(b.g[1], g[1])
        self.assertEqual(b.g[2], 7.)
        self.compare_window(a, b, 1)
        self.assertEqual(b.g[0], 0.)  # stimulus-triggered firing still resets g
        for _ in range(40):
            self.compare_window(a, b, 1)

    def test_record_window_mixture_counts_and_order(self):
        a, b = self.pair(boundary_g_values(), stimulated=(0, 1))
        events = {tick: [1, 0, 1] for tick in range(0, 100, 3)}
        buffers = (np.arange(len(a.v), dtype=np.int64), np.arange(len(a.v), dtype=np.int64))
        for ticks, record in ((19, False), (7, True), (22, False), (20, True), (1, False), (31, False)):
            if record:
                left = a.step(ticks, events, True, buffers[0])
                right = b.step(ticks, events, True, buffers[1])
                self.assertIs(left[0], buffers[0])
                self.assertIs(right[0], buffers[1])
                assert_exact(left, right, "recorded return")
                compare_simulations(a, b)
            else:
                self.compare_window(a, b, ticks, events, buffers)

    @unittest.skipUnless(os.name == "nt", "Windows floating-point control regression")
    def test_rounding_and_flush_modes_fall_back_in_an_isolated_process(self):
        child = r'''
import ctypes, importlib, json, pathlib, sys
import numpy as np
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / "Brain/MaleCNS"))
sys.path.insert(0, str(root / "tools"))
from test_malecns_fixed_point import numpy_state_update
k = importlib.import_module("lif_kernels")
a,b = np.exp(-.1/20), np.exp(-.1/5)
c=(a-b)/3
assert k._fixed_point_updates_enabled(a,b,c)
def window_once(v,g,last,rfc):
    n=len(v)
    k.run_window(v,g,last,rfc,np.zeros(n+1,dtype=np.int64),np.empty(0,dtype=np.int64),
        np.empty(0),0,1,a,b,c,np.empty(n,dtype=np.bool_),np.empty(n,dtype=np.int64),
        np.empty((19,n),dtype=np.int64),np.zeros(19,dtype=np.int64),
        np.zeros(2,dtype=np.int64),np.empty(0,dtype=np.int64),np.arange(n,dtype=np.int64),
        np.zeros(n,dtype=np.int64),np.empty((2,n)))
# Compile both call signatures before changing this child's rounding control.
warm_v=np.full(6,-52.); warm_g=np.zeros(6)
warm_last=np.full(6,-1000000,dtype=np.int64); warm_rfc=np.full(6,22,dtype=np.int64)
k.update_state_and_extract_fired(warm_v,warm_g,warm_last,warm_rfc,0,a,b,c,
    np.empty(6,dtype=np.bool_),np.empty(6,dtype=np.int64))
window_once(warm_v,warm_g,warm_last,warm_rfc)
control = ctypes.CDLL("ucrtbase")._controlfp_s
control.argtypes = [ctypes.POINTER(ctypes.c_uint), ctypes.c_uint, ctypes.c_uint]
control.restype = ctypes.c_int
current = ctypes.c_uint()
assert control(ctypes.byref(current),0,0)==0
saved=current.value
rows=[]
try:
    # _MCW_RC=0x300, _MCW_DN=0x03000000, _DN_FLUSH=0x01000000.
    # Test nearest with flushing too; production never changes these controls.
    for mode in (0x100,0x200,0x300,0x01000000):
        assert control(ctypes.byref(current),mode,0x03000300)==0
        assert not k._fixed_point_updates_enabled(a,b,c), "incompatible environment accepted"
        g=np.array([1,25,26,(1<<63)|1,(1<<63)|25,(1<<63)|26],dtype=np.uint64).view(np.float64)
        v=np.full(6,-52.); last=np.full(6,-1000000,dtype=np.int64); rfc=np.full(6,22,dtype=np.int64)
        expected_v,expected_g,expected_active,expected_fired=numpy_state_update(v,g,last,rfc,0,a,b,c)
        window_v,window_g=v.copy(),g.copy()
        active=np.empty(6,dtype=np.bool_); fired=np.empty(6,dtype=np.int64)
        nf=k.update_state_and_extract_fired(v,g,last,rfc,0,a,b,c,active,fired)
        assert v.tobytes()==expected_v.tobytes() and g.tobytes()==expected_g.tobytes()
        assert active.tobytes()==expected_active.tobytes() and fired[:nf].tobytes()==expected_fired.tobytes()
        window_once(window_v,window_g,last.copy(),rfc)
        assert window_v.tobytes()==expected_v.tobytes() and window_g.tobytes()==expected_g.tobytes()
        rows.append({"floatingPointControl":mode,"guardEnabled":False,"bitExact":True})
finally:
    assert control(ctypes.byref(current),saved,0x03000300)==0
assert (current.value&0x03000300)==(saved&0x03000300)
print(json.dumps(rows))
'''
        allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA",
                   "USERPROFILE", "PATH", "PATHEXT"}
        env = {name: value for name, value in os.environ.items() if name.upper() in allowed}
        env["PYTHONNOUSERSITE"] = "1"
        result = subprocess.run([sys.executable, "-c", child, str(ROOT)], env=env,
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
