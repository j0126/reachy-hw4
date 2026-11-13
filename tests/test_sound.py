"""Effect sounds (reachy_motion.sound, 2026-11-14 "로봇 스피커로"): the synthesised files, the cue tick, the daemon
REST requests (stubbed opener - never the network), the sessions' default "off", the laptop path on a Mock session
and the robot path on the offline SDK daemon harness (stub speaker)."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

import numpy as np

from reachy_motion import sound
from reachy_motion.gui import experiments as ex
from reachy_motion.library.registry import default_library

ROOT = Path(__file__).resolve().parents[1]
SOUNDS = ROOT / "motions" / "sounds"


def lib():
    return default_library(ROOT / "motions")


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2") / 32768.0, w.getframerate()


class TestSoundFiles(unittest.TestCase):
    def test_the_cues_of_the_signed_off_files_have_their_sounds(self):
        cues = {(s.name, s.variant): s.sound for s in lib()}
        self.assertEqual({k: (c.file, c.at_s) for k, c in cues.items() if c is not None},
                         {("aha_recommend", "expressive"): ("aha.wav", 0.85),
                          ("success", "expressive"): ("success.wav", 0.3),
                          ("failure", "expressive"): ("failure.wav", 0.2),  # revision 2 (2026-11-14)
                          ("boredom", "expressive"): ("boredom.wav", 4.9)})
        self.assertTrue(all(c is None for (_n, v), c in cues.items() if v == "neutral"))  # the assignment
        # (length s, peak): the negative cues are lower, slower and quieter (their V/A targets)
        shape = {"aha.wav": (0.5, 0.5), "success.wav": (0.6, 0.5), "failure.wav": (0.75, 0.4), "boredom.wav": (1.1, 0.3)}
        self.assertEqual(set(sound.SYNTHS), set(shape))
        for name, synth in sound.SYNTHS.items():
            x, rate = read_wav(SOUNDS / name)
            self.assertEqual(rate, sound.RATE)
            self.assertAlmostEqual(len(x) / rate, shape[name][0], delta=1e-3)
            self.assertAlmostEqual(float(np.max(np.abs(x))), shape[name][1], delta=0.01)  # no clipping
            self.assertLess(abs(x[-1]), 1e-3)  # faded out: no click
            self.assertLess(float(np.max(np.abs(x - synth()))), 1e-4)  # the file is what the synthesis makes

    def test_bright_positive_and_dark_negative_cues(self):
        """Energy above 2 kHz (dB of the total): the positive cues are bright, the negative ones dark, and the sigh's
        breath noise is no hiss."""
        def above_2k_db(name: str) -> float:
            x, rate = read_wav(SOUNDS / name)
            spec = np.abs(np.fft.rfft(x)) ** 2
            f = np.fft.rfftfreq(x.size, 1.0 / rate)
            return float(10.0 * np.log10(spec[f > 2000.0].sum() / spec.sum()))

        for name in ("aha.wav", "success.wav"):
            self.assertGreater(above_2k_db(name), -12.0, name)
        for name in ("failure.wav", "boredom.wav"):
            self.assertLess(above_2k_db(name), -40.0, name)

    def test_the_cue_tick(self):
        self.assertEqual(sound.cue_tick(1.0, 0.85, 0.0, 50.0), 93)  # first tick at or after 1.85 s
        self.assertEqual(sound.cue_tick(1.0, 0.85, 100.0, 50.0), 98)
        self.assertEqual(sound.cue_tick(0.0, 0.3, -2000.0, 50.0), 0)  # never before the stream


class TestCueTrigger(unittest.TestCase):
    def test_it_fires_once_in_its_own_thread_and_keeps_the_inner_callback(self):
        played: list = []
        inner: list[int] = []
        rec: dict = {}
        trig = sound.CueTrigger(93, lambda: played.append(threading.current_thread().name) or "ok", rec)
        on_tick = trig.wrap(lambda k, _r: inner.append(k))
        for k in range(150):
            on_tick(k, None)
        self.assertTrue(trig.done.wait(2.0))
        self.assertEqual(played, ["sound-cue"])  # not the executor's thread
        self.assertEqual(len(inner), 150)
        self.assertEqual((rec["tick"], rec["fired_tick"], rec["fired"], rec["ok"]), (93, 93, True, True))
        self.assertGreaterEqual(rec["request_ms"], 0.0)

    def test_a_failing_request_is_recorded_not_raised(self):
        rec: dict = {}

        def boom():
            raise ConnectionError("no route")

        trig = sound.CueTrigger(0, boom, rec)
        trig.on_tick(0)
        self.assertTrue(trig.done.wait(2.0))
        self.assertFalse(rec["ok"])
        self.assertIn("ConnectionError", rec["error"])


class _Resp:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


class TestRobotSpeakerRequests(unittest.TestCase):
    """The requests the daemon's media router expects (reachy_mini/daemon/app/routers/media.py:41-103, 207-262)."""

    def test_status_upload_once_and_play(self):
        sent: list = []

        def opener(req, timeout):
            sent.append((req.get_method(), req.full_url, dict(req.header_items()), req.data, timeout))
            if req.full_url.endswith("/sounds/upload"):
                return _Resp({"status": "ok", "path": "/tmp/reachy_mini_sounds/hw4_aha.wav"})
            if req.full_url.endswith("/status"):
                return _Resp({"available": False, "released": True, "no_media": False})
            return _Resp({"status": "ok"})

        spk = sound.RobotSpeaker("192.0.2.1", 8000, opener=opener)  # TEST-NET address; the opener is a stub
        self.assertFalse(spk.status()["no_media"])
        path = spk.upload(SOUNDS / "aha.wav")
        self.assertEqual(spk.upload(SOUNDS / "aha.wav"), path)  # same content: not sent again
        spk.play(path)
        self.assertEqual([(m, u) for m, u, *_ in sent],
                         [("GET", "http://192.0.2.1:8000/api/media/status"),
                          ("POST", "http://192.0.2.1:8000/api/media/sounds/upload"),
                          ("POST", "http://192.0.2.1:8000/api/media/play_sound")])
        _m, _u, headers, body, timeout = sent[1]
        boundary = headers["Content-type"].split("boundary=")[1]
        self.assertTrue(headers["Content-type"].startswith("multipart/form-data"))
        self.assertIn(b'name="file"; filename="hw4_aha.wav"', body)
        self.assertIn((SOUNDS / "aha.wav").read_bytes(), body)
        self.assertTrue(body.rstrip().endswith(f"--{boundary}--".encode()))
        self.assertGreaterEqual(timeout, 5.0)  # the daemon's GStreamer probe may take up to 5 s
        self.assertEqual(json.loads(sent[2][3]), {"file": "/tmp/reachy_mini_sounds/hw4_aha.wav"})
        self.assertEqual(sent[2][2]["Content-type"], "application/json")

    def test_a_refused_upload_raises(self):
        spk = sound.RobotSpeaker("192.0.2.1", 8000, opener=lambda req, timeout: _Resp({"detail": "invalid"}))
        with self.assertRaises(RuntimeError):
            spk.upload(SOUNDS / "success.wav")


