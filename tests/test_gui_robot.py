"""The Motion Lab's real-robot path (user decision 2026-11-12): GUI approvals (``safety.gui_approval``), the SDK wake-up
(``sdk_wake_up``) and ``gui.robot_session.RobotLabSession`` - verified with the flags as shipped (everything refused,
nothing sent) and, with the two flags patched IN THIS PROCESS ONLY, through the real SDK 1.11.0 daemon code of the
offline harness (tests/test_sdk_offline_connect.py: ``RobotBackend`` with a modelled motor bus; data_kind computed).
No network, no robot, no approval file.
"""

from __future__ import annotations

import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from reachy_mini.daemon.backend.robot.backend import RobotBackend  # noqa: F401 - the harness needs the SDK
from reachy_mini.io.protocol import SetFullTargetCmd

from reachy_motion import robot_r1
from reachy_motion.backends.base import BackendError, CommandRecord
from reachy_motion.backends.robot_connect import robot_connect_sequence
from reachy_motion.gui import experiments as ex
from reachy_motion.gui.robot_session import ROBOT_RUN_LOCKED, RobotLabSession, present_start_state
from reachy_motion.safety import gui_approval as ga
from reachy_motion.sdk_wake_up import check_wake_up
from tests.test_sdk_offline_connect import (INIT_ANT, R0_AWAKE, R0_MET, REST_Q, STARTS, HarnessBackend, Mini, SdkDaemon,
                                            TickClock, awake_daemon, deg_max)

HOST, PORT = "192.168.0.15", 8000


def r0_fixture(base: dict) -> dict:
    """An R0 report as ``robot_r0.run_r0`` returns it (enough for write_report and the GUI)."""
    return dict(base, requests="GET only (fixture)", findings=[], generated_local="2026-11-12T12:00:00", stage="R0")


def live_r0(d: SdkDaemon, base: dict):
    """An R0 reader whose motor mode is the harness daemon's own, as the real GET /api/motors/status reports it."""

    def read(host: str, port: int) -> dict:
        mode = d.b.get_motor_control_mode()
        return r0_fixture(dict(base, derived=dict(base.get("derived") or {}, motor_mode=str(getattr(mode, "value", mode)))))

    return read


class GuiHarnessBackend(HarnessBackend):
    """The harness backend plus what the robot session uses: the command record, the SDK goto (the daemon's own
    ``GotoMove`` evaluated every 10 ms until its duration, as ``Backend.play_move`` does, abstract.py:904-925 /
    944-977), the motion socket's status (``health``) and a client disconnect."""

    def __init__(self, mini: Mini, clock: TickClock, **kw: object) -> None:
        super().__init__(mini, clock, **kw)
        self.commands: list[CommandRecord] = []
        self.connection_info: dict = {}
        self.closed = False

    def set_target(self, head, antennas, body_yaw) -> None:
        super().set_target(head, antennas, body_yaw)
        self.commands.append(CommandRecord(self.clock.now_ns(), "set_target", np.asarray(head, float).copy(),
                                           (float(antennas[0]), float(antennas[1])), float(body_yaw)))

    def goto_target(self, head, antennas, body_yaw, duration, method) -> None:
        from reachy_mini.motion.goto import GotoMove
        from reachy_mini.utils.interpolation import InterpolationTechnique

        b = self.mini.d.b
        self.commands.append(CommandRecord(self.clock.now_ns(), "goto_target", np.asarray(head, float).copy(),
                                           (float(antennas[0]), float(antennas[1])), float(body_yaw), float(duration),
                                           str(method)))
        self.mini.d.log.append("goto")
        move = GotoMove(start_head_pose=b.get_present_head_pose(), target_head_pose=np.asarray(head, float),
                        start_body_yaw=b.get_present_body_yaw(), target_body_yaw=float(body_yaw),
                        start_antennas=np.array(b.get_present_antenna_joint_positions()),
                        target_antennas=np.asarray(antennas, float), duration=float(duration),
                        method=InterpolationTechnique(method))
        t = 0.0
        while t < duration:
            h, a, y = move.evaluate(t)
            if h is not None:
                b.set_target_head_pose(h)
            if y is not None:
                b.set_target_body_yaw(y)
            if a is not None:
                b.set_target_antenna_joint_positions(a)
            self.clock.advance(10_000_000)
            t += 0.01

    def health(self) -> dict:
        from reachy_motion.backends.robot_connect import _status_fields

        f = _status_fields(self.mini.client.get_status(wait=False))
        return {"state": f["state"], "error": None, "motor_mode": f["motor_mode"], "status_age_s": None,
                "face_target_set": f["face_target_set"]}

    def close(self) -> None:
        self.closed = True
        self.mini.client.disconnect()


def harness_link(d: SdkDaemon, made: list, wrap=None, **backend_kw):
    """``link_factory`` over the harness: the real connection sequence on the SDK daemon code. A refused or failed
    sequence raises with its report attached (``connect_report``, as ``RobotLabSession._make_link`` does for
    SdkBackend); ``wrap(mini)`` injects a fault into the client, ``backend_kw`` goes to the backend."""

    def make(host, port, clock, **kw):
        mini = Mini(d, clock, host, port, **kw)
        return mini if wrap is None else wrap(mini)

    def link(host, port, approval, r0, mode, clock):
        mini, rep = robot_connect_sequence(lambda host, port, **kw: make(host, port, clock, **kw), r0, clock=clock,
                                           host=host, port=port, operator_confirmed=True, mode=mode)
        if mini is None:
            exc = BackendError("robot connection refused: " + "; ".join(rep.problems))
            exc.connect_report = rep.to_dict()
            raise exc
        b = GuiHarnessBackend(mini, clock, **backend_kw)
        b.connection_info = {"connect": rep.to_dict(), "residual": rep.residual}
        made.append(b)
        return b

    return link


def wait_idle(s: RobotLabSession, timeout: float = 120.0) -> None:
    t0 = time.monotonic()
    while s.pending:
        if time.monotonic() - t0 > timeout:
            raise AssertionError("the robot session did not finish its jobs")
        time.sleep(0.01)


