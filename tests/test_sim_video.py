"""Offline MuJoCo replay and review-video helpers (simulated; no daemon, no robot)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from reachy_motion import sim_video as sv
from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics
from reachy_motion.library.pose import INIT_ANTENNAS, Pose6
from reachy_motion.library.spec import AntennaKey, Easing, HeadKey, MotionSpec, Principle, PrincipleUse


def spec(head, antennas=(), variant="expressive"):
    return MotionSpec(name="boredom", variant=variant, intent="t", valence=0.0, arousal=0.0,
                      principles=(PrincipleUse(Principle.TIMING, "t"),), head=tuple(head), antennas=tuple(antennas))


TURN = spec([HeadKey(0.6, Pose6.from_deg_mm(yaw_deg=15.0), Easing.MIN_JERK, 0.3, "turn"),
             HeadKey(0.6, Pose6(), Easing.MIN_JERK, 0.0, "back")],
            [AntennaKey(0.5, (-0.6, 0.6), Easing.MIN_JERK, 0.4, "droop"),
             AntennaKey(0.5, INIT_ANTENNAS, Easing.MIN_JERK, 0.1, "recover")])


class TestSimReplay(unittest.TestCase):
    def test_model_and_rates_match_the_sdk_backend(self):
        sim = sv.SimReplay()
        self.assertAlmostEqual(sim.model.opt.timestep, 0.002)  # backend.py:90
        self.assertEqual(sv.CONTROL_RATE_HZ, 50.0)  # backend.py:91

    def test_antenna_command_uses_the_sdk_sign_mapping(self):
        sim = sv.SimReplay()
        q = ik_joints(new_kinematics(), np.eye(4), 0.0)
        sim.start(q, (-0.5, 0.8))
        np.testing.assert_allclose(sim.data.ctrl[-2:], (0.5, -0.8))  # ctrl[-2:] = -antennas (backend.py:260)
        np.testing.assert_allclose(sim.antennas(), (-0.5, 0.8), atol=0.01)
        self.assertLess(np.degrees(sv.rotation_distance(sim.head_pose(), np.eye(4))), 1.0)

    def test_non_finite_joints_keep_the_previous_command(self):
        sim = sv.SimReplay()
        sim.command(np.arange(7) * 0.01, (0.0, 0.0))
        sim.command(np.full(7, np.nan), (0.1, 0.2))
        np.testing.assert_allclose(sim.data.ctrl[:7], np.arange(7) * 0.01)
        np.testing.assert_allclose(sim.data.ctrl[-2:], (-0.1, -0.2))

    def test_replay_follows_the_plan_and_returns_to_rest(self):
        # MuJoCo settles slowly (friction-dominated): 0.65 deg left after 0.8 s at rest, 0.03 deg after 3 s.
        r = sv.replay(TURN, lead_s=0.2, tail_s=3.0, fps=25)
        self.assertEqual(r.data_kind, "simulated")
        self.assertEqual(r.frames, [])  # no rendering requested
        self.assertEqual(len(r.frame_info), -(-round(r.total_s * 50) // 2))  # a frame every 2nd 50 Hz tick
        self.assertLess(r.end_error["head_angle_deg"], 0.2)
        self.assertLess(r.end_error["antenna_deg"], 0.5)
        self.assertLess(r.max_command_gap_deg, 10.0)  # the sim head lags the command (about 6 deg here)
        phases = [f["phase"] for f in r.frame_info]
        self.assertEqual((phases[0], phases[-1]), ("start", "end"))
        self.assertIn("turn", {f["head_key"] for f in r.frame_info})
        self.assertIn("droop", {f["antenna_key"] for f in r.frame_info})

    def test_common_length_for_a_pair(self):
        r = sv.replay(TURN, lead_s=0.5, total_s=4.0, fps=10)
        self.assertAlmostEqual(r.total_s, 4.0)
        self.assertEqual(len(r.frame_info), 40)

    def test_motion_outside_the_policy_is_not_replayed(self):
        bad = spec([HeadKey(1.0, Pose6.from_deg_mm(pitch_deg=60.0), Easing.MIN_JERK, 0.0, "too-far"),
                    HeadKey(1.0, Pose6(), Easing.MIN_JERK, 0.0, "back")])
        with self.assertRaises(ValueError):
            sv.replay(bad)

    def test_fps_must_divide_the_control_rate(self):
        with self.assertRaises(ValueError):
            sv.replay(TURN, fps=30)

    def test_offscreen_render(self):
        import mujoco

        sim = sv.SimReplay()
        try:
            mujoco.Renderer(sim.model, height=48, width=64).close()
        except Exception as e:  # environment without an OpenGL context
            self.skipTest(f"no offscreen OpenGL here: {e}")
        r = sv.replay(TURN, lead_s=0.0, tail_s=0.0, fps=10, render_size=(64, 48))
        self.assertEqual(len(r.frames), len(r.frame_info))
        self.assertEqual(r.frames[0].shape, (48, 64, 3))
        self.assertGreater(int(r.frames[0].std()), 0)  # not a blank image


class TestVideoCommand(unittest.TestCase):
    def test_video_command_writes_webp_index_and_manifest(self):
        import contextlib
        import io
        import json

        import mujoco

        from reachy_motion.cli import main
        from reachy_motion.library.io import save_spec_file

        try:
            mujoco.Renderer(sv.SimReplay().model, height=48, width=64).close()
        except Exception as e:  # environment without an OpenGL context
            self.skipTest(f"no offscreen OpenGL here: {e}")
        neutral = spec([HeadKey(0.6, Pose6.from_deg_mm(yaw_deg=15.0), Easing.LINEAR, 0.3, "turn"),
                        HeadKey(0.6, Pose6(), Easing.LINEAR, 0.0, "back")], variant="neutral")
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "boredom_test"
            folder.mkdir()
            save_spec_file(TURN, folder)
            save_spec_file(neutral, folder)
            fmt = "both" if sv.mp4_available() else "webp"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["video", "--dir", str(folder), "--size", "64x48", "--fps", "10", "--lead", "0",
                           "--tail", "0.2", "--format", fmt, "--out", str(Path(d) / "out")])
            self.assertEqual(rc, 0)
            run = next((Path(d) / "out").iterdir())
            self.assertTrue((run / "boredom_test.webp").is_file())
            page = (run / "index.html").read_text(encoding="utf-8")
            if fmt == "both":
                self.assertTrue((run / "boredom_test.mp4").is_file())
                self.assertIn('<video src="boredom_test.mp4"', page)  # MP4 is the primary file when present
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["data_kind"], "simulated")
            self.assertEqual(manifest["parameters"]["formats"], ["mp4", "webp"] if fmt == "both" else ["webp"])
            self.assertEqual([m["key"] for m in manifest["videos"][0]["motions"]],
                             ["boredom:expressive", "boredom:neutral"])
            self.assertEqual(manifest["skipped"], [])


class TestVideoFiles(unittest.TestCase):
    def test_compose_save_and_index(self):
        from PIL import Image

        rgb = np.zeros((48, 64, 3), np.uint8)
        frames = [sv.compose_frame([(rgb, {"motion_t": t, "head_key": "turn", "antenna_key": "droop"}, "expressive",
                                     2.0), (rgb, {"motion_t": t, "head_key": "-", "antenna_key": "-"}, "neutral", 2.0)],
                                   "title") for t in (0.0, 1.0, 2.0)]
        self.assertEqual(frames[0].size, (64 * 2 + 4, 52 + 48 + 50))
        with tempfile.TemporaryDirectory() as d:
            p = sv.save_webp(frames, Path(d) / "x.webp", fps=25)
            with Image.open(p) as im:
                self.assertEqual(im.n_frames, 3)
            motion = {"key": "boredom:expressive", "duration_s": 2.0, "expected": {"valence": -0.3, "arousal": -0.4},
                      "end_error": {"head_angle_deg": 0.1, "head_trans_mm": 0.1}, "max_command_gap_deg": 1.0,
                      "intent": "bored <test>"}
            index = sv.write_index(Path(d), [{"label": "boredom_scan", "file": "x.webp", "title": "t",
                                               "motions": [motion]}], {"generated_utc": "now"})
            page = index.read_text(encoding="utf-8")
            self.assertIn('src="x.webp"', page)
            self.assertIn("bored &lt;test&gt;", page)
            self.assertIn("not the robot", page)
            self.assertTrue((Path(d) / "manifest.json").is_file())

    def test_mp4_roundtrip(self):
        if not sv.mp4_available():
            self.skipTest("PyAV with libx264 not installed")
        import av
        from PIL import Image

        frames = [Image.new("RGB", (65, 49), (10 * k, 80, 160)) for k in range(5)]  # odd size -> cropped
        with tempfile.TemporaryDirectory() as d:
            p = sv.save_mp4(iter(frames), Path(d) / "x.mp4", fps=25)
            with av.open(str(p)) as c:
                s = c.streams.video[0]
                self.assertEqual(s.codec_context.name, "h264")
                self.assertEqual((s.codec_context.width, s.codec_context.height), (64, 48))
                self.assertEqual(s.average_rate, 25)
                self.assertEqual(sum(1 for _ in c.decode(video=0)), 5)
            with self.assertRaises(ValueError):
                sv.save_mp4(iter(()), Path(d) / "empty.mp4", fps=25)

    def test_render_pair_rejects_unknown_formats(self):
        with self.assertRaises(ValueError):
            sv.render_pair([TURN], "x", Path("unused"), formats=("avi",))
        with self.assertRaises(ValueError):
            sv.render_pair([TURN], "x", Path("unused"), formats=())


if __name__ == "__main__":
    unittest.main()
