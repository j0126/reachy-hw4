"""library.compare: per-key speeds, neutral conformance, comparison conditions and uniform retiming.

Pure functions on MotionSpec - hermetic, no robot, no daemon. Two tests cross-check copied SDK maths against the
installed SDK functions (the peak-speed factors against the time law through the Phase 1 helper, the head path
length against ``linear_pose_interpolation``); the library module itself stays SDK-free.
"""

from __future__ import annotations

import ast
import json
import math
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from reachy_motion.library import compare
from reachy_motion.library.compare import (
    PEAK_SPEED_FACTOR,
    SEGMENT_COLUMNS,
    Issue,
    comparison_conditions,
    comparison_issues,
    median_translation_speed_mms,
    neutral_conformance,
    retime_uniform_speed,
    segment_speeds,
    state_difference,
)
from reachy_motion.library.pose import INIT_ANTENNAS, REST, Pose6, RobotState, rotation_distance, rotation_xyz
from reachy_motion.library.spec import (
    MIN_KEY_DURATION_S,
    AntennaKey,
    BodyKey,
    Easing,
    HeadKey,
    MotionSpec,
    Principle,
    PrincipleUse,
    SoundCue,
)

PRINCIPLES = (PrincipleUse(Principle.TIMING, "test"), PrincipleUse(Principle.SLOW_IN_SLOW_OUT, "test"))
ZERO_ANTENNAS = RobotState(antennas=(0.0, 0.0))  # round numbers for antenna checks
L = Easing.LINEAR


def make(variant: str = "expressive", head: tuple[HeadKey, ...] = (), antennas: tuple[AntennaKey, ...] = (),
         body: tuple[BodyKey, ...] = (), name: str = "success", **kw: Any) -> MotionSpec:
    return MotionSpec(name=name, variant=variant, intent="test", valence=0.5, arousal=0.5, principles=PRINCIPLES,
                      head=head, antennas=antennas, body=body, **kw)


def pitch(deg: float, **kw: float) -> Pose6:
    return Pose6.from_deg_mm(pitch_deg=deg, **kw)


def expressive_pair() -> tuple[MotionSpec, MotionSpec]:
    """A matching expressive / neutral pair: same REST start, both end at REST."""
    ex = make("expressive",
              head=(HeadKey(0.5, pitch(10, z_mm=-4), Easing.MIN_JERK, 0.2, "nod"),
                    HeadKey(0.25, pitch(-5), Easing.CARTOON, 0.0, "up"),
                    HeadKey(0.5, Pose6(), Easing.EASE_IN_OUT, 0.0, "back")),
              antennas=(AntennaKey(0.2, (0.0, 0.0), Easing.EASE_IN_OUT, 0.3, "perk"),
                        AntennaKey(0.4, INIT_ANTENNAS, Easing.MIN_JERK, 0.0, "rest")),
              body=(BodyKey(1.0, math.radians(10), Easing.MIN_JERK), BodyKey(1.0, 0.0, Easing.MIN_JERK)),
              sound=SoundCue("success.wav", 0.1))
    ne = make("neutral",
              head=(HeadKey(0.5, pitch(10, z_mm=-4), L, 0.0, "down"), HeadKey(0.5, Pose6(), L, 0.0, "back")))
    return ex, ne


def failure_like_neutral() -> MotionSpec:
    """Translation-heavy neutral keys (review case): 3 deg + 15 mm, 10 mm only, 3 deg + 25 mm, 1 s each."""
    return make("neutral", name="failure",
                head=(HeadKey(1.0, pitch(3, z_mm=-15), L, 0.0, "slump"),
                      HeadKey(1.0, pitch(3, z_mm=-25), L, 0.0, "sink more"),
                      HeadKey(1.0, Pose6(), L, 0.0, "back")))


def sdk_path_deg(a: Pose6, b: Pose6, n: int = 400) -> float:
    """Length (deg) of the SDK goto head path from a to b, integrated numerically (test-only SDK use)."""
    from reachy_mini.utils.interpolation import linear_pose_interpolation

    ma, mb = a.matrix(), b.matrix()
    total, prev = 0.0, ma
    for i in range(1, n + 1):
        m = linear_pose_interpolation(ma, mb, i / n, yaw_as_scalar=True)  # as GotoMove.evaluate (goto.py:59-64)
        total += rotation_distance(prev, m)
        prev = m
    return math.degrees(total)


