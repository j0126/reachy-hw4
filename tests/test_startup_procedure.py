"""Safe start-up procedure (reachy_motion.startup_procedure) on the Mock backend with a virtual clock (data_kind mock).

The MuJoCo check is the `sim-startup` command (results recorded in docs/VERIFICATION.md); nothing here can reach the
robot.
"""

from __future__ import annotations

import math
import threading
import unittest

import numpy as np
from reachy_mini.reachy_mini import SLEEP_ANTENNAS_JOINT_POSITIONS, SLEEP_HEAD_JOINT_POSITIONS, SLEEP_HEAD_POSE

from reachy_motion.backends.base import PresentState
from reachy_motion.backends.mock import MockBackend
from reachy_motion.executor.clock import VirtualClock
from reachy_motion.executor.executor import Executor
from reachy_motion.library.pose import REST, Pose6, RobotState, pose_from_matrix, rotation_distance
from reachy_motion.startup_procedure import SLOW_CAPS, check_start, run_startup

DEG = math.pi / 180.0
SLEEP_STATE = RobotState(head=pose_from_matrix(np.asarray(SLEEP_HEAD_POSE, dtype=float)),
                         antennas=(float(SLEEP_ANTENNAS_JOINT_POSITIONS[0]), float(SLEEP_ANTENNAS_JOINT_POSITIONS[1])),
                         body_yaw=0.0)


def beyond_limits_state() -> RobotState:
    """Where the SDK sleep JOINTS put the head (FK): its joints are 0.8-9.5 deg beyond the URDF limits."""
    from reachy_motion.analysis.goto_replay import new_kinematics

    m = new_kinematics().fk(np.array(SLEEP_HEAD_JOINT_POSITIONS, dtype=float), no_iterations=400)
    return RobotState(head=pose_from_matrix(m), antennas=SLEEP_STATE.antennas, body_yaw=0.0)


class StartupCase(unittest.TestCase):
    def make(self, start: RobotState, lag_s: float = 0.05) -> None:
        self.clock = VirtualClock()
        self.mock = MockBackend(clock=self.clock, structure="robot", lag_tau_s=lag_s, start=start)
        self.mock.connect()
        self.addCleanup(self.mock.close)
        self.ex = Executor(self.mock, clock=self.clock)


class TestStartupFromSleep(StartupCase):
    def test_slow_ramp_from_the_sdk_sleep_pose(self):
        self.make(SLEEP_STATE)
        report, result = run_startup(self.mock, self.ex)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.stage, "done")
        self.assertTrue(result.completed)
        self.assertIsNone(result.stop_kind)
        cmds = result.commands
        first = np.asarray(cmds[0].record.head)
        self.assertLess(rotation_distance(first, SLEEP_STATE.head.matrix()), 1e-9)  # starts exactly where it is
        self.assertLess(float(np.linalg.norm(first[:3, 3] - SLEEP_STATE.head.matrix()[:3, 3])), 1e-12)
        rot = [math.degrees(rotation_distance(np.asarray(a.record.head), np.asarray(b.record.head))) * 50.0
               for a, b in zip(cmds, cmds[1:])]
        ant = [max(abs(x - y) for x, y in zip(a.record.antennas, b.record.antennas)) / DEG * 50.0
               for a, b in zip(cmds, cmds[1:])]
        self.assertLessEqual(max(rot), SLOW_CAPS["max_rot_dps"] * 1.02)
        self.assertLessEqual(max(ant), SLOW_CAPS["max_antenna_dps"] * 1.02)
        self.assertGreaterEqual(report.ramp_duration_s, 2.0)
        self.assertLess(report.max_command_joint_step_deg, 0.5)
        self.assertLess(report.end_error["head_rotation_deg"], 0.05)
        self.assertLess(report.end_error["head_translation_mm"], 0.05)
        self.assertLess(report.end_error["antennas_deg"], 0.05)
        self.assertEqual(report.data_kind, "mock")


class TestRefusals(StartupCase):
    def test_start_joints_beyond_the_limits(self):
        self.make(beyond_limits_state())
        report, result = run_startup(self.mock, self.ex)
        self.assertEqual((report.ok, report.stage, result), (False, "check", None))
        self.assertTrue(any("beyond the URDF limits" in p for p in report.problems))
        self.assertEqual(self.mock.motor_command_count, 0)

    def test_pose_and_joints_that_disagree(self):
        p = PresentState(t_ns=0, head=REST.head.matrix(), antennas=REST.antennas, body_yaw=0.0,
                         joints=np.array(SLEEP_HEAD_JOINT_POSITIONS, dtype=float))
        chk = check_start(p)
        self.assertFalse(chk.ok)
        self.assertTrue(any("disagree" in m for m in chk.problems))
        self.assertGreater(chk.ik_gap_deg, 1.0)

    def test_no_joint_reading(self):
        chk = check_start(PresentState(t_ns=0, head=REST.head.matrix(), antennas=REST.antennas, body_yaw=0.0))
        self.assertFalse(chk.ok)
        self.assertIn("no joint reading", chk.problems[0])

    def test_a_moving_head_is_not_started(self):
        self.make(REST, lag_s=0.3)
        self.mock.set_target(Pose6.from_deg_mm(pitch_deg=10).matrix(), REST.antennas, 0.0)  # still travelling
        report, result = run_startup(self.mock, self.ex)
        self.assertEqual((report.ok, report.stage, result), (False, "still", None))
        self.assertGreater(report.still_max_drift_deg, 0.5)
        self.assertEqual(self.mock.motor_command_count, 1)  # only the test's own command


class TestStopsDuringTheRamp(StartupCase):
    def test_cancel_is_a_controlled_stop(self):
        self.make(SLEEP_STATE)
        cancel = threading.Event()
        report, result = run_startup(self.mock, self.ex, cancel=cancel,
                                     on_tick=lambda k, rec: cancel.set() if k == 100 else None)
        self.assertEqual((report.ok, report.stage), (False, "run"))
        self.assertEqual(result.stop_kind, "S1")
        self.assertEqual(result.stop_commands, 15)
        self.assertEqual(self.mock.motor_command_count, len(result.commands))

    def test_lost_measurement_is_an_immediate_stop(self):
        self.make(SLEEP_STATE)
        report, result = run_startup(self.mock, self.ex,
                                     on_tick=lambda k, rec: setattr(self.mock, "freeze_present", True) if k == 50
                                     else None)
        self.assertEqual((report.ok, report.stage), (False, "run"))
        self.assertEqual(result.stop_kind, "S2")
        self.assertIn("measurement lost", report.problems[0])


if __name__ == "__main__":
    unittest.main()
