"""Tests for ``reachy_motion.safety.checker`` (Phase 2: V2.2 / V2.3 initial-policy checks, data_kind "computed").

Hermetic: only SDK math is called (the planner's ``time_trajectory`` / ``linear_pose_interpolation`` and the
``AnalyticalKinematics`` IK) - no daemon, no MuJoCo, no robot, no network. Reference values come from Phase 1
(docs/phase1/SDK_ANALYSIS.md 4.2, 6.3): the +-27.44 deg roll x pitch box keeps exactly 10.00 deg of Stewart margin
at its head-up corners; the tilted-head psi wrap (roll 20, pitch -20, yaw 160 -> 179 deg, body 140 deg) flips the
body target by about 255 deg without any NaN; CARTOON overshoots by about 10 % of the move.
"""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import replace

import numpy as np

from reachy_motion import planner
from reachy_motion.analysis.goto_replay import JOINT_NAMES, ik_joints, new_kinematics
from reachy_motion.analysis.limits import ANTENNA_MOTOR, BODY_MOTOR_PROXY, STEWART_MOTOR, urdf_joint_limits
from reachy_motion.library.pose import INIT_ANTENNAS, REST, Pose6, RobotState, head_yaw_psi, pose_from_matrix
from reachy_motion.library.spec import AntennaKey, BodyKey, Easing, HeadKey, MotionSpec, Principle, PrincipleUse
from reachy_motion.safety import checker
from reachy_motion.safety.checker import (
    METRIC_KEYS,
    ROW_COLUMNS,
    VIOLATION_CODES,
    WARNING_CODES,
    analyze_spec,
    analyze_timeline,
    check_spec,
    check_timeline,
    prepare,
    prepare_timeline,
)
from reachy_motion.safety.policy import DEFAULT_POLICY, POLICY_DISCLAIMER
from reachy_motion.timeline import PreparedMotion, Timeline

DEG = math.pi / 180.0
_PRINCIPLES = (PrincipleUse(Principle.TIMING, "safety checker unit test"),)


def make_spec(head=(), antennas=(), body=(), **kw) -> MotionSpec:
    fields = dict(name="aha_recommend", variant="expressive", intent="safety checker unit test", valence=0.3,
                  arousal=0.4, principles=_PRINCIPLES)
    fields.update(kw)
    return MotionSpec(head=tuple(head), antennas=tuple(antennas), body=tuple(body), **fields)


def head(duration: float, easing: Easing = Easing.MIN_JERK, hold: float = 0.0, label: str = "", **deg_mm) -> HeadKey:
    return HeadKey(duration, Pose6.from_deg_mm(**deg_mm), easing, hold=hold, label=label)


def nod_spec(**kw) -> MotionSpec:
    """A small nod with an antenna perk: well inside the initial policy."""
    return make_spec(head=(head(0.6, pitch_deg=10.0, hold=0.2, label="down"), head(0.6, label="up")),
                     antennas=(AntennaKey(0.4, (-0.4, 0.4), Easing.MIN_JERK, hold=0.2, label="perk"),
                               AntennaKey(0.5, INIT_ANTENNAS, Easing.MIN_JERK, label="relax")), **kw)


def codes(report) -> set[str]:
    return {v.code for v in report.violations}


def warning_codes(report) -> set[str]:
    return {w.code for w in report.warnings}


def violation(report, code: str):
    found = [v for v in report.violations if v.code == code]
    if len(found) != 1:
        raise AssertionError(f"expected one {code!r} violation, got {[v.code for v in report.violations]}")
    return found[0]


def warning(report, code: str):
    found = [w for w in report.warnings if w.code == code]
    if len(found) != 1:
        raise AssertionError(f"expected one {code!r} warning, got {[w.code for w in report.warnings]}")
    return found[0]


