"""MockBackend (no daemon, no robot): exact tick arithmetic on a virtual clock, SDK goto replay, lag, faults, threads."""

from __future__ import annotations

import math
import threading
import time
import unittest
from collections.abc import Callable
from typing import Any

import numpy as np
from reachy_mini.motion.goto import GotoMove
from reachy_mini.utils.interpolation import InterpolationTechnique

from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics
from reachy_motion.backends.base import Backend, BackendError, PresentState
from reachy_motion.backends.mock import DEFAULT_MAX_RECORDS, GOTO_METHODS, MockBackend
from reachy_motion.executor.clock import RealClock, VirtualClock
from reachy_motion.library.pose import INIT_ANTENNAS, REST, Pose6, RobotState, pose_from_matrix
from reachy_motion.library.spec import Easing

MS = 1_000_000
TICK = 20 * MS  # 50 Hz control tick
EVAL = 10 * MS  # 100 Hz play_move grid
T0 = 1_000 * MS  # connect time used by most tests (any value works)

POSE_A = Pose6(z=0.005, roll=0.05, pitch=0.2, yaw=0.3)
STATE_A = RobotState(head=POSE_A, antennas=(0.6, -0.4), body_yaw=0.25)
POSE_B = Pose6(x=0.004, pitch=-0.15, yaw=-0.2)
STATE_B = RobotState(head=POSE_B, antennas=(-0.3, 0.9), body_yaw=-0.1)
STATE_C = RobotState(head=Pose6(roll=-0.1, pitch=0.1), antennas=(0.2, 0.2), body_yaw=0.05)


def connected(structure: str = "robot", tau: float = 0.0, **kwargs: Any) -> tuple[MockBackend, VirtualClock]:
    clock = VirtualClock(T0)
    backend = MockBackend(clock, structure=structure, lag_tau_s=tau, **kwargs)
    backend.connect()
    return backend, clock


def send(backend: MockBackend, state: RobotState) -> None:
    backend.set_target(state.head.matrix(), state.antennas, state.body_yaw)


def move_to(clock: VirtualClock, t_ns: int) -> None:
    clock.advance(t_ns - clock.now_ns())


def call_into(errors: list[BaseException], fn: Callable[..., Any], *args: Any) -> None:
    try:
        fn(*args)
    except BaseException as exc:  # collected and asserted by the test thread
        errors.append(exc)


