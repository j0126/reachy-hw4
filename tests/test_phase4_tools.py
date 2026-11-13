"""Phase 4 preparation tools: the R0 read-only check (robot_r0, `robot-status`) and the `tracking` command.

Hermetic like tests/test_daemon_client.py: urllib's transport is replaced by its FakeDaemon and opening a socket fails
the test, so no request can reach a daemon or the robot.
"""

from __future__ import annotations

import ast
import contextlib
import csv
import inspect
import io
import json
import math
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import numpy as np

from reachy_motion import robot_r0
from reachy_motion.backends.daemon_client import ALLOWED_GET_PATHS, HEAD_JOINTS_QUERY, DaemonClient
from reachy_motion.robot_r0 import collect, evaluate, run_r0
from tests.test_daemon_client import BASE, FULL_STATE, HOST, ROBOT_STATUS, ROUTES, SIM_STATUS, FakeDaemon

DEG = math.pi / 180.0


def setUpModule() -> None:
    unittest.enterModuleContext(mock.patch.object(
        socket, "create_connection", side_effect=AssertionError("network access in a hermetic test")))


def ik(pose: dict[str, float], body_yaw: float) -> list[float]:
    from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics
    from reachy_motion.library.pose import Pose6

    p = Pose6(*(pose[k] for k in ("x", "y", "z", "roll", "pitch", "yaw")))
    return [float(v) for v in ik_joints(new_kinematics(), p.matrix(), body_yaw)]


def snapshot(pose: dict[str, float], body_yaw: float = 0.0, joints: list[float] | None = None) -> dict[str, object]:
    """/api/state/full?with_head_joints=true answer: pose and (by default IK-consistent) joints of one instant."""
    return dict(FULL_STATE, head_pose=pose, body_yaw=body_yaw,
                head_joints=ik(pose, body_yaw) if joints is None else joints)


def routes(**changes: object) -> dict[str, object]:
    """ROUTES with a consistent joint snapshot of FULL_STATE (body yaw 0.1 rad), then ``changes``."""
    r = dict(ROUTES)
    r[HEAD_JOINTS_QUERY] = snapshot(FULL_STATE["head_pose"], FULL_STATE["body_yaw"])
    r.update(changes)
    return r


def pose_of(matrix: np.ndarray) -> dict[str, float]:
    from reachy_motion.library.pose import pose_from_matrix

    p = pose_from_matrix(matrix)
    return {"x": p.x, "y": p.y, "z": p.z, "roll": p.roll, "pitch": p.pitch, "yaw": p.yaw}


def run(fake: FakeDaemon) -> dict[str, object]:
    with fake.patch():
        return run_r0(DaemonClient(HOST), timeout_s=1.0)


def codes(report: dict[str, object], level: str | None = None) -> set[str]:
    return {f["code"] for f in report["findings"] if level is None or f["level"] == level}  # type: ignore[index]


class TestR0Requests(unittest.TestCase):
    def test_only_the_five_read_only_gets_are_sent(self):
        fake = FakeDaemon(routes())
        run(fake)
        self.assertEqual({r.get_method() for r in fake.requests}, {"GET"})
        paths = [r.full_url[len(BASE):] for r in fake.requests]
        expected = (set(ALLOWED_GET_PATHS) - {"/api/state/full"}) | {HEAD_JOINTS_QUERY}
        self.assertEqual(set(paths), expected)  # the joint snapshot replaces the plain full state
        self.assertEqual(len(paths), 5)  # one request per item, no retry
        self.assertEqual([p for p in paths if "?" in p], [HEAD_JOINTS_QUERY])
        self.assertTrue(all(r.data is None for r in fake.requests))

    def test_module_never_builds_a_client_or_writes(self):
        tree = ast.parse(inspect.getsource(robot_r0))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertNotIn("ReachyMini", names | attrs | imports)
        self.assertFalse({"post", "put", "delete", "set_target", "goto_target", "enable_motors"} & attrs)
        self.assertFalse({m for m in modules if m and ("websocket" in m or "requests" in m)})
        self.assertNotIn("urllib", " ".join(m for m in modules if m))  # all HTTP goes through DaemonClient


