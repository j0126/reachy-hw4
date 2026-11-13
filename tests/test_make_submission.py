"""tools/make_submission.py: the professor's zip holds the code, motions, tests, launchers and the GUI's manuals only.

tools/ itself is not in that zip, so these tests skip there. Nothing here touches the network; the zips go to a
temporary folder.
"""

import importlib.util
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "make_submission.py"


@unittest.skipUnless(TOOL.is_file(), "tools/ is not part of the submission zip")
class TestSubmissionZip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("make_submission", TOOL)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.zip_path = cls.mod.build(ROOT, Path(cls.tmp.name))
        cls.zf = zipfile.ZipFile(cls.zip_path)
        cls.names = set(cls.zf.namelist())

    @classmethod
    def tearDownClass(cls):
        cls.zf.close()
        cls.tmp.cleanup()

    def test_has_what_is_needed_to_install_run_and_test(self):
        for rel in ("README.md", "pyproject.toml", "constraints.txt", "setup_windows.bat", "run_gui.bat",
                    "setup_mac.command", "run_gui.command", "setup_linux.sh", "run_gui.sh",
                    "reachy_motion/__init__.py", "reachy_motion/gui/app.py", "reachy_motion/sound.py",
                    "motions/success.expressive.yaml", "motions/sounds/aha.wav", "motions/sounds/README.md",
                    "tests/test_sound.py", "docs/TEAM_GUIDE.md", "docs/lab/GUI_ROBOT.md", "docs/lab/MOTION_LAB.md"):
            self.assertIn("reachy_hw4/" + rel, self.names)
        confirmed = [n for n in self.names if re.fullmatch(r"reachy_hw4/motions/[a-z_]+\.(expressive|neutral)\.yaml", n)]
        self.assertEqual(len(confirmed), 8)
        self.assertTrue(any(n.startswith("reachy_hw4/motions/candidates/") for n in self.names))  # tests read them

    def test_leaves_out_records_drafts_and_local_files(self):
        for n in self.names:
            self.assertTrue(n.startswith("reachy_hw4/"), n)
            rel = n[len("reachy_hw4/"):]
            self.assertFalse(rel.startswith(("results/", ".venv/", ".git/", ".claude/", "dist/", "tools/")), n)
            self.assertNotIn("__pycache__", n)
            self.assertFalse(n.endswith((".pyc", ".zip")), n)
        for rel in ("CLAUDE.md", "HANDOVER.md", "docs/VERIFICATION.md", "docs/report/HW4_REPORT_DRAFT.md",
                    "docs/phase1/SDK_ANALYSIS.md", ".gitignore"):
            self.assertNotIn("reachy_hw4/" + rel, self.names)
        shots = [n for n in self.names if "/screenshots/" in n]
        self.assertTrue(shots and all(Path(n).name.startswith("v3_") for n in shots), shots)

    def test_launchers_keep_execute_bit_and_line_endings(self):
        for rel in ("setup_mac.command", "run_gui.command", "setup_linux.sh", "run_gui.sh"):
            info = self.zf.getinfo("reachy_hw4/" + rel)
            self.assertEqual((info.external_attr >> 16) & 0o777, 0o755, rel)
            data = self.zf.read(info)
            self.assertTrue(data.startswith(b"#!"), rel)
            self.assertNotIn(b"\r", data, rel)
        for rel in ("setup_windows.bat", "run_gui.bat"):
            data = self.zf.read("reachy_hw4/" + rel)
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), rel)
        self.assertEqual((self.zf.getinfo("reachy_hw4/README.md").external_attr >> 16) & 0o777, 0o644)

    def test_measured_sessions_only_on_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(self.mod.build(ROOT, Path(tmp), with_data=True)) as zf:
                data = [n for n in zf.namelist() if n.startswith("reachy_hw4/results/")]
        for n in data:
            self.assertRegex(n, r"^reachy_hw4/results/lab/\d{8}_\d{6}_robot_R[123]/", n)
            self.assertNotIn("/raw/", n)


if __name__ == "__main__":
    unittest.main()
