"""The phase2 report text follows the draft / signed-off state of the motion files (2026-11-11 sign-off)."""

import unittest
from types import SimpleNamespace

from reachy_motion.cli_phase2 import _design_status
from reachy_motion.library.registry import default_library


def spec(key: str, draft: bool) -> SimpleNamespace:
    return SimpleNamespace(key=key, draft=draft)


class TestDesignStatus(unittest.TestCase):
    def test_all_drafts(self):
        en, ko = _design_status([spec("a:expressive", True), spec("a:neutral", True)])
        self.assertTrue(en.startswith("Draft motions"))
        self.assertIn("초안", ko)

    def test_all_signed_off(self):
        en, ko = _design_status([spec("a:expressive", False), spec("a:neutral", False)])
        self.assertIn("Signed-off", en)
        self.assertIn("draft: false", ko)
        self.assertNotIn("초안", ko)

    def test_mixed_lists_the_drafts(self):
        en, ko = _design_status([spec("a:expressive", True), spec("a:neutral", False)])
        self.assertIn("a:expressive", en)
        self.assertNotIn("a:neutral", en)
        self.assertIn("a:expressive", ko)

    def test_shipped_library_is_signed_off(self):
        lib = list(default_library())
        self.assertEqual(len(lib), 8)
        self.assertEqual([s.key for s in lib if s.draft], [])  # signed off by the student on 2026-11-11


if __name__ == "__main__":
    unittest.main()