class TestR0Evaluation(unittest.TestCase):
    def test_robot_near_rest_is_not_blocking(self):
        report = run(FakeDaemon(routes()))
        self.assertFalse(report["blocking"])
        self.assertEqual(report["data_kind"], "measured")
        self.assertIn("motors_enabled", codes(report, "info"))
        self.assertIn("body_yaw", codes(report, "attention"))  # FULL_STATE body yaw 0.1 rad = 5.7 deg
        joints = report["derived"]["joints"]
        self.assertTrue(joints["source"].startswith("measured"))
        self.assertGreater(joints["min_stewart_margin_deg"], 10.0)
        self.assertLess(joints["ik_of_pose_vs_joints_max_deg"], 1e-6)

    def test_wrong_version_state_or_error_block(self):
        for status, code in ((dict(ROBOT_STATUS, version="1.12.0"), "version"),
                             (dict(ROBOT_STATUS, state="error"), "state"),
                             (dict(ROBOT_STATUS, error="No response from the robot's motor"), "daemon_error")):
            with self.subTest(code=code):
                report = run(FakeDaemon(routes(**{"/api/daemon/status": status})))
                self.assertTrue(report["blocking"])
                self.assertIn(code, codes(report, "block"))

    def test_a_sim_daemon_is_labelled_simulated(self):
        report = run(FakeDaemon(routes(**{"/api/daemon/status": SIM_STATUS})))
        self.assertEqual(report["data_kind"], "simulated")
        self.assertIn("simulation", codes(report, "info"))

    def test_measured_joints_beyond_the_limits_block(self):
        """The SDK sleep JOINTS as the reading (their FK as the pose): 0.8-9.5 deg beyond the URDF limits."""
        from reachy_mini.reachy_mini import SLEEP_HEAD_JOINT_POSITIONS

        from reachy_motion.analysis.goto_replay import new_kinematics

        q = [float(v) for v in SLEEP_HEAD_JOINT_POSITIONS]
        m = new_kinematics().fk(np.array(q), no_iterations=400)
        report = run(FakeDaemon(routes(**{HEAD_JOINTS_QUERY: snapshot(pose_of(m), 0.0, q),
                                          "/api/state/present_body_yaw": 0.0})))
        self.assertTrue(report["blocking"])
        self.assertEqual(codes(report, "block"), {"start_beyond_limits"})  # FK and joints agree (< 1 deg)
        msg = next(f["message"] for f in report["findings"] if f["code"] == "start_beyond_limits")
        for joint in ("stewart_1", "stewart_2", "stewart_5", "stewart_6"):
            self.assertIn(joint, msg)
        self.assertNotIn("stewart_3", msg)

    def test_pose_that_does_not_match_the_joints_blocks(self):
        q = ik(FULL_STATE["head_pose"], 0.1)
        q[1] += 3.0 * DEG  # the reported pose and the joint reading disagree by 3 deg on stewart_1
        report = run(FakeDaemon(routes(**{HEAD_JOINTS_QUERY: snapshot(FULL_STATE["head_pose"], 0.1, q)})))
        self.assertIn("fk_joint_mismatch", codes(report, "block"))
        self.assertAlmostEqual(report["derived"]["joints"]["ik_of_pose_vs_joints_max_deg"], 3.0, delta=1e-6)

    def test_sdk_sleep_pose_is_inside_the_limits(self):
        from reachy_mini.reachy_mini import SLEEP_HEAD_POSE

        report = run(FakeDaemon(routes(**{HEAD_JOINTS_QUERY: snapshot(pose_of(SLEEP_HEAD_POSE)),
                                          "/api/state/present_body_yaw": 0.0,
                                          "/api/motors/status": {"mode": "disabled"}})))
        self.assertNotIn("start_beyond_limits", codes(report))
        self.assertIn("near_sleep", codes(report, "info"))
        self.assertIn("motors_disabled", codes(report, "info"))
        self.assertFalse(report["blocking"])

    def test_without_a_joint_reading_the_pose_ik_is_an_estimate(self):
        report = run(FakeDaemon(routes(**{HEAD_JOINTS_QUERY: dict(FULL_STATE)})))
        self.assertIn("no_joint_reading", codes(report, "attention"))
        self.assertTrue(report["derived"]["joints"]["source"].startswith("estimate"))
        self.assertFalse(report["blocking"])

    def test_missing_answers(self):
        report = run(FakeDaemon(routes(**{"/api/daemon/status": urllib.error.URLError("refused")})))
        self.assertEqual(codes(report), {"no_status"})
        self.assertTrue(report["blocking"])
        report = run(FakeDaemon(routes(**{HEAD_JOINTS_QUERY: {"control_mode": "enabled"}})))
        self.assertIn("no_pose", codes(report, "block"))

    def test_collect_records_errors_per_item(self):
        fake = FakeDaemon(routes(**{"/api/motors/status": urllib.error.URLError("refused")}))
        with fake.patch():
            answers = collect(DaemonClient(HOST), timeout_s=1.0)
        self.assertEqual(set(answers["motors_status"]), {"error"})
        derived, findings = evaluate(answers)
        self.assertIn("motors_unknown", {f.code for f in findings})


