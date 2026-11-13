"""Phase 4 stop / hold (executor ``StopPolicy``) verified on the Mock backend with a virtual clock (data_kind mock).

S1 = cancel -> slow down along the checked path, then hold; S2 = failed / slow send or lost measurement -> stop
sending at once, the (modelled) daemon holds the last target. Without a StopPolicy the Phase 2 behaviour stands.
"""

from __future__ import annotations

import math
import threading
import unittest

import numpy as np

from reachy_motion.backends.mock import MockBackend
from reachy_motion.executor.clock import VirtualClock
from reachy_motion.executor.executor import Executor, StopPolicy, _interp_sample
from reachy_motion.library.pose import Pose6, pose_from_matrix
from reachy_motion.library.spec import Easing, HeadKey, MotionSpec, Principle, PrincipleUse
from reachy_motion.safety.checker import prepare

DEG = math.pi / 180.0
MS = 1_000_000


def nod(amplitude_deg: float = 20.0, one_way_s: float = 0.6) -> MotionSpec:
    return MotionSpec(name="success", variant="expressive", intent="stop test", valence=0.0, arousal=0.0,
                      principles=(PrincipleUse(Principle.TIMING, "test"),),
                      head=(HeadKey(one_way_s, Pose6.from_deg_mm(pitch_deg=amplitude_deg), Easing.MIN_JERK, 0.0, "out"),
                            HeadKey(one_way_s, Pose6(), Easing.MIN_JERK, 0.0, "back")), draft=False)


def pitch_of(head: np.ndarray) -> float:
    return pose_from_matrix(head).pitch


class StopCase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = VirtualClock()
        self.mock = MockBackend(clock=self.clock, structure="robot", lag_tau_s=0.05)
        self.mock.connect()
        self.ex = Executor(self.mock, clock=self.clock)
        self.prep = prepare(nod())
        self.assertTrue(self.prep.runnable)
        self.tl = self.prep.timeline

    def tearDown(self) -> None:
        self.mock.close()

    def run_with(self, at_k: int, action, stop: StopPolicy | None = StopPolicy(), cancel=None):
        def on_tick(k, rec):
            if k == at_k:
                action()
        return self.ex.run(self.prep, cancel=cancel, on_tick=on_tick, stop=stop)

    def assert_holds_last_command(self, result) -> None:
        """Nothing else reaches the model, and one second later it still targets the last command."""
        self.assertEqual(self.mock.motor_command_count, len(result.commands))
        self.clock.advance(1000 * MS)
        target = self.mock.current_target().head.matrix()
        self.assertAlmostEqual(pitch_of(target), pitch_of(result.commands[-1].record.head), delta=1e-9)
        self.assertEqual(self.mock.motor_command_count, len(result.commands))


