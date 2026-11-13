"""Motion Editor model (Qt-free): files, edits, analysis, comparison, export - and edits never reach a backend."""

import json
import math
import tempfile
import time
import unittest
from pathlib import Path

from reachy_motion.library.pose import INIT_ANTENNAS, Pose6, antennas_droop
from reachy_motion.library.spec import AntennaKey, Easing, HeadKey, MotionSpec, Principle, PrincipleUse


def motion_pair() -> tuple[MotionSpec, MotionSpec]:
    expressive = MotionSpec(
        name="success", variant="expressive", intent="nod yes, pleased", valence=0.6, arousal=0.5,
        principles=(PrincipleUse(Principle.ANTICIPATION, "head key 'lift': small head-up before the nod"),
                    PrincipleUse(Principle.FOLLOW_THROUGH, "antenna track settles after the head stops")),
        head=(HeadKey(0.3, Pose6.from_deg_mm(pitch_deg=-4.0), label="lift"),
              HeadKey(0.35, Pose6.from_deg_mm(pitch_deg=12.0), hold=0.15, label="nod"),
              HeadKey(0.5, Pose6(), label="back")),
        antennas=(AntennaKey(0.4, antennas_droop(-0.3), label="perk"), AntennaKey(0.7, INIT_ANTENNAS, label="settle")),
    )
    neutral = MotionSpec(
        name="success", variant="neutral", intent="nod", valence=0.2, arousal=0.0,
        principles=(PrincipleUse(Principle.TIMING, "constant-speed baseline"),),
        head=(HeadKey(0.5, Pose6.from_deg_mm(pitch_deg=12.0), Easing.LINEAR, label="nod"),
              HeadKey(0.5, Pose6(), Easing.LINEAR, label="back")),
    )
    return expressive, neutral


class ModelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from reachy_motion.gui.model import EditorModel
        from reachy_motion.library.io import save_spec_file

        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for spec in motion_pair():
            save_spec_file(spec, self.dir / f"{spec.name}.{spec.variant}.yaml")
        self.model = EditorModel(self.dir)
        self.model.open("success", "expressive")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestEditing(ModelTestCase):
    def test_open_edit_save_revert(self):
        m = self.model
        self.assertFalse(m.dirty())
        rows = m.key_rows("head")
        self.assertEqual([r["label"] for r in rows], ["lift", "nod", "back"])
        self.assertAlmostEqual(rows[1]["pitch_deg"], 12.0, places=9)
        self.assertAlmostEqual(rows[1]["t_arrive_s"], 0.65, places=12)
        m.set_key_value("head", 1, "pitch_deg", 15.0)
        self.assertTrue(m.dirty())
        self.assertAlmostEqual(m.spec.head[1].pose.pitch, math.radians(15.0), places=12)
        m.save()
        self.assertFalse(m.dirty())
        from reachy_motion.library.io import load_spec_file

        self.assertAlmostEqual(load_spec_file(self.dir / "success.expressive.yaml").head[1].pose.pitch,
                               math.radians(15.0), places=12)
        m.set_key_value("antennas", 0, "right_deg", 5.0)
        self.assertTrue(m.dirty())
        m.revert()
        self.assertFalse(m.dirty())

    def test_key_operations_and_timing(self):
        m = self.model
        i = m.add_key("head", 0)
        self.assertEqual(i, 1)
        self.assertEqual(len(m.keys("head")), 4)
        self.assertEqual(m.keys("head")[1].pose, m.keys("head")[0].pose)  # copies the previous value
        self.assertEqual(m.move_key("head", 1, +1), 2)
        m.delete_key("head", 2)
        self.assertEqual([k.label for k in m.keys("head")], ["lift", "nod", "back"])
        m.set_key_timing("head", 0, t_arrive_s=0.5)
        self.assertAlmostEqual(m.keys("head")[0].duration, 0.5)
        m.set_key_timing("head", 1, hold_s=0.4)
        self.assertAlmostEqual(m.keys("head")[1].hold, 0.4)
        with self.assertRaises(ValueError):
            m.set_key_timing("head", 0, duration_s=0.001)
        with self.assertRaises(ValueError):
            m.set_key_timing("head", 0, hold_s=-1.0)
        m.set_key_easing("head", 1, "cartoon")
        self.assertEqual(m.keys("head")[1].easing, Easing.CARTOON)
        m.set_scale(amplitude=0.5, tempo=2.0)
        # head track: lift 0.5 + nod (0.35 + hold 0.4) + back 0.5 = 1.75 s, antennas 1.1 s -> 1.75 / tempo 2
        self.assertAlmostEqual(m.spec.duration, 0.875, places=12)
        self.assertEqual((m.spec.amplitude_scale, m.spec.tempo_scale), (0.5, 2.0))
        m.set_sound("ding.wav", 0.2)
        self.assertEqual(m.spec.sound.file, "ding.wav")
        m.set_sound(None)
        self.assertIsNone(m.spec.sound)

    def test_variants_keep_their_own_working_copies(self):
        m = self.model
        m.set_key_value("head", 1, "pitch_deg", 14.0)
        m.open("success", "neutral")
        self.assertEqual(m.spec.variant, "neutral")
        m.open("success", "expressive")
        self.assertAlmostEqual(m.spec.head[1].pose.pitch, math.radians(14.0), places=12)
        self.assertEqual(m.dirty_keys(), [("success", "expressive")])


