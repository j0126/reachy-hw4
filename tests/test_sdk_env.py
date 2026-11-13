"""The Phase 1 source references are only valid for the pinned SDK - fail loudly otherwise."""

import unittest

import reachy_mini

from reachy_motion import SDK_VERSION
from reachy_motion.sdk_env import EXPECTED_PINS, environment_report, pin_mismatches


class TestSdkPins(unittest.TestCase):
    def test_reachy_mini_is_the_analysed_version(self):
        self.assertEqual(reachy_mini.__version__, SDK_VERSION)
        self.assertEqual(SDK_VERSION, "1.11.0")

    def test_all_pins_match(self):
        self.assertEqual(pin_mismatches(), {}, "run `python -m reachy_motion env` for details")

    def test_report_contains_pinned_packages(self):
        packages = environment_report()["packages"]
        for dist in EXPECTED_PINS:
            self.assertIn(dist, packages)


if __name__ == "__main__":
    unittest.main()
