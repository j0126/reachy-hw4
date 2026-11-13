"""Robot connection sequence (backends.robot_connect) against a fake daemon that follows the SDK 1.11.0 rules:

* no head target + an IK request -> the IK of the identity pose = REST (daemon/backend/abstract.py:555-560);
* ``disable_wobbling`` (with the media object present) and ``stop_head_tracking`` request IK (abstract.py:668-680,
  702-719, 1744-1751); ``SetAutomaticBodyYawCmd`` and the media release do not (abstract.py:1159-1166,
  daemon/daemon.py:139-152);
* the global enable pins the targets to the present joints before the torque comes on; a per-motor enable does not
  (daemon/backend/robot/backend.py:352-377, abstract.py:1786-1792);
* with the torque on the current joint target is written every tick (robot/backend.py:203-210);
* ``face_target`` is reset by ``stop_head_tracking`` and set again only if tracking is turned back on
  (abstract.py:712-719, 765-790).

The same sequence against the real SDK daemon code: tests/test_sdk_offline_connect.py. Nothing here talks to a
daemon or the robot (data_kind mock).
"""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import numpy as np
from reachy_mini.reachy_mini import SLEEP_HEAD_JOINT_POSITIONS, SLEEP_HEAD_POSE

from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics
from reachy_motion.backends.robot_connect import CONSTRUCT_KWARGS, robot_connect_sequence
from reachy_motion.executor.clock import VirtualClock

KIN = new_kinematics()
REST_Q = np.asarray(ik_joints(KIN, np.eye(4), 0.0), dtype=float)
#: An R0 report whose automatic R1 entry checks pass (robot_r0.r1_entry: conditional). The sequence recomputes the
#: entry from the report and also needs the operator's confirmation of the controlled environment (``connect_seq``).
R0_OK = {"blocking": False, "data_kind": "measured", "derived": {"motor_mode": "disabled"},
         "daemon_url": "http://192.168.0.15:8000"}


def connect_seq(make, r0, **kw):
    """The sequence as the CLI calls it after the operator confirmed the controlled environment at the terminal."""
    return robot_connect_sequence(make, r0, operator_confirmed=True, **kw)
ORDER = ["ws_connect", "set_automatic_body_yaw", "media_release", "set_head_tracking_off", "set_wobbling_off",
         "set_target", "set_torque"]


class FakeDaemon:
    """The daemon state that matters for a connection: targets, IK requests, torque, written goals."""

    def __init__(self, pose: np.ndarray, motors_enabled: bool = False, has_target: bool = False,
                 media: bool = True, stale_pin_deg: float = 0.0, simulation: bool = False) -> None:
        self.present_pose = np.asarray(pose, dtype=float)
        self.present_q = np.asarray(ik_joints(KIN, self.present_pose, 0.0), dtype=float)
        self.q0 = self.present_q.copy()
        self.torque = motors_enabled
        self.target_pose = self.present_pose.copy() if has_target else None
        self.target_q = self.present_q.copy() if has_target else None
        self.ik_required = False
        self.media = media
        self.stale_pin_deg = stale_pin_deg
        self.simulation = simulation
        self.face: object = None  # face_target: None = the default
        self.face_after_stop: object = None  # what face_target becomes after our stop (another client re-enabling)
        self.log: list[str] = []
        self.ik_from: list[str] = []
        self.ik_with_torque: list[bool] = []
        self.written: list[np.ndarray] = []

    def tick(self) -> None:
        if self.torque and self.target_q is not None:
            self.written.append(self.target_q.copy())
            self.present_q = self.present_q + 0.3 * (self.target_q - self.present_q)  # the motors follow
        if self.ik_required:
            self.ik_from.append("target" if self.target_pose is not None else "identity")
            self.ik_with_torque.append(self.torque)
            self.target_q = np.asarray(ik_joints(KIN, self.target_pose if self.target_pose is not None
                                                 else np.eye(4), 0.0), dtype=float)

    def identity_ik_with_torque(self) -> bool:
        return any(src == "identity" and on for src, on in zip(self.ik_from, self.ik_with_torque))

    def command(self, name: str, **kw: object) -> None:
        self.log.append(name)
        if name == "set_torque":
            if kw.get("ids") is not None:
                self.torque = True  # per-motor: no pin
            elif not self.torque:
                self.target_q = self.present_q + math.radians(self.stale_pin_deg)  # the pin (stale if asked)
                self.target_pose = self.present_pose.copy()
                self.ik_required = False
                self.torque = True
        elif name == "set_wobbling_off" and self.media:
            self.ik_required = True
        elif name == "set_head_tracking_off":
            self.ik_required = True
            self.face = self.face_after_stop
        elif name == "set_target":
            self.target_pose = np.asarray(kw["pose"], dtype=float)
            self.ik_required = True
        for _ in range(2):
            self.tick()

    def status(self) -> SimpleNamespace:
        mode = "enabled" if self.torque else "disabled"
        return SimpleNamespace(version="1.11.0", simulation_enabled=self.simulation, mockup_sim_enabled=False,
                               state="running", backend_status=SimpleNamespace(motor_control_mode=mode),
                               face_target=self.face)