def wait_until(predicate: Callable[[], bool], timeout_s: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return predicate()


#: Finite heads (check_command accepts them) whose rotation block the SDK's Rotation.from_matrix rejects (det <= 0).
IMPROPER_HEADS = {"reflection": np.diag([1.0, 1.0, -1.0, 1.0]), "null rotation": np.diag([0.0, 0.0, 0.0, 1.0])}


class UnevaluableSegment:
    """White box: a model segment whose target cannot be evaluated (stands in for any model failure)."""

    def __init__(self, t_ns: int) -> None:
        self.t_ns = t_ns

    def at(self, t_ns: int) -> np.ndarray:
        raise ValueError("unevaluable segment")

    def next_change_after(self, t_ns: int) -> float:
        return math.inf


def break_model(backend: MockBackend, t_ns: int) -> None:
    """White box: from ``t_ns`` on, the model cannot be evaluated."""
    backend._segments.append(UnevaluableSegment(t_ns))
    backend._starts.append(t_ns)


def sdk_goto(start: RobotState, goal: RobotState, duration: float, method: str) -> GotoMove:
    """Independent reference: the SDK's GotoMove as Backend.goto_target builds it (abstract.py:966-977)."""
    return GotoMove(start_head_pose=start.head.matrix(), target_head_pose=goal.head.matrix(),
                    start_antennas=np.array(start.antennas), target_antennas=np.array(goal.antennas),
                    start_body_yaw=start.body_yaw, target_body_yaw=goal.body_yaw, duration=duration,
                    method=InterpolationTechnique(method))


class SteppedClock:
    """Test clock: time moves only when the test calls ``set``; ``sleep_until`` blocks until then."""

    def __init__(self, start_ns: int) -> None:
        self._now = start_ns
        self._cv = threading.Condition()
        self.sleeping_until: int | None = None

    def now_ns(self) -> int:
        with self._cv:
            return self._now

    def sleep_until(self, t_ns: int) -> None:
        with self._cv:
            self.sleeping_until = t_ns
            self._cv.notify_all()
            if not self._cv.wait_for(lambda: self._now >= t_ns, timeout=10.0):
                raise TimeoutError("SteppedClock: nobody moved the time")
            self.sleeping_until = None

    def set(self, t_ns: int) -> None:
        with self._cv:
            self._now = max(self._now, t_ns)
            self._cv.notify_all()

    def wait_for_sleeper(self, timeout_s: float = 5.0) -> int | None:
        with self._cv:
            self._cv.wait_for(lambda: self.sleeping_until is not None, timeout=timeout_s)
            return self.sleeping_until


class MockTestCase(unittest.TestCase):
    def assertHead(self, ps: PresentState, pose: Pose6, atol: float = 1e-12) -> None:
        np.testing.assert_allclose(ps.head, pose.matrix(), rtol=0, atol=atol)

    def assertState(self, ps: PresentState, state: RobotState, atol: float = 1e-12) -> None:
        self.assertHead(ps, state.head, atol)
        np.testing.assert_allclose(ps.antennas, state.antennas, rtol=0, atol=atol)
        self.assertAlmostEqual(ps.body_yaw, state.body_yaw, delta=atol)


class TestConnectionAndLabels(MockTestCase):
    def test_is_a_backend_labelled_mock_without_hardware(self):
        b = MockBackend(VirtualClock())
        self.assertIsInstance(b, Backend)
        self.assertEqual((b.name, b.data_kind), ("mock", "mock"))
        self.assertFalse(b.capabilities.real_hardware)
        self.assertFalse(b.capabilities.torque_control)
        self.assertEqual(b.max_records, DEFAULT_MAX_RECORDS)

    def test_everything_refused_before_connect_and_after_close(self):
        b = MockBackend(VirtualClock(T0))
        for _ in range(2):
            with self.assertRaises(BackendError):
                send(b, STATE_A)
            with self.assertRaises(BackendError):
                b.goto_target(POSE_A.matrix(), STATE_A.antennas, 0.0, 0.5, "minjerk")
            with self.assertRaises(BackendError):
                b.present()
            with self.assertRaises(BackendError):
                b.log_sound_cue("aha.wav")
            b.connect()
            b.close()
        self.assertEqual((b.commands, b.motor_command_count, b.sound_cues), ([], 0, []))

    def test_connect_and_close_are_idempotent(self):
        b, clock = connected()
        clock.advance(5 * MS)
        b.connect()  # already connected: the tick grid stays where it was
        self.assertEqual(b.connect_time_ns, T0)
        self.assertEqual(b.tick_time_ns(3), T0 + 3 * TICK)
        b.close()
        b.close()
        self.assertFalse(b.connected)

    def test_reconnect_starts_from_the_pose_left_at_close(self):
        b, clock = connected("mujoco")
        send(b, STATE_A)
        move_to(clock, T0 + 2 * TICK)
        b.close()
        clock.advance(7 * MS)
        b.connect()
        self.assertEqual(b.connect_time_ns, T0 + 2 * TICK + 7 * MS)
        self.assertState(b.present(), STATE_A)

    def test_constructor_validation(self):
        with self.assertRaises(ValueError):
            MockBackend(VirtualClock(), structure="hardware")
        for bad in (0, -50.0, math.inf, math.nan, True):
            with self.assertRaises(ValueError):
                MockBackend(VirtualClock(), control_rate_hz=bad)
        for bad in (-0.1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                MockBackend(VirtualClock(), lag_tau_s=bad)
        with self.assertRaises(ValueError):
            MockBackend(VirtualClock(), max_records=0)
        with self.assertRaises(TypeError):
            MockBackend(VirtualClock(), start=REST.head)  # type: ignore[arg-type]

    def test_start_state_and_default_real_clock(self):
        b = MockBackend(start=STATE_B)
        b.connect()
        ps = b.present()
        self.assertState(ps, STATE_B)
        self.assertLess(abs(ps.t_ns - time.perf_counter_ns()), 1_000 * MS)  # RealClock: perf_counter_ns domain
        b.close()


class TestCommandLog(MockTestCase):
    def test_commands_are_recorded_exactly_as_handed_over(self):
        b, clock = connected("mujoco")
        clock.advance(3 * MS)
        head = POSE_A.matrix()
        b.set_target(head, [0.6, -0.4], 0.25)
        head[0, 3] = 9.0  # the caller's array is not aliased by the log
        clock.advance(17 * MS)
        b.goto_target(POSE_B.matrix(), STATE_B.antennas, STATE_B.body_yaw, 0.4, Easing.CARTOON)
        recs = b.commands
        self.assertEqual([r.kind for r in recs], ["set_target", "goto_target"])
        self.assertEqual([r.t_ns for r in recs], [T0 + 3 * MS, T0 + 20 * MS])
        np.testing.assert_array_equal(recs[0].head, POSE_A.matrix())
        self.assertEqual(recs[0].antennas, (0.6, -0.4))
        self.assertIsInstance(recs[0].antennas[0], float)
        self.assertEqual((recs[0].body_yaw, recs[0].duration, recs[0].method), (0.25, None, None))
        np.testing.assert_array_equal(recs[1].head, POSE_B.matrix())
        self.assertEqual((recs[1].antennas, recs[1].body_yaw), (STATE_B.antennas, STATE_B.body_yaw))
        self.assertEqual((recs[1].duration, recs[1].method), (0.4, "cartoon"))
        self.assertEqual(b.motor_command_count, 2)

    def test_body_yaw_must_be_explicit(self):
        b, _ = connected()
        with self.assertRaises(BackendError):
            b.set_target(POSE_A.matrix(), STATE_A.antennas, None)  # type: ignore[arg-type]
        with self.assertRaises(BackendError):
            b.goto_target(POSE_A.matrix(), STATE_A.antennas, None, 0.5, "minjerk")  # type: ignore[arg-type]
        self.assertEqual((b.commands, b.motor_command_count), ([], 0))

    def test_invalid_commands_are_refused_and_not_logged(self):
        b, _ = connected()
        bad_head = POSE_A.matrix()
        bad_head[1, 1] = math.nan
        cases = [
            lambda: b.set_target(np.eye(3), STATE_A.antennas, 0.0),
            lambda: b.set_target(bad_head, STATE_A.antennas, 0.0),
            lambda: b.set_target(np.eye(4), (0.1,), 0.0),
            lambda: b.set_target(np.eye(4), STATE_A.antennas, math.inf),
            lambda: b.goto_target(np.eye(4), STATE_A.antennas, 0.0, 0.5, "bogus"),
            lambda: b.goto_target(np.eye(4), STATE_A.antennas, 0.0, 0.5, None),
            lambda: b.goto_target(np.eye(4), STATE_A.antennas, 0.0, 0.0, "linear"),
            lambda: b.goto_target(np.eye(4), STATE_A.antennas, 0.0, -1.0, "linear"),
            lambda: b.goto_target(np.eye(4), STATE_A.antennas, 0.0, math.nan, "linear"),
        ]
        for case in cases:
            with self.assertRaises(BackendError):
                case()
        self.assertEqual((b.commands, b.motor_command_count), ([], 0))

    def test_every_sdk_method_is_accepted(self):
        b, _ = connected()
        for method in (*GOTO_METHODS, *Easing, *InterpolationTechnique):
            b.goto_target(POSE_A.matrix(), STATE_A.antennas, 0.0, 0.05, method)
        self.assertEqual(set(GOTO_METHODS), {"linear", "minjerk", "ease_in_out", "cartoon"})
        self.assertEqual(b.motor_command_count, 12)
        self.assertEqual({r.method for r in b.commands}, set(GOTO_METHODS))

    def test_log_is_bounded(self):
        b, clock = connected(max_records=5)
        for k in range(12):
            send(b, STATE_A if k % 2 else STATE_B)
            b.log_sound_cue(f"cue{k}.wav")
            clock.advance(TICK)
        self.assertEqual(len(b.commands), 5)
        self.assertEqual([r.t_ns for r in b.commands], [T0 + k * TICK for k in range(7, 12)])
        self.assertEqual([f for _, f in b.sound_cues], [f"cue{k}.wav" for k in range(7, 12)])
        self.assertEqual(b.dropped_record_count, 14)
        self.assertEqual(b.motor_command_count, 12)

    def test_sound_cues_are_metadata_only(self):
        b, clock = connected()
        clock.advance(7 * MS)
        b.log_sound_cue("aha.wav")
        self.assertEqual(b.sound_cues, [(T0 + 7 * MS, "aha.wav")])
        self.assertEqual((b.commands, b.motor_command_count), ([], 0))
        for bad in ("", "  ", None):
            with self.assertRaises(BackendError):
                b.log_sound_cue(bad)  # type: ignore[arg-type]


class TestTickStructure(MockTestCase):
    """lag_tau_s = 0: the present state is the written goal, so the write timing shows exactly."""

    def test_robot_antennas_lead_head_and_body_by_one_tick(self):
        b, clock = connected("robot")
        move_to(clock, T0 + 5 * TICK + 3 * MS)
        send(b, STATE_A)
        self.assertState(b.present(), REST)  # tick 5 came before the command
        move_to(clock, T0 + 6 * TICK - 1)
        self.assertState(b.present(), REST)
        move_to(clock, T0 + 6 * TICK)  # antennas: target known at tick 6; head and body: known at tick 5
        self.assertState(b.present(), RobotState(head=REST.head, antennas=STATE_A.antennas, body_yaw=0.0))
        move_to(clock, T0 + 7 * TICK - 1)
        self.assertState(b.present(), RobotState(head=REST.head, antennas=STATE_A.antennas, body_yaw=0.0))
        move_to(clock, T0 + 7 * TICK)
        self.assertState(b.present(), STATE_A)

    def test_mujoco_writes_every_channel_in_the_same_tick(self):
        b, clock = connected("mujoco")
        move_to(clock, T0 + 5 * TICK + 3 * MS)
        send(b, STATE_A)
        move_to(clock, T0 + 6 * TICK - 1)
        self.assertState(b.present(), REST)
        move_to(clock, T0 + 6 * TICK)
        self.assertState(b.present(), STATE_A)

    def test_a_command_at_a_tick_instant_is_seen_by_that_tick(self):
        for structure, head_tick in (("robot", 6), ("mujoco", 5)):
            with self.subTest(structure=structure):
                b, clock = connected(structure)
                move_to(clock, T0 + 5 * TICK)
                send(b, STATE_A)
                ps = b.present()
                np.testing.assert_allclose(ps.antennas, STATE_A.antennas, rtol=0, atol=1e-15)
                self.assertHead(ps, POSE_A if head_tick == 5 else REST.head)
                move_to(clock, T0 + head_tick * TICK)
                self.assertState(b.present(), STATE_A)

    def test_robot_head_replays_the_antenna_sequence_one_tick_later(self):
        """Latest value wins inside a tick (no queue): STATE_B is superseded before any tick sees it."""
        b, clock = connected("robot")

        def expect_at_tick(k: int, head_body: RobotState, ant: RobotState) -> None:
            move_to(clock, T0 + k * TICK)
            self.assertState(b.present(), RobotState(head=head_body.head, antennas=ant.antennas,
                                                     body_yaw=head_body.body_yaw))

        move_to(clock, T0 + 5 * TICK + 3 * MS)
        send(b, STATE_A)
        expect_at_tick(6, REST, STATE_A)
        move_to(clock, T0 + 6 * TICK + 3 * MS)
        send(b, STATE_B)
        move_to(clock, T0 + 6 * TICK + 15 * MS)
        send(b, STATE_C)
        expect_at_tick(7, STATE_A, STATE_C)
        expect_at_tick(8, STATE_C, STATE_C)

    def test_same_instant_commands_latest_wins_and_the_head_still_waits_a_tick(self):
        b, clock = connected("robot")
        for k in range(5_000):  # all at the connect instant T0; memory must not grow with them
            send(b, (STATE_B, STATE_C)[k % 2])
        send(b, STATE_A)
        self.assertLessEqual(len(b._segments), 2)  # white box: same-instant targets are replaced, not stacked
        self.assertState(b.present(), RobotState(head=REST.head, antennas=STATE_A.antennas, body_yaw=0.0))
        move_to(clock, T0 + TICK)
        self.assertState(b.present(), STATE_A)
        self.assertEqual(b.motor_command_count, 5_001)

    def test_present_reports_time_kind_and_sdk_ik_joints(self):
        b, clock = connected("mujoco")
        send(b, STATE_A)
        clock.advance(TICK + 4 * MS)
        ps = b.present()
        self.assertEqual((ps.t_ns, ps.data_kind), (T0 + TICK + 4 * MS, "mock"))
        self.assertEqual(ps.joints.shape, (7,))
        np.testing.assert_allclose(ps.joints, ik_joints(new_kinematics(), ps.head, ps.body_yaw), rtol=0, atol=1e-12)
        self.assertAlmostEqual(ps.joints[0], STATE_A.body_yaw, places=9)  # relative yaw 0.05 rad: no auto body yaw
        ps.joints[:] = 0.0  # callers get copies
        self.assertFalse(np.allclose(b.present().joints, 0.0))

    def test_tick_period_follows_the_control_rate(self):
        b, clock = connected("mujoco", control_rate_hz=100.0)
        self.assertEqual(b.tick_period_ns, 10 * MS)
        move_to(clock, T0 + 10 * MS + 1)
        send(b, STATE_A)
        move_to(clock, T0 + 20 * MS - 1)
        self.assertState(b.present(), REST)
        move_to(clock, T0 + 20 * MS)
        self.assertState(b.present(), STATE_A)


class TestFirstOrderLag(MockTestCase):
    def test_63_percent_after_tau(self):
        tau = 0.1
        b, clock = connected("mujoco", tau=tau)
        move_to(clock, T0 + 5 * TICK)
        send(b, STATE_A)
        start, goal = REST, STATE_A

        def expect(fraction: float) -> RobotState:
            head = start.head + (goal.head - start.head).scaled(fraction)
            ant = tuple(s + (g - s) * fraction for s, g in zip(start.antennas, goal.antennas))
            return RobotState(head=head, antennas=ant, body_yaw=start.body_yaw + (goal.body_yaw - start.body_yaw) * fraction)

        self.assertState(b.present(), start)  # continuous: the new goal has not acted yet
        for dt_ms in (7, 20, 100, 260):
            move_to(clock, T0 + 5 * TICK + dt_ms * MS)
            ps = b.present()
            self.assertState(ps, expect(1.0 - math.exp(-dt_ms / 1000.0 / tau)), atol=1e-12)
            if dt_ms == 100:  # t = tau: 63.2 % of the step on every channel
                self.assertAlmostEqual(pose_from_matrix(ps.head).pitch / POSE_A.pitch, 1.0 - math.exp(-1.0),
                                       places=12)
                self.assertAlmostEqual(ps.body_yaw / STATE_A.body_yaw, 1.0 - math.exp(-1.0), places=12)

    def test_tick_to_tick_update_is_the_exact_discretisation(self):
        tau = 0.05
        b, clock = connected("mujoco", tau=tau)
        alpha = 1.0 - math.exp(-0.02 / tau)
        rng = np.random.default_rng(4)
        x = 0.0  # pitch
        for k in range(40):
            move_to(clock, T0 + k * TICK)
            self.assertAlmostEqual(pose_from_matrix(b.present().head).pitch, x, delta=1e-12)
            goal = float(rng.uniform(-0.3, 0.3))
            b.set_target(Pose6(pitch=goal).matrix(), INIT_ANTENNAS, 0.0)
            self.assertAlmostEqual(pose_from_matrix(b.present().head).pitch, x, delta=1e-12)  # same instant
            move_to(clock, T0 + k * TICK + 7 * MS)  # between ticks: exact continuous response
            between = goal + (x - goal) * math.exp(-0.007 / tau)
            self.assertAlmostEqual(pose_from_matrix(b.present().head).pitch, between, delta=1e-12)
            x = x + alpha * (goal - x)

    def test_robot_lag_starts_one_tick_later_for_the_head(self):
        b, clock = connected("robot", tau=0.04)
        move_to(clock, T0 + 5 * TICK)
        send(b, STATE_A)
        move_to(clock, T0 + 6 * TICK)
        ps = b.present()
        alpha = 1.0 - math.exp(-0.02 / 0.04)
        self.assertAlmostEqual(ps.antennas[0], INIT_ANTENNAS[0] + alpha * (0.6 - INIT_ANTENNAS[0]), delta=1e-12)
        self.assertHead(ps, REST.head)
        self.assertAlmostEqual(ps.body_yaw, 0.0, delta=1e-15)
        move_to(clock, T0 + 7 * TICK)
        self.assertAlmostEqual(b.present().body_yaw, alpha * STATE_A.body_yaw, delta=1e-12)

    def test_lag_takes_the_short_way_round_180_deg(self):
        clock = VirtualClock(T0)
        b = MockBackend(clock, structure="mujoco", lag_tau_s=0.1, start=RobotState(head=Pose6(yaw=math.radians(170))))
        b.connect()
        b.set_target(Pose6(yaw=math.radians(-170)).matrix(), INIT_ANTENNAS, 0.0)  # 20 deg further, across 180
        for k in range(1, 60):
            move_to(clock, T0 + k * TICK)
            yaw_deg = math.degrees(pose_from_matrix(b.present().head).yaw)
            self.assertGreaterEqual(abs(yaw_deg), 170.0 - 1e-9)  # through 180, never back through 0
        move_to(clock, T0 + 5_000 * MS)
        self.assertAlmostEqual(math.degrees(pose_from_matrix(b.present().head).yaw), -170.0, places=9)

    def test_long_idle_time_is_jumped_in_closed_form(self):
        b, clock = connected("robot", tau=0.05)
        send(b, STATE_A)
        clock.advance(10 * 3600 * 1000 * MS)  # 10 h of virtual time = 1.8 M ticks
        t = time.perf_counter()
        ps = b.present()
        self.assertLess(time.perf_counter() - t, 0.5)
        self.assertState(ps, STATE_A)


class TestGoto(MockTestCase):
    def test_blocks_for_duration_and_ends_on_the_target(self):
        b, clock = connected("mujoco")
        b.goto_target(POSE_A.matrix(), STATE_A.antennas, STATE_A.body_yaw, 1.0, "minjerk")
        self.assertEqual(clock.now_ns(), T0 + 1_000 * MS)  # blocked for the duration on the injected clock
        self.assertState(b.present(), STATE_A)
        self.assertEqual(b.motor_command_count, 1)
        np.testing.assert_allclose(b.current_target().head.as_array(), POSE_A.as_array(), rtol=0, atol=1e-12)

    def test_robot_head_reaches_the_target_one_tick_after_the_antennas(self):
        b, clock = connected("robot")
        b.goto_target(POSE_A.matrix(), STATE_A.antennas, STATE_A.body_yaw, 0.5, "linear")
        ps = b.present()  # tick 25 = end of the goto
        np.testing.assert_allclose(ps.antennas, STATE_A.antennas, rtol=0, atol=1e-15)
        head, _, body = sdk_goto(REST, STATE_A, 0.5, "linear").evaluate(48 * EVAL / 1e9)  # known at tick 24
        np.testing.assert_allclose(ps.head, head, rtol=0, atol=1e-12)
        self.assertAlmostEqual(ps.body_yaw, body, delta=1e-12)
        move_to(clock, T0 + 26 * TICK)
        self.assertState(b.present(), STATE_A)

    def test_send_delay_comes_before_the_goto(self):
        b, clock = connected("mujoco")
        b.send_delay_s = 0.005
        b.goto_target(POSE_A.matrix(), STATE_A.antennas, STATE_A.body_yaw, 0.2, "ease_in_out")
        self.assertEqual(clock.now_ns(), T0 + 205 * MS)
        self.assertEqual(b.commands[0].t_ns, T0)

    def test_follows_the_sdk_gotomove_on_the_play_move_grid(self):
        duration = 0.3
        for method in GOTO_METHODS:
            with self.subTest(method=method):
                clock = SteppedClock(T0)
                b = MockBackend(clock, structure="mujoco")
                b.connect()
                t_start = T0 + 5 * MS  # off the tick grid: ticks see the 100 Hz samples zero-order held
                clock.set(t_start)
                errors: list[BaseException] = []
                th = threading.Thread(target=call_into, args=(errors, b.goto_target, POSE_A.matrix(),
                                                              STATE_A.antennas, STATE_A.body_yaw, duration, method))
                th.start()
                end = t_start + round(duration * 1e9)
                self.assertEqual(clock.wait_for_sleeper(), end)
                # while the goto runs, the daemon ignores other commands (abstract.py:1661-1699, 844-846)
                send(b, STATE_B)
                b.goto_target(POSE_B.matrix(), STATE_B.antennas, STATE_B.body_yaw, 0.1, "linear")
                self.assertEqual((b.ignored_command_count, b.motor_command_count, len(b.commands)), (2, 1, 3))
                ref = sdk_goto(REST, STATE_A, duration, method)
                for k in range(1, 19):
                    t = T0 + k * TICK
                    clock.set(t)  # from t >= end on, this also releases the goto thread
                    ps = b.present()
                    if t < end:
                        head, ant, body = ref.evaluate((t - t_start) // EVAL * EVAL / 1e9)
                    else:
                        head, ant, body = POSE_A.matrix(), np.array(STATE_A.antennas), STATE_A.body_yaw
                    np.testing.assert_allclose(ps.head, head, rtol=0, atol=1e-12, err_msg=f"tick {k}")
                    np.testing.assert_allclose(ps.antennas, ant, rtol=0, atol=1e-12, err_msg=f"tick {k}")
                    self.assertAlmostEqual(ps.body_yaw, float(body), delta=1e-12, msg=f"tick {k}")
                th.join(5.0)
                self.assertFalse(th.is_alive())
                self.assertEqual(errors, [])
                send(b, STATE_B)  # accepted again once the goto is over
                self.assertEqual(b.motor_command_count, 2)

    def test_starts_from_the_present_state_not_the_previous_target(self):
        clock = SteppedClock(T0)
        b = MockBackend(clock, structure="robot", lag_tau_s=0.1)
        b.connect()
        send(b, STATE_A)
        clock.set(T0 + 3 * TICK + 7 * MS)  # the lagging present is only part of the way to STATE_A
        before = b.present()
        errors: list[BaseException] = []
        th = threading.Thread(target=call_into, args=(errors, b.goto_target, REST.head.matrix(), REST.antennas,
                                                      REST.body_yaw, 0.5, "minjerk"))
        th.start()
        end = clock.wait_for_sleeper()
        start = b.current_target()  # sample j = 0 of the goto = its start state
        np.testing.assert_allclose(start.head.as_array(), pose_from_matrix(before.head).as_array(), rtol=0,
                                   atol=1e-12)
        np.testing.assert_allclose(start.antennas, before.antennas, rtol=0, atol=1e-12)
        self.assertAlmostEqual(start.body_yaw, before.body_yaw, delta=1e-12)
        self.assertLess(start.head.pitch, 0.5 * POSE_A.pitch)  # not STATE_A
        clock.set(end)
        th.join(5.0)
        self.assertEqual(errors, [])

    def test_close_during_a_goto_fails_the_call(self):
        clock = SteppedClock(T0)
        b = MockBackend(clock)
        b.connect()
        errors: list[BaseException] = []
        th = threading.Thread(target=call_into, args=(errors, b.goto_target, POSE_A.matrix(), STATE_A.antennas,
                                                      0.0, 0.5, "minjerk"))
        th.start()
        end = clock.wait_for_sleeper()
        b.close()
        clock.set(end)
        th.join(5.0)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], BackendError)


class TestRefusedGoto(MockTestCase):
    """A goto the SDK's GotoMove cannot evaluate fails at call time, as the daemon fails the goto task."""

    def test_improper_head_rotation_is_refused_at_once_and_the_backend_stays_usable(self):
        for label, head in IMPROPER_HEADS.items():
            with self.subTest(head=label):
                b, clock = connected("robot", tau=0.05)
                twin, twin_clock = connected("robot", tau=0.05)  # same commands without the refused goto
                send(b, STATE_A)
                send(twin, STATE_A)
                t_call = T0 + 3 * TICK + 4 * MS
                move_to(clock, t_call)
                with self.assertRaises(BackendError) as ctx:
                    b.goto_target(head, STATE_B.antennas, STATE_B.body_yaw, 0.5, "minjerk")
                self.assertIn("determinant", str(ctx.exception))
                self.assertEqual(clock.now_ns(), t_call)  # refused at once: no blocking
                self.assertEqual((len(b.commands), b.motor_command_count, b.failed_send_count), (2, 1, 1))
                self.assertEqual(b.commands[-1].kind, "goto_target")  # handed over (logged), never delivered
                for t in (t_call, T0 + 4 * TICK, T0 + 9 * TICK + 1 * MS):  # the model is untouched
                    move_to(clock, t)
                    move_to(twin_clock, t)
                    ps, ref = b.present(), twin.present()
                    np.testing.assert_array_equal(ps.head, ref.head)
                    self.assertEqual((ps.antennas, ps.body_yaw), (ref.antennas, ref.body_yaw))
                b.goto_target(POSE_B.matrix(), STATE_B.antennas, STATE_B.body_yaw, 0.2, "linear")  # still usable
                move_to(clock, clock.now_ns() + 2_000 * MS)
                self.assertState(b.present(), STATE_B)
                self.assertEqual((b.motor_command_count, b.failed_send_count), (2, 1))
                b.close()
                self.assertFalse(b.connected)
                b.connect()
                self.assertState(b.present(), STATE_B)

    def test_a_proper_rotation_that_is_not_orthonormal_is_accepted_like_the_sdk(self):
        b, _ = connected("mujoco")
        head = POSE_A.matrix()
        head[:3, :3] *= 1.02  # det > 0: Rotation.from_matrix orthonormalises it (utils/rotation.py:89-101)
        b.goto_target(head, STATE_A.antennas, STATE_A.body_yaw, 0.3, "cartoon")
        self.assertEqual((b.motor_command_count, b.failed_send_count), (1, 0))
        self.assertState(b.present(), STATE_A)

    def test_while_another_goto_runs_it_is_only_ignored(self):
        """The daemon checks for a running move before it evaluates anything (abstract.py:844-846, 904-913)."""
        clock = SteppedClock(T0)
        b = MockBackend(clock, structure="mujoco")
        b.connect()
        errors: list[BaseException] = []
        th = threading.Thread(target=call_into, args=(errors, b.goto_target, POSE_A.matrix(), STATE_A.antennas,
                                                      STATE_A.body_yaw, 0.2, "minjerk"))
        th.start()
        end = clock.wait_for_sleeper()
        b.goto_target(IMPROPER_HEADS["reflection"], INIT_ANTENNAS, 0.0, 0.5, "linear")  # no error: ignored
        self.assertEqual((b.ignored_command_count, b.failed_send_count, b.motor_command_count), (1, 0, 1))
        clock.set(end)
        th.join(5.0)
        self.assertFalse(th.is_alive())
        self.assertEqual(errors, [])
        with self.assertRaises(BackendError):  # the goto is over: now it is evaluated, and refused
            b.goto_target(IMPROPER_HEADS["reflection"], INIT_ANTENNAS, 0.0, 0.5, "linear")
        self.assertEqual((b.ignored_command_count, b.failed_send_count, b.motor_command_count), (1, 1, 1))


class TestCurrentTarget(MockTestCase):
    def test_head_yaw_is_reported_wrapped_across_180_deg(self):
        """The model unwraps the yaw (lag continuity); current_target() reports it in [-pi, pi]."""
        b, clock = connected("mujoco")
        for yaw_deg in (170.0, -170.0, 170.0, -170.0):  # across +-180 deg each time
            b.set_target(Pose6(yaw=math.radians(yaw_deg)).matrix(), INIT_ANTENNAS, 0.0)
            clock.advance(TICK)
            self.assertAlmostEqual(b.current_target().head.yaw, math.radians(yaw_deg), delta=1e-12)
        for k in range(1, 8):  # a monotonic sweep: the model's yaw grows past 360 deg
            yaw = math.radians(100.0 * k)
            b.set_target(Pose6(yaw=yaw).matrix(), INIT_ANTENNAS, 0.0)
            clock.advance(TICK)
            got = b.current_target().head.yaw
            self.assertLessEqual(abs(got), math.pi)
            self.assertAlmostEqual(got, math.remainder(yaw, 2 * math.pi), delta=1e-12)
        # a goto from that unwrapped state ends on the commanded yaw too
        b.goto_target(Pose6(yaw=math.radians(100.0)).matrix(), INIT_ANTENNAS, 0.0, 0.2, "minjerk")
        self.assertAlmostEqual(b.current_target().head.yaw, math.radians(100.0), delta=1e-12)
        self.assertAlmostEqual(pose_from_matrix(b.present().head).yaw, math.radians(100.0), delta=1e-12)


class TestFaultInjection(MockTestCase):
    def test_fail_send_logs_the_command_but_moves_nothing(self):
        b, clock = connected("mujoco")
        b.fail_send = True
        with self.assertRaises(BackendError):
            send(b, STATE_A)
        with self.assertRaises(BackendError):
            b.goto_target(POSE_A.matrix(), STATE_A.antennas, 0.0, 0.5, "minjerk")
        self.assertEqual(clock.now_ns(), T0)  # a failed goto does not block
        self.assertEqual((len(b.commands), b.motor_command_count, b.failed_send_count), (2, 0, 2))
        move_to(clock, T0 + 3 * TICK)
        self.assertState(b.present(), REST)
        b.fail_send = False
        send(b, STATE_A)
        move_to(clock, T0 + 4 * TICK)
        self.assertState(b.present(), STATE_A)

    def test_send_delay_on_a_virtual_clock(self):
        b, clock = connected("mujoco")
        b.send_delay_s = 0.007
        move_to(clock, T0 + 5 * TICK - 2 * MS)
        send(b, STATE_A)  # reaches the model 7 ms later, just after tick 5
        self.assertEqual(clock.now_ns(), T0 + 5 * TICK + 5 * MS)
        self.assertEqual(b.commands[0].t_ns, T0 + 5 * TICK - 2 * MS)  # call start
        self.assertState(b.present(), REST)
        move_to(clock, T0 + 6 * TICK)
        self.assertState(b.present(), STATE_A)
        b.send_delay_s = -1.0
        with self.assertRaises(ValueError):
            send(b, STATE_B)

    def test_send_delay_on_a_real_clock(self):
        b = MockBackend(RealClock())
        b.connect()
        b.send_delay_s = 0.03
        t = time.perf_counter()
        send(b, STATE_A)
        self.assertGreaterEqual(time.perf_counter() - t, 0.029)
        self.assertEqual(b.motor_command_count, 1)

    def test_block_send_holds_the_command_while_present_keeps_answering(self):
        b, clock = connected("mujoco")
        gate = threading.Event()
        b.block_send = gate
        errors: list[BaseException] = []
        th = threading.Thread(target=call_into, args=(errors, send, b, STATE_A), daemon=True)
        th.start()
        self.assertTrue(wait_until(lambda: len(b.commands) == 1))  # handed over ...
        time.sleep(0.05)
        self.assertTrue(th.is_alive())  # ... but still blocked
        self.assertEqual(b.motor_command_count, 0)
        move_to(clock, T0 + 2 * TICK + 5 * MS)
        self.assertState(b.present(), REST)  # a reader is not blocked by the stuck sender
        gate.set()
        th.join(2.0)
        self.assertFalse(th.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(b.motor_command_count, 1)
        move_to(clock, T0 + 3 * TICK)
        self.assertState(b.present(), STATE_A)

    def test_close_releases_a_blocked_send(self):
        b, _ = connected()
        b.block_send = threading.Event()
        errors: list[BaseException] = []
        th = threading.Thread(target=call_into, args=(errors, send, b, STATE_A), daemon=True)
        th.start()
        self.assertTrue(wait_until(lambda: len(b.commands) == 1))
        b.close()
        th.join(2.0)
        self.assertFalse(th.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], BackendError)
        self.assertEqual(b.motor_command_count, 0)


class TestReset(MockTestCase):
    def test_reset_moves_the_model_and_keeps_the_log(self):
        b, clock = connected("robot", tau=0.1)
        send(b, STATE_A)
        b.log_sound_cue("aha.wav")
        move_to(clock, T0 + 3 * TICK + 4 * MS)
        b.reset()
        self.assertState(b.present(), REST)
        move_to(clock, T0 + 9 * TICK)
        self.assertState(b.present(), REST)
        b.reset(STATE_B)
        self.assertState(b.present(), STATE_B)
        self.assertEqual(b.current_target(), STATE_B)
        self.assertEqual((len(b.commands), len(b.sound_cues), b.motor_command_count), (1, 1, 1))
        b.reset(clear_log=True)
        self.assertEqual((b.commands, b.sound_cues, b.motor_command_count), ([], [], 0))
        self.assertEqual((b.failed_send_count, b.ignored_command_count, b.dropped_record_count), (0, 0, 0))

    def test_reset_while_disconnected_sets_the_next_start(self):
        b = MockBackend(VirtualClock(T0))
        b.reset(STATE_C)
        b.connect()
        self.assertState(b.present(), STATE_C)
        with self.assertRaises(TypeError):
            b.reset(POSE_A)  # type: ignore[arg-type]

    def test_non_finite_start_and_reset_states_are_refused(self):
        """Like every command (check_command): a NaN / inf state would poison the model (round(nan) in the unwrap)."""
        bad_states = [RobotState(head=Pose6(yaw=math.nan)), RobotState(head=Pose6(x=math.inf)),
                      RobotState(antennas=(math.nan, 0.0)), RobotState(body_yaw=-math.inf)]
        for bad in bad_states:
            with self.subTest(state=bad):
                with self.assertRaises(ValueError):
                    MockBackend(VirtualClock(T0), start=bad)
                b, clock = connected("robot", tau=0.05)
                send(b, STATE_A)
                with self.assertRaises(ValueError):
                    b.reset(bad)
                move_to(clock, T0 + 2_000 * MS)  # untouched: it went on to STATE_A
                self.assertState(b.present(), STATE_A)
                send(b, STATE_B)
                self.assertEqual((b.motor_command_count, b.failed_send_count), (2, 0))
                b.close()
                with self.assertRaises(ValueError):
                    b.reset(bad)  # disconnected: it would have become the next start
                b.connect()
                self.assertState(b.present(), STATE_A)

    def test_reset_and_close_recover_a_model_that_cannot_be_evaluated(self):
        b, clock = connected("robot", tau=0.05)
        send(b, STATE_A)
        break_model(b, T0 + 2 * TICK + 1)
        move_to(clock, T0 + 5 * TICK)
        with self.assertRaises(ValueError):
            b.present()
        b.reset(STATE_B)  # replaces the history without evaluating it
        self.assertState(b.present(), STATE_B)
        move_to(clock, T0 + 9 * TICK + 3 * MS)
        self.assertState(b.present(), STATE_B)
        send(b, STATE_C)
        self.assertEqual(b.motor_command_count, 2)
        break_model(b, clock.now_ns() + 1)
        move_to(clock, clock.now_ns() + 3 * TICK)
        with self.assertRaises(ValueError):
            b.close()  # the error propagates ...
        self.assertFalse(b.connected)  # ... but the backend is closed
        b.connect()  # ... and connects again, from the previous start pose
        self.assertState(b.present(), REST)
        send(b, STATE_A)
        move_to(clock, clock.now_ns() + 2_000 * MS)
        self.assertState(b.present(), STATE_A)


class TestThreads(MockTestCase):
    def test_gui_reader_thread_while_the_executor_streams(self):
        b, clock = connected("robot", tau=0.03)
        n = 1500
        first_read, done = threading.Event(), threading.Event()
        problems: list[str] = []
        reads = [0]

        def reader() -> None:
            last = -1
            while not done.is_set() or reads[0] == 0:
                try:
                    ps = b.present()
                except Exception as exc:  # reported below
                    problems.append(repr(exc))
                    return
                if ps.t_ns < last:
                    problems.append("time went backwards")
                last = ps.t_ns
                rot = ps.head[:3, :3]
                if not (np.all(np.isfinite(ps.head)) and ps.joints is not None and ps.joints.shape == (7,)
                        and np.all(np.isfinite(ps.joints)) and np.allclose(rot @ rot.T, np.eye(3), atol=1e-9)):
                    problems.append(f"bad state at {ps.t_ns}")
                reads[0] += 1
                first_read.set()

        th = threading.Thread(target=reader)
        th.start()
        try:
            self.assertTrue(first_read.wait(5.0))
            for k in range(n):
                s = math.sin(k * 0.05)
                b.set_target(Pose6(pitch=0.2 * s, yaw=0.3 * s).matrix(), (0.5 * s, -0.5 * s), 0.1 * s)
                clock.advance(TICK)
        finally:
            done.set()
            th.join(5.0)
        self.assertFalse(th.is_alive())
        self.assertEqual(problems, [])
        self.assertGreater(reads[0], 0)
        self.assertEqual(b.motor_command_count, n)

    def test_present_answers_during_a_real_time_goto(self):
        b = MockBackend(RealClock(), structure="mujoco")
        b.connect()
        errors: list[BaseException] = []
        th = threading.Thread(target=call_into, args=(errors, b.goto_target, Pose6(pitch=0.3).matrix(),
                                                      INIT_ANTENNAS, 0.0, 0.6, "minjerk"))
        t_start = time.perf_counter()
        th.start()
        pitches, slowest = [], 0.0
        while th.is_alive():
            t = time.perf_counter()
            ps = b.present()
            slowest = max(slowest, time.perf_counter() - t)
            pitches.append(pose_from_matrix(ps.head).pitch)
            time.sleep(0.02)
        th.join()
        self.assertEqual(errors, [])
        self.assertGreaterEqual(time.perf_counter() - t_start, 0.59)  # the call blocked for the duration
        self.assertGreater(len(pitches), 5)
        self.assertLess(slowest, 0.2)  # present() never waited for the goto
        self.assertTrue(np.all(np.diff(pitches) >= -1e-12))  # minjerk: monotonic progress
        time.sleep(0.03)  # one more tick: the exact target
        self.assertAlmostEqual(pose_from_matrix(b.present().head).pitch, 0.3, places=9)


if __name__ == "__main__":
    unittest.main()