def wait_event(events: list, kinds: tuple[str, ...], after: int, timeout: float = 120.0) -> dict:
    """The first event of ``kinds`` after index ``after`` (a stopped job keeps running its controlled stop after
    ``stop()`` emptied the pending list)."""
    t0 = time.monotonic()
    while True:
        for e in events[after:]:
            if e["kind"] in kinds:
                return e
        if time.monotonic() - t0 > timeout:
            raise AssertionError(f"no {kinds} event")
        time.sleep(0.01)


def unlocked():
    """Both switches on (their released values, 2026-11-12) - kept explicit so these tests do not depend on them."""
    return mock.patch.multiple("reachy_motion.safety.gui_approval", GUI_APPROVAL_ENABLED=True), \
        mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", True)


def connect_approval(r0: dict) -> ga.GuiApproval:
    req = ga.connect_request(r0, HOST, PORT)
    return ga.approve(req, ga.OPERATOR_ROWS_KO)


def trial_approval(s: RobotLabSession, trial) -> ga.GuiApproval:
    plan, probs = s.trial_plan(trial)
    req = ga.trial_request(plan, HOST, PORT, probs)
    return ga.approve(req)


def wake_approval(s: RobotLabSession) -> ga.GuiApproval:
    state, joints = present_start_state(s.backend.present())
    req = ga.wake_up_request(check_wake_up(state), HOST, PORT, joints)
    return ga.approve(req)


class TestGuiApproval(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = robot_r1.build("pitch:+2", 1, None, awake=True)
        self.req = ga.trial_request(self.plan, HOST, PORT)

    def test_the_dialog_shows_what_will_run(self):
        rows = dict(self.req.rows)
        for key in ("시행", "목표 진폭", "Duration", "정책 검사 (computed)", "예상 필요 속도", "최소 관절 여유", "승인 범위"):
            self.assertIn(key, rows)
        self.assertIn("pitch +2 deg", rows["목표 진폭"])
        self.assertIn("Stewart 속도 비", rows["예상 필요 속도"])
        self.assertEqual(self.req.digest, self.plan.run.timeline.digest())
        self.assertFalse(hasattr(self.req, "code"))  # no code to type (user decision 2026-11-12)

    def test_approve_needs_a_passing_check_and_the_operator_rows(self):
        a = ga.approve(self.req)
        self.assertEqual((a.request.label, a.valid_s), (self.plan.trial.label, ga.MOTION_VALID_S))
        self.assertEqual(a.record()["request"]["digest"], self.req.digest)
        refused = ga.GuiRequest("trial", HOST, PORT, "R3", "x", "x", "d", (), False, ("too fast",))
        with self.assertRaises(ga.GuiApprovalError):
            ga.approve(refused)
        conn = ga.connect_request(r0_fixture(R0_AWAKE), HOST, PORT)
        with self.assertRaises(ga.GuiApprovalError):
            ga.approve(conn)
        with self.assertRaises(ga.GuiApprovalError):
            ga.approve(conn, ga.OPERATOR_ROWS_KO[:-1])
        self.assertEqual(ga.approve(conn, ga.OPERATOR_ROWS_KO).request.start_mode, "awake")

    def test_problems_bind_kind_target_trial_digest_once_and_time(self):
        a = ga.approve(self.req)
        args = dict(kind="trial", host=HOST, port=PORT, label=self.plan.trial.label, digest=self.req.digest)
        with mock.patch.object(ga, "GUI_APPROVAL_ENABLED", False):  # the policy switched off: always refused
            self.assertEqual(ga.problems(a, **args), [ga.POLICY_NOT_CONFIRMED])
        with mock.patch.object(ga, "GUI_APPROVAL_ENABLED", True):
            self.assertEqual(ga.problems(a, **args), [])
            other = robot_r1.build("pitch:+5", 1, None, awake=True)
            self.assertTrue(ga.problems(a, **dict(args, label=other.trial.label, digest=other.run.timeline.digest())))
            self.assertTrue(ga.problems(a, **dict(args, host="192.168.0.99")))
            self.assertTrue(ga.problems(a, **dict(args, kind="wake_up")))
            self.assertTrue(ga.problems(a, **dict(args, used={a.approval_id})))
            late = a.approved_ns + int((ga.MOTION_VALID_S + 1) * 1e9)
            self.assertTrue(any("만료" in p for p in ga.problems(a, **args, now_ns=late)))
            self.assertTrue(ga.problems(None, **args))

    def test_connect_request_refuses_without_a_usable_r0(self):
        self.assertFalse(ga.connect_request(None, HOST, PORT).policy_ok)
        self.assertFalse(ga.connect_request(r0_fixture(dict(R0_MET, blocking=True)), HOST, PORT).policy_ok)
        self.assertFalse(ga.connect_request(r0_fixture(R0_MET), "192.168.0.99", PORT).policy_ok)
        self.assertEqual(ga.connect_request(r0_fixture(R0_MET), HOST, PORT).start_mode, "sleep")


class TestRobotPathSwitches(unittest.TestCase):
    """Released on 2026-11-12 (user decision, CLAUDE.md rule 3); turning a switch off still stops every robot job
    before anything is constructed or sent."""

    def test_switches_as_released(self):
        import inspect

        from reachy_motion.backends import sdk

        self.assertIs(ga.GUI_APPROVAL_ENABLED, True)
        self.assertIs(robot_r1.ROBOT_RUN_ENABLED, True)
        src = inspect.getsource(sdk.SdkBackend.connect)
        self.assertIn("self._connect_robot()", src)
        self.assertNotIn("NotImplementedError", src)

    def test_sdk_backend_takes_a_gui_approval_only_with_the_policy(self):
        from reachy_motion.backends.sdk import RobotApprovalError, SdkBackend

        a = connect_approval(r0_fixture(R0_AWAKE))
        with mock.patch.object(ga, "GUI_APPROVAL_ENABLED", False):
            with self.assertRaises(RobotApprovalError):
                SdkBackend("robot", armed=True, approval=a)
        with self.assertRaises(RobotApprovalError):
            SdkBackend("robot", armed=False, approval=a)
        b = SdkBackend("robot", armed=True, approval=a)
        self.assertEqual((b.host, b.port, b.data_kind), (HOST, PORT, "measured"))
        with mock.patch.object(SdkBackend, "_connect_robot") as sequence:  # stubbed: nothing reaches the network
            b.connect()
        sequence.assert_called_once_with()

    def test_switches_off_refuse_every_robot_job_and_nothing_is_built_or_sent(self):
        made: list = []
        d = awake_daemon()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ga, "GUI_APPROVAL_ENABLED", False), \
                mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", False):
            events: list[dict] = []
            calls: list = []
            s = RobotLabSession(Path(tmp) / "lab", events.append, HOST, PORT, link_factory=lambda **kw: calls.append(kw),
                                r0_reader=lambda h, p: r0_fixture(R0_AWAKE), clock=TickClock(d), r0_root=Path(tmp) / "r0")
            try:
                s.read_status()  # GET only: allowed as before
                s.connect_robot(connect_approval(r0_fixture(R0_AWAKE)))
                s.run_trial(ex.r1_trial("pitch", 2.0), Path(tmp) / "sess", approval=None)
                s.torque_off(True)
                wait_idle(s)
            finally:
                s.close()
        self.assertEqual((calls, made, d.log), ([], [], []))
        kinds = [e["kind"] for e in events]
        self.assertIn("robot_status", kinds)
        refused = [e for e in events if e["kind"] == "refused"]
        self.assertEqual([e["job"] for e in refused], ["robot_connect", "trial", "torque_off"])
        self.assertIn(ga.POLICY_NOT_CONFIRMED, refused[0]["reasons"])
        self.assertIn(ROBOT_RUN_LOCKED, refused[0]["reasons"])
        self.assertTrue(all(e["nothing_sent"] for e in refused))


