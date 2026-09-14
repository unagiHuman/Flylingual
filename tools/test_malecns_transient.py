"""Transient-subnormal bit equivalence; parent runs this in the MaleCNS environment.

No full graph, API, TCP or Unity work. Independent Python integer and NumPy
oracles preserve rounding and signed zero instead of accepting tolerances.
"""
import importlib
import unittest

import numpy as np

from test_malecns_fixed_point import numpy_state_update
from validate_malecns_compiled import assert_exact, load_implementations


def rounded_product(magnitude, significand):
    """Exact arbitrary-precision product, round to nearest with even ties."""
    quotient, remainder = divmod(int(magnitude) * int(significand), 1 << 53)
    halfway = 1 << 52
    return quotient + int(remainder > halfway or (remainder == halfway and quotient & 1))


def magnitudes():
    rng = np.random.default_rng(20260914)
    boundary = list(range(0, 130))
    for exponent in range(1, 53):
        boundary.extend([(1 << exponent) - 1, 1 << exponent, (1 << exponent) + 1])
    # Normal exponent fields 1..16 cover the complete tiny-add shortcut.
    # Include the inclusive upper threshold and the first excluded bit pattern.
    for exponent_field in range(1, 17):
        center = exponent_field << 52
        boundary.extend([center - 1, center, center + 1])
    # Mantissas straddling fixed point and all exponent-scale transitions.
    return np.unique(np.r_[np.asarray(boundary, dtype=np.uint64),
                           rng.integers(26, 1 << 52, size=8192, dtype=np.uint64)])


class TransientSubnormalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_implementations()
        cls.kernels = importlib.import_module('lif_kernels')
        cls.a, cls.b = np.exp(-.1 / 20), np.exp(-.1 / 5)
        cls.c = (cls.a-cls.b)/3

    def test_integer_helper_matches_arbitrary_precision_product(self):
        # The only direct dependency on the implementation helper name.
        helper = getattr(self.kernels, '_decay_subnormal_bits')
        rng = np.random.default_rng(20260915)
        values = magnitudes()
        values = values[values < (1 << 52)]
        nominal = (int(np.float64(self.b).view(np.uint64)) & ((1 << 52)-1)) | (1 << 52)
        coefficients = [1 << 52, (1 << 52)+1, 3 << 51, nominal, (1 << 53)-1]
        for index, magnitude in enumerate(values):
            coefficient = coefficients[index % len(coefficients)]
            self.assertEqual(int(helper(np.uint64(magnitude), np.uint64(coefficient))),
                             rounded_product(magnitude, coefficient))
        for magnitude, coefficient in zip(rng.integers(0, 1 << 52, 4096, dtype=np.uint64),
                                         rng.integers(1 << 52, 1 << 53, 4096, dtype=np.uint64)):
            self.assertEqual(int(helper(magnitude, coefficient)), rounded_product(magnitude, coefficient))
        # Exact half-way products with even and odd retained quotients.
        for magnitude in (1, 3, 5, 7, (1 << 52)-3, (1 << 52)-1):
            self.assertEqual(int(helper(np.uint64(magnitude), np.uint64(1 << 52))),
                             rounded_product(magnitude, 1 << 52))

    def compare_kernel(self, initial_v, initial_g, a, b, c, window=False):
        n = len(initial_g)
        last = np.full(n, -1000000, dtype=np.int64)
        last[::11] = 0  # Refractory cells preserve both state arrays.
        rfc = np.full(n, 22, dtype=np.int64)
        expected_v, expected_g, expected_active, expected_fired = numpy_state_update(
            initial_v, initial_g, last, rfc, 0, a, b, c)
        v, g = initial_v.copy(), initial_g.copy()
        active = np.empty(n, dtype=np.bool_)
        fired = np.empty(n, dtype=np.int64)
        if not window:
            count = self.kernels.update_state_and_extract_fired(v, g, last, rfc, 0, a, b, c, active, fired)
            assert_exact(fired[:count], expected_fired, 'fired ordering')
        else:
            counts = np.zeros(n, dtype=np.int64)
            sums = np.empty((2,n))
            ring = np.empty((19,n), dtype=np.int64)
            sizes = np.zeros(19, dtype=np.int64)
            self.kernels.run_window(v,g,last,rfc,np.zeros(n+1,dtype=np.int64),
                np.empty(0,dtype=np.int64),np.empty(0),0,1,a,b,c,active,fired,ring,sizes,
                np.zeros(2,dtype=np.int64),np.empty(0,dtype=np.int64),np.arange(n,dtype=np.int64),counts,sums)
            expected_v[expected_fired] = -52.
            expected_g[expected_fired] = 0.
            expected_counts = np.zeros(n,dtype=np.int64)
            expected_counts[expected_fired] = 1
            assert_exact(counts,expected_counts,'window counts')
            assert_exact(ring[18,:sizes[18]],expected_fired,'window delayed ordering')
            assert_exact(sums,np.stack((np.zeros(n)+expected_v,np.zeros(n)+expected_g)),'window sums')
        assert_exact(v,expected_v,'v bits')
        assert_exact(g,expected_g,'g bits')
        assert_exact(active,expected_active,'active')

    def test_random_signed_transients_and_normal_boundary(self):
        unsigned = magnitudes()
        bits = np.r_[unsigned, unsigned | np.uint64(1 << 63)]
        g = bits.view(np.float64)
        choices = np.array([-52., np.nextafter(-52.,-np.inf), np.nextafter(-52.,np.inf),
                            -53., -51., -44., -0., 0.])
        v = choices[np.arange(len(g)) % len(choices)]
        for window in (False, True):
            self.compare_kernel(v,g,self.a,self.b,self.c,window)

    def test_tiny_add_upper_boundary_and_actual_x_neighbors(self):
        boundary = np.array([0x00ffffffffffffff, 0x0100000000000000,
                             0x0100000000000001], dtype=np.uint64)
        signed = np.r_[boundary, boundary | np.uint64(1 << 63)].view(np.float64)
        # nextafter(1) collapses when adding 52. Use neighboring sums at 53/51,
        # then verify the actual operation-ordered x, not the initial v label.
        positive = np.array([np.nextafter(53., -np.inf)-52., 1.,
                             np.nextafter(53., np.inf)-52.])
        negative = np.array([np.nextafter(51., -np.inf)-52., -1.,
                             np.nextafter(51., np.inf)-52.])
        voltage = np.r_[positive, negative]
        actual_x = np.add(-52., np.multiply(np.add(voltage, 52.), 1.))
        self.assertLess(actual_x[0], 1.)
        self.assertEqual(actual_x[1], 1.)
        self.assertGreater(actual_x[2], 1.)
        self.assertLess(actual_x[3], -1.)
        self.assertEqual(actual_x[4], -1.)
        self.assertGreater(actual_x[5], -1.)
        g = np.tile(signed, len(voltage))
        v = np.repeat(voltage, len(signed))
        for coefficient in (self.c, -self.c):
            for window in (False, True):
                self.compare_kernel(v,g,1.,self.b,coefficient,window)

    def test_small_voltage_and_incompatible_coefficients_fall_back_exactly(self):
        values = magnitudes()[::13]
        g = np.r_[values,values | np.uint64(1 << 63)].view(np.float64)
        # a=1 and v=0 make the intermediate x exactly zero: g*c must survive.
        # Near +/-1 exercises both sides of the proposed large-x shortcut.
        voltage = np.array([0., -0., .5, -.5, 1., -1., np.nextafter(1.,0.),
                            np.nextafter(-1.,0.), -52.])
        v = voltage[np.arange(len(g)) % len(voltage)]
        for a,b,c in ((1.,self.b,self.c),(1.,self.b,-self.c),
                      (self.a,.9,self.c),(self.a,1.,self.c),
                      (self.a,-self.b,self.c),(self.a,self.b,1e308),
                      (self.a,self.b,-1e308),(1.,self.b,0.),(1.,self.b,-0.)):
            for window in (False, True):
                with self.subTest(a=a,b=b,c=c,window=window):
                    self.compare_kernel(v,g,a,b,c,window)


if __name__ == '__main__':
    unittest.main(verbosity=2)