class AnalysisTests(unittest.TestCase):
    """``PlanAnalysis``: the arrays the GUI plots and the checks use, against direct SDK / helper calls."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = nod_spec()
        cls.a = analyze_spec(cls.spec, 200.0)

    def test_grid_and_end_state(self) -> None:
        a, spec = self.a, self.spec
        self.assertEqual((a.source, a.data_kind, a.rate_hz, a.spec_digest), ("spec", "computed", 200.0, spec.digest()))
        np.testing.assert_array_equal(a.t, planner.grid_times(spec.duration, 200.0))
        self.assertEqual(a.t[0], 0.0)
        self.assertGreaterEqual(a.t[-1] + 1e-12, spec.duration)
        n = len(a)
        shapes = {"head": (n, 4, 4), "pose6": (n, 6), "antennas": (n, 2), "body": (n,), "joints": (n, 7),
                  "joint_velocity": (n, 7), "joint_acceleration": (n, 7), "pose_velocity": (n, 6),
                  "antenna_velocity": (n, 2), "psi": (n,), "rel_yaw": (n,), "auto_body_shift": (n,),
                  "stewart_margin": (n, 6), "stewart_speed_ratio": (n, 6), "body_speed_ratio": (n,),
                  "antenna_speed_ratio": (n, 2)}
        for name, shape in shapes.items():
            self.assertEqual(getattr(a, name).shape, shape, name)
        # the last sample is the exact end state (rest), like planner.plan
        np.testing.assert_array_equal(a.head[-1], np.eye(4))
        np.testing.assert_array_equal(a.antennas[-1], INIT_ANTENNAS)
        self.assertEqual(a.joint_names, JOINT_NAMES)
        self.assertTrue(np.all(a.ik_ok))

    def test_arrays_match_sdk_and_helpers(self) -> None:
        a = self.a
        kin = new_kinematics()
        for k in (0, 37, 120, 200, len(a) - 1):
            np.testing.assert_array_equal(a.joints[k], ik_joints(kin, a.head[k], float(a.body[k])))
            np.testing.assert_allclose(a.pose6[k], pose_from_matrix(a.head[k]).as_array(), rtol=0, atol=1e-12)
            self.assertEqual(a.psi[k], head_yaw_psi(a.head[k]))
        np.testing.assert_array_equal(a.joint_velocity, np.gradient(a.joints, a.t, axis=0))
        np.testing.assert_array_equal(a.joint_acceleration, np.gradient(a.joint_velocity, a.t, axis=0))
        np.testing.assert_array_equal(a.pose_velocity, np.gradient(a.pose6, a.t, axis=0))
        np.testing.assert_array_equal(a.antenna_velocity, np.gradient(a.antennas, a.t, axis=0))
        limits = urdf_joint_limits()
        for j, name in enumerate(JOINT_NAMES[1:]):
            lo, hi = limits[name]
            q = a.joints[:, 1 + j]
            np.testing.assert_allclose(a.stewart_margin[:, j], np.degrees(np.minimum(q - lo, hi - q)), atol=1e-12)
        qd = np.degrees(np.abs(a.joint_velocity))
        np.testing.assert_allclose(a.stewart_speed_ratio, qd[:, 1:] / STEWART_MOTOR.no_load_deg_s_5v, atol=1e-15)
        np.testing.assert_allclose(a.body_speed_ratio, qd[:, 0] / BODY_MOTOR_PROXY.no_load_deg_s_5v, atol=1e-15)
        np.testing.assert_allclose(a.antenna_speed_ratio, np.degrees(np.abs(a.antenna_velocity))
                                   / ANTENNA_MOTOR.no_load_deg_s_5v, atol=1e-15)
        np.testing.assert_array_equal(a.auto_body_shift, a.joints[:, 0] - a.body)
        # pitch-only nod: Euler pitch follows the key values, no yaw / roll / translation
        self.assertAlmostEqual(float(np.degrees(np.max(a.pose6[:, 4]))), 10.0, places=9)
        self.assertLess(float(np.max(np.abs(a.pose6[:, [0, 1, 2, 3, 5]]))), 1e-12)
        self.assertLess(float(np.max(np.abs(a.rel_yaw))), 1e-12)

    def test_rows_are_human_units(self) -> None:
        a = self.a
        rows = a.rows()
        self.assertEqual(len(rows), len(a))
        self.assertEqual(tuple(rows[0]), ROW_COLUMNS)
        k = int(np.argmax(a.pose6[:, 4]))
        r = rows[k]
        self.assertAlmostEqual(r["pitch_deg"], math.degrees(a.pose6[k, 4]), places=12)
        self.assertAlmostEqual(r["ik_stewart_3_deg"], math.degrees(a.joints[k, 3]), places=12)
        self.assertAlmostEqual(r["ik_stewart_3_speed_dps"], math.degrees(a.joint_velocity[k, 3]), places=9)
        self.assertAlmostEqual(r["stewart_3_margin_deg"], float(a.stewart_margin[k, 2]), places=12)
        self.assertAlmostEqual(r["antenna_right_deg"], math.degrees(a.antennas[k, 0]), places=12)
        self.assertIs(r["ik_ok"], True)
        self.assertEqual(r["t_s"], float(a.t[k]))
        json.dumps(rows[:3])

    def test_stream_samples_are_dense_samples(self) -> None:
        """k / 50 == 4k / 200 exactly, so the 50 Hz timeline's samples are dense samples (except the end one)."""
        tl = planner.plan(self.spec, 50.0)
        s = analyze_timeline(tl)
        self.assertEqual((s.source, s.rate_hz, s.spec_digest), ("timeline", 50.0, self.spec.digest()))
        for k in range(len(tl) - 1):
            np.testing.assert_array_equal(s.head[k], self.a.head[4 * k])
            np.testing.assert_array_equal(s.joints[k], self.a.joints[4 * k])

    def test_invalid_inputs_raise(self) -> None:
        tl = planner.plan(self.spec)
        bad = replace(tl, head=tl.head.copy())
        bad.head[5, 0, 3] = math.nan
        for fn in (analyze_timeline, check_timeline, prepare_timeline):
            with self.assertRaises(ValueError, msg=fn.__name__):
                fn(bad)
        empty = make_spec()
        for fn in (analyze_spec, check_spec, prepare):
            with self.assertRaises(ValueError, msg=fn.__name__):
                fn(empty)
        with self.assertRaises(ValueError):
            analyze_spec(replace(self.spec, tempo_scale=0.0))


