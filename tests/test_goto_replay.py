"""Offline replay of the goto_target pipeline (SDK classes, no daemon)."""

import ast
import inspect
import textwrap
import unittest
from fractions import Fraction

import numpy as np
from reachy_mini.utils.interpolation import InterpolationTechnique as IT

from reachy_motion.analysis.goto_replay import (
    JOINT_NAMES,
    GotoCase,
    HeadTarget,
    control_sampling,
    eval_times,
    pipeline_lag,
    ik_joints,
    ik_sensitivity,
    ik_table,
    new_kinematics,
    replay_goto,
)


class TestEvalSchedule(unittest.TestCase):
    def test_eval_times_excludes_duration(self):
        """Our model of the schedule; the SDK loop itself is pinned in TestSdkSourcePins."""
        t = eval_times(1.0, 100.0)
        self.assertEqual(len(t), 100)
        self.assertEqual(t[0], 0.0)
        self.assertTrue(np.all(t < 1.0))
        self.assertAlmostEqual(t[-1], 0.99)
        self.assertTrue(np.allclose(np.diff(t), 0.01))


class TestKinematics(unittest.TestCase):
    def test_neutral_pose_ik_is_symmetric(self):
        q = np.rad2deg(ik_joints(new_kinematics(), HeadTarget().matrix(), 0.0))
        self.assertEqual(q.shape, (7,))
        self.assertAlmostEqual(q[0], 0.0, places=6)  # body yaw
        stewart = q[1:]
        self.assertTrue(np.allclose(np.abs(stewart), np.abs(stewart[0]), atol=1e-2))
        self.assertTrue(np.all(np.sign(stewart) == np.array([1, -1, 1, -1, 1, -1])))

    def test_ik_table_warm_roundtrip_is_accurate(self):
        poses = {
            "neutral": HeadTarget(),
            "pitch20": HeadTarget(pitch_deg=20),
            "yaw60": HeadTarget(yaw_deg=60),
            "z10": HeadTarget(z_mm=10),
        }
        for row in ik_table(poses):
            with self.subTest(pose=row["pose"]):
                self.assertTrue(row["ik_ok"])
                self.assertLess(row["fk_warm_pos_err_mm"], 0.5)
                self.assertLess(row["fk_warm_ang_err_deg"], 0.1)

    def test_warm_fk_roundtrip_all_probe_poses(self):
        """SDK_ANALYSIS 4.4: all 31 probe poses within 0.034 mm / 0.025 deg (after 20 settle iterations)."""
        from reachy_motion.cli import ik_probe_poses

        rows = ik_table(ik_probe_poses())
        self.assertEqual(len(rows), 31)
        for row in rows:
            with self.subTest(pose=row["pose"]):
                self.assertTrue(row["ik_ok"])
                self.assertLess(row["fk_warm_pos_err_mm"], 0.05)
                self.assertLess(row["fk_warm_ang_err_deg"], 0.03)

    def test_cartoon_yaw_overshoot_past_180_makes_body_target_jump(self):
        """Documents an SDK hazard: CARTOON 0->170 deg yaw extrapolates past 180 deg, psi wraps and the
        automatic-body-yaw clip flips sides, so the body target jumps ~229 deg between two 100 Hz samples
        with no NaN (the daemon would forward it). MIN_JERK on the same move does not."""
        def max_body_step(method):
            move = GotoCase(target=HeadTarget(yaw_deg=170), duration=1.0, method=method).build_move()
            kin = new_kinematics()
            q = []
            for t in np.arange(0.0, 1.0, 0.01):
                head, _ant, body = move.evaluate(float(t))
                q.append(ik_joints(kin, head, float(body)))
            q = np.rad2deg(np.array(q))
            self.assertFalse(np.isnan(q).any())
            return float(np.max(np.abs(np.diff(q[:, 0]))))

        self.assertGreater(max_body_step(IT.CARTOON), 200.0)
        self.assertLess(max_body_step(IT.MIN_JERK), 5.0)

    def test_cold_fk_can_land_on_another_branch(self):
        """Documents SDK behaviour: FK is a stateful Newton solve (see fk_roundtrip)."""
        row = ik_table({"yaw60": HeadTarget(yaw_deg=60)})[0]
        self.assertGreater(row["fk_cold_ang_err_deg"], 10.0)
        self.assertLess(row["fk_warm_ang_err_deg"], 0.1)

    def test_rotation_error_is_not_fooled_by_scaled_matrices(self):
        """SDK trace-based angle reads a 1 deg error on a det-1.0005 matrix as 0 (documented quirk)."""
        from reachy_mini.utils.interpolation import delta_angle_between_mat_rot
        from reachy_mini.utils.rotation import Rotation as R

        from reachy_motion.analysis.goto_replay import rotation_error_deg

        scaled = R.from_euler("xyz", [0, 1.0, 0], degrees=True).as_matrix() * 1.00017
        self.assertAlmostEqual(float(np.rad2deg(delta_angle_between_mat_rot(scaled, np.eye(3)))), 0.0, places=6)
        self.assertAlmostEqual(rotation_error_deg(scaled, np.eye(3)), 1.0, places=6)

    def test_sensitivity_shape(self):
        jac = ik_sensitivity()
        self.assertEqual(jac.shape, (len(JOINT_NAMES), 6))
        self.assertTrue(np.all(np.isfinite(jac)))


class TestReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = GotoCase(target=HeadTarget(pitch_deg=20.0), duration=1.0, method=IT.MIN_JERK)
        cls.r = replay_goto(cls.case)
        kin = new_kinematics()
        cls.q_start = ik_joints(kin, cls.case.start.matrix(), 0.0)
        cls.q_goal = ik_joints(kin, cls.case.target.matrix(), 0.0)

    def test_reference_runs_from_start_to_goal(self):
        self.assertEqual(self.r.ik_failures, 0)
        self.assertTrue(np.allclose(self.r.joints_dense[0], self.q_start, atol=1e-9))
        self.assertTrue(np.allclose(self.r.joints_dense[-1], self.q_goal, atol=1e-9))

    def test_linear_goto_ends_short_of_goal(self):
        r = replay_goto(GotoCase(target=HeadTarget(pitch_deg=20.0), duration=0.5, method=IT.LINEAR))
        final = r.joints_written[-1]
        self.assertTrue(np.allclose(final, r.joints_eval[-1]))
        self.assertGreater(np.max(np.abs(final - self.q_goal)), np.deg2rad(0.05))

    def test_control_phase_validated(self):
        with self.assertRaises(ValueError):
            replay_goto(self.case, control_phase=0.02)
        with self.assertRaises(ValueError):
            replay_goto(self.case, write_delay_ticks=2)


def exact_eval_index(duration: Fraction, phase: Fraction, n_ticks: int, eval_rate: int = 100,
                     control_rate: int = 50) -> list[int]:
    """Independent event model in exact rationals: latest evaluation at or before each tick (-1: none)."""
    evals = [Fraction(k, eval_rate) for k in range(int(duration * eval_rate) + 2) if Fraction(k, eval_rate) < duration]
    ticks = [phase + Fraction(n, control_rate) for n in range(n_ticks)]
    return [max((i for i, te in enumerate(evals) if te <= tk), default=-1) for tk in ticks]


class TestControlSamplingAgainstExactModel(unittest.TestCase):
    """control_sampling vs an exact-rational event model (not its own searchsorted formula)."""

    def test_every_phase_and_both_pipelines(self):
        for duration in (Fraction(1, 5), Fraction(3, 10), Fraction(1, 1)):
            t_eval = eval_times(float(duration))
            joints_eval = np.repeat(np.arange(len(t_eval), dtype=float)[:, None], 7, axis=1)  # value = index
            for k in range(40):  # 0 ... 19.5 ms in 0.5 ms steps, including ticks that coincide with evaluations
                phase = Fraction(k, 2000)
                for delay in (0, 1):
                    t_ctrl, written = control_sampling(t_eval, joints_eval, float(duration),
                                                       control_phase=float(phase), write_delay_ticks=delay)
                    exact = exact_eval_index(duration, phase, len(t_ctrl))
                    held = [max(i, 0) for i in exact]  # before t0 the target is the start pose (index 0)
                    expected = held if delay == 0 else [0] + held[:-1]
                    with self.subTest(D=float(duration), phase_ms=float(phase) * 1000, delay=delay):
                        np.testing.assert_array_equal(written[:, 0], np.array(expected, dtype=float))

    def test_zoh_before_first_tick_is_the_pre_move_goal(self):
        case = GotoCase(target=HeadTarget(pitch_deg=20.0), duration=0.3, method=IT.MIN_JERK)
        r = replay_goto(case, control_phase=0.015, write_delay_ticks=0)
        self.assertTrue(np.allclose(r.joints_written[0], r.joints_eval[1]))  # tick at 15 ms holds the 10 ms sample
        before = r.written_zoh(np.array([0.0, 0.005, 0.0149]))
        self.assertTrue(np.allclose(before, r.joints_eval[0]))
        self.assertTrue(np.allclose(r.written_zoh(np.array([0.015]))[0], r.joints_eval[1]))


