"""Build the source-code zip for the professor (HW4 submission): only what is needed to install, run and test.

Run it from the repository folder:
    .venv\\Scripts\\python tools\\make_submission.py        (Windows)
    .venv/bin/python tools/make_submission.py              (macOS / Linux)

Options:
    --out DIR      where the zip goes (default: dist/, which git ignores)
    --with-data    also add the measured robot sessions (results/lab/*_robot_R1|R2|R3, without raw/ dumps)
    --list         print the file list and stop (no zip)
    --test         unpack the zip into a temporary folder and run the unit tests there (no network, no robot)

What goes in (see HANDOVER.md section 8): README, pyproject.toml, constraints.txt, the six setup / run launchers,
reachy_motion/ (the code), motions/ (the eight confirmed motions, their sounds, the earlier candidates the tests
read), tests/, and the GUI's own manuals (docs/TEAM_GUIDE.md and the two docs/lab pages it links, which the
"? 사용법" button opens and the GUI tests read). Everything else stays out: results/ (the report carries the
figures and tables), the team's drafts and development records in docs/, CLAUDE.md, HANDOVER.md, tools/, caches.

Standard library only (it does not import reachy_motion), so it also works in a fresh ZIP download without .venv.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "reachy_hw4"  # the folder name inside the zip

ROOT_FILES = (
    "README.md", "pyproject.toml", "constraints.txt",
    "setup_windows.bat", "run_gui.bat",
    "setup_mac.command", "run_gui.command",
    "setup_linux.sh", "run_gui.sh",
)
TREES = ("reachy_motion", "motions", "tests")
DOC_FILES = ("docs/TEAM_GUIDE.md", "docs/lab/GUI_ROBOT.md", "docs/lab/MOTION_LAB.md")
DOC_GLOBS = ("docs/lab/screenshots/v3_*.png",)  # the pictures TEAM_GUIDE.md shows
DATA_GLOBS = ("results/lab/*_robot_R1", "results/lab/*_robot_R2", "results/lab/*_robot_R3")  # --with-data

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", "raw"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
LF_ONLY = {".sh", ".command"}  # bash fails on CRLF
CRLF_ONLY = {".bat"}  # cmd.exe expects CRLF
EXECUTABLE = LF_ONLY


def _walk(folder: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix not in SKIP_SUFFIXES:
                out.append(p)
    return out


def collect(root: Path = ROOT, with_data: bool = False) -> list[Path]:
    """Repository-relative paths of every file that goes into the zip (sorted, no duplicates)."""
    files: list[Path] = []
    missing = [name for name in ROOT_FILES + DOC_FILES if not (root / name).is_file()]
    missing += [name for name in TREES if not (root / name).is_dir()]
    if missing:
        raise FileNotFoundError("not a complete reachy_hw4 folder, missing: " + ", ".join(missing))
    files += [root / name for name in ROOT_FILES + DOC_FILES]
    for tree in TREES:
        files += _walk(root / tree)
    for pattern in DOC_GLOBS:
        files += sorted(root.glob(pattern))
    if with_data:
        for pattern in DATA_GLOBS:
            for session in sorted(root.glob(pattern)):
                if session.is_dir():
                    files += _walk(session)
    return sorted({f.relative_to(root) for f in files}, key=lambda p: p.as_posix())


def _content(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix in LF_ONLY:
        data = data.replace(b"\r\n", b"\n")
    elif path.suffix in CRLF_ONLY:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def build(root: Path = ROOT, out_dir: Path | None = None, with_data: bool = False) -> Path:
    """Write the zip and return its path. Launchers keep their execute bit (unix mode in the zip entry)."""
    out_dir = Path(out_dir) if out_dir is not None else root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.date.today().strftime("%Y%m%d")
    zip_path = out_dir / f"{TOP}_source{'_with_data' if with_data else ''}_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in collect(root, with_data):
            src = root / rel
            mtime = _dt.datetime.fromtimestamp(src.stat().st_mtime)
            info = zipfile.ZipInfo(f"{TOP}/{rel.as_posix()}", date_time=max(mtime, _dt.datetime(1980, 1, 1)).timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # unix: unzip and macOS Archive Utility apply the mode below
            info.external_attr = (0o100755 if src.suffix in EXECUTABLE else 0o100644) << 16
            zf.writestr(info, _content(src))
    return zip_path


def run_tests(zip_path: Path) -> int:
    """Unpack the zip and run the unit tests from the unpacked copy with this Python (its .venv)."""
    tmp = Path(tempfile.mkdtemp(prefix="hw4_submission_"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        here = tmp / TOP
        where = subprocess.run([sys.executable, "-B", "-c", "import reachy_motion; print(reachy_motion.__file__)"],
                               cwd=here, capture_output=True, text=True, check=True).stdout.strip()
        if not Path(where).resolve().is_relative_to(here.resolve()):
            print(f"[submission] the tests would import {where}, not the unpacked copy - stop")
            return 2
        print(f"[submission] running the tests in {here} (several minutes) ...")
        return subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                              cwd=here).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the HW4 source-code zip for the professor.")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: dist/)")
    ap.add_argument("--with-data", action="store_true", help="also add results/lab/*_robot_R1|R2|R3 (measured)")
    ap.add_argument("--list", action="store_true", help="print the file list only")
    ap.add_argument("--test", action="store_true", help="run the unit tests from the unpacked zip")
    args = ap.parse_args(argv)
    files = collect(ROOT, args.with_data)
    if args.list:
        for rel in files:
            print(rel.as_posix())
        print(f"[submission] {len(files)} files")
        return 0
    zip_path = build(ROOT, args.out, args.with_data)
    size_mb = zip_path.stat().st_size / 1e6
    print(f"[submission] {zip_path} ({len(files)} files, {size_mb:.1f} MB)")
    if args.test:
        code = run_tests(zip_path)
        print("[submission] tests " + ("OK" if code == 0 else f"FAILED (exit {code})"))
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
