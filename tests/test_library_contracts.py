"""Contract types of the motion library: SI poses, multi-track specs, timelines (no daemon, no robot)."""

import math
import unittest

import numpy as np

from reachy_motion.library.pose import (
    INIT_ANTENNAS,
    REST,
    Pose6,
    RobotState,
    antennas_droop,
    head_yaw_psi,
    pose_from_matrix,
    rotation_distance,
    translation_distance,
)
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
from reachy_motion.safety.policy import DEFAULT_POLICY, POLICY_DISCLAIMER, SafetyReport
from reachy_motion.timeline import PreparedMotion, Timeline


def make_spec(**kw) -> MotionSpec:
    base = dict(
        name="success", variant="expressive", intent="test nod", valence=0.5, arousal=0.4,
        principles=(PrincipleUse(Principle.SLOW_IN_SLOW_OUT, "minjerk keys"),),
        head=(HeadKey(0.4, Pose6.from_deg_mm(pitch_deg=12.0), hold=0.1, label="down"),
              HeadKey(0.5, Pose6(), label="back")),
        antennas=(AntennaKey(0.3, antennas_droop(-0.2), label="perk"), AntennaKey(0.3, INIT_ANTENNAS)),
        body=(BodyKey(0.6, math.radians(5.0)), BodyKey(0.6, 0.0)),
    )
    base.update(kw)
    return MotionSpec(**base)


class TestPose6(unittest.TestCase):
    def test_matrix_matches_sdk_create_head_pose(self):
        from reachy_mini.utils import create_head_pose  # utils/__init__.py:14-47

        rng = np.random.default_rng(1)
        for _ in range(300):
            v = rng.uniform(-0.7, 0.7, 6)
            v[:3] *= 0.04
            ours = Pose6.from_array(v).matrix()
            sdk = create_head_pose(*v, degrees=False)
            self.assertLess(float(np.max(np.abs(ours - sdk))), 1e-12)

    def test_inverse_and_units(self):
        p = Pose6.from_deg_mm(roll_deg=5, pitch_deg=-12, yaw_deg=30, x_mm=4, y_mm=-3, z_mm=7)
        self.assertAlmostEqual(p.pitch, math.radians(-12), places=15)
        self.assertAlmostEqual(p.z, 0.007, places=15)
        back = pose_from_matrix(p.matrix())
        self.assertTrue(np.allclose(back.as_array(), p.as_array(), atol=1e-12))
        d = p.to_deg_mm()
        self.assertAlmostEqual(d["yaw_deg"], 30.0, places=12)
        self.assertAlmostEqual(d["x_mm"], 4.0, places=12)

    def test_orthonormalises_daemon_matrices(self):
        m = Pose6.from_deg_mm(pitch_deg=10).matrix()
        scaled = m.copy()
        scaled[:3, :3] *= 1.0005  # daemon matrices have det ~1.0005 (Phase 1 4.4)
        self.assertAlmostEqual(math.degrees(pose_from_matrix(scaled).pitch), 10.0, places=9)
        self.assertLess(rotation_distance(m, scaled), 1e-9)

    def test_distances_and_psi(self):
        a, b = Pose6().matrix(), Pose6.from_deg_mm(yaw_deg=40, z_mm=10).matrix()
        self.assertAlmostEqual(math.degrees(rotation_distance(a, b)), 40.0, places=9)
        self.assertAlmostEqual(translation_distance(a, b), 0.010, places=12)
        self.assertAlmostEqual(math.degrees(head_yaw_psi(b)), 40.0, places=9)
        # tilted head: psi differs from the Euler yaw and wraps before 180 deg (Phase 1 R1)
        tilted = Pose6.from_deg_mm(roll_deg=20, pitch_deg=-20, yaw_deg=175).matrix()
        self.assertLess(head_yaw_psi(tilted), 0.0)

    def test_antenna_droop_direction_is_the_sleep_side(self):
        r, l = antennas_droop(0.5)
        self.assertLess(r, INIT_ANTENNAS[0])  # right folds toward -3.05 (SDK sleep pose)
        self.assertGreater(l, INIT_ANTENNAS[1])  # left folds toward +3.05
        self.assertEqual(REST, RobotState())


