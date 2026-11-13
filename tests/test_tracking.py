"""Tracking metrics (reachy_motion.analysis.tracking): synthetic delay / bias / dynamics with known answers, the
run-file loader, and an offline MuJoCo replay (simulated) as a sanity check."""

from __future__ import annotations

import csv
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reachy_motion.analysis import tracking
from reachy_motion.analysis.tracking import channel_metrics, dedupe, load_run, tracking_metrics

DEG = math.pi / 180.0
A = 20.0 * DEG


def minjerk(s: np.ndarray) -> np.ndarray:
    s = np.clip(s, 0.0, 1.0)
    return 10 * s**3 - 15 * s**4 + 6 * s**5


def nod(t: np.ndarray, d: float = 0.5) -> np.ndarray:
    """rest 1 s -> +A in d (one way) -> hold 1 s -> back in d -> hold."""
    return A * (minjerk((t - 1.0) / d) - minjerk((t - (2.0 + d)) / d))


def nod_case(tau: float, bias: float, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    t_cmd = np.arange(0.0, 5.0, 0.02)  # 50 Hz sends
    x_cmd = nod(t_cmd)
    rng = np.random.default_rng(seed)
    t_meas = np.cumsum(rng.uniform(0.015, 0.025, 260))  # jittered arrivals
    t_meas = t_meas[t_meas < 5.0]
    x_meas = np.interp(t_meas - tau, t_cmd, x_cmd) + bias  # the command, late by tau, offset by bias
    return t_cmd, x_cmd, t_meas, x_meas


class TestDelayAndBias(unittest.TestCase):
    def test_known_delay_and_bias_are_recovered(self):
        for tau in (0.025, 0.060, 0.150):
            with self.subTest(tau=tau):
                t_cmd, x_cmd, t_meas, x_meas = nod_case(tau, 1.5 * DEG)
                m = channel_metrics("j", t_cmd, x_cmd, t_meas, x_meas, settle_abs_tol=0.2 * DEG)
                self.assertAlmostEqual(m.lag_s, tau, delta=0.0011)
                self.assertFalse(m.lag_at_bound)
                self.assertAlmostEqual(m.static_bias, 1.5 * DEG, delta=1e-9)
                self.assertLess(m.dynamic_rmse_lag_compensated, 0.05 * DEG)
                self.assertGreater(m.dynamic_rmse, 10 * m.dynamic_rmse_lag_compensated)  # the delay dominates
                self.assertAlmostEqual(m.amplitude_ratio, 1.0, delta=1e-3)
                self.assertAlmostEqual(m.command_p2p, A, delta=1e-9)
                self.assertEqual(len(m.steps), 2)
                for s in m.steps:
                    self.assertAlmostEqual(s.hold_bias, 1.5 * DEG, delta=1e-9)
                    self.assertLess(s.overshoot, 1e-9)
                self.assertEqual(m.unsettled_steps, 0)

    def test_peak_error_includes_bias_and_delay(self):
        t_cmd, x_cmd, t_meas, x_meas = nod_case(0.06, 0.0)
        m = channel_metrics("j", t_cmd, x_cmd, t_meas, x_meas)
        dense = np.linspace(t_meas[0], t_meas[-1], 200001)
        ref = np.max(np.abs(np.interp(dense - 0.06, t_cmd, x_cmd) - np.interp(dense, t_cmd, x_cmd)))
        self.assertAlmostEqual(m.peak_error, ref, delta=0.01 * ref)
        self.assertTrue(1.0 < m.peak_error_t_s < 4.0)

    def test_repeated_arrivals_are_dropped(self):
        t_cmd, x_cmd, t_meas, x_meas = nod_case(0.06, 0.0)
        t_dup = np.insert(t_meas, [10, 50, 90], t_meas[[10, 50, 90]])
        x_dup = np.insert(x_meas, [10, 50, 90], x_meas[[10, 50, 90]])
        m1 = channel_metrics("j", t_cmd, x_cmd, t_meas, x_meas)
        m2 = channel_metrics("j", t_cmd, x_cmd, t_dup, x_dup)
        self.assertEqual(m2.duplicates_removed, 3)
        self.assertEqual(m2.n_measured, m1.n_measured)
        self.assertEqual(m1.lag_s, m2.lag_s)


class TestSecondOrderStep(unittest.TestCase):
    """An underdamped 2nd-order response to an ideal step: overshoot and settling time have reference values."""

    WN, ZETA = 20.0, 0.3

    def response(self, t: np.ndarray) -> np.ndarray:
        tau = np.maximum(t - 1.0, 0.0)
        wd = self.WN * math.sqrt(1 - self.ZETA**2)
        x = 1 - np.exp(-self.ZETA * self.WN * tau) * (np.cos(wd * tau) + self.ZETA / math.sqrt(1 - self.ZETA**2)
                                                         * np.sin(wd * tau))
        return np.where(t >= 1.0, x, 0.0)

    def test_overshoot_and_settling(self):
        t_cmd = np.array([0.0, 0.999999, 1.0, 4.0])
        x_cmd = np.array([0.0, 0.0, 1.0, 1.0])
        t_meas = np.arange(0.0, 4.0 + 1e-9, 0.001)
        m = channel_metrics("step", t_cmd, x_cmd, t_meas, self.response(t_meas), settle_skip_s=1.5)
        expected = math.exp(-math.pi * self.ZETA / math.sqrt(1 - self.ZETA**2))  # 0.3725
        self.assertAlmostEqual(m.overshoot, expected, delta=0.003)
        self.assertEqual(len(m.steps), 1)
        self.assertAlmostEqual(m.steps[0].overshoot_ratio, expected, delta=0.003)
        dense = np.arange(1.0, 4.0, 1e-5)
        outside = np.nonzero(np.abs(self.response(dense) - 1.0) > 0.05)[0]
        t_ref = dense[outside[-1]] - 1.0  # last instant outside the 5 % band
        self.assertAlmostEqual(m.settling_time_s, t_ref, delta=0.006)
        self.assertAlmostEqual(m.amplitude_ratio, 1.0 + expected, delta=0.003)

    def test_a_hold_too_short_to_settle_reports_nan(self):
        t_cmd = np.array([0.0, 0.999999, 1.0, 1.25])
        x_cmd = np.array([0.0, 0.0, 1.0, 1.0])
        t_meas = np.arange(0.0, 1.25 + 1e-9, 0.001)
        m = channel_metrics("step", t_cmd, x_cmd, t_meas, self.response(t_meas), settle_skip_s=0.1)
        self.assertTrue(math.isnan(m.settling_time_s))
        self.assertEqual(m.unsettled_steps, 1)


class TestOtherShapes(unittest.TestCase):
    def test_amplitude_ratio_of_a_scaled_response(self):
        t_cmd, x_cmd, _, _ = nod_case(0.0, 0.0)
        t_meas = np.arange(0.0, 4.98, 0.01)
        m = channel_metrics("j", t_cmd, x_cmd, t_meas, 0.8 * np.interp(t_meas, t_cmd, x_cmd))
        self.assertAlmostEqual(m.amplitude_ratio, 0.8, delta=1e-3)
        self.assertEqual(m.lag_s, 0.0)
        self.assertTrue(m.lag_at_bound)

    def test_no_motion_gives_only_a_bias(self):
        t = np.arange(0.0, 2.0, 0.02)
        m = channel_metrics("j", t, np.full(t.size, 0.1), t + 0.005, np.full(t.size, 0.12))
        self.assertAlmostEqual(m.static_bias, 0.02, delta=1e-12)
        for v in (m.lag_s, m.dynamic_rmse, m.amplitude_ratio, m.overshoot, m.settling_time_s):
            self.assertTrue(math.isnan(v))
        self.assertEqual(m.steps, ())

    def test_several_channels(self):
        t_cmd, x_cmd, t_meas, x_meas = nod_case(0.05, 0.0)
        out = tracking_metrics(t_cmd, np.column_stack([x_cmd, -x_cmd]), t_meas, np.column_stack([x_meas, -x_meas]),
                               ["a", "b"], settle_abs_tols=[0.0, 0.0])
        self.assertEqual(list(out), ["a", "b"])
        self.assertAlmostEqual(out["a"].lag_s, out["b"].lag_s, delta=1e-12)
        with self.assertRaises(ValueError):
            tracking_metrics(t_cmd, x_cmd[:, None], t_meas, x_meas[:, None], ["a", "b"])
        d = out["a"].to_dict()
        self.assertIsInstance(d["steps"], list)
        self.assertEqual(len(d["span_s"]), 2)


class TestHoldRipple(unittest.TestCase):
    """Shaking while the command stands still (2026-11-13): RMS about each settled hold's own straight line."""

    def test_a_steady_follower_and_a_slow_drift_do_not_shake(self):
        t_cmd, x_cmd, t_meas, x_meas = nod_case(0.06, 1.5 * DEG)
        self.assertLess(channel_metrics("j", t_cmd, x_cmd, t_meas, x_meas).hold_ripple, 1e-6)
        drift = x_meas + 0.3 * DEG * t_meas / 5.0  # creeps 0.3 deg over the record: a trend, not shaking
        self.assertLess(channel_metrics("j", t_cmd, x_cmd, t_meas, drift).hold_ripple, 1e-3 * DEG)

    def test_an_oscillation_in_the_holds_is_its_rms(self):
        t_cmd = np.arange(0.0, 5.0, 0.02)
        x_cmd = nod(t_cmd)
        t_meas = np.arange(0.0, 5.0, 0.005)  # 200 Hz: the sine is resolved
        x_meas = np.interp(t_meas, t_cmd, x_cmd) + 0.5 * DEG * np.sin(2 * np.pi * 8.0 * t_meas)
        m = channel_metrics("j", t_cmd, x_cmd, t_meas, x_meas)
        self.assertAlmostEqual(m.hold_ripple, 0.5 * DEG / math.sqrt(2.0), delta=0.03 * DEG)
        self.assertIn("hold_ripple", m.to_dict())


class TestValidation(unittest.TestCase):
    def test_bad_inputs(self):
        t = np.arange(0.0, 1.0, 0.02)
        x = np.zeros(t.size)
        cases = [
            (t[::-1], x, t, x),  # decreasing command time
            (t, x[:-1], t, x),  # length mismatch
            (t[:1], x[:1], t, x),  # one sample
            (t, x, t, np.where(t > 0.5, np.nan, 0.0)),  # non-finite
            (t, x, np.full(t.size, 0.3), x),  # a single distinct arrival time
        ]
        for args in cases:
            with self.assertRaises(ValueError):
                channel_metrics("j", *args)
        for kw in ({"rate_hz": 0.0}, {"lag_resolution_s": -1.0}, {"max_lag_s": math.nan}, {"settle_abs_tol": -0.1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                channel_metrics("j", t, x, t, x, **kw)

    def test_dedupe_keeps_first_or_last(self):
        t, x, n = dedupe([0.0, 0.1, 0.1, 0.2], [1.0, 2.0, 3.0, 4.0], keep="first")
        self.assertEqual((t.tolist(), x.tolist(), n), ([0.0, 0.1, 0.2], [1.0, 2.0, 4.0], 1))
        t, x, n = dedupe([0.0, 0.1, 0.1, 0.2], [1.0, 2.0, 3.0, 4.0], keep="last")
        self.assertEqual((t.tolist(), x.tolist(), n), ([0.0, 0.1, 0.2], [1.0, 3.0, 4.0], 1))
        with self.assertRaises(ValueError):
            dedupe([0.0], [0.0], keep="middle")


def write_rows(path: Path, rows: list[dict[str, float | str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


class TestLoadRun(unittest.TestCase):
    def test_run_files_become_si_channels_with_ik_joints(self):
        from reachy_motion.analysis.goto_replay import ik_joints, new_kinematics
        from reachy_motion.library.pose import Pose6

        kin = new_kinematics()
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            cmd, meas = [], []
            for k in range(30):
                pitch = 5.0 * math.sin(k / 10)
                cmd.append({"k": k, "t_s": 0.02 * k, "kind": "set_target", "x_mm": 0.0, "y_mm": 0.0, "z_mm": 1.0,
                            "roll_deg": 0.0, "pitch_deg": pitch, "yaw_deg": 0.0, "antenna_right_deg": -10.0,
                            "antenna_left_deg": 10.0, "body_yaw_deg": 0.0})
                q = ik_joints(kin, Pose6.from_deg_mm(pitch_deg=pitch, z_mm=1.0).matrix(), 0.0)
                row = {"t_s": 0.02 * k + 0.001, "x_mm": 0.0, "y_mm": 0.0, "z_mm": 1.0, "roll_deg": 0.0,
                       "pitch_deg": pitch, "yaw_deg": 0.0, "antenna_right_deg": -10.0, "antenna_left_deg": 10.0,
                       "body_yaw_deg": 0.0}
                row.update({f"stewart_{i}_deg": q[i] / DEG for i in range(1, 7)})
                meas.append(row)
            write_rows(run / "commands.csv", cmd)
            write_rows(run / "present_simulated.csv", meas)
            data = load_run(run)
            self.assertEqual(data.data_kind, "simulated")
            self.assertEqual(data.channels[:6], ("x", "y", "z", "roll", "pitch", "yaw"))
            self.assertEqual(data.channels[-6:], tracking.STEWART_NAMES)
            self.assertEqual(data.units[2], "m")
            self.assertAlmostEqual(float(data.x_cmd[0, 2]), 0.001)
            self.assertAlmostEqual(float(data.x_cmd[5, 4]), 5.0 * math.sin(0.5) * DEG)
            j = data.channels.index("stewart_3")
            np.testing.assert_allclose(data.x_cmd[:, j], data.x_meas[:, j], atol=1e-9)  # same IK both sides
            self.assertIn("one push interval", data.alignment_note)
            (run / "present_measured.csv").write_text((run / "present_simulated.csv").read_text())
            with self.assertRaises(ValueError):
                load_run(run)  # two present files: ambiguous


class TestOfflineMuJoCo(unittest.TestCase):
    """Sanity check on MuJoCo dynamics (simulated): a delayed, slightly sagging follower of a pitch nod."""

    def test_pitch_nod_in_the_offline_replay(self):
        try:
            from reachy_motion.sim_video import SimReplay
            import mujoco  # noqa: F401
        except ImportError as exc:  # pragma: no cover - mujoco is in the venv
            self.skipTest(f"MuJoCo unavailable: {exc}")
        from reachy_motion.library.pose import Pose6
        from reachy_motion.library.spec import Easing, HeadKey, MotionSpec, Principle, PrincipleUse
        from reachy_motion.safety.checker import analyze_timeline, prepare

        spec = MotionSpec(name="success", variant="expressive", intent="test", valence=0.0, arousal=0.0,
                          principles=(PrincipleUse(Principle.TIMING, "test"),),
                          head=(HeadKey(1.0, Pose6(), Easing.MIN_JERK, 0.0, "rest"),
                                HeadKey(0.6, Pose6.from_deg_mm(pitch_deg=10), Easing.MIN_JERK, 1.0, "up"),
                                HeadKey(0.6, Pose6(), Easing.MIN_JERK, 1.5, "down")), draft=False)
        prep = prepare(spec)
        self.assertTrue(prep.runnable)
        tl = prep.timeline
        joints = analyze_timeline(tl).joints
        sim = SimReplay("empty")
        sim.start(joints[0], tl.antennas[0], 1.0)
        measured = []
        for k in range(len(tl.t)):
            sim.command(joints[k], tl.antennas[k])
            sim.tick()
            measured.append(sim.joints()[1:7].copy())
        t_meas = (np.arange(len(tl.t)) + 1) * 0.02  # state after each 20 ms control step (sim time)
        out = tracking_metrics(tl.t, joints[:, 1:7], t_meas, np.array(measured), tracking.STEWART_NAMES,
                               settle_abs_tols=[0.2 * DEG] * 6)
        big = [n for n, m in out.items() if m.command_p2p >= 4.0 * DEG]  # s1, s3, s4, s6 move 4.5-7 deg
        self.assertGreaterEqual(len(big), 4)
        for name, m in out.items():
            with self.subTest(joint=name):
                self.assertLess(m.dynamic_rmse_lag_compensated, m.dynamic_rmse)
                self.assertAlmostEqual(m.amplitude_ratio, 1.0, delta=0.15)
                self.assertLess(m.overshoot, 1.0 * DEG)
                self.assertLess(abs(m.static_bias), 0.5 * DEG)
                if name in big:  # a delay explains the large joints' motion: a meaningful lag
                    self.assertTrue(0.1 < m.lag_s < 0.3, m.lag_s)
                    self.assertFalse(m.lag_at_bound)
                    self.assertGreater(m.lag_fit_r2, 0.9)
        small = [m.lag_fit_r2 for n, m in out.items() if n not in big]
        self.assertTrue(all(r < min(out[n].lag_fit_r2 for n in big) for r in small))  # r2 flags the poor fits


if __name__ == "__main__":
    unittest.main()