class TestSegmentSpeeds(unittest.TestCase):
    def test_head_rows(self):
        spec = make(head=(HeadKey(0.5, pitch(10, z_mm=-4), Easing.MIN_JERK, 0.2, "nod"),
                          HeadKey(1.5, pitch(-20), L, 0.1, "up"),
                          HeadKey(0.4, pitch(-20), Easing.CARTOON, 0.0, "still")))
        r0, r1, r2 = segment_speeds(spec)
        self.assertEqual((r0["track"], r0["index"], r0["label"], r0["easing"]), ("head", 0, "nod", "minjerk"))
        self.assertAlmostEqual(r0["change_deg"], 10.0, places=9)
        self.assertAlmostEqual(r0["geodesic_deg"], 10.0, places=9)  # single axis: path = geodesic
        self.assertAlmostEqual(r0["translation_mm"], 4.0, places=9)
        self.assertAlmostEqual(r0["avg_speed_dps"], 20.0, places=9)
        self.assertAlmostEqual(r0["peak_speed_dps"], 37.5, places=9)  # minjerk 1.875 x average
        self.assertAlmostEqual(r0["avg_trans_speed_mms"], 8.0, places=9)
        self.assertAlmostEqual(r0["peak_trans_speed_mms"], 15.0, places=9)
        self.assertAlmostEqual(r0["d_pitch_deg"], 10.0, places=9)
        self.assertAlmostEqual(r0["d_z_mm"], -4.0, places=9)
        self.assertTrue(r0["moves"])
        self.assertAlmostEqual(r1["change_deg"], 30.0, places=9)
        self.assertAlmostEqual(r1["translation_mm"], 4.0, places=9)
        self.assertAlmostEqual(r1["avg_speed_dps"], 20.0, places=9)
        self.assertAlmostEqual(r1["peak_speed_dps"], 20.0, places=9)  # linear: peak = average
        self.assertAlmostEqual(r1["d_pitch_deg"], -30.0, places=9)
        self.assertEqual((r2["moves"], r2["change_deg"], r2["avg_speed_dps"]), (False, 0.0, 0.0))
        times = [(r["t_depart_s"], r["t_arrive_s"], r["t_release_s"]) for r in (r0, r1, r2)]
        expected = [(0.0, 0.5, 0.7), (0.7, 2.2, 2.3), (2.3, 2.7, 2.7)]
        np.testing.assert_allclose(np.array(times), np.array(expected), rtol=0, atol=1e-12)

    def test_antenna_and_body_rows(self):
        spec = make(start=ZERO_ANTENNAS,
                    antennas=(AntennaKey(0.5, (math.radians(-30), math.radians(20)), Easing.EASE_IN_OUT, 0.1, "a"),),
                    body=(BodyKey(1.5, math.radians(15), Easing.CARTOON, 0.0, "b"),))
        a, b = segment_speeds(spec)
        self.assertEqual((a["track"], b["track"]), ("antennas", "body"))
        self.assertAlmostEqual(a["change_deg"], 30.0, places=9)  # the larger of |-30| and |20|
        self.assertAlmostEqual(a["d_right_deg"], -30.0, places=9)
        self.assertAlmostEqual(a["d_left_deg"], 20.0, places=9)
        self.assertAlmostEqual(a["avg_speed_dps"], 60.0, places=9)
        self.assertAlmostEqual(a["peak_speed_dps"], 120.0, places=9)  # ease_in_out 2 x average
        self.assertAlmostEqual(b["change_deg"], 15.0, places=9)
        self.assertAlmostEqual(b["d_body_yaw_deg"], 15.0, places=9)
        self.assertAlmostEqual(b["avg_speed_dps"], 10.0, places=9)
        self.assertAlmostEqual(b["peak_speed_dps"], 10.0 * (3 + 1.70158 * 1.525), places=9)
        self.assertIsNone(a["geodesic_deg"])

    def test_rows_have_uniform_json_able_columns(self):
        ex, _ = expressive_pair()
        rows = segment_speeds(ex)
        self.assertEqual([r["track"] for r in rows], ["head"] * 3 + ["antennas"] * 2 + ["body"] * 2)
        for r in rows:
            self.assertEqual(tuple(r), SEGMENT_COLUMNS)
        self.assertIsNone(rows[0]["d_right_deg"])
        self.assertIsNone(rows[3]["translation_mm"])
        self.assertIsNone(rows[3]["geodesic_deg"])
        self.assertEqual(json.loads(json.dumps(rows, allow_nan=False)), rows)
        f32 = make(head=(HeadKey(np.float32(0.5), Pose6(pitch=np.float32(0.2), z=np.float32(-0.004))),),
                   antennas=(AntennaKey(np.float32(0.3), (0.1, -0.1)),), body=(BodyKey(np.float32(0.5), 0.1),))
        rows = segment_speeds(f32)  # float32 / float would stay float32 (NEP 50)
        self.assertEqual(json.loads(json.dumps(rows, allow_nan=False)), rows)
        self.assertIs(type(rows[0]["avg_speed_dps"]), float)

    def test_effective_parameters_are_used(self):
        base = make(head=(HeadKey(0.5, pitch(10), L, 0.2),), body=(BodyKey(1.0, math.radians(10), L),))
        rows = segment_speeds(base.scaled(amplitude=2.0, tempo=2.0))
        self.assertAlmostEqual(rows[0]["duration_s"], 0.25, places=12)
        self.assertAlmostEqual(rows[0]["hold_s"], 0.1, places=12)
        self.assertAlmostEqual(rows[0]["change_deg"], 20.0, places=9)
        self.assertAlmostEqual(rows[0]["avg_speed_dps"], 80.0, places=9)  # 4 x the designed 20 deg/s
        self.assertAlmostEqual(rows[1]["avg_speed_dps"], 40.0, places=9)

    def test_multi_axis_rotation_follows_the_sdk_path(self):
        spec = make(head=(HeadKey(1.0, Pose6.from_deg_mm(pitch_deg=10, yaw_deg=10), L),))
        row = segment_speeds(spec)[0]
        r = rotation_xyz(0.0, math.radians(10), math.radians(10))
        geodesic = math.degrees(math.acos((np.trace(r) - 1.0) / 2.0))
        self.assertAlmostEqual(row["geodesic_deg"], geodesic, places=9)
        # The SDK turns yaw as a scalar (10 deg) while it slerps the 10 deg pitch residual: |(0, 10, 10)| deg.
        self.assertAlmostEqual(row["change_deg"], math.hypot(10.0, 10.0), places=9)
        self.assertGreater(row["change_deg"], geodesic)
        self.assertAlmostEqual(row["avg_speed_dps"], row["change_deg"], places=12)  # 1 s key

    def test_head_change_is_the_sdk_path_length(self):
        cases = (
            (Pose6.from_deg_mm(yaw_deg=-100), Pose6.from_deg_mm(yaw_deg=100)),  # through the front: 200, not 160
            (Pose6(), Pose6.from_deg_mm(roll_deg=10, pitch_deg=20, yaw_deg=40)),
            (Pose6.from_deg_mm(yaw_deg=170), Pose6.from_deg_mm(yaw_deg=190)),  # SDK reads -170: 340 deg
            (Pose6.from_deg_mm(roll_deg=25, pitch_deg=-30, yaw_deg=-60, z_mm=5),
             Pose6.from_deg_mm(roll_deg=-20, pitch_deg=35, yaw_deg=70)),
        )
        for a, b in cases:
            with self.subTest(a=a, b=b):
                row = segment_speeds(make(start=RobotState(head=a), head=(HeadKey(2.0, b, L),)))[0]
                self.assertAlmostEqual(row["change_deg"], sdk_path_deg(a, b), delta=1e-3)
                self.assertAlmostEqual(row["geodesic_deg"], math.degrees(rotation_distance(a.matrix(), b.matrix())),
                                       places=9)
                self.assertAlmostEqual(row["avg_speed_dps"], row["change_deg"] / 2.0, places=12)
        row = segment_speeds(make(start=RobotState(head=cases[0][0]), head=(HeadKey(1.0, cases[0][1], L),)))[0]
        self.assertAlmostEqual(row["change_deg"], 200.0, places=9)
        self.assertAlmostEqual(row["geodesic_deg"], 160.0, places=9)

    def test_peak_factors_match_the_sdk_time_law(self):
        # Test-only SDK use: the library copies these numbers so that it does not import reachy_mini.
        from reachy_mini.utils.interpolation import InterpolationTechnique

        from reachy_motion.analysis.interpolation import characterize

        self.assertEqual(set(PEAK_SPEED_FACTOR), {e.value for e in Easing})
        for name, k in PEAK_SPEED_FACTOR.items():
            with self.subTest(easing=name):
                self.assertAlmostEqual(characterize(InterpolationTechnique(name), n=1001).v_peak, k, places=12)


