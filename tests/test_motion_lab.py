"""Motion Lab, Step A (Qt-free part): R1 / R3 trials (computed), the Mock runner, run files on one time base,
results and their data_kind labels, and the GUI's file guard. Mock only: no daemon, no robot."""

from __future__ import annotations

import json
import math
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from reachy_motion.gui import experiments as ex
from reachy_motion.gui import results as res
from reachy_motion.gui.lab import LabError, LabSession, new_session_dir


def run_mock_trial(trial: ex.Trial, root: Path) -> list[dict]:
    events: list[dict] = []
    done = threading.Event()

    def on(e: dict) -> None:
        events.append(e)
        if e["kind"] in ("trial_finished", "error", "refused"):
            done.set()

    s = LabSession("mock", root, on_event=on)
    try:
        s.run_trial(trial, new_session_dir("mock", trial.stage, root))
        if not done.wait(60):
            raise AssertionError(f"no result: {events}")
    finally:
        s.close()
    return events


class TestTrials(unittest.TestCase):
    def test_r3_ladder_matches_the_plan(self):
        """PHASE4_PLAN §5.2 / 5.3: A 20 deg minjerk, D 1.0 / 0.6 / 0.4 / 0.3 s -> 0.04 / 0.07 / 0.11 / 0.15, margin 30;
        0.25 / 0.2 s (robot ladder since 2026-11-13) -> 0.175 / 0.219."""
        checks = [ex.check_trial(t) for t in ex.r3_ladder("duration", ex.R3_DEFAULT_DURATIONS, 20.0)]
        self.assertTrue(all(c.runnable for c in checks))
        self.assertEqual(len(checks), 6)
        for c, want in zip(checks, (0.04, 0.07, 0.11, 0.15, 0.175, 0.219)):
            self.assertAlmostEqual(c.metrics["peak_stewart_speed_ratio"], want, delta=0.006)
            self.assertAlmostEqual(c.metrics["min_stewart_margin_deg"], 29.6, delta=0.5)
            self.assertGreaterEqual(c.record_s, c.trial.spec.duration + ex.PRE_S + ex.POST_S - 0.03)
        self.assertEqual({c.trial.condition["amplitude_deg"] for c in checks}, {20.0})  # one parameter varies

    def test_real_robot_scope_and_policy_refusal(self):
        scope = {d: ex.check_trial(ex.r3_trial(20, d)).real_scope for d in (0.3, 0.25, 0.2, 0.15)}
        self.assertIn("실제 로봇 후보", scope[0.3])
        self.assertIn("따로 승인", scope[0.25])
        self.assertIn("따로 승인", scope[0.2])  # the robot ladder reaches 0.2 s (2026-11-13)
        self.assertIn("실제 로봇 제외", scope[0.15])
        too_fast = ex.check_trial(ex.r3_trial(30, 0.1))  # 0.68 x no-load speed > the 0.5 policy (§5.2)
        self.assertFalse(too_fast.runnable)
        self.assertIsNone(too_fast.prepared)
        self.assertIn("초기 정책 밖", too_fast.real_scope)

    def test_r1_moves_are_single_axis_and_tiny(self):
        for axis, (_field, _unit, ladder, channel) in ex.R1_AXES.items():
            c = ex.check_trial(ex.r1_trial(axis, ladder[0]))
            self.assertTrue(c.runnable, axis)
            self.assertLessEqual(max(c.metrics["peak_stewart_speed_ratio"], c.metrics["peak_antenna_speed_ratio"]),
                                 0.0042, axis)  # §3 R1: <= 0.0041
            self.assertEqual(c.trial.main_channel, channel)


class TestMockRunAndResults(unittest.TestCase):
    def test_trial_files_one_time_base_metrics_and_labels(self):
        with tempfile.TemporaryDirectory() as d:
            events = run_mock_trial(ex.r3_trial(20, 0.6), Path(d))
            fin = [e for e in events if e["kind"] == "trial_finished"][-1]
            self.assertTrue(fin["completed"], fin)
            self.assertEqual(fin["ticks"]["n_ticks"], 261)
            run_dir = Path(fin["run_dir"])
            for name in ("commands.csv", "present_mock.csv", "ticks.csv", "manifest.json", "metrics.json"):
                self.assertTrue((run_dir / name).is_file(), name)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual((manifest["data_kind"], manifest["trial"]["stage"]), ("mock", "R3"))
            run = fin["loaded"]
            self.assertEqual((run.data_kind, run.stage, run.legacy_time_base), ("mock", "R3", False))
            self.assertLess(abs(run.data.t_meas[0] - run.data.t_cmd[0]), 0.03)  # one time base
            pitch = run.metrics["pitch"]
            self.assertAlmostEqual(pitch.command_p2p, math.radians(20.0), delta=1e-6)
            self.assertAlmostEqual(pitch.amplitude_ratio, 1.0, delta=0.01)
            self.assertTrue(0.0 <= pitch.lag_s <= 0.1)
            again = res.load_result(run_dir)  # from disk: the same analysis
            self.assertAlmostEqual(again.metrics["pitch"].lag_s, pitch.lag_s)
            md = res.summary_markdown([run])
            self.assertIn("measured 0개", md)
            self.assertIn("실제 로봇 측정(measured) 결과 없음", md)
            self.assertIn("실제 로봇 측정(measured) 결과 없음", res.source_banner([run]))
            self.assertTrue(res.source_banner([]).startswith("불러온 결과가 없습니다"))

    def test_the_robot_is_not_a_lab_target(self):
        with self.assertRaises(LabError):
            LabSession("robot")


class TestSignedOffFiles(unittest.TestCase):
    def test_a_signed_off_motion_file_is_recognised(self):
        from reachy_motion.gui.model import EditorModel
        from reachy_motion.library.io import save_spec_file

        spec = ex.r3_trial(20, 1.0).spec
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a").mkdir()
            (Path(d) / "b").mkdir()
            signed, draft = Path(d) / "a" / "success.expressive.yaml", Path(d) / "b" / "success.expressive.yaml"
            save_spec_file(replace(spec, draft=False), signed)
            save_spec_file(replace(spec, draft=True), draft)
            self.assertTrue(EditorModel.is_signed_off_file(signed))
            self.assertFalse(EditorModel.is_signed_off_file(draft))
            self.assertFalse(EditorModel.is_signed_off_file(Path(d) / "missing.yaml"))


if __name__ == "__main__":
    unittest.main()