class ProdMini(Mini):
    """The harness client as ``SdkBackend``'s robot path drives it: the SDK's fire-and-forget ``set_target`` (no wait),
    the blocking ``goto_target`` (the daemon's own GotoMove every 10 ms until its duration, abstract.py:904-925 /
    944-977) and the receive thread's state pushes (JointPositionsMsg / HeadPoseMsg through ``client._dispatch``, which
    SdkBackend stamps) on every control tick - plus ``push()`` for a thread while nothing ticks."""

    def __init__(self, d: SdkDaemon, clock: TickClock, host: str, port: int, **kw: object) -> None:
        super().__init__(d, clock, host, port, **kw)
        d.hooks.append(lambda _d: self.push())

    def push(self) -> None:
        from reachy_mini.io.protocol import HeadPoseMsg, JointPositionsMsg

        self.client._dispatch(JointPositionsMsg(head_joint_positions=[0.0] * 7, antennas_joint_positions=[0.0, 0.0]))
        self.client._dispatch(HeadPoseMsg(head_pose=np.eye(4).tolist()))

    def set_target(self, head=None, antennas=None, body_yaw=None) -> None:
        self.d.log.append("set_full_target")
        self.d.command(SetFullTargetCmd(head=None if head is None else np.asarray(head, float).flatten().tolist(),
                                        antennas=None if antennas is None else [float(a) for a in antennas],
                                        body_yaw=body_yaw))

    def goto_target(self, head=None, antennas=None, duration=0.5, method=None, body_yaw=0.0) -> None:
        from reachy_mini.motion.goto import GotoMove

        b = self.d.b
        self.d.log.append("goto")
        move = GotoMove(start_head_pose=b.get_present_head_pose(), target_head_pose=np.asarray(head, float),
                        start_body_yaw=b.get_present_body_yaw(), target_body_yaw=float(body_yaw),
                        start_antennas=np.array(b.get_present_antenna_joint_positions()),
                        target_antennas=None if antennas is None else np.asarray(antennas, float),
                        duration=float(duration), method=method)
        t = 0.0
        while t < duration:
            h, a, y = move.evaluate(t)
            if h is not None:
                b.set_target_head_pose(h)
            if y is not None:
                b.set_target_body_yaw(y)
            if a is not None:
                b.set_target_antenna_joint_positions(a)
            self.clock.advance(10_000_000)
            t += 0.01