class FakeClient:
    def __init__(self, daemon: FakeDaemon, host: str) -> None:
        self.daemon, self.host = daemon, host

    def get_status(self, wait: bool = True, timeout: float = 5.0) -> SimpleNamespace:
        return self.daemon.status()

    def disconnect(self) -> None:
        self.daemon.log.append("disconnect")

    def _dispatch(self, msg: object) -> None:  # the SDK receive hook that SdkBackend stamps (sdk.py)
        pass


class FakeMini:
    """The ReachyMini surface the sequence uses; the constructor does what the SDK's does (C1-C4)."""

    def __init__(self, daemon: FakeDaemon, host: str, port: int, **kw: object) -> None:
        self.kw = dict(kw, host=host, port=port)
        self.daemon = daemon
        daemon.log.append("ws_connect")
        daemon.tick()
        daemon.command("set_automatic_body_yaw")
        if daemon.media:
            daemon.command("media_release")
        self.client = FakeClient(daemon, host)
        self.enable_ids: list[object] = []

    def get_current_joint_positions(self) -> tuple[list[float], list[float]]:
        self.daemon.tick()
        return list(self.daemon.present_q), [-0.17, 0.17]

    def get_current_head_pose(self) -> np.ndarray:
        return self.daemon.present_pose

    def enable_motors(self, ids: object = None) -> None:
        self.enable_ids.append(ids)
        self.daemon.command("set_torque", ids=ids)

    def disable_wobbling(self) -> None:
        self.daemon.command("set_wobbling_off")

    def stop_head_tracking(self) -> None:
        self.daemon.command("set_head_tracking_off")

    def set_target(self, head: np.ndarray | None = None, antennas: object = None, body_yaw: float | None = None) -> None:
        self.daemon.command("set_target", pose=head)


def factory(daemon: FakeDaemon, made: list[FakeMini]):
    def make(host: str, port: int, **kw: object) -> FakeMini:
        m = FakeMini(daemon, host, port, **kw)
        made.append(m)
        return m
    return make


def max_dev_deg(goals: list[np.ndarray], ref: np.ndarray) -> float:
    return max((math.degrees(float(np.max(np.abs(g - ref)))) for g in goals), default=0.0)


