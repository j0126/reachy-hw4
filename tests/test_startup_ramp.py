"""The sleep-pose start-up exception must not let a dangerous ramp through (computed, no daemon)."""

import math
import unittest

import numpy as np

from reachy_motion.analysis.goto_replay import new_kinematics
from reachy_motion.library.pose import REST, SLEEP_ANTENNAS, SLEEP_HEAD_MATRIX, Pose6, RobotState, pose_from_matrix
from reachy_motion.safety.checker import analyze_timeline
from reachy_motion.safety.startup import prepare_startup_ramp, startup_policy, stewart_floor_violation


def _joint_sleep() -> RobotState:
    """The pose the daemon really commands for sleep: FK of SLEEP_HEAD_JOINT_POSITIONS (reachy_mini.py:56-64).

    It puts stewart_1/2/5/6 0.8-9.5 deg BEYOND the URDF limits (z -50.4 mm; MuJoCo measured -50.3 mm)."""
    from reachy_mini.reachy_mini import SLEEP_HEAD_JOINT_POSITIONS

    kin = new_kinematics()
    for _ in range(50):  # FK is an iterative solver: settle it
        m = kin.fk(np.array(SLEEP_HEAD_JOINT_POSITIONS))
    return RobotState(head=pose_from_matrix(m), antennas=SLEEP_ANTENNAS, body_yaw=0.0)


SLEEP_CONST = RobotState(head=pose_from_matrix(SLEEP_HEAD_MATRIX), antennas=SLEEP_ANTENNAS, body_yaw=0.0)
SLEEP = _joint_sleep()


def codes(prep) -> set[str]:
    return {v.code for v in prep.report.violations}


class TestStartupRamp(unittest.TestCase):
    def test_sleep_to_rest_passes_and_only_moves_away_from_limits(self):
        prep = prepare_startup_ramp(SLEEP)
        self.assertTrue(prep.runnable, codes(prep))
        self.assertTrue(prep.report.policy.name.endswith("+startup"))
        m = np.asarray(analyze_timeline(prep.timeline).stewart_margin)
        self.assertTrue(np.all(m.min(axis=0) >= np.minimum(10.0, m[0]) - 0.25))
        self.assertTrue(np.allclose(prep.timeline.head[-1], np.eye(4), atol=1e-12))

    def test_target_near_a_limit_is_refused(self):
        # roll/pitch corner +-30 deg: < 10 deg margin (Phase 1 6.3). From the joint-space sleep pose the old rule (one
        # global floor = the smallest start margin - 0.25 = -9.25 deg) let this ramp through.
        corner = RobotState(head=Pose6.from_deg_mm(roll_deg=30, pitch_deg=-30))
        prep = prepare_startup_ramp(SLEEP, corner)
        self.assertFalse(prep.runnable)
        self.assertTrue(codes(prep) & {"startup_margin", "startup_end", "stewart_margin"}, codes(prep))

    def test_joint_sleep_start_is_beyond_the_urdf_limits(self):
        m0 = np.asarray(analyze_timeline(prepare_startup_ramp(SLEEP).timeline).stewart_margin)[0]
        self.assertLess(m0.min(), -5.0)  # documents the finding the rule has to cope with
        self.assertTrue(prepare_startup_ramp(SLEEP_CONST).runnable)

    def test_each_joint_keeps_its_own_floor(self):
        t = np.linspace(0.0, 1.0, 5)
        margin = np.array([[-8.0, 40.0, 35.0, 36.0, -1.0, -9.0],
                           [-6.0, 30.0, 35.0, 36.0, 0.0, -7.0],
                           [-3.0, 5.0, 35.0, 36.0, 2.0, -4.0],  # stewart_2 drops to 5 deg: refused
                           [0.0, 20.0, 35.0, 36.0, 5.0, 0.0],
                           [12.0, 30.0, 35.0, 36.0, 12.0, 12.0]])
        v = stewart_floor_violation(margin, t, 10.0)
        self.assertIsNotNone(v)
        self.assertIn("stewart_2", v.message)
        # the old rule (one floor = smallest start margin - 0.25 = -9.25 deg for every joint) accepted this
        self.assertTrue(np.all(margin >= margin[0].min() - 0.25))
        improving = margin.copy()
        improving[2, 1] = 15.0
        self.assertIsNone(stewart_floor_violation(improving, t, 10.0))
        self.assertIsNotNone(stewart_floor_violation(np.where(improving > 30, np.nan, improving), t, 10.0))

    def test_speed_is_not_relaxed(self):
        prep = prepare_startup_ramp(SLEEP, duration=0.15)
        self.assertFalse(prep.runnable)
        self.assertIn("stewart_speed", codes(prep))

    def test_envelope_widens_only_to_the_start(self):
        pol = startup_policy(SLEEP)
        z0 = SLEEP.head.to_deg_mm()["z_mm"]
        self.assertAlmostEqual(pol.z_range_mm[0], z0 - 1.0)
        self.assertEqual(pol.z_range_mm[1], 24.0)
        self.assertEqual(pol.x_range_mm[1], 25.0)
        deeper = RobotState(head=Pose6.from_deg_mm(pitch_deg=10, z_mm=z0 - 5.0))  # below the start z
        prep = prepare_startup_ramp(SLEEP, deeper)
        self.assertFalse(prep.runnable)
        self.assertTrue(codes(prep) & {"envelope_z", "startup_end"}, codes(prep))

    def test_no_relaxation_when_starting_inside_the_envelope(self):
        pol = startup_policy(REST)
        self.assertEqual((pol.x_range_mm, pol.z_range_mm, pol.max_pitch_deg), ((-15.0, 25.0), (-40.0, 24.0), 40.0))
        prep = prepare_startup_ramp(REST, RobotState(head=Pose6.from_deg_mm(x_mm=-20.0)))
        self.assertFalse(prep.runnable)

    def test_ik_failure_and_antennas_are_checked(self):
        self.assertIn("ik_nan", codes(prepare_startup_ramp(SLEEP, RobotState(head=Pose6.from_deg_mm(z_mm=30.0)))))
        wider = RobotState(head=Pose6(), antennas=(-3.12, 3.12))  # past the sleep angle
        prep = prepare_startup_ramp(SLEEP, wider)
        self.assertFalse(prep.runnable)
        self.assertTrue(codes(prep) & {"antenna_range", "startup_end"}, codes(prep))

    def test_report_is_bound_to_the_ramp(self):
        prep = prepare_startup_ramp(SLEEP)
        self.assertEqual(prep.report.timeline_digest, prep.timeline.digest())
        self.assertTrue(math.isfinite(prep.report.metrics["min_stewart_margin_deg"]))


if __name__ == "__main__":
    unittest.main()