class TestAnalysisAndExport(ModelTestCase):
    def test_analysis_comparison_export(self):
        m = self.model
        b = m.analyze()
        self.assertEqual(b.problems, [])
        self.assertIsNone(b.error)
        self.assertTrue(b.passes_policy, b.report.violations if b.report else b.error)
        self.assertTrue(b.segments)
        self.assertIs(m.analyze(), b)  # cached by digest
        comp = m.comparison()
        self.assertIsNotNone(comp)
        self.assertTrue(comp["same_start"])
        self.assertTrue(comp["same_end"])
        out = Path(self._tmp.name) / "export"
        files = m.export_bundle(out)
        names = {p.name for p in files}
        for expected in ("success.expressive.yaml", "success.expressive.json", "policy_report.json",
                         "executed_parameters.csv", "trajectory_dense.csv", "stream_samples.csv", "comparison.json",
                         "motion.png", "joints.png", "compare.png", "manifest.json"):
            self.assertIn(expected, names)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["data_kind_by_file"]["policy_report.json"], "computed")
        self.assertIn("not measured", manifest["expected_valence_arousal"]["note"])

    def test_invalid_spec_is_reported_not_raised(self):
        m = self.model
        m.set_spec(m.spec.__class__(**{**m.spec.__dict__, "valence": 3.0}))
        b = m.analyze()
        self.assertTrue(b.problems)
        self.assertFalse(b.passes_policy)

    def test_out_of_policy_edit_is_flagged(self):
        m = self.model
        m.set_key_value("head", 1, "z_mm", 34.0)  # policy z <= +24 mm, IK NaN from +24.3 mm
        self.assertFalse(m.analyze().passes_policy)


class TestEditsNeverReachABackend(ModelTestCase):
    def test_edits_send_nothing_play_sends_and_refuses_out_of_policy(self):
        from reachy_motion.backends.mock import MockBackend
        from reachy_motion.gui.playback import PlaybackController

        events: list[dict] = []
        backend = MockBackend(structure="robot")
        ctl = PlaybackController(backend=backend, on_event=events.append)
        try:
            m = self.model
            for k in range(40):  # a slider sweep
                m.set_key_value("head", 1, "pitch_deg", 5.0 + k * 0.25)
                m.analyze()
            self.assertEqual(ctl.command_count, 0)
            h = ctl.play(m.spec)
            self.assertTrue(h.wait(timeout=15.0))
            self.assertGreater(ctl.command_count, 0)
            n = ctl.command_count
            m.set_key_value("head", 1, "z_mm", 34.0)  # outside the policy
            h2 = ctl.play(m.spec)
            self.assertTrue(h2.wait(timeout=5.0))
            self.assertEqual(getattr(h2.state, "value", h2.state), "REJECTED")
            time.sleep(0.1)
            self.assertEqual(ctl.command_count, n)
        finally:
            ctl.close()

    def test_disabled_backends(self):
        from reachy_motion.gui.playback import PlaybackController

        for name in ("sim", "robot", "nope"):
            with self.assertRaises(ValueError):
                PlaybackController(name)


if __name__ == "__main__":
    unittest.main()