class TestNeutralConformance(unittest.TestCase):
    def codes(self, spec: MotionSpec) -> list[str]:
        return [i.code for i in neutral_conformance(spec)]

    def test_clean_neutral_has_no_issues(self):
        _, ne = expressive_pair()
        self.assertEqual(neutral_conformance(ne), [])

    def test_expressive_variant_is_not_checked(self):
        ex, _ = expressive_pair()
        self.assertEqual(neutral_conformance(ex), [])

    def test_antennas(self):
        _, ne = expressive_pair()
        s = INIT_ANTENNAS
        moved = replace(ne, antennas=(AntennaKey(0.5, (s[0] + 1e-6, s[1]), L),))
        held = replace(ne, antennas=(AntennaKey(0.5, s, L),))
        tiny = replace(ne, antennas=(AntennaKey(0.5, (s[0] + 1e-10, s[1]), L),))
        big = replace(ne, antennas=(AntennaKey(0.5, (0.0, 0.0), L, label="perk"),))
        self.assertEqual(self.codes(moved), ["neutral_antennas"])
        self.assertEqual(neutral_conformance(moved)[0].severity, "warning")
        self.assertEqual(self.codes(held), [])
        self.assertEqual(self.codes(tiny), [])  # within 1e-9 rad
        issue = neutral_conformance(big)[0]
        self.assertIn("antennas[0] 'perk'", issue.message)
        self.assertNotIn("rest", issue.message)  # no sub-tick hint for a real move

    def test_ten_degrees_is_not_rest(self):
        # A file-style -10/+10 deg key is 0.0019 deg from the SDK rest angle: reported (exact rule), with a hint.
        _, ne = expressive_pair()
        ten = replace(ne, antennas=(AntennaKey(0.5, (math.radians(-10), math.radians(10)), L, label="hold"),))
        issues = neutral_conformance(ten)
        self.assertEqual([(i.code, i.severity) for i in issues], [("neutral_antennas", "warning")])
        self.assertIn("0.001886 deg", issues[0].message)
        self.assertIn("rest for the SDK rest angle", issues[0].message)
        self.assertIn("leave the antenna track empty", issues[0].message)
        c = comparison_conditions(expressive_pair()[0], ten)
        self.assertTrue(c["same_end"])  # the start / end comparison has a tolerance ...
        self.assertTrue(c["antennas_used"]["neutral"])  # ... the "no antenna motion" rule does not

    def test_sound(self):
        _, ne = expressive_pair()
        issues = neutral_conformance(replace(ne, sound=SoundCue("x.wav", 0.0)))
        self.assertEqual([(i.code, i.severity) for i in issues], [("neutral_sound", "warning")])

    def test_easing_on_head_and_body(self):
        _, ne = expressive_pair()
        curved_head = replace(ne, head=(replace(ne.head[0], easing=Easing.MIN_JERK), ne.head[1]))
        curved_body = replace(ne, body=(BodyKey(1.0, 0.0, Easing.CARTOON, label="turn"),))
        linear_antennas_ok = replace(ne, antennas=(AntennaKey(0.5, INIT_ANTENNAS, Easing.CARTOON),))
        issue = neutral_conformance(curved_head)[0]
        self.assertEqual((issue.code, issue.severity), ("neutral_not_constant_speed", "warning"))
        self.assertIn("head[0] 'down' minjerk", issue.message)
        self.assertEqual(self.codes(curved_body), ["neutral_not_constant_speed"])
        self.assertEqual(self.codes(linear_antennas_ok), [])  # antenna easing is not a speed rule

    def test_speed_uniformity(self):
        uneven = make("neutral", head=(HeadKey(0.5, pitch(10), L), HeadKey(0.5, Pose6(), L),
                                       HeadKey(0.5, pitch(20), L)))  # 20, 20, 40 deg/s
        even = make("neutral", head=(HeadKey(0.5, pitch(10), L), HeadKey(0.55, Pose6(), L)))  # 20 vs 18.2
        issues = neutral_conformance(uneven)
        self.assertEqual([(i.code, i.severity) for i in issues], [("neutral_speed_not_uniform", "info")])
        self.assertIn("head angular speeds not uniform: head[2] 40 deg/s vs median 20 deg/s", issues[0].message)
        self.assertNotIn("head[0]", issues[0].message)
        self.assertEqual(neutral_conformance(even), [])
        translation_only = make("neutral", head=(HeadKey(0.5, pitch(10), L), HeadKey(0.5, pitch(10, z_mm=5), L),
                                                 HeadKey(0.5, Pose6(), L)))
        self.assertEqual(neutral_conformance(translation_only), [])  # one pace: 20 deg/s and 10 mm/s

    def test_translation_speed_uniformity(self):
        lifts = make("neutral", head=(HeadKey(0.5, pitch(0, z_mm=10), L), HeadKey(1.0, Pose6(), L),
                                      HeadKey(0.5, pitch(0, z_mm=10), L)))  # 20, 10, 20 mm/s
        issues = neutral_conformance(lifts)
        self.assertEqual([(i.code, i.severity) for i in issues], [("neutral_speed_not_uniform", "info")])
        self.assertIn("head translation speeds not uniform: head[1] 10 mm/s vs median 20 mm/s", issues[0].message)
        # Mixed keys: 'sink more' (10 mm/s, no rotation) is slower than the pace set by the other keys.
        issues = neutral_conformance(failure_like_neutral())
        self.assertEqual([i.code for i in issues], ["neutral_speed_not_uniform"])
        self.assertIn("head[1] 'sink more'", issues[0].message)
        self.assertNotIn("head[0]", issues[0].message)
        self.assertIn("pace 40%", issues[0].message)

    def test_issue_severity_is_checked(self):
        with self.assertRaises(ValueError):
            Issue("x", "y", "error")
        self.assertEqual(Issue("a", "b").to_dict(), {"code": "a", "message": "b", "severity": "warning"})