class TestSequenceFromTheBootState(unittest.TestCase):
    def test_order_and_no_rest_target(self):
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float))  # limp at the sleep pose, no target, media on
        made: list[FakeMini] = []
        mini, rep = connect_seq(factory(d, made), R0_OK, clock=VirtualClock())
        self.assertTrue(rep.ok, rep.problems)
        self.assertIs(mini, made[0])
        self.assertEqual(d.log, ORDER)  # aim sources off and the target synced, all with the torque off
        self.assertIn("identity", d.ik_from)  # the aim-off IK of a missing target runs ...
        self.assertFalse(d.identity_ik_with_torque())  # ... only while the torque is off: never written
        self.assertTrue(d.written)
        self.assertLess(max_dev_deg(d.written, d.q0), 0.05)  # every written goal = the pinned present joints
        self.assertGreater(math.degrees(float(np.max(np.abs(d.q0 - REST_Q)))), 20.0)  # REST is far away here
        self.assertEqual(made[0].kw, dict(CONSTRUCT_KWARGS, host="192.168.0.15", port=8000))
        self.assertEqual(made[0].enable_ids, [None])  # global enable only
        self.assertEqual(rep.stage, "ready")
        self.assertEqual(len(rep.still_drift_deg), 2)  # torque off before the sync, torque on after the pin

    def test_the_naive_order_with_the_torque_on_jumps_to_rest(self):
        """Why the sequence refuses an enabled robot and turns the aim sources off while the torque is off."""
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float), motors_enabled=True)  # torque on, no target
        mini = FakeMini(d, "192.168.0.15", 8000, **CONSTRUCT_KWARGS)
        self.assertNotIn("identity", d.ik_from)  # the constructor alone requests no IK
        mini.disable_wobbling()
        mini.stop_head_tracking()
        self.assertIn("identity", d.ik_from)
        self.assertLess(math.degrees(float(np.max(np.abs(d.written[-1] - REST_Q)))), 1e-6)  # REST written
        self.assertGreater(max_dev_deg(d.written, d.q0), 20.0)  # a step of more than 20 deg on a joint