class TestSessionsDefault(unittest.TestCase):
    def test_off_unless_the_gui_main_turns_it_on_and_one_setting_for_all(self):
        from reachy_motion.gui.lab_tabs import LabSessions

        with tempfile.TemporaryDirectory() as d:
            s = LabSessions(lambda e: None, root=Path(d) / "lab")
            self.assertEqual(s.sound.output, "off")  # tests and offline runs never send a sound
            mock_session = s.get("mock")
            robot_session = s.robot("192.0.2.1", 8000)
            self.assertIs(mock_session.sound, s.sound)
            self.assertIs(robot_session.sound, s.sound)
            s.close()


class TestLaptopSoundOnTheMock(unittest.TestCase):
    def test_a_mock_preview_plays_the_cue_on_the_laptop_player(self):
        from reachy_motion.gui.lab import LabSession

        events: list[dict] = []
        played: list[tuple[str, float]] = []
        with tempfile.TemporaryDirectory() as d:
            s = LabSession("mock", Path(d) / "lab", events.append)
            try:
                s.sound = sound.SoundSettings(output="laptop", sounds_dir=SOUNDS)
                s.laptop = sound.LaptopSpeaker(player=lambda p: played.append((Path(p).name, time.monotonic())))
                spec = lib().get("success", "expressive")
                s.preview(spec)
                t0 = time.monotonic()
                while not any(e["kind"] == "preview_finished" for e in events) and time.monotonic() - t0 < 30:
                    time.sleep(0.05)
                fin = [e for e in events if e["kind"] == "preview_finished"][-1]
                self.assertTrue(fin["completed"], fin)
                self.assertEqual([p for p, _ in played], ["success.wav"])
                self.assertTrue(fin["sound"]["ok"] and fin["sound"]["fired"])
                self.assertEqual(fin["sound"]["tick"], sound.cue_tick(0.0, 0.3, 0.0, 50.0))  # no hold in a preview
                s.sound.output = "robot"  # a Mock / MuJoCo run has no robot speaker: nothing plays
                s.preview(lib().get("success", "expressive"))
                n = len(events)
                t0 = time.monotonic()
                while not any(e["kind"] == "preview_finished" for e in events[n:]) and time.monotonic() - t0 < 30:
                    time.sleep(0.05)
                self.assertEqual(len(played), 1)
            finally:
                s.close()