DISABLED_STATUS = dict(ROBOT_STATUS, backend_status=dict(ROBOT_STATUS["backend_status"], motor_control_mode="disabled"))
DEFAULT_FACE = {"detected": False, "x": None, "y": None, "roll": None, "ts": None}  # protocol.py FaceTarget()


def disabled(**changes: object) -> dict[str, object]:
    """A limp robot with a consistent joint snapshot (what R1 starts from), then ``changes``."""
    return routes(**{"/api/daemon/status": dict(DISABLED_STATUS, face_target=DEFAULT_FACE),
                     "/api/motors/status": {"mode": "disabled"}, **changes})


def entry(report: dict[str, object]) -> dict[str, str]:
    return {c["name"]: c["status"] for c in report["r1_entry"]["conditions"]}  # type: ignore[index]


class TestR0BlockingReadsAndR1Entry(unittest.TestCase):
    """2026-11-11 (docs/phase4/STARTUP_STOP.md §8.2): an unread motor mode or body yaw blocks (no default value);
    head tracking, a per-motor enable and other clients are not readable with the allowed GETs -> R1 entry not met."""

    def test_motor_mode_not_read_blocks(self):
        for answer in (urllib.error.URLError("refused"), {"mode": "something_else"}, {}):
            with self.subTest(answer=answer):
                report = run(FakeDaemon(disabled(**{"/api/motors/status": answer})))
                self.assertIn("motors_unknown", codes(report, "block"))
                self.assertTrue(report["blocking"])
                self.assertEqual(entry(report)["motors_disabled"], "unmet")

    def test_body_yaw_not_read_blocks_and_is_not_zero(self):
        for answer in (urllib.error.URLError("refused"), "0.1", None, float("nan")):
            with self.subTest(answer=answer):
                report = run(FakeDaemon(disabled(**{"/api/state/present_body_yaw": answer})))
                self.assertIn("no_body_yaw", codes(report, "block"))
                self.assertIsNone(report["derived"]["body_yaw_deg"])  # unknown, never 0.0
                self.assertNotIn("fk_joint_mismatch", codes(report))  # the cross-check needs the body yaw: skipped
                self.assertIsNone(report["derived"]["joints"]["ik_of_pose_vs_joints_max_deg"])
                self.assertIn("min_stewart_margin_deg", report["derived"]["joints"])  # measured joints still checked
        report = run(FakeDaemon(disabled(**{"/api/state/present_body_yaw": urllib.error.URLError("x"),
                                            HEAD_JOINTS_QUERY: dict(FULL_STATE)})))  # no joints and no body yaw
        self.assertTrue({"no_body_yaw", "no_joint_reading"} <= codes(report))
        self.assertEqual(report["derived"]["joints"], {})  # nothing estimated

    def test_a_set_face_target_means_tracking_is_on_and_blocks(self):
        for face in ({"detected": False, "x": None, "y": None, "roll": None, "ts": 1234.5},  # tracker ran, no face
                     {"detected": True, "x": 0.2, "y": -0.1, "roll": 0.0, "ts": 1234.5}):
            with self.subTest(face=face):
                report = run(FakeDaemon(disabled(**{"/api/daemon/status": dict(DISABLED_STATUS, face_target=face)})))
                self.assertIn("head_tracking_active", codes(report, "block"))
                self.assertEqual(entry(report)["tracking_not_seen_on"], "unmet")
                self.assertEqual(report["r1_entry"]["verdict"], "blocked")

    def test_a_default_face_target_does_not_prove_tracking_off(self):
        """Not seen on is all R0 can say; turning it off is the connection's job (category ``connection``)."""
        for status in (dict(DISABLED_STATUS, face_target=DEFAULT_FACE), DISABLED_STATUS):  # default / field absent
            with self.subTest(face=status.get("face_target")):
                report = run(FakeDaemon(disabled(**{"/api/daemon/status": status})))
                self.assertFalse(report["blocking"])
                self.assertEqual(report["derived"]["head_tracking"], "unknown")
                self.assertEqual(entry(report)["tracking_not_seen_on"], "met")
                self.assertEqual(entry(report)["head_tracking_off"], "by_connection")

    def test_no_media_proves_tracking_off(self):
        status = dict(DISABLED_STATUS, face_target=DEFAULT_FACE, no_media=True)
        report = run(FakeDaemon(disabled(**{"/api/daemon/status": status})))
        self.assertEqual(entry(report)["tracking_not_seen_on"], "met")
        self.assertEqual(report["r1_entry"]["verdict"], "conditional")  # never "met": the rest is not R0's to verify

    def test_r1_entry_sorts_the_conditions_and_is_never_met(self):
        """User decision 2026-11-12: automatic / connection / operator / residual; the other-client risk residual."""
        report = run(FakeDaemon(disabled()))
        self.assertFalse(report["blocking"])
        self.assertIn("motors_disabled", codes(report, "info"))
        r1 = report["r1_entry"]
        self.assertEqual((r1["verdict"], r1["auto_met"]), ("conditional", True))
        self.assertNotIn("met", r1)
        self.assertEqual({c["name"]: c["category"] for c in r1["conditions"] if c["category"] != "auto"},
                         {"head_tracking_off": "connection", "no_partial_torque": "connection",
                          "controlled_environment": "operator", "other_client": "residual"})
        self.assertEqual(entry(report)["other_client"], "residual")
        self.assertIn("**R1 entry: conditional**", robot_r0.report_markdown(report))

    def test_robot_status_prints_the_r1_entry_and_blocks_an_unread_motor_mode(self):
        from reachy_motion.cli import main

        with tempfile.TemporaryDirectory() as d:
            for name, fake, expected, verdict in (("ok", FakeDaemon(disabled()), 0, "conditional"),
                                                  ("motors", FakeDaemon(disabled(**{"/api/motors/status":
                                                                                    urllib.error.URLError("x")})), 2,
                                                   "blocked")):
                with self.subTest(name=name), fake.patch():
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        self.assertEqual(main(["robot-status", "--host", HOST, "--out", str(Path(d) / name)]),
                                         expected)
                    self.assertIn(f"R1 entry: {verdict}", buf.getvalue())
                    self.assertIn("[residual] other_client: residual", buf.getvalue())


