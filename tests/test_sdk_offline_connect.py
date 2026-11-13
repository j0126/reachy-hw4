"""The robot connection sequence (backends.robot_connect) against the REAL SDK 1.11.0 daemon code, offline.

The daemon side is ``reachy_mini.daemon.backend.robot.backend.RobotBackend`` itself: its control tick ``_update``,
``set_motor_control_mode`` / ``enable_motors`` / ``set_motor_torque_ids``, and ``Backend.process_command`` (the WS
server's entry point, io/ws_server.py:167-171) with the IK, head-tracking and speech-offset code behind it. Only the
serial motor controller is replaced (``FakeController``: per-motor torque and goal registers; a torqued joint moves
30 % of the way to its goal per 20 ms tick, a limp one stays). ``RobotBackend.__init__`` (opens the serial port) is
skipped: ``Backend.__init__`` runs as is and the attributes the robot constructor sets (robot/backend.py:71-128) get
the same values, then the ``run()`` prologue (162-182). States another client can leave behind (tracking with a lost
face, a running move) are set through private attributes - valid for the pinned 1.11.0 only (tests/test_sdk_env.py).

No daemon process, no network, no robot (data_kind computed). Paths relative to site-packages/reachy_mini/.
"""

from __future__ import annotations

import math
import time
import unittest
from types import SimpleNamespace

import numpy as np
from reachy_mini.daemon.backend.abstract import Backend
from reachy_mini.daemon.backend.robot.backend import RobotBackend
from reachy_mini.io.protocol import (FaceTarget, MotorControlMode, RobotBackendStatus, SetAutomaticBodyYawCmd,
                                     SetFullTargetCmd, SetHeadTrackingCmd, SetTorqueCmd, SetWobblingCmd)
from reachy_mini.reachy_mini import SLEEP_HEAD_POSE
from reachy_mini.utils import create_head_pose

from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics
from reachy_motion.backends.robot_connect import robot_connect_sequence

PERIOD_NS = 20_000_000  # the robot control loop, 50 Hz (robot/backend.py:71)
MOTORS = ("body_rotation",) + tuple(f"stewart_{i}" for i in range(1, 7)) + ("right_antenna", "left_antenna")
KIN = new_kinematics()
REST_Q = np.asarray(ik_joints(KIN, np.eye(4), 0.0), dtype=float)
#: Start joints, both inside the URDF limits: the SDK sleep POSE with the body at 3 deg, and a tilted head.
STARTS = {
    "sdk_sleep_pose_body3": np.asarray(ik_joints(KIN, np.asarray(SLEEP_HEAD_POSE, float), math.radians(3)), float),
    "tilt_body6": np.asarray(ik_joints(KIN, create_head_pose(roll=math.radians(-5), pitch=math.radians(15),
                                                             yaw=math.radians(10), degrees=False),
                                       math.radians(6)), float),
}
#: An R0 whose automatic R1 entry checks pass (robot_r0.r1_entry recomputed by the sequence: conditional); the
#: operator's confirmation is passed as the CLI passes it. The cases below put the other conditions back one by one.
R0_MET = {"blocking": False, "data_kind": "measured", "derived": {"motor_mode": "disabled"},
          "daemon_url": "http://192.168.0.15:8000"}
ORDER = ["set_automatic_body_yaw", "set_head_tracking", "set_wobbling", "set_full_target", "set_torque"]


def deg_max(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float)))))


def round_trip_deg(q: np.ndarray) -> float:
    """max |IK(FK(q)) - q| with the SDK kinematics: the SDK's own FK/IK mismatch at q (0 for an exact pair)."""
    k = new_kinematics()
    return deg_max(ik_joints(k, k.fk(np.asarray(q, float), no_iterations=200), float(q[0])), q)


class FakeController:
    """The ReachyMiniPyControlLoop calls RobotBackend makes; 9 motors in MOTORS order."""

    def __init__(self, q: np.ndarray, antennas: tuple[float, float]) -> None:
        self.pos = np.r_[np.asarray(q, float), np.asarray(antennas, float)]
        self.goal = self.pos.copy()  # a limp robot: the goal registers hold where it rests
        self.torque = np.zeros(9, dtype=bool)
        self.events: list[str] = []
        #: optional gravity model: a limp joint falls 30 % of the way back to where the limp head rests per tick
        self.gravity_rest: np.ndarray | None = None

    def get_last_position(self) -> SimpleNamespace:
        return SimpleNamespace(body_yaw=float(self.pos[0]), stewart=[float(v) for v in self.pos[1:7]],
                               antennas=[float(v) for v in self.pos[7:9]])

    def set_stewart_platform_position(self, v: list[float]) -> None:
        self.goal[1:7] = v
        self.events.append("goal")

    def set_body_rotation(self, y: float) -> None:
        self.goal[0] = float(y)

    def set_antennas_positions(self, v: list[float]) -> None:
        self.goal[7:9] = v

    def enable_torque(self) -> None:
        self.torque[:] = True
        self.events.append("torque_on_all")

    def disable_torque(self) -> None:
        self.torque[:] = False

    def enable_torque_on_ids(self, ids: list[int]) -> None:
        self.torque[list(ids)] = True
        self.events.append(f"torque_on_ids {sorted(ids)}")

    def disable_torque_on_ids(self, ids: list[int]) -> None:
        self.torque[list(ids)] = False

    def get_stats(self) -> dict:
        return {}

    def step(self) -> None:
        limp = self.pos if self.gravity_rest is None else self.pos + 0.3 * (self.gravity_rest - self.pos)
        self.pos = np.where(self.torque, self.pos + 0.3 * (self.goal - self.pos), limp)


