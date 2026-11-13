"""Step B (2026-11-12): held antennas at start-up (Mock), the R1 readiness classification, and the R1 runner on the
Mock and against the hermetic fake daemon (127.0.0.1, no socket: tests/test_daemon_client.FakeDaemon). Nothing here
can reach the robot; no approval file is created."""

from __future__ import annotations

import contextlib
import io
import json
import math
import socket
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

from reachy_motion import r1_readiness, robot_r1
from reachy_motion.backends.mock import MockBackend
from reachy_motion.executor.clock import VirtualClock
from reachy_motion.executor.executor import Executor
from reachy_motion.library.pose import Pose6, RobotState
from reachy_motion.startup_procedure import run_startup

R0_ANT_DEG = (157.061, 130.078)  # the robot's limp antennas, R0 2026-11-11 21:40
R0_POSE = {"x_mm": -21.774, "y_mm": 4.435, "z_mm": -45.876, "roll_deg": 2.646, "pitch_deg": 28.958, "yaw_deg": -2.061}


def r0_like(**changes: object) -> dict:
    """An R0 report shaped like robot_r0's, with the 2026-11-11 readings (a fixture, not a daemon answer)."""
    rep = {"stage": "R0", "daemon_url": "http://192.168.0.15:8000", "data_kind": "test_fixture",
           "generated_local": datetime.now().isoformat(timespec="seconds"), "blocking": False,
           "derived": {"daemon_version": "1.11.0", "daemon_state": "running", "motor_mode": "disabled",
                       "head_pose": dict(R0_POSE), "body_yaw_deg": -1.846, "antennas_deg": list(R0_ANT_DEG),
                       "joints": {"min_stewart_margin_deg": 15.95, "ik_of_pose_vs_joints_max_deg": 0.086}},
           "findings": [{"level": "info", "code": "motors_disabled", "message": "limp"}]}
    rep.update(changes)
    return rep


class TestHeldAntennasOnTheMock(unittest.TestCase):
    def test_start_up_from_the_r0_pose_never_moves_the_antennas(self):
        start = robot_r1.r0_state(r0_like())
        clock = VirtualClock()
        backend = MockBackend(clock=clock, structure="robot", lag_tau_s=0.05, start=start)
        backend.connect()
        self.addCleanup(backend.close)
        rep, res = run_startup(backend, Executor(backend, clock=clock), antennas="hold")
        self.assertTrue(rep.ok, rep.problems)
        ant = np.array([c.record.antennas for c in res.commands])
        self.assertEqual(float(np.max(np.abs(ant - np.array(start.antennas)))), 0.0)
        self.assertLess(rep.end_error["head_rotation_deg"], 0.5)  # the head went to REST
        self.assertLess(rep.end_error["antennas_deg"], 1e-6)  # against the held pair
        far = (start.antennas[0] + math.radians(3.0), start.antennas[1])  # 3 deg > ANTENNA_HOLD_TOL_DEG
        rep, res = run_startup(backend, Executor(backend, clock=clock), antennas=far)
        self.assertEqual((rep.ok, rep.stage, res), (False, "plan", None))  # refused before any command
        self.assertIn("does not move the antennas", rep.problems[0])


class TestR1Readiness(unittest.TestCase):
    def test_four_kinds_and_never_verified(self):
        """2026-11-12 categories: automatic (R0) / established by the connection / operator-controlled (confirmed
        right before the connection) / residual - the other-client risk always among the residual ones."""
        a = r1_readiness.assess(r0_like(data_kind="measured"))
        self.assertEqual(a["verdict"], "conditional")
        by: dict[str, list[str]] = {}
        for row in a["rows"]:
            by.setdefault(row["category"], []).append(row["status"])
        self.assertEqual(list(by), ["auto", "connection", "operator", "residual"])
        self.assertTrue(set(by["auto"]) <= {"ok", "attention"})
        self.assertEqual(by["connection"], ["by_connection"] * 2)  # tracking off, partial torque
        self.assertEqual(set(by["operator"]), {"operator_confirms"})
        self.assertEqual(by["residual"], ["residual"] * 2)  # other client, antenna convention
        self.assertIn("other_client", [r["key"] for r in a["rows"] if r["category"] == "residual"])
        self.assertIn("통제할 수 없으면 실행하지 않음", a["verdict_ko"])
        self.assertNotIn("met", json.dumps(a))  # no "verified / met" wording anywhere

    def test_blocking_states(self):
        old = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
        cases = {"stale": r0_like(data_kind="measured", generated_local=old),
                 "fixture_not_measured": r0_like(),
                 "loopback": r0_like(data_kind="measured", daemon_url="http://127.0.0.1:8000"),
                 "torque_on": r0_like(data_kind="measured", derived=dict(r0_like()["derived"], motor_mode="enabled")),
                 "tracking_on": r0_like(data_kind="measured", findings=[
                     {"level": "block", "code": "head_tracking_active", "message": "face_target set"}])}
        for name, rep in cases.items():
            with self.subTest(case=name):
                self.assertEqual(r1_readiness.assess(rep)["verdict"], "blocked")
        self.assertEqual(r1_readiness.assess(None)["verdict"], "blocked")