class TestS1ControlledStop(StopCase):
    def test_cancel_slows_down_along_the_path_then_holds(self):
        cancel = threading.Event()
        result = self.run_with(15, cancel.set, cancel=cancel)  # t = 0.30 s: the fastest instant of the 0.6 s move
        self.assertTrue(result.cancelled)
        self.assertFalse(result.completed)
        self.assertEqual(result.stop_kind, "S1")
        self.assertEqual(result.stop_commands, 15)  # 0.3 s at 50 Hz
        pitches = [pitch_of(c.record.head) for c in result.commands]
        normal, slow = pitches[:16], pitches[15:]  # sample 15 is the last planned one
        self.assertEqual([c.k for c in result.commands[:16]], list(range(16)))
        steps = np.diff(slow)
        planned_step = normal[15] - normal[14]
        self.assertGreater(planned_step, 1.0 * DEG)  # about 1.25 deg per tick at the peak
        self.assertTrue(np.all(steps >= -1e-12), "the head keeps going the same way (no reversal)")
        self.assertTrue(np.all(np.diff(steps) <= 1e-12), "each step is smaller than the one before")
        self.assertLessEqual(steps[0], planned_step + 1e-12)
        self.assertLess(steps[-1], 0.01 * DEG)  # ends at (almost) zero commanded speed
        u_end = float(self.tl.t[15]) + 0.15  # planned time advances by half the stop time
        expected = pitch_of(_interp_sample(self.tl, u_end)[0])
        self.assertAlmostEqual(pitches[-1], expected, delta=1e-9)  # the stop point lies ON the checked path
        self.assertLess(pitches[-1], max(pitch_of(h) for h in self.tl.head) + 1e-12)
        self.assert_holds_last_command(result)

    def test_without_a_stop_policy_cancel_stops_at_once(self):
        cancel = threading.Event()
        result = self.run_with(15, cancel.set, stop=None, cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertIsNone(result.stop_kind)
        self.assertEqual(len(result.commands), 16)  # Phase 2 behaviour: no further command
        self.assert_holds_last_command(result)

    def test_zero_stop_time_means_immediate(self):
        cancel = threading.Event()
        result = self.run_with(15, cancel.set, stop=StopPolicy(controlled_stop_s=0.0), cancel=cancel)
        self.assertEqual((result.stop_kind, len(result.commands)), ("S2", 16))

    def test_cancel_before_the_first_send(self):
        cancel = threading.Event()
        cancel.set()
        result = self.ex.run(self.prep, cancel=cancel, stop=StopPolicy())
        self.assertEqual((result.stop_kind, result.stop_commands, len(result.commands)), ("S1", 0, 0))
        self.assertEqual(self.mock.motor_command_count, 0)


class TestS2ImmediateStop(StopCase):
    def test_send_failure(self):
        result = self.run_with(10, lambda: setattr(self.mock, "fail_send", True))
        self.assertEqual(result.stop_kind, "S2")
        self.assertIn("set_target raised", result.stop_reason)
        self.assertEqual((len(result.commands), result.failed_command.k), (11, 11))
        self.assertEqual(result.stop_commands, 0)
        self.mock.fail_send = False
        self.assert_holds_last_command(result)

    def test_slow_send(self):
        result = self.run_with(10, lambda: setattr(self.mock, "send_delay_s", 0.15))
        self.assertEqual(result.stop_kind, "S2")
        self.assertIn("set_target took 150 ms", result.stop_reason)
        self.assertEqual(len(result.commands), 12)  # the slow one got through, nothing after it
        self.mock.send_delay_s = 0.0
        self.assert_holds_last_command(result)

    def test_failed_measurement(self):
        result = self.run_with(10, lambda: setattr(self.mock, "fail_present", True))
        self.assertEqual(result.stop_kind, "S2")
        self.assertIn("measurement lost", result.stop_reason)
        n = len(result.commands)
        self.assertTrue(20 <= n <= 22, n)  # 0.2 s = 10 ticks after the last fresh state (k = 10)
        self.assertTrue(any("present()" in w for w in result.warnings))
        self.mock.fail_present = False
        self.assert_holds_last_command(result)

    def test_stalled_measurement(self):
        result = self.run_with(10, lambda: setattr(self.mock, "freeze_present", True))
        self.assertEqual(result.stop_kind, "S2")
        self.assertIn("measurement lost", result.stop_reason)
        self.assertTrue(20 <= len(result.commands) <= 22, len(result.commands))
        self.mock.freeze_present = False
        self.assert_holds_last_command(result)

    def test_without_a_stop_policy_measurement_faults_do_not_stop(self):
        result = self.run_with(10, lambda: setattr(self.mock, "fail_present", True), stop=None)
        self.assertTrue(result.completed)
        self.assertIsNone(result.stop_kind)

    def test_a_normal_run_is_not_stopped(self):
        result = self.ex.run(self.prep, stop=StopPolicy(), record_present=True)
        self.assertTrue(result.completed)
        self.assertIsNone(result.stop_kind)
        self.assertEqual(len(result.present), len(self.tl))


def speed_dps(mock: MockBackend, clock: VirtualClock, dt_s: float = 0.01) -> float:
    """Measured (modelled) head pitch speed now: two readings ``dt_s`` apart (advances the clock)."""
    a = pitch_of(mock.present().head)
    clock.advance(int(dt_s * 1e9))
    return abs(pitch_of(mock.present().head) - a) / dt_s / DEG


class TestMeasuredAfterTheStop(StopCase):
    """What the (modelled) head does after S1 / S2: the measured speed and the gap to the last target."""

    def test_s1_measured_speed_goes_to_zero(self):
        cancel = threading.Event()
        self.run_with(15, cancel.set, cancel=cancel)
        at_end = speed_dps(self.mock, self.clock)
        self.clock.advance(290 * MS)
        later = speed_dps(self.mock, self.clock)
        # the same cancel without a StopPolicy: the commands stop at full speed
        clock = VirtualClock()
        mock = MockBackend(clock=clock, structure="robot", lag_tau_s=0.05)
        mock.connect()
        self.addCleanup(mock.close)
        ev = threading.Event()
        Executor(mock, clock=clock).run(self.prep, cancel=ev, on_tick=lambda k, r: ev.set() if k == 15 else None)
        immediate = speed_dps(mock, clock)
        self.assertGreater(immediate, 30.0)  # still moving fast when the commands stop
        self.assertLess(at_end, 0.2 * immediate)
        self.assertLess(later, 0.1)  # deg/s, 0.3 s after the end of the slow-down

    def test_s2_gap_between_the_last_target_and_the_measured_joints(self):
        from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics

        result = self.run_with(15, lambda: setattr(self.mock, "fail_send", True))
        self.mock.fail_send = False
        target = np.asarray(ik_joints(new_kinematics(), np.asarray(result.commands[-1].record.head), 0.0))
        gaps = []
        for advance_ms in (0, 500, 500):
            self.clock.advance(advance_ms * MS)
            q = np.asarray(self.mock.present().joints)
            gaps.append(float(np.max(np.abs(q - target))) / DEG)
        self.assertGreater(gaps[0], 0.5)  # at the stop the (lagging) head is behind the held target
        self.assertLess(gaps[1], 0.05)  # 0.5 s later it has reached it ...
        self.assertLess(gaps[2], 0.001)  # ... and holds it


class TestS3DaemonError(StopCase):
    def test_daemon_error_stops_and_separates_known_from_uncertain(self):
        msg = "No response from the robot's motor for the last second."
        result = self.run_with(10, lambda: setattr(self.mock, "daemon_error", msg))
        self.assertEqual(result.stop_kind, "S3")
        self.assertIn("state='error'", result.stop_reason)
        n = len(result.commands)
        self.assertTrue(11 <= n <= 22, n)  # the next health check (every 0.2 s) sees it
        d = result.stop_detail
        self.assertEqual(d["known"]["daemon_error"], msg)
        self.assertEqual(d["known"]["commands_sent"], n)
        self.assertTrue(any("torque" in u for u in d["uncertain"]))
        self.assertIn("switch the robot off", d["operator"])
        self.mock.daemon_error = None
        self.assert_holds_last_command(result)

    def test_health_checks_can_be_switched_off(self):
        self.mock.daemon_error = "boom"
        result = self.ex.run(self.prep, stop=StopPolicy(health_check_s=0.0))
        self.assertTrue(result.completed)
        self.assertIsNone(result.stop_kind)


class TestFaultInjector(StopCase):
    """The proxy used for the MuJoCo stop experiments (analysis.stop_sim): same faults, never on the robot."""

    def test_refuses_a_robot_backend(self):
        from types import SimpleNamespace

        from reachy_motion.backends.faults import FaultInjector

        robot = SimpleNamespace(name="robot", data_kind="measured",
                                capabilities=SimpleNamespace(real_hardware=True))
        with self.assertRaises(ValueError):
            FaultInjector(robot)

    def test_measurement_loss_through_the_proxy_marks_commands_unconfirmed(self):
        from reachy_motion.backends.faults import FaultInjector

        fi = FaultInjector(self.mock)
        result = Executor(fi, clock=self.clock).run(self.prep, stop=StopPolicy(),
                                                    on_tick=lambda k, r: setattr(fi, "freeze_present", True)
                                                    if k == 10 else None)
        self.assertEqual(result.stop_kind, "S2")
        self.assertFalse(result.end_state_known)
        known = result.stop_detail["known"]
        self.assertEqual(known["last_confirmed_k"], 10)
        self.assertEqual(known["unconfirmed_commands"], len(result.commands) - 11)


class TestPolicyValues(unittest.TestCase):
    def test_invalid_values(self):
        for kw in ({"controlled_stop_s": -0.1}, {"max_send_s": math.nan}, {"max_present_age_s": True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                StopPolicy(**kw)


if __name__ == "__main__":
    unittest.main()
