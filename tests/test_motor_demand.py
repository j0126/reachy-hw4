import unittest

import numpy as np
from reachy_mini.utils.interpolation import InterpolationTechnique as IT

from reachy_motion.analysis.limits import STEWART_MOTOR, urdf_joint_limits
from reachy_motion.analysis.motor_demand import demand_row


class TestLimits(unittest.TestCase):
    def test_urdf_limits_match_documented_ranges(self):
        lim = {k: tuple(np.rad2deg(v)) for k, v in urdf_joint_limits().items()}
        expected = {
            "stewart_1": (-48, 80), "stewart_2": (-80, 70), "stewart_3": (-48, 80),
            "stewart_4": (-80, 48), "stewart_5": (-70, 80), "stewart_6": (-80, 48),
            "body_yaw": (-160, 160),
        }
        for joint, (lo, hi) in expected.items():
            with self.subTest(joint=joint):
                self.assertAlmostEqual(lim[joint][0], lo, places=3)
                self.assertAlmostEqual(lim[joint][1], hi, places=3)

    def test_datasheet_conversion(self):
        self.assertAlmostEqual(STEWART_MOTOR.no_load_deg_s_5v, 618.0)
        self.assertAlmostEqual(STEWART_MOTOR.no_load_deg_s_6v, 738.0)


class TestDemand(unittest.TestCase):
    def test_minjerk_pitch20_matches_joint_peaks(self):
        row = demand_row(IT.MIN_JERK, "pitch", 20.0, 1.0)
        self.assertAlmostEqual(row["peak_stewart_speed_deg_s"], 27.1, delta=0.2)
        self.assertEqual(row["ik_nan_samples"], 0)
        self.assertGreater(row["min_margin_to_urdf_limit_deg"], 25.0)

    def test_cartoon_needs_about_three_times_the_speed(self):
        mj = demand_row(IT.MIN_JERK, "pitch", 20.0, 0.5)["peak_stewart_speed_deg_s"]
        ct = demand_row(IT.CARTOON, "pitch", 20.0, 0.5)["peak_stewart_speed_deg_s"]
        self.assertGreater(ct / mj, 2.5)

    def test_cartoon_overshoot_eats_limit_margin(self):
        mj = demand_row(IT.MIN_JERK, "pitch", 40.0, 1.0)["min_margin_to_urdf_limit_deg"]
        ct = demand_row(IT.CARTOON, "pitch", 40.0, 1.0)["min_margin_to_urdf_limit_deg"]
        self.assertLess(ct, mj)


if __name__ == "__main__":
    unittest.main()