def filled(request) -> object:
    """An approval built in code from the printed template (content checks only: the robot gate refuses it - no
    file - as tests/test_approval.make_approval says). No approval file is created."""
    from reachy_motion.safety.approval import RobotApproval, approval_template

    t = approval_template(request)
    t.update(approval_id="TEST-1", approved_by="unit test", approved_on=datetime.now().date().isoformat(),
             expires=(datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds"),
             max_stewart_speed_ratio=0.1, min_stewart_margin_deg=12.0)
    return RobotApproval(**{k: v for k, v in t.items() if k in RobotApproval.__dataclass_fields__})


class TestR1Runner(unittest.TestCase):
    def test_mock_run_records_the_three_parts_bound_by_the_two_approvals(self):
        from reachy_motion.gui.results import load_result

        plan = robot_r1.build("pitch:+2", 1, r0_like())
        self.assertTrue(plan.runnable)
        for prep in plan.parts:  # antennas held in all three
            ant = np.asarray(prep.timeline.antennas)
            self.assertEqual(float(np.max(np.abs(ant - np.radians(R0_ANT_DEG)))), 0.0)
        ramp, trial = robot_r1.ramp_request(plan, "192.168.0.15"), robot_r1.trial_request(plan, "192.168.0.15")
        with tempfile.TemporaryDirectory() as d:
            clock = VirtualClock()
            backend = MockBackend(clock=clock, structure="robot", start=plan.start)
            backend.connect()
            try:
                out = robot_r1.run_trial(backend, plan, Path(d) / "session", clock=clock, connection={"mode": "mock"})
            finally:
                backend.close()
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["stage"], "returned")
            self.assertEqual(tuple(out["digests"]), ramp.timeline_digests[:1] + trial.timeline_digests
                             + ramp.timeline_digests[1:])  # what ran is what the two approvals bind
            self.assertFalse(out["torque_off_sent"])  # the Mock has no torque: none is sent or claimed
            self.assertLess(out["end_gap"]["rotation_deg"], 0.5)  # back at the resting pose
            run = Path(out["run_dir"])
            self.assertTrue({p.name for p in run.iterdir()} >= {"commands.csv", "present_mock.csv", "ticks.csv",
                                                                "manifest.json", "metrics.json", "README.md"})
            self.assertEqual(load_result(run).data_kind, "mock")
            self.assertEqual(sorted(Path(p).name for p in out["runs"].values()),
                             ["01_r1_startup_ramp", "02_r1_pitch_p2deg_rep1", "03_r1_return_ramp"])
            ramp_run = load_result(out["runs"][robot_r1.RAMP_LABEL])  # the R1-0 ramp: its own record
            self.assertEqual((ramp_run.data_kind, ramp_run.condition["approval"]), ("mock", "R1-0"))
            self.assertEqual((ramp_run.condition["stewart_travel_max_deg"], ramp_run.condition["stewart_travel_joint"]),
                             (89.9, "stewart_5"))
            self.assertTrue((Path(d) / "session" / "session_r1_pitch_p2deg_rep1.json").is_file())

    def test_a_start_that_moved_since_the_approved_r0_is_refused_before_any_command(self):
        plan = robot_r1.build("pitch:+2", 1, r0_like())
        moved = RobotState(head=plan.start.head, antennas=(plan.start.antennas[0] + math.radians(5.0),
                                                          plan.start.antennas[1]), body_yaw=plan.start.body_yaw)
        with tempfile.TemporaryDirectory() as d:
            backend = MockBackend(structure="robot", start=moved)
            backend.connect()
            try:
                out = robot_r1.run_trial(backend, plan, Path(d) / "session")
            finally:
                backend.close()
            self.assertEqual((out["ok"], out["stage"]), (False, "start"))
            self.assertEqual(backend.commands if hasattr(backend, "commands") else [], [])

    def test_c1_on_the_mock_sends_nothing_and_the_first_ramp_sample_is_the_present_state(self):
        from reachy_motion.startup_procedure import watch_still

        plan = robot_r1.build("pitch:+2", 1, r0_like())
        clock = VirtualClock()
        backend = MockBackend(clock=clock, structure="robot", start=plan.start)
        backend.connect()
        self.addCleanup(backend.close)
        still, drift, n = watch_still(backend, clock, 3.0)  # C1's hold, as the runner would watch it
        self.assertTrue(still and drift == 0.0 and n > 100)
        self.assertEqual(getattr(backend, "commands", []), [])
        first = plan.ramp.timeline
        p = backend.present()
        self.assertLess(float(np.max(np.abs(np.asarray(p.head) - first.head[0]))), 1e-9)
        self.assertEqual(tuple(first.antennas[0]), tuple(p.antennas))

    def test_approval_requests_pass_the_gate_content_checks(self):
        from reachy_motion.safety.approval import validate_approval

        rep = r0_like()
        plan = robot_r1.build("antenna_right:+5", 2, rep)
        ramp, trial = robot_r1.ramp_request(plan, "192.168.0.15"), robot_r1.trial_request(plan, "192.168.0.15")
        self.assertEqual(ramp.motions, ("R1:startup_hold", "R1:return_hold"))  # R1-0: approved separately
        self.assertEqual(trial.motions, ("R1:r1_antenna_right_p5deg_rep2",))
        for req in (ramp, trial):
            self.assertEqual(validate_approval(filled(req), req), [])
        self.assertTrue(validate_approval(filled(ramp), trial))  # one approval never stands for the other
        self.assertNotEqual(ramp.reports[0].policy.name, trial.reports[0].policy.name)  # start-up vs default policy
        self.assertIn("89.9 deg (stewart_5)", robot_r1.ramp_summary(plan))  # shown before the confirmation
        moved = np.degrees(np.ptp(np.asarray(plan.run.timeline.antennas), axis=0))
        self.assertTrue(np.allclose(moved, [5.0, 0.0]))  # one antenna, 5 deg, from where R0 read it
        c1 = robot_r1.c1_request(rep, "192.168.0.15")
        self.assertEqual(c1.motions, (robot_r1.C1_KEY,))
        self.assertEqual(validate_approval(filled(c1), c1), [])
        self.assertEqual(c1.reports[0].metrics["peak_stewart_speed_ratio"] < 1e-9, True)  # C1 commands no motion

    def test_robot_target_on_a_fake_daemon_stops_before_any_approval_or_connection(self):
        from reachy_motion import cli
        from reachy_motion.backends import sdk
        from tests.test_daemon_client import FakeDaemon
        from tests.test_phase4_tools import disabled

        for cmd in (["robot-r1", "--r1", "pitch:+2"], ["robot-c1"]):
            with self.subTest(cmd=cmd[0]):
                fake = FakeDaemon(disabled())
                with tempfile.TemporaryDirectory() as d, fake.patch(), \
                        mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                        mock.patch.object(sdk.SdkBackend, "connect", side_effect=AssertionError("connect called")):
                    ref = Path(d) / "r0.json"
                    ref.write_text(json.dumps(r0_like()), encoding="utf-8")
                    args = cmd + ["--r0", str(ref), "--host", "127.0.0.1", "--preflight-out", str(Path(d) / "pre")]
                    if cmd[0] == "robot-r1":
                        args += ["--target", "robot", "--out", str(Path(d) / "lab")]
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        code = cli.main(args)
                    self.assertEqual(code, 2)  # blocked: a loopback daemon is not the robot
                    self.assertFalse((Path(d) / "lab").exists())  # no run folder, nothing recorded
                    pre = next((Path(d) / "pre").iterdir())
                    saved = json.loads((pre / "preflight.json").read_text(encoding="utf-8"))
                    self.assertEqual(saved["data_kind"], robot_r1.FAKE_KIND)  # never "measured"
                    self.assertEqual(json.loads((pre / "r0_report.json").read_text(encoding="utf-8"))["data_kind"],
                                     robot_r1.FAKE_KIND)
                    self.assertEqual(saved["assessment"]["verdict"], "blocked")
                self.assertTrue(fake.requests and all(r.get_method() == "GET" for r in fake.requests))
        self.assertTrue(robot_r1.ROBOT_RUN_ENABLED)  # released 2026-11-12: the loopback daemon is refused before it