class CheckSpecTests(unittest.TestCase):
    def test_small_nod_passes_with_sane_metrics(self) -> None:
        spec = nod_spec()
        r = check_spec(spec)
        self.assertTrue(r.passes_policy, [v.message for v in r.violations])
        self.assertEqual(r.violations, ())
        self.assertEqual(warning_codes(r), {"draft"})  # MIN_JERK only: no velocity step, no overshoot
        self.assertEqual((r.name, r.variant, r.data_kind), ("aha_recommend", "expressive", "computed"))
        self.assertEqual(r.disclaimer, POLICY_DISCLAIMER)
        self.assertIs(r.policy, DEFAULT_POLICY)
        self.assertEqual(r.spec_digest, spec.digest())
        self.assertEqual(r.timeline_digest, planner.plan(spec, DEFAULT_POLICY.stream_rate_hz).digest())
        m = r.metrics
        self.assertEqual(tuple(m), METRIC_KEYS)
        self.assertEqual(m["n_dense"], len(planner.grid_times(spec.duration, DEFAULT_POLICY.check_rate_hz)))
        self.assertEqual(m["n_stream"], len(planner.plan(spec)))
        self.assertAlmostEqual(m["duration_s"], 1.4, places=12)
        self.assertEqual(m["ik_nan_samples"], 0)
        # neutral IK = +-35.90 deg -> 44.10 deg to the nearest URDF limit; a 10 deg nod takes about 7 deg of it
        self.assertTrue(30.0 < m["min_stewart_margin_deg"] < 44.2, m["min_stewart_margin_deg"])
        self.assertIn(m["min_stewart_margin_joint"], JOINT_NAMES[1:])
        self.assertAlmostEqual(m["min_stewart_margin_t"], 0.6, places=9)  # the nod's lowest point
        self.assertTrue(0.0 < m["peak_stewart_speed_ratio"] < 0.1)
        self.assertAlmostEqual(m["peak_stewart_speed_dps"],
                               m["peak_stewart_speed_ratio"] * STEWART_MOTOR.no_load_deg_s_5v, places=9)
        self.assertEqual((m["peak_body_speed_dps"], m["peak_body_speed_ratio"], m["max_body_step_deg"]), (0.0, 0.0, 0.0))
        self.assertTrue(0.0 < m["peak_antenna_speed_ratio"] < 0.1)
        self.assertAlmostEqual(m["max_abs_pitch_deg"], 10.0, places=9)
        self.assertLess(m["max_abs_roll_deg"], 1e-9)
        self.assertLess(m["max_abs_rel_yaw_deg"], 1e-9)
        self.assertEqual(m["body_yaw_range_deg"], [0.0, 0.0])
        for key in ("x_range_mm", "y_range_mm", "z_range_mm"):
            self.assertLess(max(abs(v) for v in m[key]), 1e-9, key)
        lo, hi = m["antenna_range_deg"]
        self.assertAlmostEqual(lo, math.degrees(-0.4), places=9)
        self.assertAlmostEqual(hi, math.degrees(0.4), places=9)
        self.assertEqual((m["max_auto_body_shift_deg"], m["max_psi_step_deg"]), (0.0, 0.0))
        self.assertTrue(0.0 < m["max_stream_step_deg"] < 2.0)
        self.assertGreater(m["peak_joint_accel_dps2"], 0.0)
        # the GUI plots analyze_spec(spec, check_rate_hz): the report's dense peaks are those arrays' maxima
        a = analyze_spec(spec, DEFAULT_POLICY.check_rate_hz)
        self.assertEqual(m["peak_stewart_speed_ratio"], float(np.max(a.stewart_speed_ratio)))
        self.assertEqual(m["peak_antenna_speed_ratio"], float(np.max(a.antenna_speed_ratio)))
        self.assertLessEqual(m["min_stewart_margin_deg"], float(np.min(a.stewart_margin)))
        json.loads(json.dumps(r.to_dict()))

    def test_draft_warning_only_for_drafts(self) -> None:
        self.assertIn("draft", warning_codes(check_spec(nod_spec(draft=True))))
        self.assertEqual(warning_codes(check_spec(nod_spec(draft=False))), set())

    def test_ik_nan_at_z_plus_30_mm(self) -> None:
        r = check_spec(make_spec(head=(head(1.0, z_mm=30.0),)))
        self.assertFalse(r.passes_policy)
        v = violation(r, "ik_nan")
        self.assertEqual(v.severity, "violation")
        self.assertEqual(v.value, float(r.metrics["ik_nan_samples"]))
        self.assertGreater(v.value, 0)
        self.assertTrue(0.5 < v.t < 1.0, v.t)  # NaN from z = +24.3 mm on the way up
        self.assertEqual(v.limit, 0.0)
        self.assertIn("envelope_z", codes(r))
        self.assertEqual(violation(r, "envelope_z").limit, DEFAULT_POLICY.z_range_mm[1])

    def test_roll_pitch_corner_margin(self) -> None:
        """Phase 1: the +-27.44 deg box keeps exactly 10.00 deg at the head-up (pitch < 0) corners."""
        for roll in (27.44, -27.44):
            r = check_spec(make_spec(head=(head(2.0, roll_deg=roll, pitch_deg=-27.44),)))
            self.assertTrue(r.passes_policy, (roll, [v.message for v in r.violations]))
            self.assertAlmostEqual(r.metrics["min_stewart_margin_deg"], 10.0, delta=0.01)
        for roll in (30.0, -30.0):
            r = check_spec(make_spec(head=(head(2.0, roll_deg=roll, pitch_deg=-30.0),)))
            self.assertEqual(codes(r), {"stewart_margin"})
            v = violation(r, "stewart_margin")
            self.assertAlmostEqual(v.value, 5.47, delta=0.02)
            self.assertEqual(v.limit, DEFAULT_POLICY.min_stewart_margin_deg)
            self.assertEqual(v.value, r.metrics["min_stewart_margin_deg"])
            self.assertGreater(v.t, 0.0)
        # same-sign (head-down) corner keeps more margin (14.2 deg)
        r = check_spec(make_spec(head=(head(2.0, roll_deg=30.0, pitch_deg=30.0),)))
        self.assertTrue(r.passes_policy)

    def test_fast_cartoon_pitch_exceeds_stewart_speed(self) -> None:
        r = check_spec(make_spec(head=(head(0.1, Easing.CARTOON, pitch_deg=30.0),)))
        self.assertIn("stewart_speed", codes(r))
        self.assertIn("stream_step", codes(r))
        v = violation(r, "stewart_speed")
        self.assertGreater(v.value, 1.0)  # ~1.75 x the no-load speed
        self.assertEqual(v.limit, DEFAULT_POLICY.max_stewart_speed_ratio)
        self.assertEqual(v.value, r.metrics["peak_stewart_speed_ratio"])
        step = violation(r, "stream_step")
        self.assertAlmostEqual(step.limit, 0.5 * STEWART_MOTOR.no_load_deg_s_5v / 50.0, places=12)
        self.assertGreater(step.value, step.limit)
        # the same move at an unhurried MIN_JERK passes
        self.assertTrue(check_spec(make_spec(head=(head(1.5, pitch_deg=30.0),))).passes_policy)

    def test_cartoon_overshoot_leaves_pitch_envelope(self) -> None:
        """CARTOON at pitch 38 deg peaks at 38 x 1.1 = 41.8 deg (> 40); MIN_JERK to the same key passes."""
        r = check_spec(make_spec(head=(head(1.5, Easing.CARTOON, pitch_deg=38.0),)))
        self.assertFalse(r.passes_policy)
        v = violation(r, "envelope_pitch")
        self.assertAlmostEqual(v.value, 41.8, delta=0.05)
        self.assertEqual(v.limit, DEFAULT_POLICY.max_pitch_deg)
        self.assertAlmostEqual(r.metrics["max_abs_pitch_deg"], 41.8, delta=0.05)
        w = warning(r, "cartoon_overshoot")
        self.assertEqual(w.severity, "warning")
        self.assertAlmostEqual(w.value, 0.1 * 38.0, delta=0.02)  # s_max - 1 = 0.10015
        self.assertIn("pitch", w.message)
        self.assertTrue(0.0 < w.t < 0.75)  # anticipation starts right after departure
        ok = check_spec(make_spec(head=(head(1.5, Easing.MIN_JERK, pitch_deg=38.0),)))
        self.assertTrue(ok.passes_policy, [x.message for x in ok.violations])
        self.assertNotIn("cartoon_overshoot", warning_codes(ok))
        self.assertAlmostEqual(ok.metrics["max_abs_pitch_deg"], 38.0, places=9)

    def test_cartoon_overshoot_on_antennas(self) -> None:
        start = INIT_ANTENNAS[0]
        r = check_spec(make_spec(antennas=(AntennaKey(1.0, (start - 0.5, INIT_ANTENNAS[1]), Easing.CARTOON),)))
        w = warning(r, "cartoon_overshoot")
        self.assertAlmostEqual(w.value, math.degrees(0.5) * 0.10015, delta=0.01)
        self.assertIn("antennas[0]", w.message)

    def test_psi_wrap_flips_the_body(self) -> None:
        """Phase 1: body 140 deg, tilted head (roll 20, pitch -20) yaw 160 -> 179 MIN_JERK: psi wraps, no NaN."""
        start = RobotState(head=Pose6.from_deg_mm(roll_deg=20.0, pitch_deg=-20.0, yaw_deg=160.0), body_yaw=140.0 * DEG)
        r = check_spec(make_spec(head=(head(1.0, roll_deg=20.0, pitch_deg=-20.0, yaw_deg=179.0),), start=start))
        self.assertFalse(r.passes_policy)
        self.assertTrue({"psi_wrap", "body_step", "auto_body_shift", "stream_step"} <= codes(r), codes(r))
        self.assertNotIn("envelope_rel_yaw", codes(r))
        self.assertNotIn("ik_nan", codes(r))
        self.assertLess(r.metrics["max_abs_rel_yaw_deg"], 60.0)
        self.assertAlmostEqual(r.metrics["max_abs_rel_yaw_deg"], 39.0, delta=1e-6)
        psi = violation(r, "psi_wrap")
        self.assertGreater(psi.value, 300.0)
        self.assertAlmostEqual(psi.t, 0.6, delta=0.011)
        self.assertEqual(psi.limit, DEFAULT_POLICY.max_psi_step_deg)
        body = violation(r, "body_step")
        self.assertAlmostEqual(body.value, 254.9, delta=0.2)  # 140 -> -114.9 deg in one dense sample
        self.assertEqual(body.limit, DEFAULT_POLICY.max_body_step_deg)
        self.assertAlmostEqual(r.metrics["max_body_step_deg"], body.value, places=12)
        self.assertGreater(r.metrics["max_psi_step_deg"], 300.0)

    def test_linear_keys_warn_about_velocity_steps(self) -> None:
        r = check_spec(make_spec(head=(head(1.0, Easing.LINEAR, pitch_deg=10.0),)))
        self.assertTrue(r.passes_policy)  # a warning, not a violation
        w = warning(r, "velocity_step")
        self.assertEqual(w.severity, "warning")
        self.assertEqual(w.t, 0.0)  # starts at full speed from rest
        # Stewart sensitivity to pitch ~0.68-0.72 deg/deg: a 10 deg/s step is a 6.8-7.2 deg/s joint step
        self.assertTrue(6.0 < w.value < 8.0, w.value)
        self.assertIn("head rotation 10 deg/s", w.message)
        self.assertIsNone(w.limit)
        smooth = check_spec(make_spec(head=(head(1.0, Easing.MIN_JERK, pitch_deg=10.0),)))
        self.assertNotIn("velocity_step", warning_codes(smooth))

    def test_nan_in_a_warning_computation(self) -> None:
        r = check_spec(make_spec(head=(head(1.0, Easing.LINEAR, z_mm=30.0),)))
        self.assertIn("ik_nan", codes(r))
        self.assertIn("velocity_step", warning_codes(r))
        w = warning(r, "nan")
        self.assertIn("velocity_step", w.message)

    def test_each_code_is_specific(self) -> None:
        """Small specs that trip exactly the intended check (custom policies where the defaults coincide)."""
        cases = [
            ("body_speed", make_spec(head=(head(0.2, yaw_deg=40.0),), body=(BodyKey(0.2, 40.0 * DEG),)),
             DEFAULT_POLICY, {"body_speed", "stream_step"}),
            ("antenna_speed", make_spec(antennas=(AntennaKey(0.1, (-1.5, 1.5)),)), DEFAULT_POLICY, {"antenna_speed"}),
            ("antenna_range", make_spec(antennas=(AntennaKey(3.0, (-3.1, 3.1)),)), DEFAULT_POLICY, {"antenna_range"}),
            ("envelope_roll", make_spec(head=(head(2.0, roll_deg=25.0),)), replace(DEFAULT_POLICY, max_roll_deg=20.0),
             {"envelope_roll"}),
            ("envelope_pitch", make_spec(head=(head(3.0, pitch_deg=-45.0),)), DEFAULT_POLICY, {"envelope_pitch"}),
            ("envelope_x", make_spec(head=(head(2.0, x_mm=30.0),)), DEFAULT_POLICY, {"envelope_x"}),
            ("envelope_y", make_spec(head=(head(2.0, y_mm=-30.0),)), replace(DEFAULT_POLICY, y_range_mm=(-20.0, 20.0)),
             {"envelope_y"}),
            ("envelope_z", make_spec(head=(head(2.0, z_mm=-45.0),)), DEFAULT_POLICY, {"envelope_z"}),
            ("envelope_body_yaw", make_spec(head=(head(4.0, yaw_deg=158.0),), body=(BodyKey(4.0, 158.0 * DEG),)),
             DEFAULT_POLICY, {"envelope_body_yaw"}),
            ("envelope_rel_yaw", make_spec(head=(head(2.0, yaw_deg=62.0),)), DEFAULT_POLICY, {"envelope_rel_yaw"}),
            ("auto_body_shift", make_spec(head=(head(2.0, yaw_deg=70.0),)), DEFAULT_POLICY,
             {"auto_body_shift", "envelope_rel_yaw"}),
        ]
        for label, spec, policy, expected in cases:
            with self.subTest(label):
                r = check_spec(spec, policy)
                self.assertEqual(codes(r), expected, [v.message for v in r.violations])
                self.assertFalse(r.passes_policy)
        r = check_spec(cases[6][1], cases[6][2])
        v = violation(r, "envelope_y")
        self.assertEqual((v.value, v.limit), (-30.0, -20.0))  # the violated bound, in mm
        v = violation(check_spec(cases[2][1]), "antenna_range")
        self.assertEqual((v.value, v.limit), (3.1, DEFAULT_POLICY.max_antenna_abs_rad))  # rad, as the policy field
        v = violation(check_spec(cases[10][1]), "auto_body_shift")
        self.assertAlmostEqual(v.value, 5.0, delta=1e-6)  # body follows the head from 65 deg on

    def test_violation_and_warning_fields(self) -> None:
        start = RobotState(head=Pose6.from_deg_mm(roll_deg=20.0, pitch_deg=-20.0, yaw_deg=160.0), body_yaw=140.0 * DEG)
        r = check_spec(make_spec(head=(head(1.0, Easing.LINEAR, roll_deg=20.0, pitch_deg=-20.0, yaw_deg=179.0),
                                       head(0.1, Easing.CARTOON, pitch_deg=30.0, yaw_deg=150.0)), start=start))
        self.assertTrue(r.violations)
        order = [v.code for v in r.violations]
        self.assertEqual(order, [c for c in VIOLATION_CODES if c in order])
        for v in r.violations:
            self.assertEqual(v.severity, "violation")
            self.assertIn(v.code, VIOLATION_CODES)
            for x in (v.t, v.value, v.limit):
                self.assertIsInstance(x, float)
            self.assertTrue(v.message)
        self.assertEqual(len(order), len(set(order)))  # one entry per code
        wcodes = [w.code for w in r.warnings]
        self.assertEqual(wcodes, [c for c in WARNING_CODES if c in wcodes])
        for w in r.warnings:
            self.assertEqual(w.severity, "warning")
        self.assertTrue({"velocity_step", "cartoon_overshoot", "draft"} <= set(wcodes))
        json.loads(json.dumps(r.to_dict()))

    def test_stricter_custom_policy_fails_a_passing_spec(self) -> None:
        spec = nod_spec()
        self.assertTrue(check_spec(spec).passes_policy)
        strict = replace(DEFAULT_POLICY, name="strict-test", min_stewart_margin_deg=40.0, max_stewart_speed_ratio=0.01,
                         max_pitch_deg=5.0, max_antenna_abs_rad=0.2)
        r = check_spec(spec, strict)
        self.assertFalse(r.passes_policy)
        self.assertEqual(codes(r), {"stewart_margin", "stewart_speed", "envelope_pitch", "antenna_range", "stream_step"})
        self.assertIs(r.policy, strict)
        self.assertEqual(violation(r, "stewart_margin").limit, 40.0)
        self.assertEqual(violation(r, "envelope_pitch").limit, 5.0)
        # the per-tick limit follows the policy: 0.01 x 618 deg/s x 20 ms
        self.assertAlmostEqual(violation(r, "stream_step").limit, 0.01 * STEWART_MOTOR.no_load_deg_s_5v / 50.0,
                               places=12)

    def test_policy_must_be_usable(self) -> None:
        spec = nod_spec()
        for bad in (replace(DEFAULT_POLICY, min_stewart_margin_deg=math.nan),
                    replace(DEFAULT_POLICY, z_range_mm=(-40.0, math.nan)),
                    replace(DEFAULT_POLICY, check_rate_hz=0.0), replace(DEFAULT_POLICY, stream_rate_hz=-50.0)):
            with self.assertRaises(ValueError):
                check_spec(spec, bad)
        with self.assertRaises(TypeError):
            check_spec(spec, DEFAULT_POLICY.to_dict())  # type: ignore[arg-type]

    def test_amplitude_scale_is_checked_as_executed(self) -> None:
        """The checker sees the effective spec: doubling a 25 deg pitch to 50 deg leaves the envelope."""
        spec = make_spec(head=(head(2.0, pitch_deg=25.0),))
        self.assertTrue(check_spec(spec).passes_policy)
        r = check_spec(spec.scaled(amplitude=2.0))
        self.assertIn("envelope_pitch", codes(r))
        self.assertAlmostEqual(r.metrics["max_abs_pitch_deg"], 50.0, places=9)