class _MediaServer:  # the daemon's media object: it stays after /api/media/release
    def disable_wobbling(self) -> None:
        pass


class _Sink:
    def put(self, msg: object) -> None:
        pass


class SdkDaemon:
    def __init__(self, q: np.ndarray, antennas: tuple[float, float] = (-0.17, 0.17), gravity: bool = False) -> None:
        b = RobotBackend.__new__(RobotBackend)
        Backend.__init__(b, use_audio=False)
        b.control_loop_frequency = 50.0
        b.c = FakeController(q, antennas)
        if gravity:  # the start is where the limp head rests (computed model, not the robot's dynamics)
            b.c.gravity_rest = b.c.pos.copy()
        b.name2id = {n: i for i, n in enumerate(MOTORS)}
        b.motor_control_mode = MotorControlMode.Disabled  # _infer_control_mode() of a limp robot
        b._torque_enabled = False
        b._partial_torque_override = False
        b.last_alive = None
        b._status = RobotBackendStatus(motor_control_mode=b.motor_control_mode, ready=False, last_alive=None,
                                       control_loop_stats={})
        b._stats_record_period = 1.0
        b._stats = {"timestamps": [], "nb_error": 0, "record_period": 1.0}
        b._current_head_operation_mode = -1
        b._current_antennas_operation_mode = -1
        b.target_antenna_joint_current = None
        b.target_head_joint_current = None
        b.hardware_error_check_period = 1e9  # read_hardware_errors is not modelled
        b.bmi088 = None
        b._last_imu = None
        b._media_server = _MediaServer()
        b.set_joint_positions_publisher(_Sink())
        b.set_pose_publisher(_Sink())
        b.retries = 5
        b.stats_record_t0 = time.time()
        b.last_hardware_error_check_time = time.time()
        head, _ = b.get_all_joint_positions()  # run() prologue (robot/backend.py:172-182)
        b.current_head_pose = b.head_kinematics.fk(np.array(head), no_iterations=20)
        b.head_kinematics.ik(b.current_head_pose, no_iterations=20)
        self.b = b
        self.start = b.c.pos.copy()
        self.hooks: list = []  # another client, called before every tick
        self.log: list[str] = []
        self.max_dev_deg = 0.0  # how far the head joints ever got from the start
        self.defer_enable_into_ik = False

    def tick(self) -> None:
        for hook in list(self.hooks):
            hook(self)
        self.b._update()
        self.b.c.step()
        self.max_dev_deg = max(self.max_dev_deg, deg_max(self.b.c.pos[:7], self.start[:7]))

    def command(self, cmd: object) -> None:
        self.b.process_command(cmd, lambda reply: None)

    def status(self) -> SimpleNamespace:
        return SimpleNamespace(version="1.11.0", simulation_enabled=False, mockup_sim_enabled=False, state="running",
                               backend_status=SimpleNamespace(motor_control_mode=self.b.get_motor_control_mode()),
                               face_target=self.b.get_tracked_face())

    def leave_tracking_on_with_a_lost_face(self) -> None:
        """What enable_head_tracking + set_tracking_face leave after the face has been gone > 2 s
        (abstract.py:683-699, 765-790; recentring on INIT_HEAD_POSE = identity, 745-756, 1208)."""
        b = self.b
        with b._tracking_lock:
            b._tracking_enabled, b._tracking_requested_weight, b._tracking_weight = True, 1.0, 1.0
            b._last_face_seen = time.monotonic() - 5.0
            b._face_target = FaceTarget(detected=False, ts=1.0)

    def enable_inside_the_next_ik(self) -> None:
        """The WS thread's enable pin lands while the control thread is inside IK (abstract.py:586-594, no lock)."""
        b = self.b
        ik = b.head_kinematics.ik

        def ik_then_pin(*a, **k):
            result = ik(*a, **k)
            b.head_kinematics.ik = ik
            self.command(SetTorqueCmd(on=True))
            return result

        b.head_kinematics.ik = ik_then_pin