class TestRobotSessionOnTheHarness(unittest.TestCase):
    """The whole GUI flow on the real SDK daemon code, flags patched in-process: status -> connect -> wake-up ->
    trials (one approval each) -> stop -> torque-off; records in runs/ (commands vs present) and robot_log/."""

    def session(self, d: SdkDaemon, r0: dict, tmp: str, events: list, made: list) -> RobotLabSession:
        return RobotLabSession(Path(tmp) / "lab", events.append, HOST, PORT, link_factory=harness_link(d, made),
                               r0_reader=live_r0(d, r0), clock=TickClock(d), r0_root=Path(tmp) / "r0")

    def test_limp_start_connect_wake_up_trial_stop_torque_off(self):
        q_sleep = STARTS["sdk_sleep_pose_body3"]
        d = SdkDaemon(q_sleep, (-0.6, 0.6))
        made: list = []
        events: list[dict] = []
        p1, p2 = unlocked()
        with tempfile.TemporaryDirectory() as tmp, p1, p2:
            s = self.session(d, R0_MET, tmp, events, made)
            try:
                s.read_status()
                s.connect_robot(connect_approval(r0_fixture(R0_MET)))
                wait_idle(s)
                self.assertEqual(s.robot_state, "rest_torque_on", [e for e in events if e["kind"] == "refused"])
                self.assertIn("set_torque", d.log)
                # the connection sent enable_motors() and read nothing back: UNKNOWN, never a guess
                self.assertEqual(s.torque_view()["torque"], "UNKNOWN")
                s.read_status()
                wait_idle(s)
                view = s.torque_view()
                self.assertEqual(view["torque"], "ON")  # the fresh SDK status: enabled
                self.assertTrue(view["link"].startswith("열림"))
                self.assertLess(d.max_dev_deg, 0.6)  # the connection pins where it rests: no motion

                # a trial before the wake-up is refused, nothing sent
                n_log = len(d.log)
                trial = ex.r1_trial("pitch", 2.0)
                s.run_trial(trial, Path(tmp) / "sess", approval=trial_approval(s, trial))
                wait_idle(s)
                self.assertEqual(len(d.log), n_log)
                self.assertEqual(events[-1]["kind"], "refused")

                s.wake_up(wake_approval(s))
                wait_idle(s)
                fin = [e for e in events if e["kind"] == "wake_up_finished"][-1]
                self.assertTrue(fin["ok"], fin["problems"])
                self.assertEqual((s.robot_state, fin["sent"]), ("at_init", 3))
                self.assertEqual(d.log.count("goto"), 3)
                self.assertLess(deg_max(d.b.c.pos[:7], REST_Q), 0.5)
                self.assertLess(deg_max(d.b.c.pos[7:9], INIT_ANT), 0.5)
                wake_rec = Path(fin["record"])
                self.assertTrue(wake_rec.exists())

                # one approved trial: INIT -> trial -> INIT, recorded for the Results tab
                a = trial_approval(s, trial)
                s.run_trial(trial, Path(tmp) / "sess", approval=a)
                wait_idle(s)
                done = [e for e in events if e["kind"] == "trial_finished"][-1]
                self.assertTrue(done["completed"], done)
                self.assertEqual((done["robot"]["state"], done["robot"]["torque_state"]), ("at_init", "on"))
                run = Path(done["run_dir"])
                self.assertTrue((run / "commands.csv").exists() and (run / "present_computed.csv").exists())
                ev = done["robot"]["evidence"]
                self.assertGreater(ev["commands_sent"], 100)
                self.assertGreater(ev["present_samples"], 100)
                self.assertIsNotNone(done["loaded"])
                import json

                man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(man["data_kind"], "computed")  # the harness, never "measured"
                self.assertEqual(man["connection"]["trial_approval"]["approval_id"], a.approval_id)

                # the same approval twice, or another trial's approval: refused, nothing sent
                n_set = d.log.count("set_full_target")
                s.run_trial(trial, Path(tmp) / "sess", approval=a)
                other = ex.r1_trial("pitch", 5.0)
                s.run_trial(other, Path(tmp) / "sess", approval=trial_approval(s, trial))
                wait_idle(s)
                self.assertEqual(d.log.count("set_full_target"), n_set)
                self.assertEqual([e["kind"] for e in events[-2:]], ["refused", "refused"])

                # Stop during a trial: controlled stop, torque stays on, no automatic torque-off or return
                r3 = ex.r3_trial(20, 1.0)
                ticks = [0]

                def stop_later(_d):
                    ticks[0] += 1
                    if ticks[0] == 60:
                        s.stop()

                a3 = trial_approval(s, r3)
                d.hooks.append(stop_later)
                n_ev = len(events)
                s.run_trial(r3, Path(tmp) / "sess", approval=a3)
                stopped = wait_event(events, ("trial_finished", "refused"), n_ev)
                wait_idle(s)
                d.hooks.remove(stop_later)
                self.assertTrue(stopped["cancelled"])
                self.assertEqual(stopped["stop_kind"], "S1")
                self.assertEqual(s.robot_state, "holding")
                self.assertTrue(stopped["robot"]["operator_procedure"])
                self.assertTrue(d.b._torque_enabled)
                self.assertEqual(s.r3_runs, [])  # a stopped step never unlocks the next one

                # torque-off only with the operator's confirmation, then the client disconnects
                s.torque_off(False)
                wait_idle(s)
                self.assertTrue(d.b._torque_enabled)
                s.torque_off(True)
                wait_idle(s)
                off = [e for e in events if e["kind"] == "robot_torque_off"][-1]
                self.assertEqual(off["torque_state"], "off")
                self.assertEqual(off["torque"], "OFF")  # read back after the torque-off
                self.assertTrue(off["link"].startswith("닫힘"))
                self.assertFalse(d.b._torque_enabled)
                self.assertEqual((s.robot_state, s.backend), ("disconnected", None))
                self.assertTrue(made[0].closed)
                logs = sorted(p.name for p in Path(s.log_dir).glob("*.json"))
                self.assertEqual([n.split("_", 1)[1] for n in logs],
                                 ["connect.json", "sdk_wake_up.json", "torque_off.json"])
            finally:
                s.close()

    def test_awake_start_runs_r1_r2_r3_and_refuses_what_is_out_of_scope(self):
        d = awake_daemon()
        made: list = []
        events: list[dict] = []
        p1, p2 = unlocked()
        from reachy_motion.library.registry import default_library

        lib = default_library(Path("motions"))
        with tempfile.TemporaryDirectory() as tmp, p1, p2:
            s = self.session(d, R0_AWAKE, tmp, events, made)
            try:
                s.connect_robot(connect_approval(r0_fixture(R0_AWAKE)))
                wait_idle(s)
                self.assertEqual(s.robot_state, "at_init")
                self.assertNotIn("set_torque", d.log)  # awake: nothing re-pinned
                for trial in (ex.r1_trial("pitch", 2.0), ex.r2_trial(lib.get("aha_recommend", "expressive")),
                              ex.r3_trial(20, 1.0)):
                    s.run_trial(trial, Path(tmp) / trial.stage, approval=trial_approval(s, trial))
                    wait_idle(s)
                    done = [e for e in events if e["kind"] in ("trial_finished", "refused")][-1]
                    self.assertEqual(done["kind"], "trial_finished", done)
                    self.assertTrue(done["robot"]["ok"], done["robot"]["problems"])
                self.assertEqual(len(s.r3_runs), 1)
                self.assertEqual(s._r3_base(ex.r3_trial(20, 0.6)), s.r3_runs[0])  # the lag baseline of this ladder
                self.assertIsNone(s._r3_base(ex.r3_trial(10, 0.6)))  # another amplitude: another ladder
                # the next R3 step needs the robot's MEASURED previous step: the harness is computed -> refused
                plan, probs = s.trial_plan(ex.r3_trial(20, 0.6))
                self.assertTrue(any("실제 로봇 측정" in p for p in probs), probs)  # Korean in the GUI (lang="ko")
                r3_done = [e for e in events if e["kind"] == "trial_finished" and e.get("stage") == "R3"][-1]
                self.assertEqual((r3_done["r3_next"]["amplitude_deg"], r3_done["r3_next"]["duration_s"]), (20.0, 1.0))
                self.assertIsInstance(r3_done["r3_next"]["problems"], list)  # the ladder verdict, shown at once
                req = ga.trial_request(plan, HOST, PORT, probs)
                self.assertFalse(req.policy_ok)
                # D < 0.2 s is out of the robot's scope; D 0.2 s needs its previous step first
                self.assertTrue(any("실제 로봇 범위 밖" in p for p in s.trial_plan(ex.r3_trial(20, 0.15))[1]))
                self.assertTrue(s.trial_plan(ex.r3_trial(20, 0.2))[1])
                # another controller shows up (tracking left on): refused before anything is sent
                d.leave_tracking_on_with_a_lost_face()
                n_set = d.log.count("set_full_target")
                t = ex.r1_trial("pitch", 2.0, rep=2)
                s.run_trial(t, Path(tmp) / "R1", approval=trial_approval(s, t))
                wait_idle(s)
                self.assertEqual(events[-1]["kind"], "refused")
                self.assertTrue(any("face_target" in r for r in events[-1]["reasons"]))
                self.assertEqual(d.log.count("set_full_target"), n_set)
                s.disconnect()
                wait_idle(s)
                self.assertEqual(s.robot_state, "disconnected")
                self.assertTrue(d.b._torque_enabled)  # a disconnect changes nothing on the robot
            finally:
                s.close()


