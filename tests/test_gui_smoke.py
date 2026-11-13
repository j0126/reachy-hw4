"""Motion Lab window smoke test (offscreen Qt): the Motion tab shows and gates the motion files (no editing),
Experiment (hidden Mock backend) -> Results -> export. No MuJoCo, no robot."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtWidgets
except ImportError:  # pragma: no cover - the GUI extra is optional
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, "PySide6 not installed")
class TestMotionEditorWindow(unittest.TestCase):
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

    def test_motion_tab_shows_gates_and_exports(self):
        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import LabSessions
        from reachy_motion.gui.model import EditorModel
        from reachy_motion.library.io import save_spec_file
        from tests.test_gui_model import motion_pair

        with tempfile.TemporaryDirectory() as d:
            for spec in motion_pair():
                save_spec_file(spec, Path(d) / f"{spec.name}.{spec.variant}.yaml")
            sessions = LabSessions(lambda e: None, root=Path(d) / "lab")
            win = MainWindow(EditorModel(Path(d)), initial=("success", "expressive"), sessions=sessions)
            try:
                # one screen: three tabs, no editor, no start screen, no mode switch
                self.assertEqual([win.main_tabs.tabText(i) for i in range(win.main_tabs.count())],
                                 ["① 모션", "② 실험", "③ 결과"])
                for gone in ("home", "left_editor", "value_edits", "adv_action", "controller", "set_advanced"):
                    self.assertFalse(hasattr(win, gone), gone)
                self.assertEqual(win.model.spec.key, "success:expressive")
                self.assertTrue(win.play_btn.isEnabled() and win.pair_btn.isEnabled())
                self.assertIn("초기 정책 통과", win.policy_badge.text())
                self.assertIn("기구적 안전 보장 아님", win.policy_badge.text())
                self.assertIn("설계 목표, 측정 아님", win.info_view.toPlainText())  # V/A are design targets
                self.assertIn("애니메이션 원리", win.info_view.toPlainText())
                self.assertGreater(win.params_table.rowCount(), 0)  # the settings tab
                heads = [win.params_table.horizontalHeaderItem(j).text() for j in range(win.params_table.columnCount())]
                for want in ("이동 s", "정지 s", "보간", "변화량 (진폭)", "최고 속도"):  # what the assignment lists
                    self.assertIn(want, heads)
                self.assertFalse(any(h.startswith("delta_") for h in heads))
                text = win.compare_view.toPlainText()
                self.assertIn("같은 시작 자세", text)
                self.assertNotIn("design parameters", text)  # no raw English record
                win.on_help()  # the team guide inside the app; links to other .md files open there
                self.assertIn("팀원 가이드", win._help.view.toPlainText())
                from PySide6 import QtCore

                win._help.follow(QtCore.QUrl("lab/GUI_ROBOT.md"))
                self.assertIn("실제 로봇", win._help.view.toPlainText())
                win._help.close()
                # the robot button: there, off until the robot is connected and woken up (② 실험 tab's robot box)
                self.assertFalse(win.robot_play_btn.isEnabled())
                self.assertIn("연결 안 됨", win.robot_state.text())
                self.assertIsNotNone(win.experiment_tab.play_motion_on_robot("success", "expressive"))  # refused
                self.assertIsNone(sessions.existing("robot"))  # nothing was created, nothing sent
                win.rb_neut.setChecked(True)
                self.app.processEvents()
                self.assertEqual(win.model.spec.key, "success:neutral")
                files = win.model.export_bundle(Path(d) / "export")
                self.assertTrue(any(p.name == "manifest.json" for p in files))
                # a motion outside the initial policy (changed through the model, as no widget edits): not played
                win.rb_expr.setChecked(True)
                self.app.processEvents()
                win.model.set_key_value("head", 1, "z_mm", 34.0)
                win.refresh_analysis()
                self.assertFalse(win.play_btn.isEnabled())
                self.assertIn("초기 정책 밖", win.policy_badge.text())
                win.on_preview_sim()  # refused on the GUI side before any MuJoCo is started
                self.assertIn("재생 거부", win.play_state.text())
                self.assertIsNone(sessions.existing("sim"))
            finally:
                with mock.patch.object(QtWidgets.QMessageBox, "question",
                                       return_value=QtWidgets.QMessageBox.StandardButton.Yes):
                    win.close()
                self.app.processEvents()

    def test_r1_amplitude_defaults_to_the_largest_step_and_survives_an_axis_change(self):
        """2026-11-12 22:36: the user picked 10 deg, then the axis - and ran 2 deg (the axis change reset the ladder)."""
        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import LabSessions
        from reachy_motion.gui.model import EditorModel

        with tempfile.TemporaryDirectory() as d:
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"),
                             sessions=LabSessions(lambda e: None, root=Path(d) / "lab"))
            try:
                exp = win.experiment_tab
                exp.stage_buttons["R1"].setChecked(True)

                def shown():
                    return exp.r1_axis.currentData(), exp.r1_amp.currentText(), exp._selected().trial.label

                self.assertEqual(shown(), ("yaw", "10", "r1_yaw_p10deg_rep1"))  # the largest step by default
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("pitch"))
                self.assertEqual(shown(), ("pitch", "10", "r1_pitch_p10deg_rep1"))  # the step stays
                exp.r1_amp.setCurrentText("2")  # a small step on purpose (the dead-band record)
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("antenna_right"))
                self.assertEqual(shown(), ("antenna_right", "5", "r1_antenna_right_p5deg_rep1"))  # step 1 of 5/15/30
                exp.r1_amp.setCurrentIndex(2)
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("z"))
                self.assertEqual(shown()[:2], ("z", "5"))
                self.assertTrue(all(c.runnable for c in exp.checks))
                # 2026-11-13: a typed amplitude between the steps (the dead-band curve), inside the axis' R1 range
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("yaw"))
                exp.r1_amp.setCurrentText("3.5")
                exp.r1_amp.lineEdit().editingFinished.emit()
                self.assertEqual(shown(), ("yaw", "3.5", "r1_yaw_p3.5deg_rep1"))
                self.assertIn("직접 입력", exp.r1_unit.text())
                exp.r1_amp.setCurrentText("20")  # outside R1: refused before any check, the reason on the status line
                exp.r1_amp.lineEdit().editingFinished.emit()
                self.assertEqual(exp.checks, [])
                self.assertIn("R1 범위 밖", exp._build_error)
                exp._update_guide()
                self.assertFalse(exp.play_btn.isEnabled())
                self.assertIn("R1 범위 밖", exp.status_line.text())
                exp.r1_axis.setCurrentIndex(exp.r1_axis.findData("pitch"))  # a new axis: back to its ladder
                self.assertEqual(shown()[:2], ("pitch", "10"))
            finally:
                win.close()
                self.app.processEvents()

    def test_the_robot_box_is_above_the_tabs(self):
        """2026-11-13: one robot box for every tab (connect / Wake-up / torque-off without leaving the Motion tab)."""
        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import LabSessions
        from reachy_motion.gui.model import EditorModel

        with tempfile.TemporaryDirectory() as d:
            win = MainWindow(EditorModel(Path("motions")), initial=("success", "expressive"),
                             sessions=LabSessions(lambda e: None, root=Path(d) / "lab"))
            try:
                exp, box = win.experiment_tab, win.robot_box
                self.assertIs(box, exp.robot_panel)  # one box, the Experiment tab's handlers
                self.assertFalse(exp.isAncestorOf(box))
                self.assertFalse(box.isHidden())  # shown from the start (user decision 2026-11-13)
                self.assertTrue(win.robot_toggle.isChecked())
                win.robot_toggle.setChecked(False)  # not connected, not the robot backend: the person may hide it
                self.assertTrue(box.isHidden())
                self.assertEqual(win.main_tabs.currentWidget(), win.motion_page)
                win.go_robot_box()  # the Motion tab's link: the box opens again, the tab stays
                self.assertFalse(box.isHidden())
                self.assertEqual(win.main_tabs.currentWidget(), win.motion_page)
                self.assertIn("위쪽 로봇 상자", win.robot_state.text())
                win.robot_toggle.setChecked(False)
                self.assertTrue(box.isHidden())
                exp.rb_real.setChecked(True)  # the robot as the backend: the box shows and cannot be hidden
                self.assertFalse(box.isHidden())
                self.assertFalse(win.robot_toggle.isEnabled())
                exp._update_guide()
                self.assertIn("실제 로봇", exp.play_btn.text())  # where the click runs, on the button
                exp.rb_sim.setChecked(True)
                exp._update_guide()
                self.assertIn("MuJoCo", exp.play_btn.text())
                self.assertTrue(win.robot_toggle.isEnabled())
                win.robot_toggle.setChecked(False)
                self.assertTrue(box.isHidden())
                self.assertIsNone(win.sessions.existing("robot"))  # nothing was created, nothing sent
            finally:
                win.close()
                self.app.processEvents()

    def test_motion_lab_experiment_to_results_on_the_mock(self):
        """Experiment tab (Mock R3 step) -> Results tab -> export; the robot and R0 stay unavailable."""
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
                # backends: MuJoCo (default) and the robot; the Mock is the hidden offline backend of the tests
                self.assertTrue(exp.rb_sim.isChecked())
                self.assertFalse(exp.rb_mock.isVisibleTo(exp))
                self.assertEqual(list(exp.stage_buttons), ["R1", "R2", "R3"])
                self.assertEqual(exp.table.columnCount(), 6)
                # the robot box (2026-11-12): selectable, every robot action one click (gui/robot_session.py)
                self.assertTrue(exp.rb_real.isEnabled())
                exp.rb_real.setChecked(True)
                self.assertTrue(exp.robot_panel.isVisibleTo(win))  # above the tabs (2026-11-13)
                self.assertFalse(exp.play_btn.isEnabled())  # not connected: no trial
                self.assertFalse(exp.run_all_btn.isEnabled())  # the robot never runs a batch
                self.assertTrue(exp.robot_panel.connect_btn.isEnabled())  # one click: connect reads the robot itself
                self.assertFalse(exp.robot_panel.switch_warning.isVisibleTo(win))  # every robot switch on
                exp.rb_mock.setChecked(True)
                win.robot_toggle.setChecked(False)  # no longer forced: the person hides it
                self.assertFalse(exp.robot_panel.isVisibleTo(win))
                exp.stage_buttons["R3"].setChecked(True)
                self.assertFalse(exp.run_all_btn.isVisibleTo(exp))  # R3: one step at a time
                exp.r3_values.setText("1.0, 0.1")
                exp.r3_fixed.setValue(30.0)
                exp.rebuild_trials()
                self.assertEqual([c.runnable for c in exp.checks], [True, False])  # 0.1 s at 30 deg: refused
                exp.table.selectRow(1)
                exp.on_play()
                self.assertFalse(exp.sessions.busy())  # a refused step is never queued
                exp.table.selectRow(0)
                exp.on_play()
                self.assertTrue(self._pump(lambda: len(results.runs) == 1, timeout=60.0))
                self.assertEqual(results.runs[0].data_kind, "mock")
                win.main_tabs.setCurrentWidget(results)
                self.assertEqual(results.key_table.columnCount(), 6)
                self.assertIn("지연 포함", results.key_table.horizontalHeaderItem(2).text())  # RMSE keeps the delay
                self.assertEqual([results.tabs.tabText(i) for i in range(results.tabs.count())],
                                 ["주 채널", "R1 진폭비", "R3 단계 비교", "한계 지도", "Expressive vs Neutral"])
                results.tabs.setCurrentWidget(results._tab_pages["limit"])  # drawn when shown (computed once)
                self.assertGreater(results.limit_table.rowCount(), 8)  # this folder's motions + the R3 ladder
                files = {p.name for p in results.export_all(Path(d) / "export")}
                self.assertTrue({"metrics_representative.csv", "metrics.json", "pose.png", "joints.png",
                                 "r1_amplitude.png", "r3_ladder.png", "limit_map.png", "limit_map.csv", "summary.md",
                                 "manifest.json"} <= files)
            finally:
                with mock.patch.object(QtWidgets.QMessageBox, "question",
                                       return_value=QtWidgets.QMessageBox.StandardButton.Yes):
                    win.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
