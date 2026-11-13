"""Results tab views (2026-11-13 usability): the R3 figure marks the step where tracking broke down with the robot
ladder's own criteria, and the run list keeps the reading order. Offscreen Qt, synthetic rows and runs only."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:  # pragma: no cover - the GUI extra is optional
    QtWidgets = None

from reachy_motion.gui import lab_plots
from reachy_motion.gui.plots import new_figure
from reachy_motion.gui.results import ROLE_AXIS, ROLE_JOINT


def row(d: float, kind: str = "measured", role: str = ROLE_AXIS, **kw: float) -> dict:
    """One R3 row like ``results.r3_rows`` (display units): the 2026-11-12 robot baseline unless overridden."""
    r = {"run": f"r3_pitch20_D{d:.2f}_rep1", "data_kind": kind, "vary": "duration", "amplitude_deg": 20.0,
         "duration_s": d, "rep": 1, "channel": "pitch", "role": role, "unit": "deg", "lag_ms": 188.0, "lag_fit_r2": 0.97,
         "shape_error_pct": 7.0, "overshoot_pct": 0.2, "amplitude_ratio": 1.0, "peak_error": 8.8, "overshoot": 0.04,
         "settling_time_s": 0.1, "dynamic_rmse": 3.8, "dynamic_rmse_lag_compensated": 1.4, "hold_ripple": 0.03}
    r.update(kw)
    return r


class TestR3Figure(unittest.TestCase):
    def test_the_first_step_beyond_a_criterion_is_the_breakdown(self):
        rows = [row(1.0), row(0.6), row(0.4, shape_error_pct=16.0), row(0.3, shape_error_pct=22.0),
                row(1.0, kind="simulated"), row(0.6, kind="simulated", lag_ms=300.0)]  # 188 + 100 < 300
        self.assertEqual(lab_plots.r3_breakdown(rows), {"measured": 0.4, "simulated": 0.6})
        self.assertEqual(lab_plots.r3_breakdown([row(1.0), row(0.6, peak_error=12.0)]), {})  # a delay alone is fine
        joint_only = [row(1.0, role=ROLE_JOINT), row(0.6, role=ROLE_JOINT, amplitude_ratio=0.5)]
        self.assertEqual(lab_plots.r3_breakdown(joint_only), {})  # judged on the trial axis, as on the robot

    def test_the_figure_draws_the_criteria(self):
        fig = new_figure()
        lab_plots.draw_r3(fig, [row(1.0), row(0.6), row(0.4, amplitude_ratio=0.7)])
        self.assertIn("D 0.4 s", fig._suptitle.get_text())
        shape_ax = fig.axes[1]
        self.assertIn("지연 보정 RMSE", shape_ax.get_title(loc="left"))  # one name with the tables and robot messages
        self.assertTrue(any(abs(line.get_ydata()[0] - 15.0) < 1e-9 for line in shape_ax.lines
                            if len(set(line.get_ydata())) == 1))  # the 15 % stop line
        titles = [ax.get_title(loc="left") for ax in fig.axes]
        self.assertTrue(any("떨림" in t for t in titles))  # shaking: shown, not a criterion
        self.assertTrue(any("Peak Error (지연 포함)" in t for t in titles))

    def test_the_amplitude_ladder_breaks_down_at_the_first_large_a(self):
        def a_row(a: float, **kw: float) -> dict:
            return row(1.0, vary="amplitude", amplitude_deg=a, **kw)

        rows = [a_row(10.0), a_row(20.0), a_row(30.0, shape_error_pct=18.0), a_row(40.0, shape_error_pct=25.0)]
        self.assertEqual(lab_plots.r3_breakdown(rows, "amplitude"), {"measured": 30.0})
        self.assertEqual(lab_plots.r3_breakdown(rows), {})  # the duration ladder has no step here
        fig = new_figure()
        lab_plots.draw_r3(fig, rows + [row(0.6)])  # one ladder per figure: the other is named, not drawn
        text = fig._suptitle.get_text()
        self.assertIn("A 변경", text)
        self.assertIn("A 30°", text)
        self.assertIn("A 10°", text)  # the lag criterion against the ladder's first step
        self.assertIn("다른 사다리", text)


class TestNewFigures(unittest.TestCase):
    """R1 amplitude ratios and the limit map (2026-11-13): analysis data the report needs as figures."""

    def test_r1_panels_follow_the_units(self):
        rows = [{"axis": "yaw", "unit": "deg", "amplitude": 2.0, "amplitude_ratio": 0.15, "data_kind": "measured"},
                {"axis": "yaw", "unit": "deg", "amplitude": 10.0, "amplitude_ratio": 0.6, "data_kind": "measured"},
                {"axis": "z", "unit": "mm", "amplitude": 5.0, "amplitude_ratio": 0.72, "data_kind": "measured"}]
        fig = new_figure()
        lab_plots.draw_r1(fig, rows)
        panels = [ax for ax in fig.axes if ax.get_visible()]
        self.assertEqual([ax.get_title(loc="left") for ax in panels], ["머리 회전 (deg)", "머리 위아래 z (mm)"])
        self.assertIn("measured", fig._suptitle.get_text())
        lab_plots.draw_r1(fig, [])  # nothing to draw: a message, no axes
        self.assertEqual(fig.axes, [])

    def test_the_limit_map_marks_the_robot_runs_and_the_breakdown(self):
        pts = [{"kind": "motion", "motion": "aha_recommend", "variant": "expressive", "duration_s": 3.5,
                "speed_ratio": 0.386, "accel_dps2": 2941.0, "runnable": True, "robot_scope": True},
               {"kind": "motion", "motion": "aha_recommend", "variant": "neutral", "duration_s": 2.6,
                "speed_ratio": 0.02, "accel_dps2": 1250.0, "runnable": True, "robot_scope": True}]
        pts += [{"kind": "r3", "amplitude_deg": 20.0, "duration_s": d, "speed_ratio": s, "accel_dps2": a,
                 "runnable": True, "robot_scope": d >= 0.2}
                for d, s, a in ((1.0, 0.044, 87.0), (0.3, 0.146, 967.0), (0.15, 0.291, 3825.0))]
        fig = new_figure()
        lab_plots.draw_limit_map(fig, pts, {"robot_motions": {("aha_recommend", "expressive")}, "r3_measured": {1.0},
                                            "breakdown": {"measured": 0.3}, "kinds": ["measured"]})
        ax = fig.axes[0]
        self.assertEqual((ax.get_xscale(), ax.get_yscale()), ("log", "log"))
        texts = {t.get_text() for t in ax.texts}
        self.assertTrue({"D 1", "D 0.3", "aha E", "aha N"} <= texts, texts)
        self.assertIn("measured D 0.3 s", fig._suptitle.get_text())

    def test_the_limit_points_are_computed_once(self):
        from reachy_motion.gui import experiments as ex

        pts = ex.limit_points(_library())
        self.assertEqual(sum(p["kind"] == "motion" for p in pts), 8)
        r3 = {p["duration_s"]: p for p in pts if p["kind"] == "r3"}
        self.assertEqual(set(r3), set(ex.R3_DEFAULT_DURATIONS + ex.R3_SIM_ONLY_DURATIONS))
        self.assertTrue(r3[0.2]["robot_scope"])
        self.assertFalse(r3[0.15]["robot_scope"])
        speeds = [r3[d]["speed_ratio"] for d in sorted(r3, reverse=True)]
        self.assertEqual(speeds, sorted(speeds))  # shorter D, faster
        self.assertTrue(all(p["data_kind"] == "computed" for p in pts))
        self.assertIs(type(ex.limit_points(_library())), list)  # cached copy


@unittest.skipIf(QtWidgets is None, "PySide6 not installed")
class TestRunListOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_runs_appear_in_ladder_order_whatever_the_loading_order(self):
        import tempfile

        from reachy_motion.gui.lab_tabs import ResultsTab

        with tempfile.TemporaryDirectory() as d:
            tab = ResultsTab(Path(d) / "lab", extra_roots=())
            tab._refresh_timer.stop()
            session = Path(d) / "lab" / "20261114_120000_robot_R3"
            runs = []
            for dur in (0.4, 0.3, 1.0, 0.6):  # arrival order of the loading threads
                runs.append(SimpleNamespace(label=f"r3_pitch20_D{dur:.2f}_rep1", data_kind="measured", stage="R3",
                                            condition={"vary": "duration", "duration_s": dur, "amplitude_deg": 20.0,
                                                       "rep": 1}, completed=True,
                                            run_dir=session / "runs" / f"{dur}"))
            parent = QtWidgets.QTreeWidgetItem(["s"])
            tab.tree.addTopLevelItem(parent)
            for r in runs:
                tab.runs.append(r)
                it = QtWidgets.QTreeWidgetItem([r.label])
                it.setData(0, QtCore.Qt.ItemDataRole.UserRole, tab._key(r.run_dir))
                parent.insertChild(tab._child_index(parent, r), it)
            self.assertEqual([parent.child(i).text(0)[-9:-5] for i in range(parent.childCount())],
                             ["1.00", "0.60", "0.40", "0.30"])
            tab.close()


def _library():
    from reachy_motion.library.registry import default_library

    return default_library(Path(__file__).resolve().parents[1] / "motions")


if __name__ == "__main__":
    unittest.main()