class TestPipelineLag(unittest.TestCase):
    """SDK_ANALYSIS 5.2: modelled command-path lag = 30 ms (robot) / 10 ms (MuJoCo) + (phase mod 10 ms)."""

    def test_lag_sawtooth(self):
        for method in (IT.LINEAR, IT.MIN_JERK, IT.CARTOON):
            base = replay_goto(GotoCase(target=HeadTarget(pitch_deg=20.0), duration=1.0, method=method))
            j = int(np.argmax(np.ptp(base.joints_dense[:, 1:], axis=0))) + 1
            for phase_ms in (0.0, 3.5, 9.5, 10.0, 17.5):
                for delay, offset_ms in ((1, 30.0), (0, 10.0)):
                    with self.subTest(method=method.value, phase_ms=phase_ms, delay=delay):
                        lag = pipeline_lag(base, j, phase_ms / 1000, delay)
                        self.assertAlmostEqual(lag * 1000, offset_ms + phase_ms % 10.0, places=6)


class TestSdkSourcePins(unittest.TestCase):
    """Pin the SDK 1.11.0 code paths the replay model encodes; an SDK change must fail here."""

    @staticmethod
    def _tree(func) -> ast.AST:
        return ast.parse(textwrap.dedent(inspect.getsource(func)))

    @staticmethod
    def _attr_calls(tree: ast.AST) -> list[ast.Call]:
        return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]

    def test_play_move_never_commands_t_equal_duration(self):
        from reachy_mini.daemon.backend.abstract import Backend

        tree = self._tree(Backend.play_move)
        loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
        self.assertEqual(len(loops), 1)
        loop = loops[0]
        self.assertEqual(ast.unparse(loop.test), "time.time() - t0 < move.duration")

        def inside(node: ast.AST) -> bool:
            return loop.lineno <= node.lineno <= loop.end_lineno

        calls = self._attr_calls(tree)
        setters = [c for c in calls if c.func.attr.startswith("set_target")]
        self.assertTrue(setters)
        self.assertTrue(all(inside(c) for c in setters), "a target is written outside the playback loop")
        for c in calls:
            if c.func.attr == "evaluate" and not inside(c):  # only the optional initial goto, before the loop
                self.assertLess(c.lineno, loop.lineno)
                self.assertEqual(ast.unparse(c.args[0]), "0.0")

    def test_robot_tick_writes_goals_before_ik(self):
        from reachy_mini.daemon.backend.robot.backend import RobotBackend

        first = {}
        for c in self._attr_calls(self._tree(RobotBackend._update)):
            first.setdefault(c.func.attr, c.lineno)
        ik = first["update_target_head_joints_from_ik"]
        self.assertLess(first["set_stewart_platform_position"], ik)  # head goal = previous tick's IK
        self.assertLess(first["set_body_rotation"], ik)
        self.assertLess(first["set_antennas_positions"], ik)  # antennas need no IK: one tick ahead of head

    def test_mujoco_tick_runs_ik_before_ctrl(self):
        from reachy_mini.daemon.backend.mujoco.backend import MujocoBackend

        src = inspect.getsource(MujocoBackend.run)
        self.assertLess(src.index("self.update_target_head_joints_from_ik("),
                        src.index("self.data.ctrl[:7] = self.target_head_joint_positions"))


if __name__ == "__main__":
    unittest.main()