class PrepareTests(unittest.TestCase):
    def test_prepare_binds_the_report_to_its_timeline(self) -> None:
        spec = nod_spec()
        p = prepare(spec)
        self.assertIsInstance(p, PreparedMotion)
        self.assertTrue(p.runnable)
        self.assertIs(p.spec, spec)
        self.assertEqual(p.timeline.digest(), planner.plan(spec, DEFAULT_POLICY.stream_rate_hz).digest())
        self.assertEqual(p.report.timeline_digest, p.timeline.digest())
        self.assertEqual(p.report.spec_digest, p.timeline.spec_digest)
        self.assertEqual(p.report.to_dict(), check_spec(spec).to_dict())
        other = planner.plan(nod_spec(amplitude_scale=0.9))
        self.assertFalse(PreparedMotion(other, p.report, spec).runnable)  # same report, other commands
        self.assertFalse(PreparedMotion(planner.plan(spec, 100.0), p.report, spec).runnable)

    def test_prepare_at_another_rate(self) -> None:
        spec = nod_spec()
        p = prepare(spec, rate_hz=100.0)
        self.assertTrue(p.runnable)
        self.assertEqual(p.timeline.rate_hz, 100.0)
        self.assertEqual(p.report.timeline_digest, planner.plan(spec, 100.0).digest())
        self.assertEqual(p.report.metrics["n_stream"], len(p.timeline))

    def test_prepare_refuses_outside_the_policy(self) -> None:
        p = prepare(make_spec(head=(head(0.1, Easing.CARTOON, pitch_deg=30.0),)))
        self.assertFalse(p.report.passes_policy)
        self.assertEqual(p.report.timeline_digest, p.timeline.digest())  # bound, but not runnable
        self.assertFalse(p.runnable)


