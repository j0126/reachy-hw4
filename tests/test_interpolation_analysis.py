"""Regression tests that pin down how SDK 1.11.0 interpolation behaves.

If an SDK change alters any of these properties, the Phase 1 analysis (and every motion
designed on top of it) must be revisited - that is the point of these tests.
"""

import unittest

import numpy as np
from reachy_mini.utils.interpolation import InterpolationTechnique as IT
from reachy_mini.utils.interpolation import time_trajectory

from reachy_motion.analysis.interpolation import (
    CARTOON_C2,
    METHODS,
    PLAY_MOVE_PERIOD_S,
    analytic_dds,
    analytic_ds,
    characterize,
    endpoint_shortfall,
    physical_peaks,
    sdk_s,
)


class TestSdkTimeTrajectory(unittest.TestCase):
    def test_enum_has_exactly_four_methods(self):
        self.assertEqual({m.value for m in IT}, {"linear", "minjerk", "ease_in_out", "cartoon"})
        self.assertEqual(set(METHODS), set(IT))

    def test_boundaries(self):
        for m in METHODS:
            with self.subTest(method=m.value):
                self.assertAlmostEqual(time_trajectory(0.0, m), 0.0, places=12)
                self.assertAlmostEqual(time_trajectory(1.0, m), 1.0, places=12)
                self.assertAlmostEqual(time_trajectory(0.5, m), 0.5, places=12)

    def test_rejects_tau_outside_unit_interval(self):
        for m in METHODS:
            with self.subTest(method=m.value):
                with self.assertRaises(ValueError):
                    time_trajectory(-1e-9, m)
                with self.assertRaises(ValueError):
                    time_trajectory(1.0 + 1e-9, m)


class TestHandFormulas(unittest.TestCase):
    def test_sdk_matches_hand_formulas(self):
        """The report's closed forms (SDK_ANALYSIS section 3.1) reproduce time_trajectory exactly."""
        tau = np.linspace(0.0, 1.0, 20_001)
        c2 = CARTOON_C2
        hand = {
            IT.LINEAR: tau,
            IT.MIN_JERK: 10 * tau**3 - 15 * tau**4 + 6 * tau**5,
            IT.EASE_IN_OUT: np.where(tau < 0.5, 2 * tau**2, 1 - 2 * (1 - tau) ** 2),
            IT.CARTOON: np.where(
                tau < 0.5,
                4 * (c2 + 1) * tau**3 - 2 * c2 * tau**2,
                1 + 4 * (c2 + 1) * (tau - 1) ** 3 + 2 * c2 * (tau - 1) ** 2,
            ),
        }
        for m, s in hand.items():
            with self.subTest(method=m.value):
                self.assertLess(float(np.max(np.abs(sdk_s(m, tau) - s))), 1e-12)


class TestDerivedDerivatives(unittest.TestCase):
    """Our closed-form derivatives must agree with finite differences of the SDK function."""

    def test_first_derivative_matches_sdk(self):
        tau = np.linspace(0.0, 1.0, 100_001)
        h = tau[1] - tau[0]
        away = np.abs(tau - 0.5) > 2 * h
        for m in METHODS:
            with self.subTest(method=m.value):
                num = np.gradient(sdk_s(m, tau), tau, edge_order=2)
                self.assertLess(np.max(np.abs(num[away] - analytic_ds(m, tau)[away])), 1e-6)

    def test_second_derivative_matches_sdk(self):
        tau = np.linspace(0.0, 1.0, 20_001)
        h = tau[1] - tau[0]
        inner = (np.abs(tau - 0.5) > 4 * h) & (tau > 4 * h) & (tau < 1 - 4 * h)
        for m in METHODS:
            with self.subTest(method=m.value):
                s = sdk_s(m, tau)
                num = np.gradient(np.gradient(s, tau), tau)
                self.assertLess(np.max(np.abs(num[inner] - analytic_dds(m, tau)[inner])), 1e-3)


