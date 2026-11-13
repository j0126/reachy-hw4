"""The sim interlock must refuse anything that is not our local MuJoCo daemon."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reachy_motion.backends.sim_daemon import (
    SIM_HOST,
    SIM_ROBOT_NAME,
    SimDaemon,
    assert_local_sim,
    assert_motion_client_is_local_sim,
)

SD = "reachy_motion.backends.sim_daemon"

GOOD = {
    "robot_name": SIM_ROBOT_NAME,
    "state": "running",
    "simulation_enabled": True,
    "mockup_sim_enabled": False,
    "version": "1.11.0",
}


class TestAssertLocalSim(unittest.TestCase):
    def test_accepts_our_sim(self):
        status = dict(GOOD)
        self.assertIs(assert_local_sim(status), status)

    def test_refuses_no_answer(self):
        with self.assertRaises(RuntimeError):
            assert_local_sim(None)

    def test_refuses_real_robot_status(self):
        robot = dict(GOOD, simulation_enabled=False, robot_name="reachy_mini")
        with self.assertRaises(RuntimeError):
            assert_local_sim(robot)

    def test_refuses_mockup_status(self):
        # what a --mockup-sim daemon reports (SDK daemon/daemon.py:363-366): like the real robot
        with self.assertRaises(RuntimeError):
            assert_local_sim(dict(GOOD, simulation_enabled=False, mockup_sim_enabled=True))

    def test_refuses_not_started_status(self):
        with self.assertRaises(RuntimeError):
            assert_local_sim(dict(GOOD, simulation_enabled=None))

    def test_refuses_other_name(self):
        with self.assertRaises(RuntimeError):
            assert_local_sim(dict(GOOD, robot_name="reachy_mini"))

    def test_refuses_other_version(self):
        with self.assertRaises(RuntimeError):
            assert_local_sim(dict(GOOD, version="1.12.0"))


class FakeStatus:
    def __init__(self, **fields):
        self.fields = fields

    def model_dump(self, mode: str = "python") -> dict:
        return dict(self.fields)


class FakeClient:
    def __init__(self, host: str, status: FakeStatus):
        self.host = host
        self.status = status
        self.disconnect = mock.Mock()

    def get_status(self, timeout: float = 5.0) -> FakeStatus:
        return self.status


class FakeMini:
    def __init__(self, client: FakeClient):
        self.client = client
        self.goto_target = mock.Mock()


class TestMotionSocketInterlock(unittest.TestCase):
    """The check must run on the socket that carries motion, not only on the REST endpoint."""

    def test_accepts_local_sim_on_the_socket(self):
        mini = FakeMini(FakeClient("localhost", FakeStatus(**GOOD)))
        self.assertEqual(assert_motion_client_is_local_sim(mini)["robot_name"], SIM_ROBOT_NAME)

    def test_refuses_socket_to_a_non_sim_daemon(self):
        mini = FakeMini(FakeClient("localhost", FakeStatus(**dict(GOOD, simulation_enabled=False))))
        with self.assertRaises(RuntimeError):
            assert_motion_client_is_local_sim(mini)

    def test_refuses_non_loopback_host(self):
        mini = FakeMini(FakeClient("reachy-mini.local", FakeStatus(**GOOD)))
        with self.assertRaises(RuntimeError):
            assert_motion_client_is_local_sim(mini)

    def test_sim_smoke_refuses_before_any_motion(self):
        from reachy_motion.analysis import sim_smoke

        mini = FakeMini(FakeClient("localhost", FakeStatus(**dict(GOOD, simulation_enabled=False))))
        fake_daemon = mock.MagicMock()
        fake_daemon.return_value.__enter__.return_value = fake_daemon
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sim_smoke, "SimDaemon", fake_daemon), \
                mock.patch.object(sim_smoke, "get_status", return_value=dict(GOOD)), \
                mock.patch.object(sim_smoke, "port_answers", return_value=False), \
                mock.patch("reachy_mini.ReachyMini", return_value=mini):
            with self.assertRaises(RuntimeError):
                sim_smoke.run_sim_smoke(Path(tmp))
        mini.goto_target.assert_not_called()
        mini.client.disconnect.assert_called_once()

    def test_sim_smoke_refuses_when_ipv6_loopback_is_taken(self):
        from reachy_motion.analysis import sim_smoke

        fake_daemon = mock.MagicMock()
        fake_daemon.return_value.__enter__.return_value = fake_daemon
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sim_smoke, "SimDaemon", fake_daemon), \
                mock.patch.object(sim_smoke, "get_status", return_value=dict(GOOD)), \
                mock.patch.object(sim_smoke, "port_answers", return_value=True), \
                mock.patch("reachy_mini.ReachyMini") as ctor:
            with self.assertRaises(RuntimeError):
                sim_smoke.run_sim_smoke(Path(tmp))
        ctor.assert_not_called()  # the constructor itself sends a command, so it must not run


@mock.patch(f"{SD}.daemon_executable", return_value=Path("reachy-mini-daemon"))
class TestSimDaemonNeverOrphansTheChild(unittest.TestCase):
    """start() must stop the spawned daemon on every failure path (no process is really created)."""

    def _assert_child_stopped(self, d: SimDaemon, popen: mock.Mock) -> None:
        self.assertIsNone(d.proc)
        child = popen.return_value
        self.assertTrue(child.send_signal.called or child.terminate.called or child.kill.called)

    @mock.patch(f"{SD}.port_answers", return_value=False)
    @mock.patch(f"{SD}.subprocess.Popen")
    def test_interlock_refusal_stops_child(self, popen, _busy, _exe):
        popen.return_value.poll.return_value = None  # child alive
        d = SimDaemon(port=8123)
        with mock.patch(f"{SD}.get_status", return_value=dict(GOOD, simulation_enabled=False)):
            with self.assertRaises(RuntimeError):
                d.start(timeout=1.0)
        self._assert_child_stopped(d, popen)

    @mock.patch(f"{SD}.port_answers", return_value=False)
    @mock.patch(f"{SD}.subprocess.Popen")
    def test_ctrl_c_while_waiting_stops_child(self, popen, _busy, _exe):
        popen.return_value.poll.return_value = None
        d = SimDaemon(port=8123)
        with mock.patch(f"{SD}.get_status", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                d.start(timeout=1.0)
        self._assert_child_stopped(d, popen)

    @mock.patch(f"{SD}.subprocess.Popen")
    def test_refuses_when_ipv6_loopback_is_taken(self, popen, _exe):
        with mock.patch(f"{SD}.port_answers", side_effect=lambda host, port, timeout=0.5: host == "::1"):
            with self.assertRaises(RuntimeError):
                SimDaemon(port=8123).start(timeout=1.0)
        popen.assert_not_called()


class TestCommandLine(unittest.TestCase):
    def test_loopback_sim_only(self):
        cmd = SimDaemon(port=8123).command()
        self.assertIn("--sim", cmd)
        self.assertIn("--headless", cmd)
        self.assertNotIn("--wireless-version", cmd)
        self.assertEqual(cmd[cmd.index("--fastapi-host") + 1], SIM_HOST)
        self.assertEqual(cmd[cmd.index("--fastapi-port") + 1], "8123")
        self.assertEqual(cmd[cmd.index("--robot-name") + 1], SIM_ROBOT_NAME)
        self.assertIn("--no-wake-up-on-start", cmd)


@mock.patch(f"{SD}.daemon_executable", return_value=Path("reachy-mini-daemon"))
class TestHeadlessOption(unittest.TestCase):
    """``headless`` only toggles --headless (``--headless`` is store_true, default False: main.py:84, 715-720)."""

    def test_headless_is_the_default(self, _exe):
        d = SimDaemon(port=8123)
        self.assertTrue(d.headless)
        self.assertEqual(d.command().count("--headless"), 1)
        self.assertIn("--headless", SimDaemon(port=8123, headless=True).command())

    def test_viewer_mode_only_drops_headless(self, _exe):
        # without --headless the daemon opens the MuJoCo viewer (daemon/backend/mujoco/backend.py:170-183);
        # everything else - sim, loopback, robot name, no wake-up - stays exactly the same
        headless = SimDaemon(port=8123, headless=True).command()
        viewer = SimDaemon(port=8123, headless=False).command()
        self.assertNotIn("--headless", viewer)
        self.assertEqual([a for a in headless if a != "--headless"], viewer)
        self.assertIn("--sim", viewer)
        self.assertEqual(viewer[viewer.index("--fastapi-host") + 1], SIM_HOST)
        self.assertEqual(viewer[viewer.index("--robot-name") + 1], SIM_ROBOT_NAME)
        self.assertIn("--no-wake-up-on-start", viewer)

    def test_the_macos_viewer_runs_under_mjpython(self, _exe):
        """macOS: mujoco.viewer.launch_passive needs mjpython (2026-11-14, teammates on a Mac); without it, headless."""
        from unittest import mock

        d = SimDaemon(port=8123, headless=False)
        with mock.patch("reachy_motion.backends.sim_daemon.Path.exists", return_value=False):
            self.assertIn("--headless", d.command(platform="darwin"))  # no mjpython: no viewer, still a daemon
        with mock.patch("reachy_motion.backends.sim_daemon.Path.exists", return_value=True):
            mac = d.command(platform="darwin")
        self.assertTrue(Path(mac[0]).name.startswith("mjpython"), mac[:3])
        self.assertEqual(mac[1:3], ["-m", "reachy_mini.daemon.app.main"])
        self.assertNotIn("--headless", mac)
        self.assertEqual(mac[3:], d.command()[1:])  # the same daemon arguments as on Windows / Linux


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class TestReadOnlyRestHelpers(unittest.TestCase):
    """GET helpers only ever address 127.0.0.1 and send no body (urlopen is faked: no socket is opened)."""

    def _get(self, func, body: bytes = b"", exc: BaseException | None = None):
        calls = []

        def fake_urlopen(url, timeout=None, data=None):
            calls.append((url, data))
            if exc is not None:
                raise exc
            return FakeResponse(body)

        with mock.patch(f"{SD}.urllib.request.urlopen", fake_urlopen):
            result = func(8123)
        return result, calls

    def test_kinematics_info(self):
        from reachy_motion.backends.sim_daemon import get_kinematics_info

        body = b'{"info": {"engine": "AnalyticalKinematics", "collision check": false}}'
        result, calls = self._get(get_kinematics_info, body)
        self.assertEqual(result, {"info": {"engine": "AnalyticalKinematics", "collision check": False}})
        self.assertEqual(calls, [(f"http://{SIM_HOST}:8123/api/kinematics/info", None)])

    def test_status_uses_the_same_read_only_path(self):
        from reachy_motion.backends.sim_daemon import get_status

        result, calls = self._get(get_status, b'{"robot_name": "hw4_sim"}')
        self.assertEqual(result, {"robot_name": "hw4_sim"})
        self.assertEqual(calls, [(f"http://{SIM_HOST}:8123/api/daemon/status", None)])

    def test_no_answer_or_not_json_is_none(self):
        import urllib.error

        from reachy_motion.backends.sim_daemon import get_kinematics_info, get_status

        for func in (get_status, get_kinematics_info):
            self.assertIsNone(self._get(func, exc=urllib.error.URLError("refused"))[0])
            self.assertIsNone(self._get(func, exc=TimeoutError())[0])
            self.assertIsNone(self._get(func, body=b"<html>not json</html>")[0])


if __name__ == "__main__":
    unittest.main()