class TimelineTests(unittest.TestCase):
    OFF = RobotState(head=Pose6.from_deg_mm(pitch_deg=-8.0, yaw_deg=15.0, z_mm=4.0), antennas=(-0.6, 0.5),
                     body_yaw=10.0 * DEG)

    def test_transition_plus_motion_composite(self) -> None:
        spec = nod_spec()
        ramp = planner.plan_transition(self.OFF, REST, planner.transition_duration(self.OFF, REST))
        tl = planner.concat(ramp, planner.plan(spec))
        r = check_timeline(tl)
        self.assertTrue(r.passes_policy, [v.message for v in r.violations])
        self.assertEqual(r.warnings, ())  # key-based warnings need a spec
        self.assertEqual((r.name, r.variant, r.spec_digest, r.timeline_digest), (tl.name, "", "", tl.digest()))
        self.assertEqual(r.disclaimer, POLICY_DISCLAIMER)
        m = r.metrics
        self.assertEqual(tuple(m), METRIC_KEYS)
        self.assertEqual((m["n_dense"], m["n_stream"], m["duration_s"]), (0, len(tl), tl.duration))
        self.assertAlmostEqual(m["body_yaw_range_deg"][1], 10.0, places=9)
        self.assertAlmostEqual(m["max_abs_pitch_deg"], 10.0, places=9)
        p = prepare_timeline(tl)
        self.assertTrue(p.runnable)
        self.assertIsNone(p.spec)
        self.assertEqual(p.report.to_dict(), r.to_dict())
        # a plain planned timeline keeps its spec digest
        self.assertEqual(check_timeline(planner.plan(spec)).spec_digest, spec.digest())

    def test_fast_transition_is_refused(self) -> None:
        ramp = planner.plan_transition(RobotState(head=Pose6.from_deg_mm(pitch_deg=25.0)), REST, 0.04)
        tl = planner.concat(ramp, planner.plan(nod_spec()))
        p = prepare_timeline(tl)
        self.assertFalse(p.runnable)
        self.assertTrue({"stewart_speed", "stream_step"} <= codes(p.report), codes(p.report))
        self.assertLess(violation(p.report, "stream_step").t, 0.1)  # in the ramp, not in the motion

    def test_single_sample_hold(self) -> None:
        keys = np.full(1, -1, dtype=np.int64)
        tl = Timeline(name="hold", variant="", rate_hz=50.0, duration=0.0, t=np.zeros(1), head=REST.head.matrix()[None],
                      antennas=np.array([INIT_ANTENNAS]), body_yaw=np.zeros(1), head_key=keys, antenna_key=keys.copy(),
                      body_key=keys.copy())
        r = check_timeline(tl)
        self.assertTrue(r.passes_policy)
        m = r.metrics
        self.assertAlmostEqual(m["min_stewart_margin_deg"], 44.10, delta=0.01)  # neutral IK +-35.90 deg
        for key in ("peak_stewart_speed_dps", "peak_body_speed_ratio", "peak_antenna_speed_ratio", "max_psi_step_deg",
                    "max_body_step_deg", "max_stream_step_deg", "peak_joint_accel_dps2"):
            self.assertEqual(m[key], 0.0, key)
        self.assertEqual((m["n_dense"], m["n_stream"]), (0, 1))


class ModuleTests(unittest.TestCase):
    def test_public_constants(self) -> None:
        self.assertEqual(len(METRIC_KEYS), len(set(METRIC_KEYS)))
        self.assertEqual(len(ROW_COLUMNS), len(set(ROW_COLUMNS)))
        self.assertEqual(checker.DATA_KIND, "computed")
        self.assertEqual(checker.STEWART_NAMES, JOINT_NAMES[1:])
        # the CARTOON extremes used by the overshoot warning are where the SDK's s(tau) peaks
        from reachy_mini.utils.interpolation import InterpolationTechnique, time_trajectory

        lo, hi = checker.CARTOON_TAU_EXTREMES
        s = lambda tau: time_trajectory(tau, InterpolationTechnique.CARTOON)  # noqa: E731
        self.assertLess(s(lo), min(s(lo - 1e-4), s(lo + 1e-4)))
        self.assertGreater(s(hi), max(s(hi - 1e-4), s(hi + 1e-4)))
        self.assertAlmostEqual(s(hi), 1.10015, places=5)


if __name__ == "__main__":
    unittest.main()
