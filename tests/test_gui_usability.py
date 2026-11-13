"""Motion Lab usability layer: the guide logic (button state and the reason a button is off), mixed-selection
warnings, the one-screen Experiment tab (status line, R2 expressive + neutral in one go on the hidden Mock), saved
notes and the one-click report export. Offscreen Qt; no MuJoCo, no robot."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtWidgets
except ImportError:  # pragma: no cover - the GUI extra is optional
    QtWidgets = None

from reachy_motion.gui import guide as gd
from reachy_motion.gui import results as res

CAUSAL_WORDS = ("때문", "원인", "인해", "탓", "because", "due to")


class TestGuide(unittest.TestCase):
    def test_steps_and_disabled_reasons(self):
        g = gd.guide(gd.GuideState("R3", "mock", build_error="사다리 값 'x'을(를) 읽을 수 없습니다"))
        self.assertEqual((g.step, g.play_enabled), (0, False))
        self.assertIn("사다리 값", g.play_reason)
        g = gd.guide(gd.GuideState("R3", "mock", n_trials=2, n_runnable=0, refused=["D 0.1 s: 너무 빠름"]))
        self.assertEqual((g.step, g.play_enabled), (1, False))
        self.assertIn("D 0.1 s", g.play_reason)
        ok = gd.GuideState("R3", "sim", n_trials=2, n_runnable=2, selected="D 1 s", selected_runnable=True)
        g = gd.guide(ok, n_pending_runnable=2)
        self.assertEqual((g.step, g.play_enabled, g.run_all_enabled), (3, True, False))  # R3: one step at a time
        self.assertIn("MuJoCo", g.next_action)  # the daemon starts by itself: say so
        g = gd.guide(gd.GuideState("R2", "mock", n_trials=2, n_runnable=2, selected="E", selected_runnable=True),
                     n_pending_runnable=2)
        self.assertTrue(g.run_all_enabled)
        g = gd.guide(gd.GuideState("R2", "mock", n_trials=2, n_runnable=2, selected="E", selected_runnable=True,
                                   busy=True, running="E"))
        self.assertEqual((g.step, g.play_enabled, g.run_all_enabled), (3, False, False))
        g = gd.guide(gd.GuideState("R3", "mock", n_trials=2, n_runnable=2, selected="D 1 s", selected_runnable=True,
                                   halted_at="D 0.3 s"))
        self.assertEqual((g.step, g.play_enabled, g.results_enabled), (4, False, True))

    def test_mixing_warnings(self):
        def run(kind, stage, session, legacy=False):
            return SimpleNamespace(data_kind=kind, stage=stage, legacy_time_base=legacy,
                                   run_dir=Path("lab") / session / "runs" / f"{stage}_{kind}")

        self.assertEqual(res.mixing_warnings([run("mock", "R3", "s1"), run("mock", "R3", "s1")]), [])
        w = res.mixing_warnings([run("mock", "R3", "s1"), run("simulated", "R2", "s2", legacy=True)])
        self.assertEqual(len(w), 4)  # data_kind, stage, sessions, legacy time base
        self.assertIn("mock, simulated", w[0])


@unittest.skipIf(QtWidgets is None, "PySide6 not installed")
class TestOneScreenWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _pump(self, until, timeout: float = 15.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.app.processEvents()
            if until():
                return True
            time.sleep(0.01)
        return until()

    def test_status_line_and_expressive_neutral_comparison_on_the_mock(self):
        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import LabSessions
        from reachy_motion.gui.model import EditorModel
        from reachy_motion.library.io import save_spec_file
        from tests.test_gui_model import motion_pair

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "motions").mkdir()
            for spec in motion_pair():
                save_spec_file(spec, Path(d) / "motions" / f"{spec.name}.{spec.variant}.yaml")
            win = MainWindow(EditorModel(Path(d) / "motions"), initial=("success", "expressive"),
                             sessions=LabSessions(lambda e: None, root=Path(d) / "lab"))
            try:
                exp, results = win.experiment_tab, win.results_tab
                # starts on the Motion tab; MuJoCo is the default backend, never the robot
                self.assertIs(win.main_tabs.currentWidget(), win.motion_page)
                self.assertFalse(exp.rb_real.isChecked())
                self.assertIn("MuJoCo", exp.status_line.text())
                # an invalid ladder: the run button is off and the status line says why
                exp.stage_buttons["R3"].setChecked(True)
                exp.r3_values.setText("1.0, abc")
                exp.rebuild_trials()
                self.assertFalse(exp.play_btn.isEnabled())
                self.assertIn("사다리 값", exp.status_line.text())
                exp.r3_values.setText("1.0, 0.6")
                exp.rebuild_trials()
                self.assertTrue(exp.play_btn.isEnabled())
                self.assertFalse(exp.run_all_btn.isEnabled())  # R3: never several steps in a row
                self.assertIn("선택:", exp.status_line.text())
                # R2 expressive + neutral in one go (on the hidden Mock: no MuJoCo in the tests)
                exp.rb_mock.setChecked(True)
                exp.stage_buttons["R2"].setChecked(True)
                exp.r2_motion.setCurrentIndex(exp.r2_motion.findData("success"))
                exp.r2_variant.setCurrentIndex(0)
                exp.r2_reps.setValue(1)
                exp.notes_edit.setText("1조 사용성 시험")
                self.assertTrue(exp.run_all_btn.isEnabled())
                exp.on_run_all()
                self.assertTrue(self._pump(lambda: len(results.runs) == 2 and not exp.sessions.busy(), timeout=120.0))
                exp._update_guide()
                self.assertTrue(exp.results_btn.isEnabled())
                exp.results_btn.click()
                self.assertTrue(self._pump(lambda: win.main_tabs.currentWidget() is results
                                           and len(results.checked_runs()) == 2, timeout=30.0))
                runs = results.checked_runs()
                self.assertEqual({r.condition.get("variant") for r in runs}, {"expressive", "neutral"})
                for r in runs:
                    self.assertEqual(res.read_notes(r.run_dir), "1조 사용성 시험")
                    self.assertTrue((Path(r.run_dir) / "README.md").is_file())
                self.assertTrue((res.session_of(runs[0]) / "README.md").is_file())
                self.assertEqual(len(res.main_metrics_rows(runs)), 2)
                self.assertEqual(res.mixing_warnings(runs), [])
                facts = res.describe(runs)
                self.assertTrue(any("Expressive가" in f for f in facts))
                self.assertEqual(facts[-1], res.CAUSAL_DISCLAIMER)
                for f in facts[:-1]:
                    self.assertFalse(any(w in f for w in CAUSAL_WORDS), f)
                # one-click report export, then the same runs read back by "another team member"
                results.on_export_report()
                out = results._last_export
                self.assertIsNotNone(out)
                names = {p.name for p in out.iterdir()}
                self.assertTrue({"key_metrics.csv", "auto_summary.md", "main_channel.png", "summary.md",
                                 "expressive_vs_neutral.csv", "manifest.json"} <= names)
                again = [res.load_result(r.run_dir) for r in runs]
                self.assertEqual([round(x["dynamic_rmse"], 9) for x in res.main_metrics_rows(again)],
                                 [round(x["dynamic_rmse"], 9) for x in res.main_metrics_rows(runs)])
            finally:
                with mock.patch.object(QtWidgets.QMessageBox, "question",
                                       return_value=QtWidgets.QMessageBox.StandardButton.Yes):
                    win.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
