"""Phase 3 candidate folders (motions/candidates/*): each is a complete, checkable expressive/neutral pair.

Folders: boredom_scan / boredom_story / boredom_doze (alternatives) and aha_v0 / boredom_v0 (the versions before
revision 1, kept for before/after videos). The library default stays motions/<name>.<variant>.yaml; candidates are
used with ``--dir motions/candidates/<folder>``.
"""

import unittest
from pathlib import Path

from reachy_motion.library.compare import comparison_issues, state_difference
from reachy_motion.library.registry import default_library
from reachy_motion.safety.checker import check_spec
from reachy_motion.sim_review import functional_match

MOTIONS = Path(__file__).resolve().parents[1] / "motions"
CANDIDATE_DIRS = sorted(p for p in (MOTIONS / "candidates").iterdir() if p.is_dir())


class TestCandidateFolders(unittest.TestCase):
    def test_expected_folders_exist(self):
        names = {d.name for d in CANDIDATE_DIRS}
        self.assertTrue({"boredom_scan", "boredom_story", "boredom_doze", "aha_v0", "boredom_v0"} <= names)

    def test_each_candidate_is_a_valid_comparable_pair(self):
        for d in CANDIDATE_DIRS:
            with self.subTest(candidate=d.name):
                lib = default_library(d)
                keys = sorted(s.key for s in lib)
                name = keys[0].split(":")[0]
                self.assertEqual(keys, [f"{name}:expressive", f"{name}:neutral"])
                e, n = lib.get(name, "expressive"), lib.get(name, "neutral")
                for s in (e, n):
                    self.assertEqual(s.validate(), [])
                    self.assertTrue(check_spec(s).passes_policy, f"{d.name} {s.key} outside the initial policy")
                    self.assertTrue(s.draft)
                warnings = [i.code for i in comparison_issues(e, n) if i.severity == "warning"]
                self.assertEqual(warnings, [])  # same start/end, neutral linear, no antennas, no sound
                self.assertEqual(max(state_difference(e.end_state, n.end_state).values()), 0.0)
                self.assertTrue(functional_match(e, n)["all_matched"])  # neutral act is inside the expressive

    def test_scan_and_story_look_both_ways(self):
        for c in ("boredom_scan", "boredom_story"):
            lib = default_library(MOTIONS / "candidates" / c)
            for v in ("expressive", "neutral"):
                with self.subTest(candidate=c, variant=v):
                    yaws = [k.value.yaw for k in lib.get("boredom", v).head]
                    self.assertGreater(max(yaws), 0.0)
                    self.assertLess(min(yaws), 0.0)

    def test_shipped_library_does_not_pick_up_the_candidates(self):
        lib = default_library(MOTIONS)
        self.assertEqual(len(lib), 8)
        self.assertEqual(lib.missing(), [])


if __name__ == "__main__":
    unittest.main()
