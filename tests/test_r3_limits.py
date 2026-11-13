"""R3 stop criteria (``robot_r1.R3_LIMITS``) against the measured robot baseline, and the robot's R3 range.

Baseline (measured 2026-11-12, pitch 20 deg, D 1.0 s): amplitude ratio 0.92-1.03, lag 184-188 ms (r2 0.96-0.97),
lag-compensated RMSE 1.39-1.65 deg, overshoot ~0 deg, peak error 8.6-8.8 deg. Revised 2026-11-13 (user decision): a
constant delay is not a breakdown - the former absolute peak error 10 deg / lag 200 ms limits refused D 0.4 s on the
delay alone. No network, no robot: the metrics are plain stand-ins.
"""

import math
import unittest
from types import SimpleNamespace

from reachy_motion import robot_r1
from reachy_motion.gui import experiments as ex

K = 180.0 / math.pi  # rad -> deg (the pitch channel's report unit)
BASE_LAG_S = 0.188


def metrics(**kw: float) -> SimpleNamespace:
    """The main-channel metrics of a D 1.0 s step as measured on 2026-11-12 (SI), overridden by ``kw``."""
    m = dict(amplitude_ratio=1.03, command_p2p=math.radians(20.0), dynamic_rmse_lag_compensated=math.radians(1.39),
             overshoot=math.radians(0.04), lag_s=BASE_LAG_S, lag_fit_r2=0.97, peak_error=math.radians(8.84))
    m.update(kw)
    return SimpleNamespace(**m)


class TestR3Limits(unittest.TestCase):
    def test_the_baseline_and_a_constant_delay_do_not_end_the_ladder(self):
        self.assertEqual(robot_r1.r3_metric_problems(metrics(), K, BASE_LAG_S), [])
        # D 0.6 s: the same ~0.19 s delay at 62.5 deg/s gives a peak error of ~12 deg (the old 10 deg limit refused it)
        self.assertEqual(robot_r1.r3_metric_problems(metrics(peak_error=math.radians(12.0)), K, BASE_LAG_S), [])
        self.assertEqual(robot_r1.r3_metric_problems(metrics(lag_s=0.25), K, BASE_LAG_S), [])  # +62 ms: not yet

    def test_a_breakdown_ends_the_ladder(self):
        cases = {"amplitude ratio": metrics(amplitude_ratio=0.7),
                 "lag-compensated RMSE": metrics(dynamic_rmse_lag_compensated=math.radians(3.5)),  # 17.5 % of 20 deg
                 "overshoot": metrics(overshoot=math.radians(3.5)),
                 "lag 300 ms": metrics(lag_s=0.30)}  # > 188 + 100 ms
        for word, m in cases.items():
            probs = robot_r1.r3_metric_problems(m, K, BASE_LAG_S)
            self.assertEqual(len(probs), 1, (word, probs))
            self.assertIn(word.split()[0], probs[0])

    def test_korean_messages_for_the_gui_with_one_decimal(self):
        m = metrics(dynamic_rmse_lag_compensated=math.radians(3.06))  # 15.3 % of 20 deg: not "15 % > 15 %"
        en = robot_r1.r3_metric_problems(m, K, BASE_LAG_S)
        ko = robot_r1.r3_metric_problems(m, K, BASE_LAG_S, lang="ko")
        self.assertIn("15.3%", en[0])
        self.assertIn("15.3%", ko[0])
        self.assertIn("무너짐", ko[0])
        probs = robot_r1.r3_step_problems(robot_r1.r3_plan(20, 0.15, 1, None, awake=True), None, robot=True, lang="ko")
        self.assertTrue(any("실제 로봇 범위 밖" in p for p in probs), probs)
        self.assertTrue(any("앞 단계가 먼저" in p for p in probs), probs)

    def test_lag_rules(self):
        self.assertEqual(robot_r1.r3_metric_problems(metrics(lag_s=0.30, lag_fit_r2=0.5), K, BASE_LAG_S), [])  # unreliable
        self.assertTrue(robot_r1.r3_metric_problems(metrics(lag_s=0.31), K, None))  # no D 1.0 s run known: 300 ms bound
        self.assertEqual(robot_r1.r3_metric_problems(metrics(lag_s=0.29), K, None), [])
        self.assertEqual(robot_r1.r3_metric_problems(metrics(overshoot=float("nan")), K, BASE_LAG_S), [])  # not judged

    def test_the_robot_ladder_reaches_0_2_s_one_step_at_a_time(self):
        self.assertEqual(ex.R3_DEFAULT_DURATIONS, (1.0, 0.6, 0.4, 0.3, 0.25, 0.2))
        self.assertEqual(ex.REAL_MIN_DURATION_S, 0.2)
        # inside what the robot already ran with aha_recommend expressive (computed: speed ratio 0.386, 2941 deg/s^2)
        aha = ex.check_trial(ex.r2_trial(_aha()))
        for d in (0.25, 0.2):
            c = ex.check_trial(ex.r3_trial(20.0, d))
            self.assertTrue(c.runnable)
            self.assertLess(c.metrics["peak_stewart_speed_ratio"], aha.metrics["peak_stewart_speed_ratio"])
            self.assertLess(c.metrics["peak_joint_accel_dps2"], aha.metrics["peak_joint_accel_dps2"])
        fast = ex.check_trial(ex.r3_trial(20.0, 0.15))
        self.assertGreater(fast.metrics["peak_joint_accel_dps2"], aha.metrics["peak_joint_accel_dps2"])  # MuJoCo only
        for d, scope in ((0.2, False), (0.15, True)):
            probs = robot_r1.r3_step_problems(robot_r1.r3_plan(20, d, 1, None, awake=True), None, robot=True)
            self.assertEqual(any("outside the real-robot scope" in p for p in probs), scope, (d, probs))
            self.assertTrue(any("--after" in p for p in probs))  # and never without the previous step


def _aha():
    from pathlib import Path

    from reachy_motion.library.registry import default_library

    return default_library(Path(__file__).resolve().parents[1] / "motions").get("aha_recommend", "expressive")


if __name__ == "__main__":
    unittest.main()