class TestR2R3Paths(unittest.TestCase):
    """R2 (confirmed E/N motions) and R3 (one duration step at a time) through the same runner (2026-11-12)."""

    def run_mock(self, plan, d: Path) -> dict:
        clock = VirtualClock()
        backend = MockBackend(clock=clock, structure="robot", start=plan.start)
        backend.connect()
        try:
            return robot_r1.run_trial(backend, plan, d, clock=clock, connection={"mode": "mock"})
        finally:
            backend.close()

    def test_r2_refuses_unmatched_antennas_and_runs_the_held_head_only_trial(self):
        from reachy_motion.gui.results import load_result
        from reachy_motion.safety.approval import validate_approval

        rep = r0_like()
        with self.assertRaisesRegex(ValueError, "does not move the antennas"):  # never moved to rest automatically
            robot_r1.r2_plan("aha_recommend", "expressive", 1, rep)
        plans = [robot_r1.r2_plan(m, v, 1, rep, hold=True) for m in robot_r1.R2_DEFAULT_MOTIONS
                 for v in ("expressive", "neutral")]
        e = plans[0]
        self.assertTrue(all(p.runnable for p in plans))
        self.assertEqual((e.trial.label, e.trial.condition["antenna_keys_removed"]),
                         ("r2_aha_recommend_expressive_rep1_antheld", 5))
        self.assertEqual(float(np.max(np.ptp(np.asarray(e.run.timeline.antennas), axis=0))), 0.0)  # held, not moved
        from dataclasses import replace as dc_replace

        whole = robot_r1.trials_request(plans, "192.168.0.15")  # one approval for the 3 E/N pairs
        self.assertEqual((whole.stage, len(whole.motions)), ("R2", 6))
        low = filled(whole)  # the person's speed cap decides: 0.1 refuses aha E (computed 0.36)
        self.assertTrue(validate_approval(low, robot_r1.trial_request(e, "192.168.0.15")))
        for p in plans:
            self.assertEqual(validate_approval(dc_replace(low, max_stewart_speed_ratio=0.5),
                                               robot_r1.trial_request(p, "192.168.0.15")), [])
        self.assertEqual(robot_r1.ramp_request(e, "h").timeline_digests,
                         robot_r1.ramp_request(robot_r1.build("pitch:+2", 1, rep), "h").timeline_digests)  # same R1-0
        with tempfile.TemporaryDirectory() as d:
            out = self.run_mock(e, Path(d))
            self.assertTrue(out["ok"], out["problems"])
            self.assertEqual(load_result(out["run_dir"]).stage, "R2")
            self.assertEqual(len(out["runs"]), 3)

    def test_r3_goes_one_step_at_a_time(self):
        rep = r0_like()
        base = robot_r1.r3_plan(20, 1.0, 1, rep, hold=True)
        self.assertEqual(robot_r1.r3_step_problems(base, None, robot=False), [])
        nxt = robot_r1.r3_plan(20, 0.6, 1, rep, hold=True)
        self.assertIn("--after", robot_r1.r3_step_problems(nxt, None, robot=False)[0])
        self.assertTrue(robot_r1.r3_step_problems(robot_r1.r3_plan(20, 0.2, 1, rep, hold=True), None, robot=True))
        self.assertTrue(any("outside the real-robot scope" in p for p in robot_r1.r3_step_problems(
            robot_r1.r3_plan(20, 0.15, 1, rep, hold=True), None, robot=True)))
        with tempfile.TemporaryDirectory() as d:
            out = self.run_mock(base, Path(d))
            self.assertTrue(out["ok"], out["problems"])
            self.assertEqual(robot_r1.r3_step_problems(nxt, out["run_dir"], robot=False), [])  # reviewed, no anomaly
            self.assertEqual(robot_r1.r3_next_step_problems(out["run_dir"]), [])  # the verdict the GUI shows at once
            self.assertEqual(robot_r1.r3_next_step_problems(out["run_dir"], out["run_dir"], lang="ko"), [])  # = its base
            skip = robot_r1.r3_plan(20, 0.4, 1, rep, hold=True)
            self.assertIn("D 0.6 s", " ".join(robot_r1.r3_step_problems(skip, out["run_dir"], robot=False)))
            other = robot_r1.r3_plan(10, 0.6, 1, rep, hold=True)
            self.assertIn("one setting at a time", " ".join(robot_r1.r3_step_problems(other, out["run_dir"], False)))
            self.assertIn("measurement", " ".join(robot_r1.r3_step_problems(nxt, out["run_dir"], robot=True)))

    def test_r3_amplitude_ladder_goes_from_small_to_large(self):
        """2026-11-13 (user decision): the amplitude ladder mirrors the duration ladder - small A first, one step at a
        time after the previous step's result; on the robot at D >= 1 s only (a large A in a short D exceeds the
        acceleration the robot has run: A 30 deg in 0.2 s = 3521 deg/s^2 > 2941, computed)."""
        from reachy_motion.gui import experiments as ex

        self.assertEqual(robot_r1.R3_BASE_A_DEG, ex.R3_DEFAULT_AMPLITUDES[0])

        def plan(a: float, d: float = 1.0):
            return robot_r1.build_plan(ex.r3_trial(a, d, vary="amplitude"), None, awake=True)

        self.assertEqual(robot_r1.r3_step_problems(plan(10), None, robot=True), [])  # the base step
        self.assertIn("--after", " ".join(robot_r1.r3_step_problems(plan(20), None, robot=False)))
        self.assertTrue(any("D >= 1 s" in p for p in robot_r1.r3_step_problems(plan(10, 0.4), None, robot=True)))
        self.assertEqual(robot_r1.r3_step_problems(plan(10, 0.4), None, robot=False), [])  # MuJoCo: any D
        with tempfile.TemporaryDirectory() as d:
            out = self.run_mock(plan(10), Path(d))
            self.assertTrue(out["ok"], out["problems"])
            self.assertEqual(robot_r1.r3_step_problems(plan(20), out["run_dir"], robot=False), [])
            self.assertIn("A 20 deg", " ".join(robot_r1.r3_step_problems(plan(30), out["run_dir"], robot=False)))
            self.assertIn("one setting at a time",
                          " ".join(robot_r1.r3_step_problems(plan(20, 0.6), out["run_dir"], robot=False)))
            self.assertIn("measurement", " ".join(robot_r1.r3_step_problems(plan(20), out["run_dir"], robot=True)))
            ko = robot_r1.r3_step_problems(plan(30), out["run_dir"], robot=True, lang="ko")
            self.assertTrue(any("A 30°의 앞 단계는 A 20°" in p for p in ko), ko)
            back = robot_r1.r3_step_problems(plan(10), out["run_dir"], robot=False)  # never back down the ladder
            self.assertTrue(any("smaller" in p for p in back), back)

    def test_robot_r2_r3_need_a_clean_measured_c1_and_r1(self):
        c1 = {"data_kind": "measured", "ok": True, "torque_state": "off"}
        head = {"data_kind": "measured", "ok": True, "torque_state": "off", "trial": "r1_pitch_p2deg_rep1"}
        ant = [dict(head, trial=f"r1_antenna_{s}_p5deg_rep1") for s in ("right", "left")]
        self.assertEqual(len(robot_r1.prerequisite_problems(None, [], False)), 2)
        self.assertEqual(robot_r1.prerequisite_problems(c1, [head], False), [])
        self.assertEqual(len(robot_r1.prerequisite_problems(c1, [head], True)), 1)  # antennas unverified
        self.assertEqual(robot_r1.prerequisite_problems(c1, [head] + ant, True), [])
        for bad_c1, bad_r1 in ((dict(c1, torque_state="on"), head), (c1, dict(head, data_kind="mock")),
                               (c1, dict(head, ok=False))):
            self.assertTrue(robot_r1.prerequisite_problems(bad_c1, [bad_r1], False))


