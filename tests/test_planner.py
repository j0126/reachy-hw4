"""Tests for ``reachy_motion.planner`` (Phase 2: V2.1 goto equivalence and the planner contract).

Hermetic: only SDK math is called (``GotoMove``, ``time_trajectory``, ``linear_pose_interpolation`` and the SDK
``Rotation``) - no daemon, no MuJoCo, no robot, no network. Everything checked here is "computed" data.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

import numpy as np
from reachy_mini.motion.goto import GotoMove
from reachy_mini.utils.interpolation import InterpolationTechnique, linear_pose_interpolation

from reachy_motion import planner
from reachy_motion.library.pose import INIT_ANTENNAS, REST, Pose6, RobotState, pose_from_matrix, rotation_distance
from reachy_motion.library.spec import (
    MIN_KEY_DURATION_S,
    TRACKS,
    AntennaKey,
    BodyKey,
    Easing,
    HeadKey,
    MotionSpec,
    Principle,
    PrincipleUse,
)
from reachy_motion.timeline import Timeline

DEG = math.pi / 180.0
_PRINCIPLES = (PrincipleUse(Principle.TIMING, "planner unit test"),)

#: A start / end state away from rest on every channel (combined head rotation + translation).
OFF_REST = RobotState(head=Pose6.from_deg_mm(roll_deg=-6.0, pitch_deg=9.0, yaw_deg=40.0, x_mm=3.0, y_mm=4.0, z_mm=-5.0),
                      antennas=(-1.0, 0.7), body_yaw=12.0 * DEG)

#: V2.1 targets: (label, head pose, antennas (right, left) rad, body yaw rad). The last one combines
#: yaw + pitch + roll + translation.
V21_TARGETS = (
    ("yaw", Pose6.from_deg_mm(yaw_deg=30.0), (-0.6, 0.6), 20.0 * DEG),
    ("pitch_z", Pose6.from_deg_mm(pitch_deg=-15.0, z_mm=10.0), (0.4, -0.4), -30.0 * DEG),
    ("combined", Pose6.from_deg_mm(roll_deg=8.0, pitch_deg=12.0, yaw_deg=-35.0, x_mm=5.0, y_mm=-8.0, z_mm=6.0),
     (-1.2, 0.9), 25.0 * DEG),
)
V21_DURATIONS = (0.8, 1.23, 2.0)  # on the grid, off the grid, long

#: head_path_angle pairs (start, end). All but the third combine a yaw change with pitch / roll; the third
#: changes pitch / roll only (no yaw change: the SDK path is the geodesic).
PATH_PAIRS = (
    (Pose6(), Pose6.from_deg_mm(yaw_deg=30.0, pitch_deg=20.0)),
    (Pose6(), V21_TARGETS[2][1]),
    (Pose6.from_deg_mm(roll_deg=10.0, pitch_deg=5.0), Pose6.from_deg_mm(roll_deg=-10.0, pitch_deg=15.0)),
    (Pose6.from_deg_mm(roll_deg=-20.0, pitch_deg=25.0, yaw_deg=50.0),
     Pose6.from_deg_mm(roll_deg=25.0, pitch_deg=-30.0, yaw_deg=-60.0)),
    (OFF_REST.head, Pose6()),
)
COMBINED_PATH_PAIRS = PATH_PAIRS[:2] + PATH_PAIRS[3:]


def make_spec(head=(), antennas=(), body=(), **kw) -> MotionSpec:
    fields = dict(name="aha_recommend", variant="expressive", intent="planner unit test", valence=0.3, arousal=0.4,
                  principles=_PRINCIPLES)
    fields.update(kw)
    return MotionSpec(head=tuple(head), antennas=tuple(antennas), body=tuple(body), **fields)


def multi_key_spec(**kw) -> MotionSpec:
    """Three tracks of different lengths (head 2.1 s, antennas 0.9 s, body 1.9 s) with holds and all four easings."""
    head = (HeadKey(0.5, Pose6.from_deg_mm(pitch_deg=-10.0, z_mm=5.0), Easing.MIN_JERK, hold=0.2, label="look up"),
            HeadKey(0.7, Pose6.from_deg_mm(yaw_deg=25.0, roll_deg=5.0), Easing.CARTOON, label="turn"),
            HeadKey(0.4, Pose6(), Easing.EASE_IN_OUT, hold=0.3, label="back"))
    antennas = (AntennaKey(0.3, (-0.6, 0.6), Easing.LINEAR, hold=0.1, label="perk"),
                AntennaKey(0.5, INIT_ANTENNAS, Easing.MIN_JERK, label="relax"))
    body = (BodyKey(0.9, 15.0 * DEG, Easing.MIN_JERK, hold=0.4, label="lean"),
            BodyKey(0.6, 0.0, Easing.EASE_IN_OUT, label="return"))
    return make_spec(head=head, antennas=antennas, body=body, **kw)


def sdk_goto(start: RobotState, pose: Pose6, antennas, body_yaw: float, duration: float, easing: Easing) -> GotoMove:
    """The SDK's own GotoMove, built like Backend.goto_target does (daemon/backend/abstract.py:966-977)."""
    return GotoMove(start_head_pose=start.head.matrix(), target_head_pose=pose.matrix(),
                    start_antennas=np.array(start.antennas), target_antennas=np.array(antennas, dtype=float),
                    start_body_yaw=start.body_yaw, target_body_yaw=body_yaw, duration=duration,
                    method=planner.easing_to_sdk(easing))