class TickClock:
    """Virtual time; the daemon ticks at every 20 ms boundary crossed."""

    def __init__(self, daemon: SdkDaemon) -> None:
        self.d, self._now = daemon, 0

    def now_ns(self) -> int:
        return self._now

    def sleep_until(self, t_ns: int) -> None:
        target = max(self._now, int(t_ns))
        nxt = (self._now // PERIOD_NS + 1) * PERIOD_NS
        while nxt <= target:
            self.d.tick()
            nxt += PERIOD_NS
        self._now = target

    def advance(self, ns: int) -> None:
        self.sleep_until(self._now + ns)


class Client:
    def __init__(self, d: SdkDaemon, clock: TickClock, host: str) -> None:
        self.d, self.clock, self.host = d, clock, host

    def get_status(self, wait: bool = True, timeout: float = 5.0) -> SimpleNamespace:
        if wait:
            self.clock.advance(PERIOD_NS)  # the next status push
        return self.d.status()

    def disconnect(self) -> None:
        self.d.log.append("disconnect")

    def _dispatch(self, msg: object) -> None:
        pass


class Mini:
    """The ReachyMini surface the sequence uses, sending the SDK's own command models (reachy_mini.py)."""

    def __init__(self, d: SdkDaemon, clock: TickClock, host: str, port: int, **kw: object) -> None:
        self.d, self.clock = d, clock
        clock.advance(PERIOD_NS)  # C1: the first pushes
        self._send(SetAutomaticBodyYawCmd(enabled=bool(kw.get("automatic_body_yaw", True))))  # C2
        # C4 POST /api/media/release stops the daemon's media pipeline only: nothing on the backend
        self.client = Client(d, clock, host)

    def _send(self, cmd: object) -> None:
        self.d.log.append(cmd.type)  # type: ignore[attr-defined]
        if isinstance(cmd, SetTorqueCmd) and cmd.on and self.d.defer_enable_into_ik:  # models the enable only
            self.d.enable_inside_the_next_ik()
        else:
            self.d.command(cmd)
        self.clock.advance(PERIOD_NS)  # one control tick between consecutive commands

    def get_current_joint_positions(self) -> tuple[list[float], list[float]]:
        head, antennas = self.d.b.get_all_joint_positions()  # the joint push: the controller's cached read
        return list(head), list(antennas)

    def get_current_head_pose(self) -> np.ndarray:
        return self.d.b.get_present_head_pose().copy()  # the pose push: FK of the last tick

    def enable_motors(self, ids: list[str] | None = None) -> None:
        self._send(SetTorqueCmd(on=True, ids=ids))

    def disable_wobbling(self) -> None:
        self._send(SetWobblingCmd(enabled=False))

    def stop_head_tracking(self) -> None:
        self._send(SetHeadTrackingCmd(enabled=False))

    def disable_motors(self, ids: list[str] | None = None) -> None:
        self._send(SetTorqueCmd(on=False, ids=ids))

    def set_target(self, head: np.ndarray | None = None, antennas: object = None,
                   body_yaw: float | None = None) -> None:
        self._send(SetFullTargetCmd(head=None if head is None else np.asarray(head, float).flatten().tolist(),
                                    antennas=None if antennas is None else list(antennas), body_yaw=body_yaw))


def connect(d: SdkDaemon, r0: dict = R0_MET, operator_confirmed: bool = True):
    clock = TickClock(d)
    return robot_connect_sequence(lambda host, port, **kw: Mini(d, clock, host, port, **kw), r0, clock=clock,
                                  operator_confirmed=operator_confirmed)


class TestRealSdkConnection(unittest.TestCase):
    def assert_pinned_and_still(self, d: SdkDaemon, rep, tol_deg: float = 1e-9) -> None:
        b = d.b
        self.assertTrue(rep.ok, rep.problems)
        self.assertEqual([x for x in d.log if x != "disconnect"], ORDER)
        self.assertLessEqual(d.max_dev_deg, tol_deg)  # the head never moved (beyond tol)
        self.assertTrue(b._torque_enabled and b.c.torque.all())
        self.assertEqual(b.get_motor_control_mode(), MotorControlMode.Enabled)
        self.assertFalse(b._tracking_enabled)
        self.assertEqual(b._speech_offsets, (0.0,) * 6)
        first_goal = b.c.events.index("goal")
        self.assertLess(first_goal, b.c.events.index("torque_on_all"))  # the pin writes the goals, then torque on

    def test_boot_state_targets_after_the_sequence(self):
        for name, q in STARTS.items():
            with self.subTest(start=name):
                d = SdkDaemon(q)
                b = d.b
                self.assertEqual((b.target_head_pose, b.target_head_joint_positions, b.target_body_yaw,
                                  b.ik_required), (None, None, None, False))  # the boot state
                mini, rep = connect(d)
                self.assert_pinned_and_still(d, rep)
                # after the global enable: the pin of robot/backend.py:352-377, then no further IK request
                self.assertTrue(np.array_equal(b.target_head_joint_positions, d.start[:7]))
                self.assertFalse(b.ik_required)
                self.assertEqual(b.target_body_yaw, float(d.start[0]))
                fk = new_kinematics().fk(d.start[:7], no_iterations=200)  # the daemon's per-tick FK of the start
                self.assertTrue(np.allclose(b.target_head_pose, fk, atol=1e-5))  # (Newton: ~1e-6 apart)
                self.assertEqual(len(rep.still_drift_deg), 2)

    def test_tracking_left_on_by_another_client_is_off_before_the_pin(self):
        for name, q in STARTS.items():
            with self.subTest(start=name):
                d = SdkDaemon(q)
                d.leave_tracking_on_with_a_lost_face()
                TickClock(d).advance(50 * PERIOD_NS)  # limp for 1 s: the aim converges on identity, IK runs
                self.assertTrue(d.b.ik_required)
                mini, rep = connect(d)
                self.assert_pinned_and_still(d, rep)
                self.assertEqual(d.b.get_tracked_face(), FaceTarget())  # reset by our stop

    def test_why_tracking_must_be_off_before_the_pin(self):
        """The previous order (pin first, aim sources after): the aim overrides the pin at the next tick."""
        q = STARTS["tilt_body6"]
        d = SdkDaemon(q)
        d.leave_tracking_on_with_a_lost_face()
        clock = TickClock(d)
        clock.advance(50 * PERIOD_NS)
        d.command(SetTorqueCmd(on=True))
        clock.advance(25 * PERIOD_NS)
        self.assertGreater(d.max_dev_deg, 0.9 * deg_max(q, REST_Q))  # a step toward REST (12.5 deg here)

    def test_enable_pin_overwritten_by_an_ik_in_flight_lands_on_the_present_pose(self):
        for name, q in STARTS.items():
            with self.subTest(start=name):
                d = SdkDaemon(q)
                d.defer_enable_into_ik = True  # the pin lands inside the control thread's IK (forced interleaving)
                mini, rep = connect(d)
                b = d.b
                rt = round_trip_deg(q)
                self.assertLess(rt, 0.5)
                self.assertGreater(d.max_dev_deg, 0.9 * rt)  # the IK result did replace the pin ...
                self.assert_pinned_and_still(d, rep, tol_deg=rt + 1e-6)  # ... but it is the present pose's IK
                self.assertFalse(b.ik_required)

    def test_why_the_target_is_synced_before_the_pin(self):
        """Same interleaving without the sync: the IK in flight is the identity's (no target) and REST is written."""
        q = STARTS["tilt_body6"]
        d = SdkDaemon(q)
        clock = TickClock(d)
        d.command(SetHeadTrackingCmd(enabled=False))  # IK requested, no head target, torque off
        clock.advance(3 * PERIOD_NS)
        d.enable_inside_the_next_ik()
        clock.advance(30 * PERIOD_NS)
        self.assertGreater(d.max_dev_deg, 0.9 * deg_max(q, REST_Q))
        self.assertLess(deg_max(d.b.target_head_joint_positions[1:], REST_Q[1:]), 1e-9)  # REST, held

    def test_partial_enable_left_by_another_client(self):
        q = STARTS["sdk_sleep_pose_body3"]
        d = SdkDaemon(q)
        d.command(SetTorqueCmd(on=True, ids=["stewart_1", "stewart_4"]))  # robot/backend.py:646-667
        self.assertEqual(d.b.c.torque.tolist(), [False, True, False, False, True] + [False] * 4)
        self.assertEqual(d.status().backend_status.motor_control_mode.value, "disabled")  # all that R0 can see
        mini, rep = connect(d)
        self.assert_pinned_and_still(d, rep)  # the global enable re-applies the mode: pin, goals, all torque on
        self.assertFalse(d.b._partial_torque_override)

    def test_another_client_streaming_targets_is_detected_not_prevented(self):
        q = STARTS["tilt_body6"]
        d = SdkDaemon(q)
        nod = create_head_pose(pitch=math.radians(20), degrees=False).flatten().tolist()
        d.hooks.append(lambda dd: dd.b._torque_enabled and dd.command(SetFullTargetCmd(head=nod)))
        mini, rep = connect(d)
        self.assertIsNone(mini)
        self.assertEqual(rep.stage, "enable")
        self.assertIn("after the torque came on", rep.problems[0])
        self.assertGreater(d.max_dev_deg, 0.5)  # the head did move: detection only
        self.assertEqual(d.log[-2:], ["set_torque", "disconnect"])  # nothing more sent by us

    def test_a_running_move_ignores_the_sync_and_drives_after_the_pin(self):
        q = STARTS["tilt_body6"]
        d = SdkDaemon(q)
        d.b._active_move_depth = 1  # another client's goto / play_move in progress (abstract.py:484-486)
        k = {"n": 0}

        def move(dd: SdkDaemon) -> None:  # its evaluation loop sets the target every step (abstract.py:904-925)
            k["n"] += 1
            dd.b.set_target(head=create_head_pose(pitch=math.radians(min(20.0, 0.2 * k["n"])), degrees=False))

        d.hooks.append(move)
        with self.assertLogs("reachy_mini.daemon.backend.abstract", level="WARNING") as logs:
            mini, rep = connect(d)
        self.assertTrue(any("Ignoring set_full_target" in m for m in logs.output))  # our sync was dropped
        self.assertIsNone(mini)
        self.assertEqual(rep.stage, "enable")
        self.assertGreater(d.max_dev_deg, 0.5)

    def test_limp_antennas_stay_put_through_connect_and_the_held_startup(self):
        """R0 2026-11-11: the limp antennas read 157.1 / 130.1 deg against the -10 / +10 deg rest. The global enable
        pins them (robot/backend.py:352-373) and the start-up with the antennas held streams them unchanged, while
        the head goes to REST (docs/phase4/STARTUP_STOP.md §11). A ramp to the rest antennas would sweep them."""
        from reachy_motion.library.pose import RobotState, pose_from_matrix
        from reachy_motion.startup_procedure import plan_startup

        ant = (math.radians(157.061), math.radians(130.078))
        d = SdkDaemon(STARTS["sdk_sleep_pose_body3"], ant)
        mini, rep = connect(d)
        self.assert_pinned_and_still(d, rep)
        b = d.b
        self.assertTrue(np.array_equal(b.c.goal[7:9], ant))  # pinned to the present reading
        head = mini.get_current_head_pose()
        _, a_now = mini.get_current_joint_positions()
        start = RobotState(head=pose_from_matrix(head), antennas=(a_now[0], a_now[1]), body_yaw=float(d.start[0]))
        held = plan_startup(start, antennas="hold")
        self.assertTrue(held.runnable, held.report.violations)
        worst = 0.0
        for k in range(len(held.timeline)):
            tl = held.timeline
            mini.set_target(head=tl.head[k], antennas=tl.antennas[k], body_yaw=float(tl.body_yaw[k]))
            worst = max(worst, deg_max(b.c.goal[7:9], ant), deg_max(b.c.pos[7:9], ant))
        self.assertEqual(worst, 0.0)  # the antennas never got a different goal
        TickClock(d).advance(50 * PERIOD_NS)
        self.assertLess(deg_max(b.c.pos[1:7], REST_Q[1:]), 0.5)  # the head reached REST
        swept = plan_startup(start, antennas="rest").timeline.antennas  # what holding avoids
        self.assertGreater(math.degrees(float(np.max(np.abs(swept[-1] - swept[0])))), 160.0)

    def test_c1_holds_where_the_head_rests_then_turns_the_torque_off(self):
        """C1 (docs/phase4/C1_R1_CHECKLIST.md): connection sequence, a 3 s hold with nothing sent, global torque off.
        Head and antenna goals never change; also with tracking left on, a partial enable or an IK in flight."""
        from reachy_motion.backends.robot_connect import run_c1

        ant = (math.radians(157.061), math.radians(130.078))  # R0 2026-11-11
        setups = {"plain": None, "tracking_lost_face": SdkDaemon.leave_tracking_on_with_a_lost_face,
                  "partial_enable": lambda d: d.command(SetTorqueCmd(on=True, ids=["stewart_1", "stewart_4"])),
                  "ik_in_flight": lambda d: setattr(d, "defer_enable_into_ik", True)}
        for name, q in STARTS.items():
            for setup, prepare in setups.items():
                with self.subTest(start=name, setup=setup):
                    d = SdkDaemon(q, ant)
                    if prepare is not None:
                        prepare(d)
                    clock = TickClock(d)
                    if setup == "tracking_lost_face":
                        clock.advance(50 * PERIOD_NS)
                    rep = run_c1(lambda host, port, **kw: Mini(d, clock, host, port, **kw), R0_MET, clock=clock,
                                 operator_confirmed=True)
                    self.assertTrue(rep.ok, rep.problems)
                    self.assertEqual((rep.torque_state, rep.residual), ("off", ["other_client"]))  # read back
                    tol = round_trip_deg(q) + 1e-6 if setup == "ik_in_flight" else 1e-9
                    self.assertLessEqual(d.max_dev_deg, tol)  # the head never moved (beyond the FK/IK round trip)
                    self.assertLessEqual(rep.hold_head_drift_deg, tol)
                    self.assertEqual(rep.hold_antenna_drift_deg, 0.0)
                    self.assertTrue(np.array_equal(d.b.c.goal[7:9], ant))  # antenna goals: the present reading
                    self.assertTrue(rep.torque_off_sent)
                    self.assertFalse(d.b._torque_enabled or d.b.c.torque.any())  # all off at the end
                    self.assertEqual(d.log.count("set_torque"), 2)  # our enable and our torque off, nothing else
                    self.assertEqual(rep.off_head_drift_deg, 0.0)  # the model has no gravity: see the checklist

    def test_r1_path_streams_its_timelines_without_jumps(self):
        """The R1 run after C1's connection: start-up ramp (antennas held), pitch +2 trial, return ramp, torque off -
        streamed sample by sample into the real daemon code. No target step beyond the plan's own, antennas fixed,
        back where the head rested."""
        from reachy_motion import robot_r1
        from reachy_motion.safety.checker import analyze_timeline
        from tests.test_step_b import r0_like

        rep0 = r0_like()
        plan = robot_r1.build("pitch:+2", 1, rep0)
        start = plan.start
        q = np.asarray(ik_joints(KIN, start.head.matrix(), start.body_yaw), float)
        d = SdkDaemon(q, start.antennas)
        clock = TickClock(d)
        mini, rep = robot_connect_sequence(lambda host, port, **kw: Mini(d, clock, host, port, **kw), R0_MET,
                                           clock=clock, operator_confirmed=True)
        self.assertTrue(rep.ok, rep.problems)
        b = d.b
        worst_step, worst_ant = 0.0, 0.0
        for prep in plan.parts:
            tl = prep.timeline
            planned = np.asarray(analyze_timeline(tl).joints, float)
            plan_step = math.degrees(float(np.max(np.abs(np.diff(planned, axis=0))))) if len(tl) > 1 else 0.0
            prev = np.asarray(b.target_head_joint_positions, float)
            for k in range(len(tl)):
                mini.set_target(head=tl.head[k], antennas=tl.antennas[k], body_yaw=float(tl.body_yaw[k]))
                cur = np.asarray(b.target_head_joint_positions, float)
                worst_step = max(worst_step, deg_max(cur, prev) - plan_step)  # beyond the plan's own step
                prev = cur
                worst_ant = max(worst_ant, deg_max(b.c.goal[7:9], start.antennas))
        self.assertLess(worst_step, 0.05)  # no jump: the first target is the present pose, then the plan
        self.assertEqual(worst_ant, 0.0)  # the antennas never got another goal
        TickClock(d).advance(50 * PERIOD_NS)
        self.assertLess(deg_max(b.c.pos[:7], q), 0.5)  # back where the head rested limp
        mini.disable_motors()
        self.assertFalse(b._torque_enabled or b.c.torque.any())

    def test_no_operator_confirmation_or_tracking_seen_on_sends_nothing(self):
        """The environment the operator does not confirm, or an R0 that saw tracking running: refused before the
        constructor (nothing sent). A stored 'met' in the report is not trusted: the entry is recomputed."""
        for name, r0, confirmed, text in (
                ("operator", dict(R0_MET, r1_entry={"met": True}), False, "operator has not confirmed"),
                ("tracking_on", dict(R0_MET, derived={"motor_mode": "disabled", "head_tracking": "on"}), True,
                 "tracking_not_seen_on")):
            with self.subTest(case=name):
                d = SdkDaemon(STARTS["tilt_body6"])
                mini, rep = connect(d, r0, operator_confirmed=confirmed)
                self.assertIsNone(mini)
                self.assertEqual((d.log, rep.stage, rep.torque_state), ([], "precondition", "never_on"))
                self.assertIn(text, " ".join(rep.problems))


class HarnessBackend:
    """The Backend protocol over the harness client, as ``SdkBackend`` would serve the robot once unlocked:
    ``set_target`` (one SetFullTargetCmd per sample; the executor's clock ticks the daemon), present from the
    pushes, the global torque-off read back (``robot_connect.send_torque_off``). ``fail_at`` / ``fail_with``: the
    n-th set_target raises (a stop request or a lost link). data_kind computed: the daemon code is real, the motors
    and the gravity are a model."""

    name, data_kind = "sdk_harness", "computed"

    def __init__(self, mini: Mini, clock: TickClock, fail_at: int | None = None,
                 fail_with: BaseException | None = None) -> None:
        from reachy_motion.backends.base import Capabilities

        self.capabilities = Capabilities(stream=True, goto=False, present=True, torque_control=True)
        self.mini, self.clock, self.fail_at, self.fail_with = mini, clock, fail_at, fail_with
        self.sent = 0
        self.torque_log: list[str] = []

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def goto_target(self, *a: object, **k: object) -> None:
        raise AssertionError("the runner streams; it never sends a goto")

    def set_target(self, head: np.ndarray, antennas: object, body_yaw: float) -> None:
        if self.fail_at is not None and self.sent >= self.fail_at:
            raise self.fail_with  # type: ignore[misc]
        self.sent += 1
        self.mini.d.log.append("set_full_target")
        self.mini.d.command(SetFullTargetCmd(head=np.asarray(head, float).flatten().tolist(),
                                             antennas=[float(a) for a in antennas], body_yaw=float(body_yaw)))

    def present(self):
        from reachy_motion.backends.base import PresentState

        joints, antennas = self.mini.get_current_joint_positions()
        q = np.asarray(joints, float)
        return PresentState(t_ns=self.clock.now_ns(), head=np.asarray(self.mini.get_current_head_pose(), float),
                            antennas=(float(antennas[0]), float(antennas[1])), body_yaw=float(q[0]), joints=q,
                            data_kind=self.data_kind)

    def disable_motors(self) -> str:
        from reachy_motion.backends.robot_connect import send_torque_off

        return send_torque_off(self.mini, self.torque_log)


class TestEndOfRunTorque(unittest.TestCase):
    """User decision 2026-11-12: the torque goes off automatically only back where the head rests; a stop request or
    a lost link leaves it on (or unknown), recorded, and the operator supports the head before any torque-off. With
    the harness gravity model (a limp joint falls back to where it rested; computed, not the robot's dynamics)."""

    def setUp(self) -> None:
        import tempfile

        from reachy_motion import robot_r1
        from tests.test_step_b import r0_like

        self.r1 = robot_r1
        self.plan = robot_r1.build("pitch:+2", 1, r0_like())
        s = self.plan.start
        self.q = np.asarray(ik_joints(KIN, s.head.matrix(), s.body_yaw), float)
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def run_r1(self, **backend_kw: object):
        from pathlib import Path

        d = SdkDaemon(self.q, self.plan.start.antennas, gravity=True)
        clock = TickClock(d)
        mini, rep = robot_connect_sequence(lambda host, port, **kw: Mini(d, clock, host, port, **kw), R0_MET,
                                           clock=clock, operator_confirmed=True)
        self.assertTrue(rep.ok, rep.problems)
        return d, clock, HarnessBackend(mini, clock, **backend_kw), Path(self.tmp)  # type: ignore[arg-type]

    def test_clean_run_three_records_then_torque_off_at_rest(self):
        from reachy_motion.gui.results import load_result

        d, clock, backend, tmp = self.run_r1()
        prompts: list[str] = []
        out = self.r1.run_trial(backend, self.plan, tmp / "s", clock=clock, torque_off=backend.disable_motors,
                                confirm_torque_off=lambda p: prompts.append(p) or False)
        self.assertTrue(out["ok"], out["problems"])
        self.assertEqual((out["stage"], out["torque_state"], out["torque_off_sent"]), ("returned", "off", True))
        self.assertEqual(prompts, [])  # a clean run asks nothing
        ramp, trial = self.r1.ramp_request(self.plan, "h"), self.r1.trial_request(self.plan, "h")
        self.assertEqual(tuple(out["digests"]), ramp.timeline_digests[:1] + trial.timeline_digests
                         + ramp.timeline_digests[1:])  # what ran is what the two approvals bind
        runs = {k: load_result(v) for k, v in out["runs"].items()}
        self.assertEqual(sorted(runs), sorted([self.r1.RAMP_LABEL, self.plan.trial.label, self.r1.RETURN_LABEL]))
        self.assertTrue(all(r.data_kind == "computed" for r in runs.values()))  # the harness, never "measured"
        self.assertLess(out["end_gap_from_rest"]["rotation_deg"], self.r1.END_TOL["rotation_deg"])
        self.assertLess(out["off_drift_deg"], 0.5)  # switched off where it rests: gravity has nowhere to take it
        self.assertFalse(d.b._torque_enabled or d.b.c.torque.any())
        self.assertTrue(np.array_equal(d.b.c.goal[7:9], self.plan.start.antennas))  # antennas: never another goal

    def test_stop_request_or_lost_link_leaves_the_torque_on_and_the_procedure(self):
        from reachy_motion.backends.base import BackendError
        from reachy_motion.backends.robot_connect import OPERATOR_PROCEDURE_KO

        n_ramp = len(self.plan.ramp.timeline)
        for name, exc in (("stop_request", KeyboardInterrupt()), ("lost_link", BackendError("link lost"))):
            with self.subTest(case=name):
                d, clock, backend, tmp = self.run_r1(fail_at=n_ramp + 30, fail_with=exc)  # inside the trial
                out = self.r1.run_trial(backend, self.plan, tmp / name, clock=clock, torque_off=backend.disable_motors)
                self.assertFalse(out["ok"])
                self.assertIn(out["torque_state"], ("on", "unknown"))
                self.assertFalse(out["torque_off_sent"])  # never automatic away from rest
                self.assertEqual(out["operator_procedure"], OPERATOR_PROCEDURE_KO)
                self.assertTrue(d.b._torque_enabled and d.b.c.torque.all())  # the daemon holds the last target
                self.assertGreater(deg_max(d.b.c.pos[1:7], self.q[1:]), 20.0)  # far from where the head rests
                self.assertIn(self.plan.trial.label, out["runs"])  # the partial trial is recorded

    def test_operator_torque_off_away_from_rest_lets_the_head_fall(self):
        """Why the operator supports the head first: in the gravity model the head falls > 20 deg."""
        from reachy_motion.backends.base import BackendError

        n_ramp = len(self.plan.ramp.timeline)
        d, clock, backend, tmp = self.run_r1(fail_at=n_ramp + 30, fail_with=BackendError("link lost"))
        out = self.r1.run_trial(backend, self.plan, tmp / "s", clock=clock, torque_off=backend.disable_motors,
                                confirm_torque_off=lambda p: "머리를 손으로 받쳤으면" in p)
        self.assertEqual((out["torque_state"], out["torque_off_by"]), ("off", "operator (head supported)"))
        self.assertGreater(out["end_gap_from_rest"]["rotation_deg"], 20.0)  # held near REST when it stopped
        clock.advance(50 * PERIOD_NS)
        self.assertLess(deg_max(d.b.c.pos[1:7], self.q[1:]), 0.5)  # then fell all the way to where it rests limp

    def test_c1_failures_record_the_torque_state_and_never_switch_off_by_themselves(self):
        from reachy_motion.backends.robot_connect import run_c1

        q, ant = STARTS["tilt_body6"], (math.radians(157.061), math.radians(130.078))
        nod = create_head_pose(pitch=math.radians(20), degrees=False).flatten().tolist()
        for name, confirm, expected in (("no_confirm", None, "on"), ("operator_off", lambda p: True, "off")):
            with self.subTest(case=name):
                d = SdkDaemon(q, ant, gravity=True)
                d.hooks.append(lambda dd: dd.b._torque_enabled and dd.command(SetFullTargetCmd(head=nod)))
                clock = TickClock(d)
                rep = run_c1(lambda host, port, **kw: Mini(d, clock, host, port, **kw), R0_MET, clock=clock,
                             operator_confirmed=True, confirm_torque_off=confirm)
                self.assertFalse(rep.ok)
                self.assertEqual(rep.torque_state, expected)  # another client's commands: torque on unless confirmed
                self.assertEqual(d.b._torque_enabled, expected == "on")
                self.assertEqual(bool(rep.operator_procedure), expected == "on")
        d = SdkDaemon(q, ant)  # a lost link during the hold: the state is unknown, a torque-off cannot be confirmed
        clock = TickClock(d)
        minis: list[Mini] = []

        def make(host: str, port: int, **kw: object) -> Mini:
            minis.append(Mini(d, clock, host, port, **kw))
            return minis[-1]

        def lose_link_after_the_enable(dd: SdkDaemon) -> None:
            if dd.b._torque_enabled and dd.log.count("set_torque") and clock.now_ns() > 3_000_000_000:
                def broken(*a: object, **k: object) -> None:
                    raise ConnectionError("link lost")
                minis[0].get_current_joint_positions = broken  # type: ignore[method-assign]
                minis[0]._send = broken  # type: ignore[method-assign]

        d.hooks.append(lose_link_after_the_enable)
        rep = run_c1(make, R0_MET, clock=clock, operator_confirmed=True, confirm_torque_off=lambda p: True)
        self.assertFalse(rep.ok)
        self.assertEqual((rep.stage, rep.torque_state), ("hold", "unknown"))
        self.assertTrue(rep.operator_procedure)
        self.assertTrue(d.b._torque_enabled)  # nothing got through: the operator's power switch


INIT_ANT = (-0.1745, 0.1745)  # SDK INIT_ANTENNAS_JOINT_POSITIONS (reachy_mini.py:67)
#: R0 of a robot woken the usual way: torque on, at INIT (robot_r0.init_pose_error reads these derived fields)
R0_AWAKE = {"blocking": False, "data_kind": "measured", "daemon_url": "http://192.168.0.15:8000",
            "derived": {"motor_mode": "enabled", "distance_to_rest": {"rotation_deg": 0.0, "translation_mm": 0.0},
                        "antennas_deg": [math.degrees(a) for a in INIT_ANT], "body_yaw_deg": 0.0}}


def awake_daemon(q: np.ndarray = REST_Q) -> SdkDaemon:
    """A robot woken the usual way: torque on and every target pinned where it stands (INIT for REST_Q)."""
    d = SdkDaemon(q, INIT_ANT)
    d.command(SetTorqueCmd(on=True))  # robot/backend.py:352-376: targets = the present joints, torque on
    return d


def awake_connect(d: SdkDaemon, clock: TickClock, r0: dict = R0_AWAKE):
    return robot_connect_sequence(lambda host, port, **kw: Mini(d, clock, host, port, **kw), r0, clock=clock,
                                  operator_confirmed=True, mode="awake")


class TestAwakeStart(unittest.TestCase):
    """User decision 2026-11-12: a robot woken the usual way (at INIT, torque on) is a start of its own - no sync, no
    re-pin, no ramps; INIT -> trial -> INIT, then it stays awake."""

    def test_connecting_sends_no_sync_and_no_enable_and_nothing_moves(self):
        d = awake_daemon()
        mini, rep = awake_connect(d, TickClock(d))
        self.assertTrue(rep.ok, rep.problems)
        self.assertEqual(d.log, ["set_automatic_body_yaw", "set_head_tracking", "set_wobbling"])  # no target, no torque
        self.assertLessEqual(d.max_dev_deg, round_trip_deg(REST_Q) + 1e-6)  # no step: the SDK FK/IK round trip only
        self.assertLess(d.max_dev_deg, 0.1)
        self.assertTrue(d.b._torque_enabled and d.b.c.torque.all())
        self.assertEqual((rep.torque_state, rep.torque_enabled_by_us), ("on", False))

    def test_refusals_before_anything_is_sent(self):
        nod = create_head_pose(pitch=math.radians(20), degrees=False).flatten().tolist()
        cases = {"limp": (SdkDaemon(REST_Q, INIT_ANT), None, "verify"),
                 "tracking_running": (awake_daemon(), SdkDaemon.leave_tracking_on_with_a_lost_face, "verify"),
                 "another_motion": (awake_daemon(), lambda d: d.hooks.append(
                     lambda dd: dd.command(SetFullTargetCmd(head=nod))), "still"),
                 "not_at_init": (awake_daemon(STARTS["tilt_body6"]), None, "present")}
        for name, (d, prepare, stage) in cases.items():
            with self.subTest(case=name):
                if prepare is not None:
                    prepare(d)
                mini, rep = awake_connect(d, TickClock(d))
                self.assertIsNone(mini)
                self.assertEqual(rep.stage, stage)
                self.assertNotIn("set_head_tracking", d.log)  # refused before our first command
                self.assertNotIn("set_torque", d.log)

    def run_awake(self, plan, **backend_kw):
        import tempfile
        from pathlib import Path

        from reachy_motion import robot_r1

        d = awake_daemon()
        worst_ant = [0.0]
        d.hooks.append(lambda dd: worst_ant.__setitem__(0, max(worst_ant[0], deg_max(dd.b.c.goal[7:9], INIT_ANT))))
        clock = TickClock(d)
        mini, rep = awake_connect(d, clock)
        self.assertTrue(rep.ok, rep.problems)
        backend = HarnessBackend(mini, clock, **backend_kw)
        with tempfile.TemporaryDirectory() as tmp:
            out = robot_r1.run_trial(backend, plan, Path(tmp) / "s", clock=clock, torque_off=backend.disable_motors)
        return d, out, worst_ant[0]

    def test_r1_r2_r3_run_init_to_init_and_stay_awake(self):
        from reachy_motion import robot_r1

        for plan in (robot_r1.build("pitch:+2", 1, None, awake=True),
                     robot_r1.r2_plan("aha_recommend", "expressive", 1, None, awake=True),
                     robot_r1.r3_plan(20, 1.0, 1, None, awake=True)):
            with self.subTest(trial=plan.trial.label):
                d, out, worst_ant = self.run_awake(plan)
                self.assertTrue(out["ok"], out["problems"])
                self.assertEqual((out["stage"], out["torque_state"], out["torque_off_sent"]), ("at_init", "on", False))
                self.assertEqual(len(out["runs"]), 1)  # the trial alone: no start-up / return ramp
                self.assertEqual(tuple(out["digests"]), robot_r1.trial_request(plan, "h").timeline_digests)
                self.assertTrue(d.b._torque_enabled and d.b.c.torque.all())  # standby at INIT
                self.assertLess(deg_max(d.b.c.pos[:7], REST_Q), 0.5)
                self.assertLess(deg_max(d.b.c.pos[7:9], INIT_ANT), 0.5)
                if plan.trial.stage == "R2":
                    self.assertGreater(worst_ant, 20.0)  # the designed antenna motion is kept, not held

    def test_a_failure_keeps_the_existing_end_procedure(self):
        from reachy_motion import robot_r1
        from reachy_motion.backends.base import BackendError

        plan = robot_r1.r3_plan(20, 1.0, 1, None, awake=True)
        d, out, _ = self.run_awake(plan, fail_at=40, fail_with=BackendError("link lost"))
        self.assertFalse(out["ok"])
        self.assertIn(out["torque_state"], ("on", "unknown"))
        self.assertFalse(out["torque_off_sent"])  # never automatic away from INIT
        self.assertTrue(out["operator_procedure"])
        self.assertTrue(d.b._torque_enabled)


if __name__ == "__main__":
    unittest.main()