class TestComparisonConditions(unittest.TestCase):
    def test_matching_pair(self):
        ex, ne = expressive_pair()
        c = comparison_conditions(ex, ne)
        self.assertEqual(c["data_kind"], "computed")
        self.assertTrue(c["same_start"])
        self.assertTrue(c["same_end"])
        self.assertTrue(all(v == 0.0 for v in c["start_difference"].values()))
        self.assertLess(max(c["end_difference"].values()), 1e-9)
        self.assertEqual(c["issues"], [])
        self.assertEqual(c["motion"], {"expressive": "success:expressive", "neutral": "success:neutral"})
        self.assertEqual(c["duration_s"], {"expressive": 2.0, "neutral": 1.0})
        self.assertEqual(c["key_counts"]["expressive"], {"head": 3, "antennas": 2, "body": 2})
        self.assertEqual(c["key_counts"]["neutral"], {"head": 2, "antennas": 0, "body": 0})
        self.assertEqual(c["antennas_used"], {"expressive": True, "neutral": False})
        self.assertEqual(c["easings"]["expressive"]["head"], ["minjerk", "cartoon", "ease_in_out"])
        self.assertEqual(c["easings"]["neutral"], {"head": ["linear"], "antennas": [], "body": []})
        self.assertAlmostEqual(c["max_head_rotation_deg"]["expressive"], 10.0, places=9)
        self.assertAlmostEqual(c["max_head_translation_mm"]["neutral"], 4.0, places=9)
        self.assertAlmostEqual(c["max_antenna_change_deg"]["expressive"], math.degrees(0.1745), places=9)
        self.assertAlmostEqual(c["max_body_yaw_change_deg"]["expressive"], 10.0, places=9)
        self.assertEqual(c["sound"], {"expressive": {"file": "success.wav", "at_s": 0.1}, "neutral": None})
        self.assertEqual(c["principles"]["neutral"], ["timing", "slow_in_slow_out"])
        rot = c["speeds"]["neutral"]["head_rotation_dps"]
        self.assertEqual(rot["moving_keys"], 2)
        self.assertAlmostEqual(rot["overall_avg"], 20.0, places=9)
        self.assertAlmostEqual(rot["max_nominal_peak"], 20.0, places=9)
        self.assertAlmostEqual(c["speeds"]["expressive"]["head_rotation_dps"]["max_nominal_peak"],
                               60.0 * (3 + 1.70158 * 1.525), places=6)  # the cartoon key: 15 deg in 0.25 s

    def test_output_is_json_able(self):
        ex, ne = expressive_pair()
        f32 = Pose6(pitch=np.float32(0.2), z=np.float32(-0.004))  # NumPy 2 keeps float32 through x * 1000.0
        ex32 = make("expressive", head=(HeadKey(0.5, f32), HeadKey(0.5, Pose6())),
                    antennas=(AntennaKey(0.3, (np.float32(0.1), -0.1)),), body=(BodyKey(0.5, np.float32(0.1)),))
        ne32 = make("neutral", head=(HeadKey(0.5, f32, L), HeadKey(0.5, Pose6(), L)), start=RobotState(head=f32))
        ends_at_f32 = replace(ex32, head=(HeadKey(0.5, f32),))
        cases = (comparison_conditions(ex, ne),
                 comparison_conditions(ex, replace(ne, start=RobotState(head=pitch(5)), sound=SoundCue("x.wav", 0.2))),
                 comparison_conditions(ex32, ne32), comparison_conditions(ends_at_f32, ne32))
        for c in cases:
            text = json.dumps(c, allow_nan=False)
            self.assertEqual(json.loads(text), c)  # only dict / list / str / float / int / bool / None
        self.assertIs(type(cases[3]["end_state"]["expressive"]["head"]["z_mm"]), float)

    def test_start_mismatch(self):
        ex, ne = expressive_pair()
        c = comparison_conditions(ex, replace(ne, start=RobotState(head=pitch(5))))
        self.assertFalse(c["same_start"])
        self.assertAlmostEqual(c["start_difference"]["head_rotation_deg"], 5.0, places=9)
        self.assertTrue(c["same_end"])
        issue = next(i for i in c["issues"] if i["code"] == "start_mismatch")
        self.assertEqual(issue["severity"], "warning")
        self.assertIn("head 5 deg", issue["message"])

    def test_end_mismatch(self):
        ex, ne = expressive_pair()
        c = comparison_conditions(ex, replace(ne, head=(ne.head[0], HeadKey(0.35, pitch(3), L))))  # 20 deg/s
        self.assertTrue(c["same_start"])
        self.assertFalse(c["same_end"])
        self.assertAlmostEqual(c["end_difference"]["head_rotation_deg"], 3.0, places=9)
        self.assertEqual([i["code"] for i in c["issues"]], ["end_mismatch"])
        antennas_end_up = replace(ex, antennas=(AntennaKey(0.4, (0.0, 0.0)),))
        c = comparison_conditions(antennas_end_up, ne)
        self.assertFalse(c["same_end"])
        self.assertAlmostEqual(c["end_difference"]["antennas_max_deg"], math.degrees(0.1745), places=9)

    def test_tolerance(self):
        ex, ne = expressive_pair()
        ten = replace(ex, antennas=(AntennaKey(0.4, (math.radians(-10), math.radians(10))),))  # file-style -10/+10
        c = comparison_conditions(ten, ne)
        self.assertTrue(c["same_end"])  # 0.0019 deg from the SDK rest constant
        self.assertAlmostEqual(c["end_difference"]["antennas_max_deg"], 10.0 - math.degrees(0.1745), places=12)
        self.assertFalse(comparison_conditions(ten, ne, tol_deg=1e-4)["same_end"])
        self.assertEqual(c["tolerance"], {"deg": compare.SAME_POSE_TOL_DEG, "mm": compare.SAME_POSE_TOL_MM})

    def test_neutral_conformance_and_role_issues_are_included(self):
        ex, ne = expressive_pair()
        c = comparison_conditions(ex, replace(ne, sound=SoundCue("x.wav", 0.0)))
        self.assertEqual([i["code"] for i in c["issues"]], ["neutral_sound"])
        c = comparison_conditions(ne, ex)  # roles swapped
        self.assertIn("variant_mismatch", [i["code"] for i in c["issues"]])
        c = comparison_conditions(ex, replace(ne, name="failure"))
        self.assertIn("name_mismatch", [i["code"] for i in c["issues"]])

    def test_issues_are_plain_dicts_and_comparison_issues_gives_objects(self):
        ex, ne = expressive_pair()
        bad = replace(ne, start=RobotState(head=pitch(5)), head=(ne.head[0], HeadKey(0.5, pitch(3), L)),
                      sound=SoundCue("x.wav", 0.0))
        c = comparison_conditions(ex, bad)
        objects = comparison_issues(ex, bad)
        self.assertEqual([i.code for i in objects], ["start_mismatch", "end_mismatch", "neutral_sound"])
        self.assertTrue(all(isinstance(i, Issue) for i in objects))
        self.assertEqual(c["issues"], [i.to_dict() for i in objects])
        self.assertTrue(all(type(i) is dict and set(i) == {"code", "message", "severity"} for i in c["issues"]))
        self.assertEqual(comparison_issues(ex, ne), [])

    def test_yaw_path_issues(self):
        ex, ne = expressive_pair()
        long_way = replace(ex, start=RobotState(head=Pose6.from_deg_mm(yaw_deg=-100)),
                           head=(HeadKey(2.0, Pose6.from_deg_mm(yaw_deg=100), L, label="sweep"),))
        issues = [i for i in comparison_issues(long_way, ne) if i.code.startswith("yaw_")]
        self.assertEqual([(i.code, i.severity) for i in issues], [("yaw_long_way", "info")])
        self.assertIn("head[0] 'sweep' +200.0 deg", issues[0].message)
        wraps = replace(ex, head=(HeadKey(1.0, Pose6.from_deg_mm(yaw_deg=170), L),
                                  HeadKey(1.0, Pose6.from_deg_mm(yaw_deg=190), L), HeadKey(1.0, Pose6(), L)))
        issues = [i for i in comparison_issues(wraps, ne) if i.code.startswith("yaw_")]
        self.assertEqual([(i.code, i.severity) for i in issues], [("yaw_wraps", "warning")])
        self.assertIn("head[1] designed +20.0 deg, SDK -340.0 deg", issues[0].message)
        self.assertEqual(segment_speeds(wraps)[1]["change_deg"], segment_speeds(wraps)[1]["avg_speed_dps"])
        self.assertAlmostEqual(segment_speeds(wraps)[1]["change_deg"], 340.0, places=9)
        self.assertFalse([i for i in comparison_issues(ex, ne) if i.code.startswith("yaw_")])

    def test_state_difference(self):
        a = RobotState(head=Pose6.from_deg_mm(yaw_deg=3, x_mm=3, y_mm=4), antennas=(0.0, 0.1), body_yaw=0.2)
        d = state_difference(REST, a)
        self.assertAlmostEqual(d["head_rotation_deg"], 3.0, places=9)
        self.assertAlmostEqual(d["head_translation_mm"], 5.0, places=9)
        self.assertAlmostEqual(d["antennas_max_deg"], math.degrees(0.1745), places=9)
        self.assertAlmostEqual(d["body_yaw_deg"], math.degrees(0.2), places=12)