def goto_samples(move: GotoMove, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    out = [move.evaluate(float(t)) for t in ts]
    return (np.array([o[0] for o in out]), np.array([o[1] for o in out]),
            np.array([float(o[2]) for o in out]))


def channel(track: str, values: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    head, antennas, body = values
    return {"head": head, "antennas": antennas, "body": body}[track]


def key_value(track: str, key) -> np.ndarray:
    return key.pose.matrix() if track == "head" else np.asarray(key.value, dtype=float)


def hold_timeline(duration: float, rate: float, state: RobotState = REST) -> Timeline:
    """A valid constant timeline on the planner's own grid (no SDK call: cheap enough for property sweeps)."""
    t = planner.grid_times(duration, rate)
    n = len(t)
    keys = np.zeros(n, dtype=np.int64)
    return Timeline(name="hold", variant="", rate_hz=rate, duration=duration, t=t,
                    head=np.repeat(state.head.matrix()[None], n, axis=0),
                    antennas=np.repeat(np.array([state.antennas]), n, axis=0), body_yaw=np.full(n, state.body_yaw),
                    head_key=keys, antenna_key=keys.copy(), body_key=keys.copy())


def numeric_peaks(tl: Timeline) -> dict[str, float]:
    """Largest per-sample speeds of a timeline (chord / dt: never above the continuous-time peak)."""
    rate = tl.rate_hz
    rot = max(rotation_distance(tl.head[k], tl.head[k + 1]) for k in range(len(tl) - 1))
    trans = np.max(np.linalg.norm(np.diff(tl.head[:, :3, 3], axis=0), axis=1))
    return {"rot_dps": math.degrees(rot) * rate, "trans_mms": float(trans) * 1000.0 * rate,
            "antenna_dps": math.degrees(float(np.max(np.abs(np.diff(tl.antennas, axis=0))))) * rate,
            "body_dps": math.degrees(float(np.max(np.abs(np.diff(tl.body_yaw))))) * rate}


class EasingMappingTest(unittest.TestCase):
    def test_easing_maps_one_to_one_by_value(self) -> None:
        self.assertEqual(len(Easing), len(InterpolationTechnique))
        for e in Easing:
            m = planner.easing_to_sdk(e)
            self.assertIsInstance(m, InterpolationTechnique)
            self.assertEqual(m.value, e.value)
            self.assertIs(planner.easing_to_sdk(e.value), m)  # plain strings are accepted too
        self.assertEqual({planner.easing_to_sdk(e) for e in Easing}, set(InterpolationTechnique))
        with self.assertRaises(ValueError):
            planner.easing_to_sdk("bounce")

    def test_peak_speed_ratios(self) -> None:
        c2 = 1.70158 * 1.525  # interpolation.py:137-138; peak s' of easeInOutBack at tau = 0.5 is c2 + 3
        expected = {Easing.LINEAR: 1.0, Easing.MIN_JERK: 1.875, Easing.EASE_IN_OUT: 2.0, Easing.CARTOON: c2 + 3.0}
        for e, k in expected.items():
            self.assertAlmostEqual(planner.peak_speed_ratio(e), k, delta=1e-9 * k, msg=e.value)


class GotoEquivalenceTest(unittest.TestCase):
    """V2.1: a single-key spec (same duration / easing on all tracks, start REST) IS one SDK goto."""

    def test_v2_1_single_key_spec_equals_sdk_gotomove(self) -> None:
        rate = 50.0
        for easing in Easing:
            for label, pose, ant, body in V21_TARGETS:
                for d in V21_DURATIONS:
                    with self.subTest(easing=easing.value, target=label, duration=d):
                        spec = make_spec(head=[HeadKey(d, pose, easing)], antennas=[AntennaKey(d, ant, easing)],
                                         body=[BodyKey(d, body, easing)])
                        tl = planner.plan(spec, rate)
                        self.assertEqual(tl.validate(), [])
                        # uniform grid t_k = k / rate, k = 0..ceil(D * rate - 1e-9)
                        k_last = math.ceil(d * rate - 1e-9)
                        self.assertEqual(len(tl), k_last + 1)
                        np.testing.assert_array_equal(tl.t, np.arange(k_last + 1) / rate)
                        self.assertTrue(np.allclose(np.diff(tl.t), 1.0 / rate, rtol=0.0, atol=1e-12))
                        # every grid sample before D equals GotoMove.evaluate(t)
                        before = np.flatnonzero(tl.t < d)
                        self.assertGreaterEqual(len(before), int(d * rate) - 1)
                        h, a, b = goto_samples(sdk_goto(REST, pose, ant, body, d, easing), tl.t[before])
                        self.assertLessEqual(float(np.max(np.abs(tl.head[before] - h))), 1e-12)
                        self.assertLessEqual(float(np.max(np.abs(tl.antennas[before] - a))), 1e-12)
                        self.assertLessEqual(float(np.max(np.abs(tl.body_yaw[before] - b))), 1e-12)
                        # ... and in fact bit for bit (same SDK calls with the same float inputs)
                        np.testing.assert_array_equal(tl.head[before], h)
                        np.testing.assert_array_equal(tl.antennas[before], a)
                        np.testing.assert_array_equal(tl.body_yaw[before], b)
                        # the last sample is the end state exactly (a daemon goto never evaluates t = D)
                        self.assertGreaterEqual(tl.t[-1], d)
                        np.testing.assert_array_equal(tl.head[-1], pose.matrix())
                        np.testing.assert_array_equal(tl.antennas[-1], np.array(ant))
                        self.assertEqual(float(tl.body_yaw[-1]), body)
                        # metadata
                        self.assertEqual((tl.name, tl.variant, tl.rate_hz), ("aha_recommend", "expressive", rate))
                        self.assertEqual(tl.duration, spec.duration)
                        self.assertEqual(tl.spec_digest, spec.digest())
                        for keys in (tl.head_key, tl.antenna_key, tl.body_key):
                            np.testing.assert_array_equal(keys, np.zeros(len(tl), dtype=int))

    def test_other_rate_and_arbitrary_times_from_any_start(self) -> None:
        rng = np.random.default_rng(20261110)
        _label, pose, ant, body = V21_TARGETS[2]
        d = 0.97
        for easing in Easing:
            with self.subTest(easing=easing.value):
                spec = make_spec(head=[HeadKey(d, pose, easing)], antennas=[AntennaKey(d, ant, easing)],
                                 body=[BodyKey(d, body, easing)], start=OFF_REST)
                move = sdk_goto(OFF_REST, pose, ant, body, d, easing)
                tl = planner.plan(spec, 100.0)
                self.assertEqual(tl.validate(), [])
                before = np.flatnonzero(tl.t < d)
                h, a, b = goto_samples(move, tl.t[before])
                np.testing.assert_array_equal(tl.head[before], h)
                np.testing.assert_array_equal(tl.antennas[before], a)
                np.testing.assert_array_equal(tl.body_yaw[before], b)
                ts = np.sort(rng.uniform(0.0, d, 40))
                head, antennas, body_yaw = planner.evaluate(spec, ts)
                h, a, b = goto_samples(move, ts)
                np.testing.assert_array_equal(head, h)
                np.testing.assert_array_equal(antennas, a)
                np.testing.assert_array_equal(body_yaw, b)

    def test_scalar_time_shapes(self) -> None:
        head, antennas, body = planner.evaluate(multi_key_spec(), 0.3)
        self.assertEqual((head.shape, antennas.shape, body.shape), ((1, 4, 4), (1, 2), (1,)))


class MultiKeyTest(unittest.TestCase):
    def test_continuity_at_arrive_times(self) -> None:
        spec = multi_key_spec()
        for track in TRACKS:
            keys = spec.track(track)
            for i, (_dep, arr, _rel) in enumerate(spec.key_times(track)):
                with self.subTest(track=track, key=i):
                    exact = key_value(track, keys[i])
                    at = channel(track, planner.evaluate(spec, arr))[0]
                    just_before = channel(track, planner.evaluate(spec, arr - 1e-9))[0]
                    # at the arrive time: the key value (exactly when held / last, else s = 0 of the next key)
                    np.testing.assert_allclose(at, exact, rtol=0.0, atol=1e-12)
                    np.testing.assert_allclose(just_before, exact, rtol=0.0, atol=1e-6)

    def test_holds_are_exact_and_constant(self) -> None:
        spec = multi_key_spec()
        tl = planner.plan(spec, 200.0)
        arrays = {"head": tl.head, "antennas": tl.antennas, "body": tl.body_yaw}
        checked = 0
        for track in TRACKS:
            keys = spec.track(track)
            times = spec.key_times(track)
            for i, (_dep, arr, rel) in enumerate(times):
                end = rel if i < len(times) - 1 else math.inf  # after the last key the track holds forever
                window = (tl.t >= arr) & (tl.t < end)
                if not np.any(window):
                    continue
                exact = key_value(track, keys[i])
                values = arrays[track][window]
                np.testing.assert_array_equal(values, np.broadcast_to(exact, values.shape))
                checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_tracks_of_different_lengths(self) -> None:
        p1, p2 = Pose6.from_deg_mm(yaw_deg=20.0), Pose6.from_deg_mm(pitch_deg=-8.0)
        spec = make_spec(head=[HeadKey(0.8, p1), HeadKey(0.7, p2, hold=0.2)],
                         antennas=[AntennaKey(0.6, (-0.5, 0.5), Easing.EASE_IN_OUT)])
        tl = planner.plan(spec, 50.0)
        self.assertEqual(tl.validate(), [])
        self.assertAlmostEqual(tl.duration, 1.7, places=12)
        after = tl.t >= 0.6
        np.testing.assert_array_equal(tl.antennas[after], np.broadcast_to([-0.5, 0.5], (int(after.sum()), 2)))
        np.testing.assert_array_equal(tl.antenna_key, np.zeros(len(tl), dtype=int))
        np.testing.assert_array_equal(tl.body_yaw, np.zeros(len(tl)))  # empty track: start value exactly
        np.testing.assert_array_equal(tl.body_key, np.full(len(tl), -1))
        np.testing.assert_array_equal(tl.head_key, np.where(tl.t < 0.8, 0, 1))
        np.testing.assert_array_equal(tl.head[tl.t >= 1.5], np.broadcast_to(p2.matrix(), (int((tl.t >= 1.5).sum()), 4, 4)))

    def test_before_start_and_after_end(self) -> None:
        spec = multi_key_spec(start=OFF_REST)
        head, antennas, body = planner.evaluate(spec, [-5.0, -1e-6])
        np.testing.assert_array_equal(head, np.broadcast_to(OFF_REST.head.matrix(), (2, 4, 4)))
        np.testing.assert_array_equal(antennas, np.broadcast_to(OFF_REST.antennas, (2, 2)))
        np.testing.assert_array_equal(body, np.full(2, OFF_REST.body_yaw))
        end = spec.end_state
        ts = [spec.duration, spec.duration + 0.5, 1e3]
        head, antennas, body = planner.evaluate(spec, ts)
        np.testing.assert_array_equal(head, np.broadcast_to(end.head.matrix(), (3, 4, 4)))
        np.testing.assert_array_equal(antennas, np.broadcast_to(end.antennas, (3, 2)))
        np.testing.assert_array_equal(body, np.full(3, end.body_yaw))
        tl = planner.plan(spec)
        self.assertEqual((tl.head_key[-1], tl.antenna_key[-1], tl.body_key[-1]), (2, 1, 1))

    def test_antennas_only_spec(self) -> None:
        spec = make_spec(antennas=[AntennaKey(0.4, (-0.8, 0.8), Easing.EASE_IN_OUT, hold=0.3),
                                   AntennaKey(0.5, INIT_ANTENNAS)])
        self.assertEqual(spec.validate(), [])
        tl = planner.plan(spec)
        self.assertEqual(tl.validate(), [])
        self.assertAlmostEqual(tl.duration, 1.2, places=12)
        np.testing.assert_array_equal(tl.head, np.broadcast_to(REST.head.matrix(), (len(tl), 4, 4)))
        np.testing.assert_array_equal(tl.head_key, np.full(len(tl), -1))
        np.testing.assert_array_equal(tl.body_yaw, np.zeros(len(tl)))
        np.testing.assert_array_equal(tl.body_key, np.full(len(tl), -1))
        np.testing.assert_array_equal(tl.antennas[-1], np.array(INIT_ANTENNAS))
        self.assertEqual(int(tl.antenna_key[-1]), 1)
        self.assertGreater(float(np.max(tl.antennas[:, 1])), 0.79)  # the perk was really commanded

    def test_cartoon_overshoots_between_keys_min_jerk_does_not(self) -> None:
        up = 30.0 * DEG
        for easing, overshoots in ((Easing.CARTOON, True), (Easing.MIN_JERK, False), (Easing.EASE_IN_OUT, False)):
            with self.subTest(easing=easing.value):
                spec = make_spec(head=[HeadKey(1.0, Pose6(yaw=up), easing), HeadKey(1.0, Pose6(), easing)],
                                 body=[BodyKey(1.0, up, easing), BodyKey(1.0, 0.0, easing)])
                tl = planner.plan(spec, 50.0)
                yaw = np.array([pose_from_matrix(m).yaw for m in tl.head])
                key0, key1 = tl.t < 1.0, (tl.t >= 1.0) & (tl.t < 2.0)
                for name, v in (("body", tl.body_yaw), ("head yaw", yaw)):
                    if overshoots:  # SDK cartoon: about 10 % before the start and past every key value
                        self.assertGreater(float(np.max(v[key0])), up * 1.09, name)  # beyond key 0 (30 deg)
                        self.assertLess(float(np.min(v[key0])), -up * 0.09, name)  # anticipation below the start
                        self.assertLess(float(np.min(v[key1])), -up * 0.09, name)  # beyond key 1 (0 deg)
                    else:
                        self.assertLessEqual(float(np.max(v)), up + 1e-12, name)
                        self.assertGreaterEqual(float(np.min(v)), -1e-12, name)


class KnobsTest(unittest.TestCase):
    def test_scaled_spec_equals_baked_effective_keys(self) -> None:
        base = multi_key_spec(start=OFF_REST)
        a, tempo = 0.6, 1.5
        scaled = base.scaled(a, tempo)
        s0 = base.start
        baked = replace(base, head=tuple(replace(k, pose=s0.head + (k.pose - s0.head).scaled(a),
                                                 duration=k.duration / tempo, hold=k.hold / tempo) for k in base.head),
                        antennas=tuple(replace(k, antennas=tuple(s + (v - s) * a for s, v in zip(s0.antennas, k.antennas)),
                                               duration=k.duration / tempo, hold=k.hold / tempo) for k in base.antennas),
                        body=tuple(replace(k, yaw=s0.body_yaw + (k.yaw - s0.body_yaw) * a, duration=k.duration / tempo,
                                           hold=k.hold / tempo) for k in base.body))
        tl_s, tl_b = planner.plan(scaled), planner.plan(baked)
        self.assertEqual(len(tl_s), len(tl_b))
        self.assertAlmostEqual(tl_s.duration, base.duration / tempo, places=12)
        self.assertAlmostEqual(tl_s.duration, tl_b.duration, places=12)
        for name in ("head", "antennas", "body_yaw"):
            np.testing.assert_allclose(getattr(tl_s, name), getattr(tl_b, name), rtol=0.0, atol=1e-12, err_msg=name)
        for name in ("head_key", "antenna_key", "body_key"):
            np.testing.assert_array_equal(getattr(tl_s, name), getattr(tl_b, name))
        self.assertEqual(tl_s.spec_digest, scaled.digest())
        # amplitude acts about the start state, tempo divides time (linear channels: exact relation)
        t = np.linspace(-0.1, base.duration + 0.1, 301)
        _h0, ant0, body0 = planner.evaluate(base, t)
        _h1, ant1, body1 = planner.evaluate(scaled, t / tempo)
        start_ant = np.array(s0.antennas)
        np.testing.assert_allclose(ant1, start_ant + a * (ant0 - start_ant), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(body1, s0.body_yaw + a * (body0 - s0.body_yaw), rtol=0.0, atol=1e-12)


class GridTest(unittest.TestCase):
    def test_valid_timeline_and_exact_end_for_awkward_durations(self) -> None:
        # (key 1 s, key 2 s, hold s, tempo, rate Hz)
        cases = ((0.1, 0.2, 0.0, 1.0, 50.0), (0.35, 0.47, 0.13, 1.1, 50.0), (0.7, 0.3, 0.0, 0.7, 30.0),
                 (0.333, 0.25, 0.111, 1.3, 100.0), (0.05, 0.02, 0.0, 1.0, 200.0), (0.41, 0.59, 0.0, 3.0, 50.0))
        for d1, d2, hold, tempo, rate in cases:
            with self.subTest(d1=d1, d2=d2, hold=hold, tempo=tempo, rate=rate):
                spec = make_spec(head=[HeadKey(d1, Pose6(yaw=0.2), Easing.LINEAR),
                                       HeadKey(d2, Pose6(pitch=-0.1, z=0.004), Easing.LINEAR, hold=hold)],
                                 antennas=[AntennaKey(d1 + d2, (-0.4, 0.4), Easing.LINEAR)],
                                 body=[BodyKey(d1, 0.1, Easing.LINEAR)]).scaled(1.0, tempo)
                self.assertEqual(spec.validate(), [])
                tl = planner.plan(spec, rate)
                self.assertEqual(tl.validate(), [])
                self.assertGreaterEqual(tl.t[-1] + 1e-12, spec.duration)
                end = spec.end_state
                np.testing.assert_array_equal(tl.head[-1], end.head.matrix())
                np.testing.assert_array_equal(tl.antennas[-1], np.array(end.antennas))
                self.assertEqual(float(tl.body_yaw[-1]), end.body_yaw)

    def test_grid_edge_cases(self) -> None:
        # a duration that is a grid point up to rounding gets no extra sample
        self.assertEqual(len(planner.grid_times(0.1 + 0.2, 50.0)), 16)
        self.assertEqual(len(planner.grid_times(2.0, 50.0)), 101)
        # a hair (> 1e-12 s) past a tick: one more sample so that Timeline.validate holds
        t = planner.grid_times(1.0 + 1e-11, 50.0)
        self.assertEqual(len(t), 52)
        self.assertGreaterEqual(t[-1], 1.0 + 1e-11)
        for bad in (0.0, -1.0, math.nan, math.inf):
            with self.assertRaises(ValueError):
                planner.grid_times(bad, 50.0)

    def test_last_sample_snaps_to_the_end_state(self) -> None:
        # D = 1 + 1e-13 s: K = 50, t_K = 1.0 is 1e-13 s before the (LINEAR, non-zero end speed) arrival.
        for d in (1.0 + 1e-13, 1.0 + 1e-11):
            with self.subTest(duration=d):
                pose = Pose6(yaw=0.5, x=0.01)
                spec = make_spec(head=[HeadKey(d, pose, Easing.LINEAR)],
                                 antennas=[AntennaKey(d, (-0.9, 0.9), Easing.LINEAR)],
                                 body=[BodyKey(d, 0.3, Easing.LINEAR)])
                tl = planner.plan(spec, 50.0)
                self.assertEqual(tl.validate(), [])
                np.testing.assert_array_equal(tl.head[-1], pose.matrix())
                np.testing.assert_array_equal(tl.antennas[-1], np.array([-0.9, 0.9]))
                self.assertEqual(float(tl.body_yaw[-1]), 0.3)

    def test_invalid_input_raises_value_error(self) -> None:
        ok = make_spec(head=[HeadKey(0.5, Pose6(yaw=0.1))])
        zero = make_spec(head=[HeadKey(0.0, Pose6(yaw=0.1))])
        with self.assertRaisesRegex(ValueError, "duration"):
            planner.plan(zero)
        with self.assertRaisesRegex(ValueError, "name"):
            planner.plan(replace(ok, name="bogus"))
        with self.assertRaisesRegex(ValueError, "no keys"):
            planner.plan(make_spec())
        with self.assertRaisesRegex(ValueError, "non-finite"):
            planner.plan(make_spec(head=[HeadKey(0.5, Pose6(yaw=math.nan))]))
        for rate in (0.0, -50.0, math.nan):
            with self.assertRaises(ValueError):
                planner.plan(ok, rate)
        with self.assertRaises(ValueError):
            planner.evaluate(zero, 0.1)
        with self.assertRaises(ValueError):
            planner.evaluate(ok, [0.1, math.nan])
        with self.assertRaises(ValueError):
            planner.segment_table(zero)
        # metadata problems do not stop the pure arithmetic of evaluate()
        head, _a, _b = planner.evaluate(replace(ok, name="bogus", intent=""), 10.0)
        np.testing.assert_array_equal(head[0], Pose6(yaw=0.1).matrix())

    def test_non_finite_start_state_is_refused(self) -> None:
        # review PLANNER-1: MotionSpec.validate() never looks at spec.start, so plan() checks it itself (it used to
        # return NaN samples, or raise LinAlgError from the SDK's SVD for a NaN head yaw)
        starts = {"antennas nan": RobotState(antennas=(math.nan, 0.17)), "body inf": RobotState(body_yaw=math.inf),
                  "head x nan": RobotState(head=Pose6(x=math.nan)),
                  "head yaw nan": RobotState(head=Pose6(yaw=math.nan))}
        for label, start in starts.items():
            with self.subTest(start=label):
                spec = make_spec(head=[HeadKey(0.5, Pose6(yaw=0.2))], antennas=[AntennaKey(0.5, (-0.3, 0.3))],
                                 body=[BodyKey(0.5, 0.1)], start=start)
                self.assertEqual(spec.validate(), [])
                with self.assertRaisesRegex(ValueError, "start state has a non-finite value"):
                    planner.plan(spec)
                with self.assertRaisesRegex(ValueError, "start state has a non-finite value"):  # consistent
                    planner.evaluate(spec, 0.1)
                with self.assertRaisesRegex(ValueError, "start state has a non-finite value"):
                    planner.segment_table(spec)

    def test_overflow_raises_instead_of_returning_an_invalid_timeline(self) -> None:
        # finite keys (spec.validate() passes) whose difference overflows to inf: the planner never hands an
        # invalid timeline to an executor
        spec = make_spec(antennas=[AntennaKey(0.5, (1e308, -1e308)), AntennaKey(0.5, (-1e308, 1e308))])
        self.assertEqual(spec.validate(), [])
        with np.errstate(over="ignore", invalid="ignore"):
            with self.assertRaisesRegex(ValueError, "antennas has non-finite values"):
                planner.plan(spec)

    def test_duration_is_bounded_where_the_grid_stays_uniform(self) -> None:
        # review PLANNER-3: Timeline.validate checks the spacing with an ABSOLUTE 1e-12 s, which t = k / rate meets
        # only below 8192 s; spec.validate() sets no upper bound, so the planner limits timelines to MAX_DURATION_S
        cap = planner.MAX_DURATION_S
        self.assertLess(cap + 1.0, 4096.0)  # whole grid below 2**12 s at rates >= 1 Hz
        t_9000 = np.arange(450_001, dtype=np.int64) / 50.0  # 9000 s at 50 Hz: float64 alone breaks the check
        self.assertGreater(float(np.max(np.abs(np.diff(t_9000) - 1.0 / 50.0))), 1e-12)
        for rate in (30.0, 50.0, 100.0, 200.0):
            with self.subTest(rate=rate):
                t = planner.grid_times(cap, rate)
                self.assertGreaterEqual(float(t[-1]), cap)
                self.assertTrue(np.allclose(np.diff(t), 1.0 / rate, rtol=0.0, atol=1e-12))
        with self.assertRaisesRegex(ValueError, "MAX_DURATION_S"):
            planner.grid_times(cap + 1e-6, 50.0)
        long_hold = make_spec(head=[HeadKey(0.5, Pose6(yaw=0.2), Easing.LINEAR, hold=9000.0)])
        self.assertEqual(long_hold.validate(), [])
        with self.assertRaisesRegex(ValueError, "MAX_DURATION_S"):
            planner.plan(long_hold)
        # the bound applies to the effective length (tempo 0.5 doubles 0.5 + 2000 s)
        slow = make_spec(head=[HeadKey(0.5, Pose6(yaw=0.2), hold=2000.0)]).scaled(1.0, 0.5)
        self.assertEqual(slow.validate(), [])
        with self.assertRaisesRegex(ValueError, "MAX_DURATION_S"):
            planner.plan(slow)
        with self.assertRaisesRegex(ValueError, "MAX_DURATION_S"):
            planner.plan_transition(REST, OFF_REST, cap + 1.0)
        # exactly at the bound the timeline is valid and ends exactly (10 Hz keeps the test quick)
        at_cap = make_spec(head=[HeadKey(0.5, Pose6(yaw=0.2), Easing.LINEAR, hold=cap - 0.5)])
        self.assertEqual(at_cap.duration, cap)
        tl = planner.plan(at_cap, 10.0)
        self.assertEqual(tl.validate(), [])
        np.testing.assert_array_equal(tl.head[-1], Pose6(yaw=0.2).matrix())


class TransitionTest(unittest.TestCase):
    def test_plan_transition_endpoints_and_goto_equivalence(self) -> None:
        d = 0.9
        for easing in (Easing.MIN_JERK, Easing.CARTOON, Easing.LINEAR):
            with self.subTest(easing=easing.value):
                tl = planner.plan_transition(OFF_REST, REST, d, easing)
                self.assertEqual(tl.validate(), [])
                self.assertEqual((tl.name, tl.variant, tl.spec_digest, tl.duration), ("transition", "", "", d))
                for keys in (tl.head_key, tl.antenna_key, tl.body_key):
                    np.testing.assert_array_equal(keys, np.zeros(len(tl), dtype=int))
                # end exactly, start exactly on the linear channels and to rounding on the head (SVD in the SDK)
                np.testing.assert_array_equal(tl.head[-1], REST.head.matrix())
                np.testing.assert_array_equal(tl.antennas[-1], np.array(REST.antennas))
                self.assertEqual(float(tl.body_yaw[-1]), REST.body_yaw)
                np.testing.assert_allclose(tl.head[0], OFF_REST.head.matrix(), rtol=0.0, atol=1e-14)
                np.testing.assert_array_equal(tl.antennas[0], np.array(OFF_REST.antennas))
                self.assertEqual(float(tl.body_yaw[0]), OFF_REST.body_yaw)
                # one SDK goto for all channels
                before = np.flatnonzero(tl.t < d)
                h, a, b = goto_samples(sdk_goto(OFF_REST, REST.head, REST.antennas, REST.body_yaw, d, easing),
                                       tl.t[before])
                np.testing.assert_array_equal(tl.head[before], h)
                np.testing.assert_array_equal(tl.antennas[before], a)
                np.testing.assert_array_equal(tl.body_yaw[before], b)
        self.assertEqual(planner.plan_transition(REST, OFF_REST, 0.5, name="blend").name, "blend")
        for bad in (0.0, MIN_KEY_DURATION_S / 2, math.nan):
            with self.assertRaises(ValueError):
                planner.plan_transition(OFF_REST, REST, bad)
        with self.assertRaises(ValueError):
            planner.plan_transition(OFF_REST, REST, 0.5, rate_hz=0.0)

    def test_transition_duration_caps_hold_on_a_dense_plan(self) -> None:
        caps = {"rot_dps": 60.0, "trans_mms": 50.0, "antenna_dps": 180.0, "body_dps": 45.0}
        big = (Pose6.from_deg_mm(roll_deg=-20.0, pitch_deg=25.0, yaw_deg=50.0),
               Pose6.from_deg_mm(roll_deg=25.0, pitch_deg=-30.0, yaw_deg=-60.0))
        # (label, start, end, binding channel or None for min_s, expected duration or None)
        cases = (
            ("yaw 90", RobotState(head=Pose6.from_deg_mm(yaw_deg=90.0)), REST, "rot_dps", 1.875 * 90.0 / 60.0),
            ("z 30 mm", RobotState(head=Pose6.from_deg_mm(z_mm=-30.0)), REST, "trans_mms", 1.875 * 30.0 / 50.0),
            ("antennas", RobotState(antennas=(-2.0, 2.0)), REST, "antenna_dps",
             1.875 * math.degrees(2.0 - INIT_ANTENNAS[1]) / 180.0),
            ("body 60", RobotState(body_yaw=60.0 * DEG), REST, "body_dps", 1.875 * 60.0 / 45.0),
            ("combined head", RobotState(head=big[0]), RobotState(head=big[1]), "rot_dps", None),
            ("all channels", OFF_REST, REST, None, None),
            ("tiny", RobotState(head=Pose6.from_deg_mm(yaw_deg=1.0)), REST, None, 0.5),
        )
        for label, start, end, binding, expected in cases:
            with self.subTest(case=label):
                d = planner.transition_duration(start, end)
                if expected is not None:
                    self.assertAlmostEqual(d, expected, delta=1e-12)
                peaks = numeric_peaks(planner.plan_transition(start, end, d, rate_hz=500.0))
                for ch, cap in caps.items():
                    self.assertLessEqual(peaks[ch], cap * (1.0 + 1e-9), f"{ch}: {peaks[ch]} > {cap}")
                if binding is not None:  # the binding channel reaches its cap (dense grid around the flat peak)
                    self.assertGreaterEqual(peaks[binding], caps[binding] * (1.0 - 1e-4))
                if label == "all channels":  # some channel binds unless min_s does
                    self.assertTrue(d == 0.5 or max(peaks[c] / caps[c] for c in caps) > 1.0 - 1e-4)

    def test_geodesic_alone_would_exceed_the_rotation_cap(self) -> None:
        a = Pose6.from_deg_mm(roll_deg=-20.0, pitch_deg=25.0, yaw_deg=50.0)
        b = Pose6.from_deg_mm(roll_deg=25.0, pitch_deg=-30.0, yaw_deg=-60.0)
        geodesic = rotation_distance(a.matrix(), b.matrix())
        self.assertGreater(planner.head_path_angle(a.matrix(), b.matrix()), 1.05 * geodesic)
        d_geo = 1.875 * math.degrees(geodesic) / 60.0
        peak = numeric_peaks(planner.plan_transition(RobotState(head=a), RobotState(head=b), d_geo, rate_hz=500.0))
        self.assertGreater(peak["rot_dps"], 60.0 * 1.04)
        self.assertGreater(planner.transition_duration(RobotState(head=a), RobotState(head=b)), d_geo * 1.05)

    def test_transition_duration_floor_and_arguments(self) -> None:
        self.assertEqual(planner.transition_duration(REST, REST), 0.5)
        self.assertEqual(planner.transition_duration(REST, REST, min_s=0.0), MIN_KEY_DURATION_S)
        self.assertEqual(planner.transition_duration(REST, REST, min_s=1.25), 1.25)
        for kw in ({"max_rot_dps": 0.0}, {"max_trans_mms": -1.0}, {"max_antenna_dps": math.nan},
                   {"max_body_dps": math.inf}, {"min_s": -0.1}):
            with self.assertRaises(ValueError, msg=str(kw)):
                planner.transition_duration(OFF_REST, REST, **kw)

    def test_transition_duration_refuses_non_finite_states(self) -> None:
        # review PLANNER-4: a NaN distance used to drop out of max() silently (0.5 s for NaN antennas, the
        # body-only value with a moving body), inf gave inf and a NaN head angle a LinAlgError
        bad = {"antennas nan": RobotState(antennas=(math.nan, 0.17)),
               "antennas inf": RobotState(antennas=(math.inf, 0.17)),
               "body nan": RobotState(body_yaw=math.nan), "head x nan": RobotState(head=Pose6(x=math.nan)),
               "head pitch nan": RobotState(head=Pose6(pitch=math.nan)),
               "antennas nan, body 1 rad": RobotState(antennas=(math.nan, 0.17), body_yaw=1.0)}
        for label, state in bad.items():
            with self.subTest(state=label):
                with self.assertRaisesRegex(ValueError, "start state has a non-finite value"):
                    planner.transition_duration(state, REST)
                with self.assertRaisesRegex(ValueError, "end state has a non-finite value"):
                    planner.transition_duration(REST, state)
                with self.assertRaisesRegex(ValueError, "start state has a non-finite value"):  # same refusal
                    planner.plan_transition(state, REST, 0.5)
        # finite states so far apart that a distance overflows: an error, not an infinite duration
        far = (RobotState(antennas=(1e308, -1e308)), RobotState(antennas=(-1e308, 1e308)))
        with self.assertRaisesRegex(ValueError, "overflows"):
            planner.transition_duration(*far)
        with np.errstate(over="ignore", invalid="ignore"):
            with self.assertRaisesRegex(ValueError, "antennas has non-finite values"):
                planner.plan_transition(*far, 0.5)


class HeadPathAngleTest(unittest.TestCase):
    def test_constant_angular_rate_of_the_sdk_path(self) -> None:
        h = 1e-5
        for a, b in PATH_PAIRS:
            ma, mb = a.matrix(), b.matrix()
            g = planner.head_path_angle(ma, mb)
            self.assertGreaterEqual(g, rotation_distance(ma, mb) - 1e-12)
            for s in (-0.1, 0.0, 0.3, 0.5, 0.8, 1.1):  # also CARTOON's extrapolated s
                p0 = linear_pose_interpolation(ma, mb, s - h, yaw_as_scalar=True)
                p1 = linear_pose_interpolation(ma, mb, s + h, yaw_as_scalar=True)
                rate = rotation_distance(p0, p1) / (2.0 * h)
                self.assertAlmostEqual(rate, g, delta=1e-8 * max(g, 1.0), msg=f"{a} -> {b} at s={s}")

    def test_single_axis_moves_follow_the_geodesic(self) -> None:
        for b in (Pose6.from_deg_mm(yaw_deg=40.0), Pose6.from_deg_mm(pitch_deg=-25.0),
                  Pose6.from_deg_mm(roll_deg=15.0, z_mm=8.0)):
            ma, mb = Pose6().matrix(), b.matrix()
            self.assertAlmostEqual(planner.head_path_angle(ma, mb), rotation_distance(ma, mb), delta=1e-12)
        self.assertEqual(planner.head_path_angle(np.eye(4), np.eye(4)), 0.0)

    def test_documented_excess_over_the_geodesic(self) -> None:
        # head_path_angle docstring: "+0.14 % to +5.3 %" for the combined yaw + pitch/roll pairs (review PLANNER-5)
        excess = [planner.head_path_angle(a.matrix(), b.matrix()) / rotation_distance(a.matrix(), b.matrix()) - 1.0
                  for a, b in COMBINED_PATH_PAIRS]
        self.assertEqual(round(100.0 * min(excess), 2), 0.14)
        self.assertEqual(round(100.0 * max(excess), 1), 5.3)
        a, b = PATH_PAIRS[2]  # pitch / roll only: no excess
        self.assertAlmostEqual(planner.head_path_angle(a.matrix(), b.matrix()),
                               rotation_distance(a.matrix(), b.matrix()), delta=1e-12)


class ConcatTest(unittest.TestCase):
    def test_duplicate_first_sample_is_dropped(self) -> None:
        motion = planner.plan(multi_key_spec())  # starts at REST
        tr = planner.plan_transition(OFF_REST, REST, 0.6)
        tl = planner.concat(tr, motion)
        self.assertEqual(tl.validate(), [])
        self.assertEqual(len(tl), len(tr) + len(motion) - 1)
        np.testing.assert_array_equal(tl.t, np.arange(len(tl)) / tr.rate_hz)
        self.assertTrue(np.allclose(np.diff(tl.t), 1.0 / tr.rate_hz, rtol=0.0, atol=1e-12))
        n1 = len(tr)
        np.testing.assert_array_equal(tl.head[:n1], tr.head)
        np.testing.assert_array_equal(tl.head[n1:], motion.head[1:])
        np.testing.assert_array_equal(tl.antennas[n1:], motion.antennas[1:])
        np.testing.assert_array_equal(tl.body_yaw[n1:], motion.body_yaw[1:])
        self.assertAlmostEqual(tl.duration, tr.t[-1] + motion.duration, delta=1e-12)
        np.testing.assert_array_equal(tl.head_key, np.concatenate([tr.head_key, motion.head_key[1:]]))
        np.testing.assert_array_equal(tl.antenna_key, np.concatenate([tr.antenna_key, motion.antenna_key[1:]]))
        np.testing.assert_array_equal(tl.body_key, np.concatenate([tr.body_key, motion.body_key[1:]]))
        self.assertEqual((tl.name, tl.variant, tl.spec_digest), ("transition+aha_recommend", "", ""))
        np.testing.assert_array_equal(tl.head[-1], motion.head[-1])

    def test_distinct_first_sample_is_kept(self) -> None:
        a = planner.plan_transition(REST, OFF_REST, 0.5)
        b = planner.plan_transition(REST, OFF_REST, 0.5)  # starts at REST, a ends at OFF_REST
        tl = planner.concat(a, b, name="twice")
        self.assertEqual(tl.validate(), [])
        self.assertEqual(len(tl), len(a) + len(b))
        self.assertAlmostEqual(tl.t[len(a)], a.t[-1] + 1.0 / a.rate_hz, delta=1e-12)
        self.assertAlmostEqual(tl.duration, a.t[-1] + 1.0 / a.rate_hz + b.duration, delta=1e-12)
        np.testing.assert_array_equal(tl.head[len(a):], b.head)
        self.assertEqual((tl.name, tl.variant), ("twice", ""))
        # chaining keeps the grid uniform and valid
        chain = planner.concat(tl, planner.plan_transition(OFF_REST, REST, 0.4))
        self.assertEqual(chain.validate(), [])
        np.testing.assert_array_equal(chain.head[-1], REST.head.matrix())

    def test_same_variant_is_kept_and_rates_must_match(self) -> None:
        motion = planner.plan(multi_key_spec())
        both = planner.concat(motion, motion)
        self.assertEqual((both.variant, both.name), ("expressive", "aha_recommend+aha_recommend"))
        self.assertEqual(both.validate(), [])
        with self.assertRaisesRegex(ValueError, "rate"):
            planner.concat(planner.plan_transition(REST, OFF_REST, 0.5, rate_hz=50.0),
                           planner.plan_transition(OFF_REST, REST, 0.5, rate_hz=100.0))

    def test_end_stays_covered_when_second_ends_a_hair_past_its_last_tick(self) -> None:
        # review PLANNER-2: Timeline.validate lets duration lie up to 1e-12 s past the last sample, and adding the
        # shift could round the concatenated duration one step further -> the end state gets one more sample
        first = planner.plan_transition(RobotState(head=Pose6(pitch=0.1)), REST, 0.52, rate_hz=50.0)
        second = planner.plan(make_spec(head=[HeadKey(0.06 + 1e-12, Pose6(yaw=0.2), Easing.LINEAR)]), 50.0)
        self.assertEqual((first.validate(), second.validate()), ([], []))
        self.assertGreater(second.duration, float(second.t[-1]))  # valid, yet ends after its last sample
        tl = planner.concat(first, second)
        self.assertEqual(tl.validate(), [])
        n1, n = len(first), len(first) + len(second) - 1  # second starts at REST = first's end: duplicate dropped
        self.assertEqual(len(tl), n + 1)  # one padding sample
        np.testing.assert_array_equal(tl.t, np.arange(n + 1) / 50.0)
        self.assertEqual(tl.duration, (n1 - 1) / 50.0 + second.duration)  # duration as documented, unchanged
        for name in ("head", "antennas", "body_yaw", "head_key", "antenna_key", "body_key"):
            arr, src = getattr(tl, name), getattr(second, name)
            np.testing.assert_array_equal(arr[:n1], getattr(first, name), err_msg=name)
            np.testing.assert_array_equal(arr[n1:n], src[1:], err_msg=name)
            np.testing.assert_array_equal(arr[-1], src[-1], err_msg=name)  # the end state, repeated
        # property sweep: second lasting k / rate + {1, 0.9999, 0.5} e-12 s, with and without the duplicate drop
        failures: list[str] = []
        padded = 0
        for rate in (50.0, 30.0, 100.0, 200.0):
            firsts = [(hold_timeline(d1, rate, state), state is REST) for d1 in (0.5, 0.52, 1.3)
                      for state in (REST, OFF_REST)]
            for k in range(1, 120):
                for extra in (1e-12, 0.9999e-12, 0.5e-12):
                    second = hold_timeline(k / rate + extra, rate)
                    for first, dropped in firsts:
                        tl = planner.concat(first, second)
                        n = len(first) + len(second) - dropped
                        padded += len(tl) - n
                        problems = tl.validate()
                        if problems or len(tl) - n not in (0, 1) or \
                                tl.duration != (len(first) - dropped) / rate + second.duration:
                            failures.append(f"{rate} Hz, second {second.duration!r}, first {first.duration}: "
                                            f"{problems}, {len(tl) - n} extra")
        self.assertEqual(failures[:5], [])
        self.assertGreater(padded, 0)  # the sweep reaches the rounding case (hundreds of cases before the fix)

    def test_concat_respects_max_duration(self) -> None:
        half = planner.MAX_DURATION_S / 2.0
        first = hold_timeline(half, 10.0)
        both = planner.concat(first, hold_timeline(half - 1.0, 10.0, OFF_REST))
        self.assertEqual(both.validate(), [])
        self.assertLessEqual(both.duration, planner.MAX_DURATION_S)
        with self.assertRaisesRegex(ValueError, "MAX_DURATION_S"):
            planner.concat(first, hold_timeline(half + 1.0, 10.0, OFF_REST))


class SegmentTableTest(unittest.TestCase):
    def test_rows_columns_units_and_effective_parameters(self) -> None:
        spec = multi_key_spec().scaled(0.5, 2.0)  # amplitude 0.5 about REST, everything twice as fast
        rows = planner.segment_table(spec)
        self.assertEqual(len(rows), 3 + 2 + 2)
        for r in rows:
            self.assertEqual(tuple(r), planner.SEGMENT_COLUMNS)
        self.assertEqual([(r["track"], r["index"]) for r in rows],
                         [("head", 0), ("head", 1), ("head", 2), ("antennas", 0), ("antennas", 1), ("body", 0),
                          ("body", 1)])
        eff = spec.effective()
        for track in TRACKS:
            track_rows = [r for r in rows if r["track"] == track]
            self.assertEqual([(r["t_depart_s"], r["t_arrive_s"], r["t_release_s"]) for r in track_rows],
                             spec.key_times(track))
            for r, k in zip(track_rows, eff.track(track)):
                self.assertEqual((r["duration_s"], r["hold_s"], r["easing"], r["label"]),
                                 (k.duration, k.hold, k.easing.value, k.label))
                self.assertAlmostEqual(r["peak_ratio"], planner.peak_speed_ratio(k.easing), delta=1e-12)
        h0, h1, _h2, a0, _a1, b0, b1 = rows
        # head key 0: pitch -10 deg, z 5 mm at amplitude 0.5 -> -5 deg, 2.5 mm, in 0.5 / 2 = 0.25 s (MIN_JERK)
        self.assertAlmostEqual(h0["duration_s"], 0.25, places=12)
        self.assertAlmostEqual(h0["pitch_deg"], -5.0, places=9)
        self.assertAlmostEqual(h0["z_mm"], 2.5, places=9)
        self.assertAlmostEqual(h0["delta_pitch_deg"], -5.0, places=9)
        self.assertAlmostEqual(h0["rot_deg"], 5.0, places=9)
        self.assertAlmostEqual(h0["trans_mm"], 2.5, places=9)
        self.assertAlmostEqual(h0["peak_rot_dps"], 1.875 * 5.0 / 0.25, places=6)
        self.assertAlmostEqual(h0["peak_rot_path_dps"], h0["peak_rot_dps"], places=6)  # single axis
        self.assertAlmostEqual(h0["peak_trans_mms"], 1.875 * 2.5 / 0.25, places=6)
        for col in ("right_deg", "delta_left_deg", "peak_antenna_dps", "peak_body_dps"):
            self.assertIsNone(h0[col])
        # head key 1 (CARTOON) departs from key 0's value: yaw 12.5, roll 2.5, pitch 0, z 0
        self.assertAlmostEqual(h1["yaw_deg"], 12.5, places=9)
        self.assertAlmostEqual(h1["delta_yaw_deg"], 12.5, places=9)
        self.assertAlmostEqual(h1["delta_pitch_deg"], 5.0, places=9)
        self.assertAlmostEqual(h1["delta_z_mm"], -2.5, places=9)
        self.assertGreaterEqual(h1["peak_rot_path_dps"], h1["peak_rot_dps"] - 1e-9)
        # antenna key 0 (LINEAR, k = 1): from INIT_ANTENNAS halfway to (-0.6, 0.6) in 0.15 s
        right = INIT_ANTENNAS[0] + 0.5 * (-0.6 - INIT_ANTENNAS[0])
        left = INIT_ANTENNAS[1] + 0.5 * (0.6 - INIT_ANTENNAS[1])
        self.assertAlmostEqual(a0["right_deg"], math.degrees(right), places=9)
        self.assertAlmostEqual(a0["left_deg"], math.degrees(left), places=9)
        self.assertAlmostEqual(a0["delta_right_deg"], math.degrees(right - INIT_ANTENNAS[0]), places=9)
        self.assertAlmostEqual(a0["peak_antenna_dps"], math.degrees(max(abs(right - INIT_ANTENNAS[0]),
                                                                        abs(left - INIT_ANTENNAS[1]))) / 0.15, places=6)
        for col in ("x_mm", "yaw_deg", "rot_deg", "peak_rot_dps", "peak_body_dps"):
            self.assertIsNone(a0[col])
        # body: 15 deg * 0.5 = 7.5 deg in 0.45 s (MIN_JERK), then back to 0 (EASE_IN_OUT, k = 2) in 0.3 s
        self.assertAlmostEqual(b0["yaw_deg"], 7.5, places=9)
        self.assertAlmostEqual(b0["delta_yaw_deg"], 7.5, places=9)
        self.assertAlmostEqual(b0["peak_body_dps"], 1.875 * 7.5 / 0.45, places=6)
        self.assertAlmostEqual(b1["delta_yaw_deg"], -7.5, places=9)
        self.assertAlmostEqual(b1["peak_body_dps"], 2.0 * 7.5 / 0.3, places=6)
        for col in ("x_mm", "right_deg", "peak_rot_dps", "peak_antenna_dps"):
            self.assertIsNone(b0[col])

    def test_nominal_peaks_match_the_planned_motion(self) -> None:
        spec = multi_key_spec()
        rows = planner.segment_table(spec)
        h = 1e-6
        # body key 0 (MIN_JERK): peak at mid-travel
        b0 = next(r for r in rows if r["track"] == "body" and r["index"] == 0)
        t_mid = b0["t_depart_s"] + b0["duration_s"] / 2.0
        _hd, _a, body = planner.evaluate(spec, [t_mid - h, t_mid + h])
        self.assertAlmostEqual(math.degrees(abs(body[1] - body[0])) / (2 * h), b0["peak_body_dps"],
                               delta=1e-4 * b0["peak_body_dps"])
        # head key 1 (CARTOON, combined yaw + roll from a pitched pose): the executed path's exact peak
        h1 = next(r for r in rows if r["track"] == "head" and r["index"] == 1)
        t_mid = h1["t_depart_s"] + h1["duration_s"] / 2.0
        head, _a, _b = planner.evaluate(spec, [t_mid - h, t_mid + h])
        speed = math.degrees(rotation_distance(head[0], head[1])) / (2 * h)
        self.assertAlmostEqual(speed, h1["peak_rot_path_dps"], delta=1e-4 * h1["peak_rot_path_dps"])


if __name__ == "__main__":
    unittest.main()