class TestCommands(unittest.TestCase):
    def test_robot_status_command_writes_reports_and_sets_the_exit_code(self):
        from reachy_motion.cli import main

        with tempfile.TemporaryDirectory() as d:
            for fake, expected in ((FakeDaemon(routes()), 0),
                                   (FakeDaemon(routes(**{"/api/daemon/status": dict(ROBOT_STATUS, version="0")})), 2),
                                   (FakeDaemon(routes(**{"/api/daemon/status": urllib.error.URLError("x")})), 1)):
                with self.subTest(expected=expected), fake.patch(), contextlib.redirect_stdout(io.StringIO()):
                    out = Path(d) / str(expected)
                    self.assertEqual(main(["robot-status", "--host", HOST, "--out", str(out)]), expected)
                    report = json.loads(next(out.glob("*/r0_report.json")).read_text(encoding="utf-8"))
                    self.assertEqual(report["stage"], "R0")
                    self.assertTrue(next(out.glob("*/r0_report.md")).is_file())

    def test_robot_status_defaults_to_the_project_robot(self):
        from reachy_motion.cli import build_parser
        from reachy_motion.settings import ROBOT_DAEMON_PORT, ROBOT_HOST

        args = build_parser().parse_args(["robot-status"])  # parsing only: nothing is sent
        self.assertEqual((args.host, args.port), (ROBOT_HOST, ROBOT_DAEMON_PORT))
        self.assertEqual(ROBOT_HOST, "192.168.0.15")

    def test_tracking_command_on_a_review_folder(self):
        from reachy_motion.cli import main

        with tempfile.TemporaryDirectory() as d:
            review = Path(d) / "review"
            for name, tau in (("a.expressive", 0.04), ("b.neutral", 0.08)):
                run_dir = review / "runs" / name
                run_dir.mkdir(parents=True)
                t = np.arange(0.0, 4.0, 0.02)
                pitch = 10.0 * (np.clip((t - 1.0) / 0.5, 0, 1) - np.clip((t - 2.5) / 0.5, 0, 1))
                cmd = [{"k": k, "t_s": tk, "kind": "set_target", "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
                        "roll_deg": 0.0, "pitch_deg": p, "yaw_deg": 0.0, "antenna_right_deg": -10.0,
                        "antenna_left_deg": 10.0, "body_yaw_deg": 0.0} for k, (tk, p) in enumerate(zip(t, pitch))]
                tm = t + 0.005
                pm = np.interp(tm - tau, t, pitch)
                meas = [{"t_s": a, "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0, "roll_deg": 0.0, "pitch_deg": b,
                         "yaw_deg": 0.0, "antenna_right_deg": -10.0, "antenna_left_deg": 10.0, "body_yaw_deg": 0.0}
                        for a, b in zip(tm, pm)]
                for fname, rows in (("commands.csv", cmd), ("present_simulated.csv", meas)):
                    with open(run_dir / fname, "w", newline="", encoding="utf-8") as f:
                        w = csv.DictWriter(f, fieldnames=list(rows[0]))
                        w.writeheader()
                        w.writerows(rows)
            out = Path(d) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["tracking", str(review), "--out", str(out)]), 0)
            folder = next(out.iterdir())
            data = json.loads((folder / "tracking.json").read_text(encoding="utf-8"))
            self.assertEqual(data["manifest"]["data_kind"], "simulated")
            self.assertEqual(set(data["runs"]), {"a.expressive", "b.neutral"})
            self.assertEqual(data["runs"]["a.expressive"]["headline_channel"], "pitch")  # no joint columns here
            with open(folder / "tracking.csv", newline="", encoding="utf-8") as f:
                rows = {(r["run"], r["channel"]): r for r in csv.DictReader(f)}
            self.assertAlmostEqual(float(rows[("a.expressive", "pitch")]["lag_ms"]), 40, delta=1.5)  # value(t) = cmd(t - tau)
            self.assertAlmostEqual(float(rows[("b.neutral", "pitch")]["lag_ms"]), 80, delta=1.5)
            self.assertEqual(rows[("a.expressive", "pitch")]["unit"], "deg")