class TestRefusalsAndStops(unittest.TestCase):
    def test_refused_before_constructing(self):
        """The automatic R1 entry checks (recomputed from the report: a stored verdict is not trusted) and the
        operator's confirmation are checked before the constructor; the residual risk is carried, never verified."""
        from reachy_motion.robot_r0 import r1_entry

        entry = r1_entry(R0_OK)
        self.assertEqual((entry["verdict"], entry["auto_met"]), ("conditional", True))
        self.assertNotIn("met", entry)  # no "met / verified" for the whole entry
        tracking_on = dict(R0_OK, derived={"motor_mode": "disabled", "head_tracking": "on"})
        stored_met = dict(R0_OK, derived={"motor_mode": "enabled"}, r1_entry={"met": True, "verdict": "conditional"})
        cases = [(dict(R0_OK, derived={"motor_mode": "enabled"}), True), (dict(R0_OK, blocking=True), True),
                 (dict(R0_OK, data_kind="simulated"), True), (dict(R0_OK, daemon_url="http://192.168.0.99:8000"), True),
                 ({}, True), (tracking_on, True), (stored_met, True),
                 (R0_OK, False)]  # everything automatic passes, but the operator did not confirm: no run
        for r0, confirmed in cases:
            with self.subTest(r0=r0, confirmed=confirmed):
                d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float))
                made: list[FakeMini] = []
                mini, rep = robot_connect_sequence(factory(d, made), r0, clock=VirtualClock(),
                                                   operator_confirmed=confirmed)
                self.assertIsNone(mini)
                self.assertEqual((made, d.log, rep.stage, rep.torque_state), ([], [], "precondition", "never_on"))
        mini, rep = connect_seq(factory(FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float)), []), R0_OK,
                                clock=VirtualClock())
        self.assertTrue(rep.ok and rep.operator_confirmed)
        self.assertEqual(rep.residual, ["other_client"])  # carried by the run, never verified
        self.assertEqual([c["category"] for c in rep.entry["conditions"]].count("connection"), 2)

    def test_motors_enabled_since_r0(self):
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float), motors_enabled=True, has_target=True)
        mini, rep = connect_seq(factory(d, []), R0_OK, clock=VirtualClock())
        self.assertIsNone(mini)
        self.assertEqual(rep.stage, "verify")
        self.assertEqual(d.log, ["ws_connect", "set_automatic_body_yaw", "media_release", "disconnect"])

    def test_simulation_on_the_motion_socket(self):
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float), simulation=True)
        mini, rep = connect_seq(factory(d, []), R0_OK, clock=VirtualClock())
        self.assertIsNone(mini)
        self.assertIn("not the robot", rep.problems[0])
        self.assertNotIn("set_torque", d.log)

    def test_start_joints_beyond_the_limits(self):
        m = new_kinematics().fk(np.array(SLEEP_HEAD_JOINT_POSITIONS, dtype=float), no_iterations=400)
        d = FakeDaemon(m)
        mini, rep = connect_seq(factory(d, []), R0_OK, clock=VirtualClock())
        self.assertIsNone(mini)
        self.assertEqual(rep.stage, "present")
        self.assertNotIn("set_target", d.log)
        self.assertNotIn("set_torque", d.log)
        self.assertEqual(d.log[-1], "disconnect")

    def test_tracking_turned_back_on_before_the_pin(self):
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float))
        d.face_after_stop = SimpleNamespace(detected=True, x=0.1, y=0.0, roll=0.0, ts=1.0)  # another client
        mini, rep = connect_seq(factory(d, []), R0_OK, clock=VirtualClock())
        self.assertIsNone(mini)
        self.assertEqual(rep.stage, "sync")
        self.assertIn("tracking is on again", rep.problems[0])
        self.assertNotIn("set_torque", d.log)
        self.assertEqual(d.log[-1], "disconnect")

    def test_a_small_settle_at_torque_on_connects(self):
        # the robot moved 0.53 deg right after a clean enable on 2026-11-12: within SETTLE_TOL_DEG, not a refusal
        from reachy_motion.backends.robot_connect import SETTLE_TOL_DEG

        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float), stale_pin_deg=2.0)  # settles ~0.7 deg
        mini, rep = connect_seq(factory(d, []), R0_OK, clock=VirtualClock())
        self.assertIsNotNone(mini, rep.problems)
        self.assertGreater(rep.still_drift_deg[-1], 0.5)
        self.assertLessEqual(rep.still_drift_deg[-1], SETTLE_TOL_DEG)

    def test_a_snap_at_torque_on_stops_everything_else(self):
        from reachy_motion.backends.robot_connect import SETTLE_TOL_DEG

        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float), stale_pin_deg=10.0)  # the pin is 10 deg off
        mini, rep = connect_seq(factory(d, []), R0_OK, clock=VirtualClock())
        self.assertIsNone(mini)
        self.assertEqual(rep.stage, "enable")
        self.assertGreater(rep.still_drift_deg[-1], SETTLE_TOL_DEG)
        self.assertEqual(d.log, ORDER + ["disconnect"])  # no automatic torque-off
        self.assertIn("the torque stays ON", " ".join(rep.log))
        self.assertEqual(rep.torque_state, "on")
        self.assertIn("머리를 손으로 받친다", rep.operator_procedure)