class TestRetimeUniformSpeed(unittest.TestCase):
    def source(self) -> MotionSpec:
        return make("neutral",
                    head=(HeadKey(0.3, pitch(10), Easing.MIN_JERK, 0.2, "a"),
                          HeadKey(0.3, pitch(-20), Easing.CARTOON, 0.0, "b"),
                          HeadKey(0.7, pitch(-20), Easing.EASE_IN_OUT, 0.1, "still"),
                          HeadKey(0.1, Pose6(), Easing.MIN_JERK, 0.0, "c")),
                    antennas=(AntennaKey(0.2, (0.0, 0.0), Easing.CARTOON, 0.3, "kept"),),
                    body=(BodyKey(0.2, math.radians(15), Easing.MIN_JERK, 0.4, "turn"), BodyKey(0.5, math.radians(15))),
                    sound=SoundCue("kept.wav", 0.1))

    def test_uniform_speed_and_linear_easing(self):
        out = retime_uniform_speed(self.source(), 20.0)
        moving = [r for r in segment_speeds(out) if r["track"] in ("head", "body") and r["moves"]]
        self.assertEqual(len(moving), 4)
        for r in moving:
            self.assertAlmostEqual(r["avg_speed_dps"], 20.0, delta=20.0 * 1e-6)
        self.assertEqual({k.easing for k in out.head + out.body}, {Easing.LINEAR})
        self.assertEqual([k.duration for k in out.head], [0.5, 1.5, 0.7, 1.0])  # 1 us rounding gives clean values
        self.assertEqual([k.duration for k in out.body], [0.75, 0.5])
        neutral_ready = replace(out, antennas=(), sound=None)
        self.assertEqual(neutral_conformance(neutral_ready), [])
        self.assertIn("neutral_speed_not_uniform", [i.code for i in neutral_conformance(self.source())])

    def test_everything_else_is_unchanged(self):
        src = self.source()
        out = retime_uniform_speed(src, 20.0)
        self.assertEqual([(k.hold, k.label, k.pose) for k in out.head], [(k.hold, k.label, k.pose) for k in src.head])
        self.assertEqual([(k.hold, k.label, k.yaw) for k in out.body], [(k.hold, k.label, k.yaw) for k in src.body])
        self.assertEqual(out.antennas, src.antennas)  # antenna track untouched, easing included
        self.assertEqual((out.start, out.sound, out.amplitude_scale, out.tempo_scale),
                         (src.start, src.sound, src.amplitude_scale, src.tempo_scale))
        self.assertEqual(out.head[2].duration, 0.7)  # non-moving key keeps its duration

    def test_set_linear_false_keeps_easings(self):
        src = self.source()
        out = retime_uniform_speed(src, 20.0, set_linear=False)
        self.assertEqual([k.easing for k in out.head], [k.easing for k in src.head])
        self.assertEqual([k.easing for k in out.body], [k.easing for k in src.body])

    def test_translation_speed_and_minimum_duration(self):
        spec = make("neutral", head=(HeadKey(0.3, pitch(2, z_mm=10), L),  # 2 deg and 10 mm
                                     HeadKey(0.3, pitch(2, z_mm=0), L),  # translation only
                                     HeadKey(0.3, pitch(2.1), L)))  # 0.1 deg
        # Default translation speed = the designed median, 10 mm / 0.3 s: the 2 deg key is not squeezed to 0.1 s.
        self.assertAlmostEqual(median_translation_speed_mms(spec), 100.0 / 3.0, places=9)
        no_trans = retime_uniform_speed(spec, 20.0)
        self.assertEqual([k.duration for k in no_trans.head], [0.3, 0.3, MIN_KEY_DURATION_S])
        speeds = [r["avg_trans_speed_mms"] for r in segment_speeds(no_trans)[:2]]
        np.testing.assert_allclose(speeds, [100.0 / 3.0] * 2, rtol=1e-5)  # uniform and not raised
        with_trans = retime_uniform_speed(spec, 20.0, trans_speed_mms=25.0)
        self.assertEqual([k.duration for k in with_trans.head], [0.4, 0.4, MIN_KEY_DURATION_S])

    def test_default_translation_speed_never_exceeds_the_design(self):
        # The GUI's "Apply uniform head speed" passes only an angular speed (40 deg/s).
        src = failure_like_neutral()
        designed = [r["avg_trans_speed_mms"] for r in segment_speeds(src)]  # 15, 10, 25 mm/s
        self.assertAlmostEqual(median_translation_speed_mms(src), 15.0, places=9)
        out = retime_uniform_speed(src, 40.0)
        self.assertEqual([k.duration for k in out.head], [1.0, 0.666667, 1.666667])
        speeds = [r["avg_trans_speed_mms"] for r in segment_speeds(out)]
        np.testing.assert_allclose(speeds, [15.0] * 3, rtol=1e-5)  # uniform at the designed median ...
        self.assertLessEqual(max(speeds), max(designed))  # ... never faster than the fastest designed key
        self.assertEqual(out.validate(), [])
        self.assertEqual(neutral_conformance(out), [])

    def test_no_jump_at_the_rotation_threshold(self):
        # Review case: a 10 mm move with 1e-5 deg of pitch used to collapse from 0.5 s to 0.02 s (500 mm/s).
        spec = make("neutral", head=(HeadKey(0.5, pitch(0, z_mm=10), L, label="pure lift"),
                                     HeadKey(0.5, pitch(1e-5, z_mm=0), L, label="drop + 1e-5 deg"),
                                     HeadKey(0.5, pitch(0.5, z_mm=10), L, label="lift + 0.5 deg")))
        out = retime_uniform_speed(spec, 20.0)
        self.assertEqual([k.duration for k in out.head], [0.5, 0.5, 0.5])

    def test_translation_without_any_usable_duration_needs_a_speed(self):
        spec = make("neutral", head=(HeadKey(0.0, pitch(5, z_mm=10), L, label="instant"),))
        self.assertIsNone(median_translation_speed_mms(spec))
        with self.assertRaisesRegex(ValueError, r"head\[0\] 'instant' translates .*pass trans_speed_mms"):
            retime_uniform_speed(spec, 20.0)
        self.assertEqual(retime_uniform_speed(spec, 20.0, trans_speed_mms=20.0).head[0].duration, 0.5)
        rotation_only = make("neutral", head=(HeadKey(0.0, pitch(5), L),))
        self.assertEqual(retime_uniform_speed(rotation_only, 20.0).head[0].duration, 0.25)

    def test_rotation_is_measured_along_the_sdk_yaw_path(self):
        spec = make("neutral", start=RobotState(head=Pose6.from_deg_mm(yaw_deg=-100)),
                    head=(HeadKey(1.0, Pose6.from_deg_mm(yaw_deg=100), L),))
        out = retime_uniform_speed(spec, 20.0)
        self.assertEqual(out.head[0].duration, 10.0)  # 200 deg through the front, not the 160 deg geodesic
        self.assertAlmostEqual(segment_speeds(out)[0]["avg_speed_dps"], 20.0, places=9)

    def test_tempo_scale_still_applies_on_top(self):
        out = retime_uniform_speed(self.source().scaled(tempo=2.0), 20.0)
        self.assertEqual(out.tempo_scale, 2.0)
        self.assertEqual(out.head[0].duration, 0.5)  # designed keys
        self.assertAlmostEqual(segment_speeds(out)[0]["avg_speed_dps"], 40.0, places=6)  # executed

    def test_invalid_speeds(self):
        for bad in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(rot=bad), self.assertRaises(ValueError):
                retime_uniform_speed(self.source(), bad)
            with self.subTest(trans=bad), self.assertRaises(ValueError):
                retime_uniform_speed(self.source(), 20.0, trans_speed_mms=bad)


class TestSdkFree(unittest.TestCase):
    def test_compare_imports_no_sdk_and_only_library_modules(self):
        tree = ast.parse(Path(compare.__file__).read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse([m for m in modules if m.split(".")[0] == "reachy_mini"], modules)
        own = [m for m in modules if m.startswith("reachy_motion")]
        self.assertTrue(all(m.startswith("reachy_motion.library.") for m in own), own)


if __name__ == "__main__":
    unittest.main()
