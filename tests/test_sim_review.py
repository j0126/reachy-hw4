"""Pure helpers of the MuJoCo review (no daemon): basic-act matching, pose differences, report rendering."""

import unittest

from reachy_motion.library.pose import Pose6
from reachy_motion.library.registry import default_library
from reachy_motion.library.spec import Easing, HeadKey, MotionSpec, Principle, PrincipleUse
from reachy_motion.sim_review import functional_match, planned_state, review_markdown, state_diff


def spec(variant: str, keys: tuple) -> MotionSpec:
    return MotionSpec(name="success", variant=variant, intent="t", valence=0.0, arousal=0.0,
                      principles=(PrincipleUse(Principle.TIMING, "t"),), head=keys)


class TestReviewHelpers(unittest.TestCase):
    def test_shipped_drafts_contain_the_neutral_act(self):
        lib = default_library()
        for name in ("aha_recommend", "boredom", "success", "failure"):
            with self.subTest(name=name):
                self.assertTrue(functional_match(lib.get(name, "expressive"), lib.get(name, "neutral"))["all_matched"])

    def test_mismatch_is_reported(self):
        nod = spec("neutral", (HeadKey(0.5, Pose6.from_deg_mm(pitch_deg=10), Easing.LINEAR),
                               HeadKey(0.5, Pose6(), Easing.LINEAR)))
        turn = spec("expressive", (HeadKey(0.5, Pose6.from_deg_mm(yaw_deg=20)), HeadKey(0.5, Pose6())))
        m = functional_match(turn, nod)
        self.assertFalse(m["all_matched"])
        self.assertIsNone(m["matches"][0]["expressive_match"])

    def test_state_diff_and_markdown(self):
        a = planned_state(spec("neutral", ()).start)
        b = {**a, "head": {**a["head"], "pitch_deg": 0.3, "z_mm": -0.2}, "antennas_deg": [a["antennas_deg"][0] + 0.5,
                                                                                         a["antennas_deg"][1]]}
        d = state_diff(b, a)
        self.assertAlmostEqual(d["head_angle_deg"], 0.3)
        self.assertAlmostEqual(d["head_trans_mm"], 0.2)
        self.assertAlmostEqual(d["antenna_deg"], 0.5)
        md = review_markdown({"generated_utc": "x", "motions": {}, "pairs": {}}, {})
        self.assertIn("roll 부호", md)
        self.assertIn("안테나 방향", md)


if __name__ == "__main__":
    unittest.main()