class StubSpeaker:
    """Stands for sound.RobotSpeaker: records the calls (the robot path, offline)."""

    def __init__(self, status: dict | None = None, play_error: Exception | None = None) -> None:
        self.calls: list = []
        self._status = status or {"available": False, "released": True, "no_media": False}
        self._play_error = play_error

    def status(self) -> dict:
        self.calls.append(("status",))
        return dict(self._status)

    def upload(self, path) -> str:
        self.calls.append(("upload", Path(path).name))
        return "/tmp/reachy_mini_sounds/hw4_" + Path(path).name

    def play(self, daemon_path: str) -> dict:
        self.calls.append(("play", daemon_path))
        if self._play_error is not None:
            raise self._play_error
        return {"status": "ok"}


class TestRobotSoundOnTheHarness(unittest.TestCase):
    """The GUI robot session on the real SDK 1.11.0 daemon code (offline harness, data_kind computed): the approved
    R2 trial uploads its sound before the stream and asks the daemon to play it at the cue tick of the stream."""

    def test_the_robot_speaker_path(self):
        from reachy_motion.gui.robot_session import RobotLabSession
        from tests.test_gui_robot import (HOST, PORT, connect_approval, harness_link, live_r0, r0_fixture,
                                          trial_approval, unlocked, wait_idle)
        from tests.test_sdk_offline_connect import R0_AWAKE, TickClock, awake_daemon

        d = awake_daemon()
        made: list = []
        events: list[dict] = []
        speakers: list[StubSpeaker] = []

        def factory(host: str, port: int) -> StubSpeaker:
            self.assertEqual((host, port), (HOST, PORT))
            speakers.append(StubSpeaker())
            return speakers[-1]

        p1, p2 = unlocked()
        with tempfile.TemporaryDirectory() as tmp, p1, p2:
            s = RobotLabSession(Path(tmp) / "lab", events.append, HOST, PORT, link_factory=harness_link(d, made),
                                r0_reader=live_r0(d, R0_AWAKE), clock=TickClock(d), r0_root=Path(tmp) / "r0",
                                speaker_factory=factory)
            try:
                s.sound = sound.SoundSettings(output="robot", sounds_dir=SOUNDS)
                s.connect_robot(connect_approval(r0_fixture(R0_AWAKE)))
                wait_idle(s)
                self.assertEqual(s.robot_state, "at_init")
                self.assertEqual(speakers, [])  # nothing about sound at the connection

                def run(motion: str, variant: str) -> dict:
                    trial = ex.r2_trial(lib().get(motion, variant))
                    s.run_trial(trial, Path(tmp) / "R2", approval=trial_approval(s, trial))
                    wait_idle(s)
                    done = [e for e in events if e["kind"] in ("trial_finished", "refused")][-1]
                    self.assertEqual(done["kind"], "trial_finished", done)
                    self.assertTrue(done["completed"], done)
                    return done

                done = run("success", "expressive")
                spk = speakers[0]
                self.assertEqual(spk.calls, [("status",), ("upload", "success.wav"),
                                             ("play", "/tmp/reachy_mini_sounds/hw4_success.wav")])
                rec = done["sound"]
                self.assertTrue(rec["fired"] and rec["ok"])
                self.assertEqual(rec["fired_tick"], rec["tick"])
                self.assertEqual(rec["tick"], sound.cue_tick(ex.PRE_S, 0.3, 0.0, 50.0))  # after the 1 s hold
                man = json.loads((Path(done["run_dir"]) / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(man["connection"]["sound"]["daemon_path"], "/tmp/reachy_mini_sounds/hw4_success.wav")
                self.assertTrue(man["connection"]["sound"]["fired"])

                run("success", "neutral")  # the Neutral has no sound: nothing more
                self.assertEqual(len(spk.calls), 3)
                s.sound.output = "off"
                run("success", "expressive")
                self.assertEqual(len(spk.calls), 3)

                # a daemon without media: reported at once, the approved motion runs without its sound
                s.sound.output = "robot"
                s._speaker_obj = StubSpeaker(status={"no_media": True})
                n = len(events)
                done = run("aha_recommend", "expressive")
                failed = [e for e in events[n:] if e["kind"] == "sound"]
                self.assertEqual(len(failed), 1)
                self.assertIn("no-media", failed[0]["error"])
                self.assertIsNone(done["sound"])
                self.assertEqual(s._speaker_obj.calls, [("status",)])

                # a failed play request: recorded, the motion still completes
                s._speaker_obj = StubSpeaker(play_error=ConnectionError("timeout"))
                done = run("aha_recommend", "expressive")
                self.assertFalse(done["sound"]["ok"])
                self.assertIn("ConnectionError", done["sound"]["error"])
            finally:
                s.close()


class TestSoundControls(unittest.TestCase):
    """The Motion tab's '효과음' row (offscreen): one shared setting, the cue of the shown motion, the listen button."""

    def test_the_row_drives_the_shared_setting(self):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        from reachy_motion.gui.app import MainWindow
        from reachy_motion.gui.lab_tabs import LabSessions
        from reachy_motion.gui.model import EditorModel

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as d:
            sessions = LabSessions(lambda e: None, root=Path(d) / "lab")
            win = MainWindow(EditorModel(ROOT / "motions"), initial=("aha_recommend", "expressive"), sessions=sessions)
            try:
                self.assertEqual(win.sound_combo.currentData(), "off")  # MainWindow alone: off (main() turns it on)
                self.assertEqual(sessions.sound.sounds_dir, ROOT / "motions" / "sounds")
                self.assertIn("aha.wav @ 0.85 s", win.sound_label.text())
                win.sound_combo.setCurrentIndex(win.sound_combo.findData("robot"))
                win.sound_offset.setValue(120)
                self.assertEqual((sessions.sound.output, sessions.sound.offset_ms), ("robot", 120.0))
                self.assertIn("로봇 스피커", win.sound_label.text())
                played: list[str] = []
                win.laptop = sound.LaptopSpeaker(player=played.append)
                win.on_sound_listen()  # this PC only
                self.assertEqual([Path(p).name for p in played], ["aha.wav"])
                self.assertIsNone(sessions.existing("robot"))  # nothing created, nothing sent
                win.rb_neut.setChecked(True)
                app.processEvents()
                self.assertIn("효과음 없음", win.sound_label.text())
                self.assertFalse(win.sound_listen.isEnabled())
            finally:
                win.close()
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