class TestSimStartupHelpers(unittest.TestCase):
    """Pure helpers of `sim-startup` (the MuJoCo run itself needs a local daemon: docs/VERIFICATION.md)."""

    def test_measured_motion_peaks_and_repeated_pushes(self):
        from reachy_motion.backends.base import PresentState
        from reachy_motion.cli_phase4 import _distinct, _measured_motion
        from reachy_motion.library.pose import Pose6

        states = []
        for k in range(50):
            q = np.radians([0.0] + [30.0 + 0.2 * k] * 6)  # every Stewart joint at 10 deg/s (0.2 deg per 20 ms)
            head = Pose6.from_deg_mm(pitch_deg=0.1 * k).matrix()  # 5 deg/s
            p = PresentState(t_ns=k * 20_000_000, head=head, antennas=(math.radians(-10 + k), math.radians(10)),
                             body_yaw=0.0, joints=q)
            states += [p, p] if k % 7 == 0 else [p]  # the same push read twice
        self.assertEqual(len(_distinct(states)), 50)
        m = _measured_motion(states)
        self.assertEqual(m["samples"], 50)
        self.assertAlmostEqual(m["peak_stewart_speed_dps"], 10.0, places=6)
        self.assertAlmostEqual(m["max_stewart_step_deg"], 0.2, places=9)
        self.assertAlmostEqual(m["peak_head_rotation_dps"], 5.0, places=4)
        self.assertAlmostEqual(m["peak_antenna_speed_dps"], 50.0, places=6)
        self.assertEqual(_measured_motion(states[:2]), {"samples": 1})


if __name__ == "__main__":
    unittest.main()