class TestPreparedSdkBackendConnect(unittest.TestCase):
    """``SdkBackend.connect()`` runs ``_connect_robot`` (wired 2026-11-12, user decision); offline: R0 and the SDK client
    are stand-ins, nothing reaches the network."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from reachy_motion.backends.sdk import SdkBackend
        from tests.test_approval import loaded_valid_now_pair
        from tests.test_sdk_backend import Recorder

        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.approval, self.request = loaded_valid_now_pair(tmp)  # a test fixture in a temp folder
        self.backend = SdkBackend("robot", armed=True, approval=self.approval, request=self.request,
                                  confirm=Recorder(True))
        self.r0 = dict(R0_OK, daemon_url=f"http://{self.request.host}:8000")
        self.backend.operator_confirmed = True  # as robot-r1 sets it after the operator's confirmation

    def run_prepared(self, r0: dict, daemon: FakeDaemon, made: list) -> None:
        from unittest import mock

        with mock.patch("reachy_motion.robot_r0.run_r0", return_value=r0), \
                mock.patch("reachy_mini.ReachyMini", factory(daemon, made)):
            self.backend._connect_robot()

    def test_connect_runs_the_connection_sequence(self):
        import inspect
        from unittest import mock

        from reachy_motion.backends.sdk import SdkBackend

        src = inspect.getsource(SdkBackend.connect)
        self.assertIn("self._connect_robot()", src)
        self.assertNotIn("NotImplementedError", src)
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float))
        made: list[FakeMini] = []
        with mock.patch("reachy_motion.robot_r0.run_r0", return_value=self.r0), \
                mock.patch("reachy_mini.ReachyMini", factory(d, made)):
            self.backend.connect()
        self.assertTrue(self.backend.connected)
        self.assertEqual(d.log, ORDER)

    def test_the_connected_path_sends_through_the_client(self):
        from reachy_motion.backends.base import BackendError

        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float))
        made: list[FakeMini] = []
        self.run_prepared(self.r0, d, made)
        self.assertEqual(d.log, ORDER)
        self.assertTrue(self.backend.connection_info["connect"]["ok"])
        self.assertEqual(made[0].kw["host"], self.request.host)
        self.backend.set_target(np.eye(4), (0.0, 0.0), 0.0)  # live: one SetFullTarget through the client
        self.assertEqual(d.log[-1], "set_target")
        self.backend.push_timeout_s = 0.05
        with self.assertRaises(BackendError):  # this stand-in client pushes no state: present() says so
            self.backend.present()

    def test_prepared_path_refuses_without_the_operator_confirmation(self):
        from reachy_motion.backends.base import BackendError

        self.backend.operator_confirmed = False
        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float))
        made: list[FakeMini] = []
        with self.assertRaises(BackendError) as ctx:
            self.run_prepared(self.r0, d, made)
        self.assertIn("operator has not confirmed", str(ctx.exception))
        self.assertEqual((made, d.log), ([], []))

    def test_robot_commands_need_the_connection(self):
        from reachy_motion.backends.base import BackendError

        with self.assertRaises(BackendError):
            self.backend.disable_motors()
        with self.assertRaises(BackendError):
            self.backend.set_target(np.eye(4), (0.0, 0.0), 0.0)

    def test_prepared_path_refuses_an_enabled_robot_without_constructing(self):
        from reachy_motion.backends.base import BackendError

        d = FakeDaemon(np.asarray(SLEEP_HEAD_POSE, dtype=float), motors_enabled=True)
        made: list[FakeMini] = []
        with self.assertRaises(BackendError):
            self.run_prepared(dict(self.r0, derived={"motor_mode": "enabled"}), d, made)
        self.assertEqual((made, d.log), ([], []))
        self.assertFalse(self.backend.connected)



class TestTorqueOffReadBack(unittest.TestCase):
    """The first status message after the torque-off may predate it (io/ws_client.py:194-196, 228-234; the robot read
    'enabled' on 2026-11-12): the read-back waits for up to TORQUE_OFF_READS messages."""

    @staticmethod
    def mini(modes: list[str]):
        from types import SimpleNamespace

        it = iter(modes)

        class Client:
            def get_status(self, wait: bool = True, timeout: float = 2.0):
                return SimpleNamespace(backend_status=SimpleNamespace(motor_control_mode=next(it)))

        return SimpleNamespace(disable_motors=lambda: None, client=Client())

    def test_a_stale_first_status_is_read_again(self):
        from reachy_motion.backends.robot_connect import send_torque_off

        log: list[str] = []
        self.assertEqual(send_torque_off(self.mini(["enabled", "disabled"]), log), "off")
        self.assertIn("status message 2", log[-1])

    def test_still_enabled_after_every_read_is_unconfirmed(self):
        from reachy_motion.backends.robot_connect import TORQUE_OFF_READS, send_torque_off

        log: list[str] = []
        self.assertEqual(send_torque_off(self.mini(["enabled"] * TORQUE_OFF_READS), log), "off_unconfirmed")

if __name__ == "__main__":
    unittest.main()
