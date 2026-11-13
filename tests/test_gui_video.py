"""Motion tab side-by-side E/N video: finding a finished video by spec digests, the job folder, the policy gate of
the render process, and one real render + playback (offscreen Qt, offline MuJoCo, small and fast)."""

import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtGui, QtWidgets
except ImportError:  # pragma: no cover - the GUI extra is optional
    QtWidgets = None

from reachy_motion.gui import video as vd
from reachy_motion.library.pose import Pose6
from reachy_motion.library.spec import HeadKey
from tests.test_gui_model import motion_pair


def out_of_policy(spec):
    """The expressive test motion with its nod lifted 34 mm (outside the initial policy, as in the smoke test)."""
    return replace(spec, head=(HeadKey(0.3, Pose6.from_deg_mm(pitch_deg=-4.0), label="lift"),
                               HeadKey(0.35, Pose6.from_deg_mm(pitch_deg=12.0, z_mm=34.0), hold=0.15, label="nod"),
                               HeadKey(0.5, Pose6(), label="back")))


class TestVideoFiles(unittest.TestCase):
    def test_find_video_by_digests(self):
        e, n = motion_pair()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)

            def folder(name, digests, files):
                f = root / name
                f.mkdir()
                for x in files.values():
                    (f / x).write_bytes(b"x")
                (f / "manifest.json").write_text(json.dumps({"videos": [
                    {"files": files, "file": next(iter(files.values())),
                     "motions": [{"spec_digest": g} for g in digests]}]}), encoding="utf-8")
                return f

            self.assertIsNone(vd.find_video((e.digest(), n.digest()), [root]))
            folder("20260101_000000_success", (e.digest(), n.digest()), {"mp4": "s.mp4"})  # no WebP: not playable
            folder("20260101_000001_success", (e.digest(), "other"), {"webp": "s.webp"})  # another neutral
            self.assertIsNone(vd.find_video((e.digest(), n.digest()), [root]))
            old = folder("20260101_000002_success", (n.digest(), e.digest()), {"mp4": "s.mp4", "webp": "s.webp"})
            new = folder("20260101_000003_success", (e.digest(), n.digest()), {"webp": "s.webp"})
            found = vd.find_video((e.digest(), n.digest()), [root])
            self.assertEqual(found.folder, new)  # the newest of the matching ones
            self.assertIsNone(found.mp4)
            (new / "manifest.json").unlink()
            self.assertEqual(vd.find_video((e.digest(), n.digest()), [root]).folder, old)

    def test_job_folder_and_policy_gate(self):
        from reachy_motion.safety.checker import prepare

        e, n = motion_pair()
        with tempfile.TemporaryDirectory() as d:
            job = vd.prepare_job(e, n, Path(d), edited=True, stamp="20260101_000000")
            self.assertEqual(job.out_dir.name, "20260101_000000_success")
            self.assertEqual([p.name for p in job.spec_files], ["success.expressive.yaml", "success.neutral.yaml"])
            self.assertIn("edited working copy", job.title)
            self.assertTrue(job.title.isascii())  # the frame font has no Hangul
            self.assertEqual(job.command("py")[:3], ["py", "-m", "reachy_motion.gui.video"])
            with self.assertRaises(ValueError):
                vd.prepare_job(n, e, Path(d))  # variants swapped
            bad = out_of_policy(e)
            self.assertFalse(prepare(bad).runnable)
            job = vd.prepare_job(bad, n, Path(d), stamp="20260101_000001")
            out = job.out_dir / "render"
            code = vd.main([str(job.spec_files[0]), str(job.spec_files[1]), "--out", str(out)])
            self.assertEqual(code, 3)  # refused before any MuJoCo work
            self.assertFalse(out.exists())


@unittest.skipIf(QtWidgets is None, "PySide6 not installed")
class TestVideoTab(unittest.TestCase):
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

    def test_render_play_and_reuse(self):
        from reachy_motion.gui.video_tab import MotionVideoTab

        e, n = motion_pair()
        with tempfile.TemporaryDirectory() as d:
            tab = MotionVideoTab(root=Path(d), search_roots=(), fps=10, size=(160, 120))
            tab.show()
            try:
                tab.set_specs(e, n)
                self.assertIsNone(tab.found)
                self.assertTrue(tab.make_btn.isEnabled())
                tab.on_make()
                self.assertTrue(tab.rendering)
                self.assertFalse(tab.make_btn.isEnabled())  # one render at a time
                self.assertTrue(self._pump(lambda: not tab.rendering, timeout=120.0), tab.state.text())
                self.assertIsNotNone(tab.found, tab.state.text())
                self.assertTrue(tab.movie.isValid())
                self.assertGreater(tab.movie.frameCount(), 10)
                self.assertEqual(tab.table.rowCount(), 2)
                files = {p.name for p in tab.found.folder.iterdir()}
                self.assertTrue({"success.webp", "index.html", "manifest.json", "specs"} <= files)
                manifest = json.loads((tab.found.folder / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["data_kind"], "simulated")
                running, paused = QtGui.QMovie.MovieState.Running, QtGui.QMovie.MovieState.Paused
                self.assertEqual(tab.movie.state(), running)
                tab.toggle_play()
                self.assertEqual(tab.movie.state(), paused)
                tab.toggle_play()
                tab.hide()  # nobody looks: no decoding
                self.assertEqual(tab.movie.state(), paused)
                tab.show()
                self.assertEqual(tab.movie.state(), running)
                # another motion pair, then the same one again: shown at once, nothing rendered
                folder = tab.found.folder
                tab.set_specs(out_of_policy(e), n, why_not="두 변형 중 하나가 초기 정책 밖입니다")
                self.assertIsNone(tab.found)
                self.assertFalse(tab.make_btn.isEnabled())
                tab.set_specs(e, n)
                self.assertEqual(tab.found.folder, folder)
                self.assertFalse(tab.rendering)
            finally:
                tab.shutdown()
                tab.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