class TestRobotPanelGui(unittest.TestCase):
    """The Experiment tab's robot box, offscreen: the dialog itself, and the clicks of the whole flow on the harness
    (the dialogs answered by the test - the role of the person - with the flags patched in this process)."""

    @classmethod
    def setUpClass(cls) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def pump(self, cond, timeout: float = 60.0) -> None:
        t0 = time.monotonic()
        while not cond():
            self.app.processEvents()
            if time.monotonic() - t0 > timeout:
                raise AssertionError("GUI condition not reached")
            time.sleep(0.01)
        self.app.processEvents()

    def test_the_production_sdk_backend_path_click_through_offline(self):
        """The GUI's own default link - ``SdkBackend("robot")`` with the GUI approval, ``connect()`` ->
        ``_connect_robot`` - with only what would leave the PC replaced: ``reachy_mini.ReachyMini`` by the SDK-daemon
        harness client, ``run_r0`` by the R0 fixture, and every socket connection blocked. Connect (limp robot:
        enable_motors), Wake-up, R1 pitch +2 deg, torque-off - clicked as the user will."""
        import socket
        import threading

        from reachy_motion.backends.sdk import SdkBackend
        from reachy_motion.gui import lab_tabs
        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.model import EditorModel

        d = SdkDaemon(STARTS["sdk_sleep_pose_body3"], (-0.6, 0.6))
        clock = TickClock(d)
        minis: list = []

        def make_client(host, port, **kw):
            minis.append(ProdMini(d, clock, host, port, **kw))
            return minis[-1]

        stop = threading.Event()

        def receive_thread():  # the SDK client's receive thread keeps pushing while nothing ticks
            while not stop.wait(0.005):
                for m in list(minis):
                    m.push()

        pusher = threading.Thread(target=receive_thread, daemon=True)
        pusher.start()
        r0 = live_r0(d, R0_MET)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("reachy_mini.ReachyMini", make_client), \
                mock.patch("reachy_motion.robot_r0.run_r0", side_effect=lambda client, timeout_s=None: r0(HOST, PORT)), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(lab_tabs, "ask_torque_off", lambda _p: True):
            sessions = lab_tabs.LabSessions(lambda e: None, root=Path(tmp) / "lab",
                                            robot_options={"r0_reader": r0, "clock": clock})
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"), sessions=sessions)
            try:
                exp = win.experiment_tab
                exp.r0_root = Path(tmp) / "r0"
                rp = exp.robot_panel

                def settle():
                    self.pump(lambda: not exp.sessions.busy())
                    exp._update_guide()
                    self.app.processEvents()

                exp.rb_real.setChecked(True)
                exp.stage_buttons["R1"].setChecked(True)
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("pitch"))
                self.assertTrue(rp.connect_btn.isEnabled())  # one click: the connection reads the robot itself
                rp.connect_btn.click()
                self.pump(lambda: rp.state == "rest_torque_on" and rp.last_socket is not None)
                settle()
                s = exp.sessions.existing("robot")
                self.assertIsInstance(s.backend, SdkBackend)  # the production backend, not a test link
                self.assertEqual(rp.view["torque"], "ON")  # read back on the socket after the enable
                rp.wake_btn.click()
                self.pump(lambda: rp.state == "at_init")
                settle()
                self.assertEqual(d.log.count("goto"), 3)  # the SDK wake-up gotos
                self.assertTrue(exp.play_btn.isEnabled())
                c = exp._selected()
                self.assertEqual(c.trial.label, "r1_pitch_p10deg_rep1")  # default: the largest step
                exp.play_btn.click()
                self.pump(lambda: exp.status.get(f"robot:{c.trial.label}") in ("done", "anomaly", "refused", "stopped",
                                                                               "cancelled"))
                self.assertEqual(exp.status[f"robot:{c.trial.label}"], "done", exp.log_view.toPlainText()[-800:])
                self.assertGreater(d.log.count("set_full_target"), 250)  # streamed through SdkBackend.set_target
                run = Path(exp._finished[("robot", "R1")][-1])
                self.assertTrue((run / "present_measured.csv").exists())  # the robot path's label (temporary folder)
                settle()
                self.pump(rp.off_btn.isEnabled)
                rp.off_btn.click()
                self.pump(lambda: rp.state == "disconnected")
                self.assertFalse(d.b._torque_enabled)
                self.assertEqual(rp.view["torque"], "OFF")
                self.assertIn("disconnect", d.log)
            finally:
                stop.set()
                pusher.join(timeout=1.0)
                sessions.close()
                win.close()
                win.deleteLater()

    def test_click_through_status_connect_wake_up_trial_torque_off_on_the_harness(self):
        from reachy_motion.gui import lab_tabs
        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.model import EditorModel

        d = SdkDaemon(STARTS["sdk_sleep_pose_body3"], (-0.6, 0.6))
        made: list = []
        p1, p2 = unlocked()
        with tempfile.TemporaryDirectory() as tmp, p1, p2, mock.patch.object(lab_tabs, "ask_torque_off", lambda _p: True):
            sessions = lab_tabs.LabSessions(lambda e: None, root=Path(tmp) / "lab", robot_options={
                "link_factory": harness_link(d, made), "r0_reader": live_r0(d, R0_MET),
                "clock": TickClock(d)})
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"), sessions=sessions)
            try:
                exp = win.experiment_tab
                exp.r0_root = Path(tmp) / "r0"
                rp = exp.robot_panel
                exp.rb_real.setChecked(True)
                exp.stage_buttons["R1"].setChecked(True)
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("pitch"))  # R1 pitch, the largest step (10 deg)
                self.assertFalse(exp.play_btn.isEnabled())
                def settle():  # the session's job (and its automatic status read) is over, the buttons refreshed
                    self.pump(lambda: not exp.sessions.busy())
                    exp._update_guide()
                    self.app.processEvents()

                self.assertTrue(rp.connect_btn.isEnabled())
                rp.connect_btn.click()
                self.pump(lambda: rp.state == "rest_torque_on" and rp.last_socket is not None)
                settle()
                self.assertFalse(exp.play_btn.isEnabled())  # not woken up yet
                self.assertTrue(rp.wake_btn.isEnabled())
                rp.wake_btn.click()
                self.pump(lambda: rp.state == "at_init")
                settle()  # the automatic status read after the wake-up
                self.assertTrue(exp.play_btn.isEnabled())
                self.assertFalse(exp.run_all_btn.isEnabled())
                c = exp._selected()
                self.assertEqual(c.trial.label, "r1_pitch_p10deg_rep1")  # default: the largest step
                exp.play_btn.click()
                self.pump(lambda: exp.status.get(f"robot:{c.trial.label}") in ("done", "anomaly", "refused", "stopped"))
                self.assertEqual(exp.status[f"robot:{c.trial.label}"], "done", exp.log_view.toPlainText()[-800:])
                self.assertTrue(exp._finished.get(("robot", "R1")))
                self.assertIn("명령", exp.log_view.toPlainText())  # sent vs measured in the log
                self.assertIn("시행 끝 · 진폭비", rp.message.text())  # how much of the command the head did
                settle()
                # the Motion tab's '▶ 실제 로봇 재생': the shown motion once, as an R2 trial (same check / approval /
                # record), with the Experiment tab still on R1
                win.main_tabs.setCurrentWidget(win.motion_page)
                win._refresh_robot_play()
                self.assertTrue(win.robot_play_btn.isEnabled())
                self.assertIn("INIT", win.robot_state.text())
                win.robot_play_btn.click()
                label = "r2_success_expressive_rep1"
                self.pump(lambda: exp.status.get(f"robot:{label}") in ("done", "anomaly", "refused", "stopped"))
                self.assertEqual(exp.status[f"robot:{label}"], "done", exp.log_view.toPlainText()[-800:])
                runs = exp._finished.get(("robot", "R2"))
                self.assertTrue(runs and "_robot_R2" in Path(runs[-1]).parent.parent.name)
                self.assertIn("완료", win.play_state.text())
                settle()
                win._refresh_robot_play()
                self.assertTrue(win.robot_play_btn.isEnabled())  # back at INIT: the next motion can run
                self.pump(rp.off_btn.isEnabled)
                rp.off_btn.click()
                self.pump(lambda: rp.state == "disconnected")
                self.assertFalse(d.b._torque_enabled)
                self.assertIn("토크 OFF: OFF", rp.message.text())  # read back: disabled
                self.assertIn("연결 닫힘", rp.state_label.text())
            finally:
                sessions.close()
                win.close()
                win.deleteLater()