def awake_r0(**derived: object) -> dict:
    """An R0 fixture of a robot woken the usual way (torque on, at INIT); ``derived`` overrides fields."""
    d = dict(r0_like()["derived"], motor_mode="enabled", head_pose={k: 0.0 for k in R0_POSE}, body_yaw_deg=0.0,
             antennas_deg=[-9.998, 9.998], distance_to_rest={"rotation_deg": 0.0, "translation_mm": 0.0})
    d.update(derived)
    return r0_like(data_kind="measured", derived=d, findings=[{"level": "info", "code": "motors_enabled",
                                                              "message": "torque on"}])


class TestAwakeEntry(unittest.TestCase):
    def test_awake_is_its_own_start_and_the_sleep_start_is_unchanged(self):
        from reachy_motion.robot_r0 import r1_entry

        rep = awake_r0()
        awake = r1_entry(rep, "awake")
        self.assertEqual(awake["verdict"], "conditional")
        self.assertEqual({c["name"] for c in awake["conditions"] if c["category"] == "auto" and c["status"] == "met"},
                         {"r0_not_blocking", "measured_robot", "motors_enabled", "tracking_not_seen_on", "at_init"})
        self.assertEqual(r1_entry(rep)["verdict"], "blocked")  # the limp start still needs the motors off
        self.assertEqual(r1_entry(r0_like(data_kind="measured"), "awake")["verdict"], "blocked")  # limp: not awake
        sagged = awake_r0(distance_to_rest={"rotation_deg": 4.1, "translation_mm": 3.0})  # HW3-like sag: allowed
        self.assertEqual(r1_entry(sagged, "awake")["verdict"], "conditional")
        far = awake_r0(distance_to_rest={"rotation_deg": 15.0, "translation_mm": 3.0})
        self.assertEqual(r1_entry(far, "awake")["verdict"], "blocked")
        rows = {r["key"]: r["status"] for r in r1_readiness.assess(rep, mode="awake")["rows"]}
        self.assertEqual((rows["motors_enabled"], rows["init_pose"]), ("ok", "ok"))
        self.assertEqual(r1_readiness.assess(rep)["verdict"], "blocked")  # default (sleep) display unchanged

    def test_the_r0_assessment_follows_the_awake_start(self):
        """A robot with the motors on is judged by the AWAKE criteria (the CLI path; the GUI copy box was removed in
        the 2026-11-12 declutter)."""
        self.assertEqual((r1_readiness.start_mode(awake_r0()), r1_readiness.start_mode(r0_like())), ("awake", "sleep"))
        rep = awake_r0()
        self.assertEqual(r1_readiness.assess(rep, mode=r1_readiness.start_mode(rep))["verdict"], "conditional")

    def test_awake_r2_r3_need_a_clean_r1_but_no_c1(self):
        head_on = {"data_kind": "measured", "ok": True, "torque_state": "on", "trial": "r1_pitch_p2deg_rep1"}
        self.assertEqual(robot_r1.prerequisite_problems(None, [head_on], False, awake=True), [])
        self.assertTrue(robot_r1.prerequisite_problems(None, [], False, awake=True))  # R1 first
        with self.assertRaisesRegex(ValueError, "AWAKE"):
            robot_r1.r2_plan("aha_recommend", "expressive", 1, r0_like(), hold=True, awake=True)