class TestCharacteristics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = {m: characterize(m) for m in METHODS}

    def test_peak_velocity_ratio(self):
        expected = {
            IT.LINEAR: 1.0,
            IT.MIN_JERK: 1.875,
            IT.EASE_IN_OUT: 2.0,
            IT.CARTOON: CARTOON_C2 + 3.0,  # = 5.5949...
        }
        for m, k in expected.items():
            with self.subTest(method=m.value):
                self.assertAlmostEqual(self.c[m].v_peak, k, places=6)
        for m in (IT.MIN_JERK, IT.EASE_IN_OUT, IT.CARTOON):
            self.assertAlmostEqual(self.c[m].tau_at_v_peak, 0.5, places=4)

    def test_only_cartoon_leaves_the_segment(self):
        for m in (IT.LINEAR, IT.MIN_JERK, IT.EASE_IN_OUT):
            self.assertEqual(self.c[m].overshoot, 0.0)
            self.assertEqual(self.c[m].anticipation, 0.0)
        cart = self.c[IT.CARTOON]
        # Extremum where ds/du = 0: u* = 2 c2 / (3 (c2 + 1)), tau* = u*/2.
        u_star = 2 * CARTOON_C2 / (3 * (CARTOON_C2 + 1))
        s_star = (CARTOON_C2 + 1) * u_star**3 / 2 - CARTOON_C2 * u_star**2 / 2
        self.assertAlmostEqual(cart.anticipation, -s_star, places=6)
        self.assertAlmostEqual(cart.overshoot, -s_star, places=6)  # symmetric
        self.assertAlmostEqual(cart.tau_at_s_min, u_star / 2, places=4)
        self.assertAlmostEqual(cart.tau_at_s_max, 1 - u_star / 2, places=4)
        self.assertAlmostEqual(cart.anticipation, 0.1002, places=4)

    def test_smoothness_classes(self):
        self.assertFalse(self.c[IT.LINEAR].velocity_continuous)  # velocity step at both ends
        self.assertTrue(self.c[IT.MIN_JERK].acceleration_continuous)
        self.assertTrue(self.c[IT.EASE_IN_OUT].velocity_continuous)
        self.assertFalse(self.c[IT.EASE_IN_OUT].acceleration_continuous)  # +-4 steps
        self.assertTrue(self.c[IT.CARTOON].velocity_continuous)
        self.assertFalse(self.c[IT.CARTOON].acceleration_continuous)
        self.assertAlmostEqual(self.c[IT.EASE_IN_OUT].a_seam_jump, 8.0, places=9)
        self.assertAlmostEqual(self.c[IT.CARTOON].a_seam_jump, 2 * (8 * CARTOON_C2 + 12), places=6)
        self.assertAlmostEqual(self.c[IT.MIN_JERK].a_peak, 10 / np.sqrt(3), places=4)

    def test_physical_scaling(self):
        row = physical_peaks(self.c[IT.MIN_JERK], amplitude=30.0, duration=0.5)
        self.assertAlmostEqual(row["peak_velocity_per_s"], 1.875 * 30 / 0.5)
        self.assertAlmostEqual(row["peak_accel_per_s2"], self.c[IT.MIN_JERK].a_peak * 30 / 0.25)
        self.assertEqual(row["velocity_step_at_ends_per_s"], 0.0)

    def test_linear_acceleration_is_impulsive_not_zero(self):
        row = physical_peaks(self.c[IT.LINEAR], amplitude=30.0, duration=0.5)
        self.assertEqual(row["peak_accel_per_s2"], float("inf"))  # s' jumps 0 -> 1 -> 0 at the ends
        self.assertAlmostEqual(row["velocity_step_at_ends_per_s"], 30.0 / 0.5)


class TestEndpointShortfall(unittest.TestCase):
    def test_linear_misses_by_one_sample_over_duration(self):
        for d in (0.3, 0.5, 1.0, 2.0):
            self.assertAlmostEqual(endpoint_shortfall(IT.LINEAR, d), PLAY_MOVE_PERIOD_S / d, places=12)

    def test_smooth_methods_are_negligible(self):
        for d in (0.3, 0.5, 1.0, 2.0):
            self.assertLess(abs(endpoint_shortfall(IT.MIN_JERK, d)), 1e-3)
            self.assertLess(abs(endpoint_shortfall(IT.EASE_IN_OUT, d)), 3e-3)
            self.assertLess(endpoint_shortfall(IT.CARTOON, d), 0.0)  # approaches from above


if __name__ == "__main__":
    unittest.main()