class TestConnectOutcomesAndTorqueView(unittest.TestCase):
    """What the GUI says after a connection attempt, a failed run and a Stop before the first command: only what is
    known (the sequence's report, read-backs). Harness, flags patched in this process."""

    def run_connect(self, d: SdkDaemon, r0: dict, wrap=None):
        made: list = []
        events: list[dict] = []
        p1, p2 = unlocked()
        with tempfile.TemporaryDirectory() as tmp, p1, p2:
            s = RobotLabSession(Path(tmp) / "lab", events.append, HOST, PORT, link_factory=harness_link(d, made, wrap),
                                r0_reader=live_r0(d, r0), clock=TickClock(d), r0_root=Path(tmp) / "r0")
            try:
                s.connect_robot(connect_approval(r0_fixture(r0)))
                wait_idle(s)
                return s, events, s.torque_view()
            finally:
                s.close()

    def test_the_outcome_follows_the_report(self):
        from reachy_motion.gui.robot_session import connect_outcome
        from reachy_motion.safety.approval import ApprovalError

        self.assertEqual(connect_outcome(None, {"stage": "ready"}), "connected")
        self.assertEqual(connect_outcome(NotImplementedError("locked"), None), "refused_before_send")
        self.assertEqual(connect_outcome(ApprovalError("expired"), None), "refused_before_send")
        self.assertEqual(connect_outcome(BackendError("x"), {"stage": "precondition", "torque_state": "never_on"}),
                         "refused_before_send")
        self.assertEqual(connect_outcome(OSError("constructor"), None), "failed_after_partial_send")
        self.assertEqual(connect_outcome(BackendError("x"), {"stage": "present", "torque_state": "never_on"}),
                         "failed_after_partial_send")
        self.assertEqual(connect_outcome(BackendError("x"), {"stage": "enable", "torque_state": "on",
                                                             "torque_enabled_by_us": True}), "failed_after_enable")
        self.assertEqual(connect_outcome(BackendError("x"), {"stage": "enable", "torque_state": "unknown"}),
                         "comm_lost_torque_unknown")
        # approved, connected, then the approval re-check failed: the torque was already enabled
        self.assertEqual(connect_outcome(ApprovalError("re-check"), {"stage": "ready", "torque_state": "on",
                                                                     "torque_enabled_by_us": True}),
                         "failed_after_enable")

    def test_failed_after_some_commands_keeps_the_last_read_back(self):
        d = awake_daemon()
        d.leave_tracking_on_with_a_lost_face()  # refused on the motion socket, after the constructor's commands
        s, events, view = self.run_connect(d, R0_AWAKE)
        failed = [e for e in events if e["kind"] == "robot_connect_failed"][-1]
        self.assertEqual((failed["outcome"], failed["nothing_sent"]), ("failed_after_partial_send", False))
        self.assertEqual(view["torque"], "ON")  # R0 GET read "enabled" and this connection sent no torque command
        self.assertTrue(view["link"].startswith("닫힘"))
        self.assertNotIn("refused", [e["kind"] for e in events])

    def test_failed_after_the_enable_is_unknown_and_the_torque_stays_on(self):
        from reachy_mini.utils import create_head_pose

        d = SdkDaemon(STARTS["tilt_body6"])
        nod = create_head_pose(pitch=math.radians(20), degrees=False).flatten().tolist()
        d.hooks.append(lambda dd: dd.b._torque_enabled and dd.command(SetFullTargetCmd(head=nod)))  # another client
        s, events, view = self.run_connect(d, R0_MET)
        failed = [e for e in events if e["kind"] == "robot_connect_failed"][-1]
        self.assertEqual(failed["outcome"], "failed_after_enable")
        self.assertEqual(view["torque"], "UNKNOWN")  # enable_motors() was sent; nothing read back since
        self.assertTrue(failed["operator_procedure"])
        self.assertTrue(d.b._torque_enabled)  # what the robot actually does: torque on, client closed
        self.assertTrue(view["link"].startswith("닫힘"))

    def test_a_link_lost_during_the_enable_is_unknown(self):
        def lose_link_at_enable(mini):
            def enable_motors(ids=None):
                raise ConnectionError("Lost connection with the server.")

            mini.enable_motors = enable_motors
            return mini

        d = SdkDaemon(STARTS["tilt_body6"])
        s, events, view = self.run_connect(d, R0_MET, wrap=lose_link_at_enable)
        failed = [e for e in events if e["kind"] == "robot_connect_failed"][-1]
        self.assertEqual(failed["outcome"], "comm_lost_torque_unknown")
        self.assertEqual(view["torque"], "UNKNOWN")
        self.assertTrue(failed["operator_procedure"])

    def test_a_run_lost_link_leaves_the_object_and_unknown_and_a_stop_before_sending_is_a_cancel(self):
        d = awake_daemon()
        made: list = []
        events: list[dict] = []
        p1, p2 = unlocked()
        with tempfile.TemporaryDirectory() as tmp, p1, p2:
            s = RobotLabSession(Path(tmp) / "lab", events.append, HOST, PORT,
                                link_factory=harness_link(d, made, fail_at=40, fail_with=BackendError("link lost")),
                                r0_reader=live_r0(d, R0_AWAKE), clock=TickClock(d),
                                r0_root=Path(tmp) / "r0")
            try:
                s.connect_robot(connect_approval(r0_fixture(R0_AWAKE)))
                wait_idle(s)
                self.assertEqual(s.torque_view()["torque"], "ON")  # awake: read "enabled" while connecting
                # Stop while the runner still checks that the head is still: no command at all -> cancelled
                ticks = [0]

                def stop_early(_d):
                    ticks[0] += 1
                    if ticks[0] == 10:
                        s.stop()

                d.hooks.append(stop_early)
                n_set, n_ev = d.log.count("set_full_target"), len(events)
                t = ex.r1_trial("pitch", 2.0)
                s.run_trial(t, Path(tmp) / "R1", approval=trial_approval(s, t))
                cancelled = wait_event(events, ("trial_cancelled", "trial_finished", "refused"), n_ev)
                wait_idle(s)
                d.hooks.remove(stop_early)
                self.assertEqual(cancelled["kind"], "trial_cancelled")
                self.assertEqual(d.log.count("set_full_target"), n_set)
                self.assertEqual(s.robot_state, "at_init")  # unchanged: not "holding"
                # a link lost in the middle of a run: torque UNKNOWN, the SDK object is still there
                t2 = ex.r1_trial("pitch", 2.0, rep=2)
                n_ev = len(events)
                s.run_trial(t2, Path(tmp) / "R1", approval=trial_approval(s, t2))
                done = wait_event(events, ("trial_finished", "refused", "trial_cancelled"), n_ev)
                wait_idle(s)
                self.assertEqual(done["kind"], "trial_finished")
                view = s.torque_view()
                self.assertEqual((s.robot_state, view["torque"]), ("holding", "UNKNOWN"))
                self.assertTrue(view["link"].startswith("SDK 객체 남음"))
                s.disconnect()
                wait_idle(s)
                gone = [e for e in events if e["kind"] == "robot_disconnected"][-1]
                self.assertIn("토크 OFF 아님", gone["link"])
                self.assertTrue(d.b._torque_enabled)  # a disconnect never turns the torque off
            finally:
                s.close()

    def test_a_silent_link_makes_the_torque_unknown_until_a_get_answers(self):
        import dataclasses

        d = awake_daemon()
        made: list = []
        r0 = {"v": r0_fixture(R0_AWAKE)}
        p1, p2 = unlocked()
        with tempfile.TemporaryDirectory() as tmp, p1, p2:
            s = RobotLabSession(Path(tmp) / "lab", None, HOST, PORT, link_factory=harness_link(d, made),
                                r0_reader=lambda h, p: r0["v"], clock=TickClock(d), r0_root=Path(tmp) / "r0")
            try:
                s.connect_robot(connect_approval(r0["v"]))
                wait_idle(s)
                self.assertEqual(s.torque_view()["torque"], "ON")
                live = made[0].present
                made[0].present = lambda: dataclasses.replace(live(), t_ns=s.clock.now_ns() - 5_000_000_000)
                r0["v"] = dict(r0_fixture(R0_AWAKE), derived=dict(R0_AWAKE["derived"], motor_mode=None))  # GET silent
                s.read_status()
                wait_idle(s)
                view = s.torque_view()
                self.assertEqual(view["torque"], "UNKNOWN")  # the earlier ON no longer counts
                self.assertTrue(view["link"].startswith("SDK 객체 남음 · 응답 없음"))
                r0["v"] = r0_fixture(R0_AWAKE)  # the REST GET answers "enabled"
                s.read_status()
                wait_idle(s)
                self.assertEqual(s.torque_view()["torque"], "ON")
                self.assertIn("R0 GET", s.torque_view()["torque_basis"])
            finally:
                s.close()

    def test_the_end_of_the_r3_ladder_is_shown_at_once(self):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import STATUS_COL, LabSessions
        from reachy_motion.gui.model import EditorModel

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"),
                             sessions=LabSessions(lambda e: None, root=Path(tmp) / "lab"))
            try:
                exp, rp = win.experiment_tab, win.experiment_tab.robot_panel
                exp.rb_real.setChecked(True)
                exp.stage_buttons["R3"].setChecked(True)
                d06 = next(c for c in exp.checks if abs(c.trial.condition["duration_s"] - 0.6) < 1e-9)
                why = "지연 보정 RMSE 3.40° = 진폭의 17.0% > 15%: 동작 모양이 무너짐"
                exp.on_lab_event({"kind": "trial_finished", "mode": "robot", "label": d06.trial.label, "stage": "R3",
                                  "completed": True, "metrics": {}, "robot": {"state": "at_init", "evidence": {}},
                                  "r3_next": {"amplitude_deg": 20.0, "duration_s": 0.6, "problems": [why]}})
                self.assertIn("R3 사다리 끝", rp.message.text())
                rows = {round(c.trial.condition["duration_s"], 2): i for i, c in enumerate(exp.checks)}
                self.assertEqual(exp.table.item(rows[0.4], STATUS_COL).text(), "거부")  # shorter steps are off
                self.assertIn("17.0%", exp.table.item(rows[0.4], STATUS_COL).toolTip())
                self.assertNotEqual(exp.table.item(rows[1.0], STATUS_COL).text(), "거부")  # longer ones stay
                exp.table.selectRow(rows[0.4])
                exp._update_guide()
                self.assertFalse(exp.play_btn.isEnabled())
                self.assertIn("R3 사다리 끝", exp.status_line.text())
                exp.on_lab_event({"kind": "robot_connected", "mode": "robot", "start_mode": "awake"})
                self.assertNotEqual(exp.table.item(rows[0.4], STATUS_COL).text(), "거부")  # a new connection: again
                app.processEvents()
            finally:
                win.close()
                win.deleteLater()

    def test_the_end_of_the_amplitude_ladder_refuses_larger_a(self):
        """2026-11-13: the amplitude ladder ends like the duration ladder - larger A at that D are refused."""
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import STATUS_COL, LabSessions
        from reachy_motion.gui.model import EditorModel

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"),
                             sessions=LabSessions(lambda e: None, root=Path(tmp) / "lab"))
            try:
                exp, rp = win.experiment_tab, win.experiment_tab.robot_panel
                exp.rb_real.setChecked(True)
                exp.stage_buttons["R3"].setChecked(True)
                exp.r3_vary.setCurrentIndex(1)  # A ladder at D 1 s: 10, 20, 30 deg
                rows = {round(c.trial.condition["amplitude_deg"]): i for i, c in enumerate(exp.checks)}
                self.assertEqual(sorted(rows), [10, 20, 30])
                self.assertIn("진폭 사다리", exp.checks[rows[20]].real_scope)
                a20 = exp.checks[rows[20]].trial
                why = "진폭비 0.70 < 0.8: 명령한 크기만큼 움직이지 못함"
                exp.on_lab_event({"kind": "trial_finished", "mode": "robot", "label": a20.label, "stage": "R3",
                                  "completed": True, "metrics": {}, "robot": {"state": "at_init", "evidence": {}},
                                  "r3_next": {"amplitude_deg": 20.0, "duration_s": 1.0, "vary": "amplitude",
                                              "problems": [why]}})
                self.assertIn("R3 진폭 사다리 끝 — A 20°", rp.message.text())
                self.assertEqual(exp.table.item(rows[30], STATUS_COL).text(), "거부")  # larger A: off
                self.assertNotEqual(exp.table.item(rows[10], STATUS_COL).text(), "거부")  # smaller A: may run
                exp.r3_vary.setCurrentIndex(0)  # the duration ladder (A 20 deg) is another ladder: not ended
                self.assertFalse(any(exp.table.item(i, STATUS_COL).text() == "거부" for i in range(exp.table.rowCount())
                                     if exp.checks[i].runnable))
                app.processEvents()
            finally:
                win.close()
                win.deleteLater()

    def test_the_panel_says_what_was_sent(self):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import STATUS_COL, LabSessions
        from reachy_motion.gui.model import EditorModel

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"),
                             sessions=LabSessions(lambda e: None, root=Path(tmp) / "lab"))
            try:
                exp, rp = win.experiment_tab, win.experiment_tab.robot_panel
                view = {"torque": "UNKNOWN", "torque_basis": "확인 안 됨 - x", "link": "닫힘 (연결 순서가 정리)"}
                exp._robot_event(dict(view, kind="robot_connect_failed", mode="robot", outcome="failed_after_enable",
                                      outcome_ko="토크 켜기(enable_motors)를 보낸 뒤 실패: 토크가 켜져 있을 수 있음",
                                      reasons=["BackendError: x"], nothing_sent=False))
                self.assertIn("연결 실패", rp.message.text())
                self.assertNotIn("보낸 것 없음", rp.message.text())
                exp._robot_event(dict(view, kind="robot_state", mode="robot", state="disconnected",
                                      operator_procedure="머리를 받친다"))
                self.assertIn("토크 <b", rp.state_label.text())
                self.assertIn("UNKNOWN", rp.state_label.text())
                self.assertIn("연결 닫힘", rp.state_label.text())
                exp.rb_real.setChecked(True)
                exp.stage_buttons["R1"].setChecked(True)
                label = exp.checks[0].trial.label
                exp._robot_event({"kind": "trial_cancelled", "mode": "robot", "label": label, "reason": "명령 0개"})
                self.assertEqual(exp.status[f"robot:{label}"], "cancelled")
                self.assertIn("실행 취소", exp.table.item(0, STATUS_COL).text())
                app.processEvents()
            finally:
                win.close()
                win.deleteLater()


if __name__ == "__main__":
    unittest.main()