class TestRobotPathWiring(unittest.TestCase):
    """The robot branch of robot-c1 / robot-r1 past the approval gate, offline (2026-11-12). Stand-ins: the preflight
    (an in-memory R0 fixture, no daemon) and the approval gates (no approval file exists or is created); the client
    is the SDK harness (tests/test_sdk_offline_connect). ``ROBOT_RUN_ENABLED`` is True since 2026-11-12 (user decision);
    the tests that check the stop at the switch turn it off with mock.patch only; the network is blocked."""

    def setUp(self) -> None:
        from reachy_motion.analysis.goto_replay import ik_joints
        from tests.test_sdk_offline_connect import KIN, SdkDaemon, TickClock

        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.ref = self.tmp / "r0.json"
        self.ref.write_text(json.dumps(r0_like()), encoding="utf-8")
        fresh = r0_like(data_kind="measured", requests="GET only (test fixture: no daemon)")  # the preflight's R0
        self.pre = {"report": fresh, "assessment": r1_readiness.assess(fresh), "gaps": {}}
        start = robot_r1.r0_state(fresh)
        self.daemon = SdkDaemon(np.asarray(ik_joints(KIN, start.head.matrix(), start.body_yaw), float), start.antennas)
        self.clock = TickClock(self.daemon)
        self.made: list[object] = []
        self.gates: list[tuple] = []
        self.enterContext(mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")))
        self.enterContext(mock.patch.object(robot_r1, "preflight", return_value=self.pre))

    def make_client(self, host: str, port: int, **kw: object) -> object:
        from tests.test_sdk_offline_connect import Mini

        self.made.append(Mini(self.daemon, self.clock, host, port, **kw))
        return self.made[-1]

    def stand_in_gates(self, held: dict | None = None):
        def gates(args, g):  # records what would be confirmed, confirms nothing itself
            self.gates.extend(g)
            return held or {}
        return mock.patch("reachy_motion.cli_phase4._approval_gates", side_effect=gates)

    def c1(self, **kw: object) -> int:
        from reachy_motion import cli, cli_phase4

        args = cli.build_parser().parse_args(["robot-c1", "--r0", str(self.ref), "--preflight-out",
                                              str(self.tmp / "pre")])
        with contextlib.redirect_stdout(io.StringIO()):
            return cli_phase4.cmd_robot_c1(args, make_client=self.make_client, clock=self.clock, data_kind="computed",
                                           **kw)

    def decision(self) -> dict:
        return json.loads(next((self.tmp / "pre").iterdir()).joinpath("preflight.json").read_text(encoding="utf-8"))

    def test_the_run_switch_off_stops_after_the_gate(self):
        with self.stand_in_gates(), mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", False):
            self.assertEqual(self.c1(confirm_env=lambda a: self.fail("asked past the lock")), 3)
        self.assertEqual((self.made, self.daemon.log), ([], []))  # no client, nothing sent
        self.assertEqual(self.decision()["decision"], "approvals confirmed; robot run disabled")

    def test_no_run_without_the_operator_confirmation(self):
        with self.stand_in_gates(), mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", True):
            self.assertEqual(self.c1(confirm_env=lambda a: {"confirmed": False}), 5)
        self.assertEqual((self.made, self.daemon.log), ([], []))
        self.assertIn("did not confirm the controlled environment", self.decision()["decision"])

    def test_c1_runs_its_stage_and_records_it(self):
        seen: list[dict] = []
        with self.stand_in_gates(), mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", True):
            code = self.c1(confirm_env=lambda a: seen.append(a) or {"confirmed": True, "by": "test"},
                           confirm_off=lambda p: self.fail("a clean C1 asks nothing"))
        self.assertEqual(code, 0)
        self.assertEqual([g[0] for g in self.gates], ["C1"])
        self.assertEqual({r["category"] for r in seen[0]["rows"]}, {"auto", "connection", "operator", "residual"})
        rec = json.loads(next((self.tmp / "pre").iterdir()).joinpath("c1_report.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["data_kind"], rec["ok"], rec["torque_state"]), ("computed", True, "off"))
        self.assertEqual(rec["residual_risks"], ["other_client"])
        self.assertEqual(rec["what"]["operator_environment"], {"confirmed": True, "by": "test"})
        self.assertEqual(self.daemon.log.count("set_torque"), 2)  # our enable and our torque-off
        self.assertFalse(self.daemon.b._torque_enabled)

    def test_r1_asks_two_approvals_then_stops_at_the_backend_lock(self):
        from reachy_motion import cli, cli_phase4
        from reachy_motion.backends.sdk import ROBOT_NOT_IN_PHASE2

        class Locked:  # stands for the SdkBackend the R1-0 gate returns: its connect() is the Phase 2 lock
            operator_confirmed = False

            def connect(self) -> None:
                raise NotImplementedError(ROBOT_NOT_IN_PHASE2)

        locked = Locked()
        args = cli.build_parser().parse_args(["robot-r1", "--r1", "pitch:+2", "--r0", str(self.ref), "--target",
                                              "robot", "--preflight-out", str(self.tmp / "pre"), "--out",
                                              str(self.tmp / "lab")])
        with self.stand_in_gates({"R1-0": locked, "R1": object()}), \
                mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", True), \
                contextlib.redirect_stdout(io.StringIO()):
            code = cli_phase4.cmd_robot_r1(args, confirm_env=lambda a: {"confirmed": True})
        self.assertEqual(code, 3)
        self.assertEqual([g[0] for g in self.gates], ["R1-0", "R1"])  # the ramps, then the trial
        self.assertEqual(self.gates[0][1].motions, ("R1:startup_hold", "R1:return_hold"))
        self.assertIn("NOT a small motion", self.gates[0][3])
        self.assertIn("Stewart joint travel up to 89.9 deg (stewart_5)", self.gates[0][3])
        self.assertEqual(self.gates[1][1].motions, ("R1:r1_pitch_p2deg_rep1",))
        self.assertTrue(locked.operator_confirmed)
        self.assertFalse((self.tmp / "lab").exists())  # nothing ran, nothing recorded
        self.assertIn("SdkBackend locked", self.decision()["decision"])

    def test_awake_runs_ask_only_the_trial_approval_then_stop_at_the_lock(self):
        from reachy_motion import cli

        rep = dict(awake_r0(), requests="GET only (test fixture: no daemon)")
        awake_pre = {"report": rep, "assessment": r1_readiness.assess(rep, mode="awake"), "gaps": {}}
        self.assertEqual(awake_pre["assessment"]["verdict"], "conditional")
        ref = self.tmp / "r0_awake.json"
        ref.write_text(json.dumps(rep), encoding="utf-8")
        for argv, stage in ((["robot-r1", "--r1", "pitch:+2"], "R1"),
                            (["robot-r2", "--motion", "aha_recommend", "--variant", "expressive"], "R2")):
            with self.subTest(stage=stage):
                self.gates.clear()
                args = cli.build_parser().parse_args(argv + ["--start", "awake", "--r0", str(ref), "--target", "robot",
                                                             "--preflight-out", str(self.tmp / "pre"), "--out",
                                                             str(self.tmp / "lab")])
                with self.stand_in_gates(), contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.object(robot_r1, "preflight", return_value=awake_pre) as pf, \
                        mock.patch.object(robot_r1, "check_prerequisites", return_value=[]), \
                        mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", False):
                    self.assertEqual(args.func(args), 3)  # the run switch off: stops after the gates
                self.assertEqual(pf.call_args.kwargs["mode"], "awake")
                self.assertEqual([g[0] for g in self.gates], [stage])  # no R1-0 ramp approval in AWAKE
                self.assertEqual(len(self.gates[0][1].motions), 1)
        self.assertEqual((self.made, self.daemon.log), ([], []))
        self.assertFalse((self.tmp / "lab").exists())

    def test_r2_and_r3_reach_the_same_gates_then_stop_at_the_lock(self):
        from reachy_motion import cli, cli_phase4

        common = ["--r0", str(self.ref), "--antennas", "hold", "--target", "robot", "--preflight-out",
                  str(self.tmp / "pre"), "--out", str(self.tmp / "lab")]
        for argv, stage, motion in ((["robot-r2", "--motion", "boredom", "--variant", "neutral"], "R2",
                                     "R2:r2_boredom_neutral_rep1_antheld"),
                                    (["robot-r3", "--duration", "1.0"], "R3", "R3:r3_pitch20_D1.00_rep1_antheld")):
            with self.subTest(stage=stage):
                self.gates.clear()
                args = cli.build_parser().parse_args(argv + common)
                with self.stand_in_gates(), contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.object(robot_r1, "check_prerequisites", return_value=[]), \
                        mock.patch.object(robot_r1, "ROBOT_RUN_ENABLED", False):
                    code = args.func(args)
                self.assertEqual(code, 3)  # the run switch off: stops after the gates
                self.assertEqual([g[0] for g in self.gates], ["R1-0", stage])
                self.assertEqual(self.gates[1][1].motions, (motion,))
                self.assertEqual((self.made, self.daemon.log), ([], []))
        self.assertFalse((self.tmp / "lab").exists())


if __name__ == "__main__":
    unittest.main()