class TestMotionSpec(unittest.TestCase):
    def test_valid_and_times(self):
        s = make_spec()
        self.assertEqual(s.validate(), [])
        self.assertAlmostEqual(s.duration, 1.2)
        self.assertEqual(s.key_times("head"), [(0.0, 0.4, 0.5), (0.5, 1.0, 1.0)])
        self.assertEqual(s.end_state, REST)
        self.assertEqual(s.key, "success:expressive")

    def test_validation_catches_bad_data(self):
        bad = make_spec(name="dance", variant="loud", valence=2.0, intent=" ", principles=(),
                        head=(HeadKey(0.001, Pose6(), hold=-1.0),))
        problems = " | ".join(bad.validate())
        for word in ("name", "variant", "valence", "intent", "principle", "duration", "hold"):
            self.assertIn(word, problems)
        self.assertIn("no keys", " ".join(make_spec(head=(), antennas=(), body=()).validate()))

    def test_scale_knobs_are_applied_by_effective(self):
        s = make_spec().scaled(amplitude=0.5, tempo=2.0)
        self.assertEqual(s.head[0].pose, make_spec().head[0].pose)  # designed keys unchanged
        e = s.effective()
        self.assertAlmostEqual(math.degrees(e.head[0].pose.pitch), 6.0, places=12)
        self.assertAlmostEqual(e.head[0].duration, 0.2, places=12)
        self.assertAlmostEqual(e.head[0].hold, 0.05, places=12)
        self.assertAlmostEqual(s.duration, 0.6, places=12)
        self.assertEqual((e.amplitude_scale, e.tempo_scale), (1.0, 1.0))
        self.assertAlmostEqual(math.degrees(e.body[0].yaw), 2.5, places=12)
        r0, l0 = INIT_ANTENNAS
        self.assertAlmostEqual(e.antennas[0].antennas[0], r0 + (make_spec().antennas[0].antennas[0] - r0) * 0.5)
        with self.assertRaises(ValueError):
            make_spec().scaled(tempo=0.0)
        self.assertTrue(any("tempo_scale" in p for p in make_spec(tempo_scale=100.0).validate()))
        too_fast = make_spec(tempo_scale=0.3 / MIN_KEY_DURATION_S * 1.01)  # the 0.3 s antenna key drops below one tick
        self.assertTrue(any("shorter than" in p for p in too_fast.validate()))

    def test_digest_tracks_every_change(self):
        s = make_spec()
        self.assertEqual(s.digest(), make_spec().digest())
        self.assertNotEqual(s.digest(), s.scaled(amplitude=1.1).digest())
        self.assertNotEqual(s.digest(), make_spec(head=(HeadKey(0.4, Pose6.from_deg_mm(pitch_deg=12.0001)),)).digest())

    def test_sound_cue_checks(self):
        ok = make_spec(sound=SoundCue("aha.wav", 0.2))
        self.assertEqual(ok.validate(), [])
        self.assertTrue(any("sound" in p for p in make_spec(sound=SoundCue("aha.wav", 9.0)).validate()))
        self.assertAlmostEqual(ok.scaled(tempo=2.0).effective().sound.at_s, 0.1)

    def test_easing_values_match_sdk(self):
        from reachy_mini.utils.interpolation import InterpolationTechnique

        self.assertEqual({e.value for e in Easing}, {m.value for m in InterpolationTechnique})


def uniform_timeline(n: int = 5, rate: float = 50.0) -> Timeline:
    t = np.arange(n) / rate
    head = np.repeat(np.eye(4)[None], n, axis=0)
    ant = np.tile(np.array(INIT_ANTENNAS), (n, 1))
    z = np.zeros(n)
    k = np.zeros(n, dtype=int)
    return Timeline("success", "neutral", rate, float(t[-1]), t, head, ant, z, k, k, k)


class TestTimelineContract(unittest.TestCase):
    def test_validate_and_digest(self):
        tl = uniform_timeline()
        self.assertEqual(tl.validate(), [])
        self.assertEqual(tl.digest(), uniform_timeline().digest())
        moved = uniform_timeline()
        moved.body_yaw[2] = 1e-6
        self.assertNotEqual(tl.digest(), moved.digest())
        neg = uniform_timeline()
        neg.body_yaw[1] = -1e-12  # rounds to -0.0: must hash like 0.0
        self.assertEqual(tl.digest(), neg.digest())
        bad = Timeline("x", "", 50.0, 1.0, np.array([0.0, 0.03]), np.zeros((2, 4, 4)), np.zeros((2, 2)),
                       np.zeros(2), np.zeros(2, int), np.zeros(2, int), np.zeros(2, int))
        problems = " ".join(bad.validate())
        self.assertIn("uniform", problems)
        self.assertIn("last sample", problems)

    def test_prepared_motion_binds_report_to_timeline(self):
        tl = uniform_timeline()
        rep = SafetyReport("success", "neutral", DEFAULT_POLICY, True, (), (), {}, timeline_digest=tl.digest())
        self.assertTrue(PreparedMotion(tl, rep).runnable)
        self.assertIn("not a guarantee", POLICY_DISCLAIMER)
        other = uniform_timeline(6)
        self.assertFalse(PreparedMotion(other, rep).runnable)
        failing = SafetyReport("success", "neutral", DEFAULT_POLICY, False, (), (), {}, timeline_digest=tl.digest())
        self.assertFalse(PreparedMotion(tl, failing).runnable)


if __name__ == "__main__":
    unittest.main()
