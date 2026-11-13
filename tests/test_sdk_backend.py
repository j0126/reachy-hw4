"""SdkBackend: the robot target never builds a client in Phase 2; the sim target runs every interlock first.

Hermetic: a fake daemon, a fake ReachyMini (or the pinned SDK's own ReachyMini / WSClient methods on a fake
websocket) and patched REST / socket probes - no process, no network. Approval files are written only into
temporary directories (standing in for the human supervisor's file).
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import warnings
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
from reachy_mini.io.protocol import HeadPoseMsg, JointPositionsMsg, TaskProgress  # io/protocol.py:995-1120

from reachy_motion.backends.base import Backend, BackendError, CommandRecord, PresentState
from reachy_motion.backends.sdk import (
    PRESENT_T_NS,
    ROBOT_NOT_IN_PHASE2,
    SIM_DAEMON_LOG,
    CommandNotConfirmedError,
    RobotApprovalError,
    SdkBackend,
    make_backend,
)
from reachy_motion.backends.sim_daemon import SIM_HOST, SIM_ROBOT_NAME
from reachy_motion.executor.clock import VirtualClock
from reachy_motion.library.spec import Easing
from reachy_motion.safety.approval import ApprovalError
from tests.test_approval import loaded_valid_now_pair, make_request, valid_now_pair

SDK = "reachy_motion.backends.sdk"
APPROVAL = "reachy_motion.safety.approval"
REPO = Path(__file__).resolve().parents[1]
PORT = 8123
GOOD = {
    "robot_name": SIM_ROBOT_NAME,
    "state": "running",
    "simulation_enabled": True,
    "mockup_sim_enabled": False,
    "version": "1.11.0",
}
COMMANDS = ("set_automatic_body_yaw", "disable_wobbling", "stop_head_tracking", "set_target", "goto_target")
JOINTS = [0.12, 0.5, -0.6, 0.55, -0.5, 0.6, -0.55]


class Recorder:
    """Callable that records every call and returns ``result``."""

    def __init__(self, result: object = None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


# ------------------------------------------------------------------------------------------ robot target
class TestRobotTargetIsGated(unittest.TestCase):
    """Every refusal path: zero client / daemon factory calls. Approved: the sim factories are never used; connect()
    runs the robot connection sequence (2026-11-12), stubbed here - nothing reaches the network."""

    def setUp(self) -> None:
        self.client_factory = Recorder()
        self.daemon_factory = Recorder()
        self.confirm = Recorder(True)
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.approval, self.request = loaded_valid_now_pair(self.tmp)  # a saved approval file, read back
        self.path = Path(self.approval.source.path)

    def kwargs(self, **kw) -> dict:
        base = dict(armed=True, approval=self.approval, request=self.request, confirm=self.confirm,
                    client_factory=self.client_factory, daemon_factory=self.daemon_factory)
        base.update(kw)
        return base

    def assertNothingBuilt(self) -> None:
        self.assertEqual(self.client_factory.calls, [])
        self.assertEqual(self.daemon_factory.calls, [])

    def assertRefused(self, confirm_calls: int = 0, **kw) -> str:
        with self.assertRaises(RobotApprovalError) as ctx:
            SdkBackend("robot", **self.kwargs(**kw))
        self.assertNothingBuilt()
        self.assertEqual(len(self.confirm.calls), confirm_calls)
        self.assertIsInstance(ctx.exception, ApprovalError)
        return str(ctx.exception)

    def edit_file(self) -> None:
        self.path.write_text(self.path.read_text(encoding="utf-8").replace('"unit test"', '"edited later"'),
                             encoding="utf-8")

    def test_not_armed(self):
        self.assertIn("armed=True", self.assertRefused(armed=False))

    def test_truthy_but_not_true_armed(self):
        for armed in (1, "yes", [True]):
            self.assertRefused(armed=armed)

    def test_missing_approval_or_request(self):
        self.assertRefused(approval=None)
        self.assertRefused(request=None)
        self.assertRefused(approval=self.approval.to_dict())  # a dict is not a loaded approval

    def test_invalid_approval(self):
        expired = replace(self.approval, approved_on="2020-01-01", expires="2020-01-02T00:00:00")
        self.assertIn("expired", self.assertRefused(approval=expired))
        self.assertIn("host mismatch", self.assertRefused(request=make_request(host="reachy-mini.local")))
        self.assertIn("not covered", self.assertRefused(approval=replace(self.approval, timeline_digests=())))
        self.assertIn("approved_by is empty", self.assertRefused(approval=replace(self.approval, approved_by="")))

    def test_approval_built_in_code_is_refused(self):
        approval, request = valid_now_pair()  # valid content, but no human-written file behind it
        self.assertIn("not loaded from a file", self.assertRefused(approval=approval, request=request))

    def test_approval_copied_in_code_is_refused(self):
        self.assertIn("not loaded from a file", self.assertRefused(approval=replace(self.approval, notes="copy")))

    def test_approval_file_changed_after_loading_is_refused(self):
        self.edit_file()
        self.assertIn("changed since it was loaded", self.assertRefused())

    def test_r0_is_refused(self):
        approval, request = loaded_valid_now_pair(self.tmp, stage="R0")
        self.assertIn("R0 is REST GET only", self.assertRefused(approval=approval, request=request))

    def test_failing_plan_is_refused(self):
        request = make_request(passes=False)
        approval = replace(self.approval, timeline_digests=request.timeline_digests)
        self.assertIn("does not pass policy", self.assertRefused(approval=approval, request=request))

    def test_cap_exceeded_is_refused(self):
        self.assertIn("above the approval cap",
                      self.assertRefused(approval=replace(self.approval, max_stewart_speed_ratio=0.1)))

    def test_not_confirmed(self):
        self.confirm = Recorder(False)
        self.assertRefused(confirm_calls=1)
        for answer in (1, "yes", mock.MagicMock()):  # only a real True confirms
            self.confirm = Recorder(answer)
            self.assertRefused(confirm_calls=1)

    def test_confirmation_typed_after_expiry_is_refused(self):
        later = datetime.now() + timedelta(hours=3)  # the approval is valid for 2 h

        def slow_human(approval) -> bool:  # answers the (time-unlimited) prompt after the approval expired
            self.confirm.calls.append(((approval,), {}))
            self.enterContext(mock.patch(f"{APPROVAL}._now", return_value=later))
            return True

        msg = self.assertRefused(confirm_calls=1, confirm=slow_human)
        self.assertIn("re-checked after the confirmation", msg)
        self.assertIn("expired", msg)

    def test_file_changed_during_the_confirmation_is_refused(self):
        def editing_human(approval) -> bool:
            self.confirm.calls.append(((approval,), {}))
            self.edit_file()
            return True

        msg = self.assertRefused(confirm_calls=1, confirm=editing_human)
        self.assertIn("re-checked after the confirmation", msg)
        self.assertIn("changed since it was loaded", msg)

    def test_default_confirm_refuses_without_a_terminal(self):
        with mock.patch(f"{APPROVAL}._stdin_isatty", return_value=False), \
                mock.patch("builtins.input", side_effect=AssertionError("must not prompt")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            with self.assertRaises(RobotApprovalError) as ctx:
                SdkBackend("robot", **self.kwargs(confirm=None))
        self.assertIn("not confirmed", str(ctx.exception))  # the gate got as far as the confirmation
        self.assertIn("not an interactive terminal", out.getvalue())
        self.assertNothingBuilt()

    def test_default_confirm_prompts_through_builtins_input(self):
        typed = mock.Mock(return_value=self.approval.approval_id)
        with mock.patch(f"{APPROVAL}._stdin_isatty", return_value=True), mock.patch("builtins.input", typed), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            b = SdkBackend("robot", **self.kwargs(confirm=None))
        self.assertFalse(b.connected)
        typed.assert_called_once()
        self.assertIn("PHYSICAL motors", out.getvalue())
        self.assertNothingBuilt()

    def test_make_backend_robot_without_anything(self):
        with self.assertRaises(RobotApprovalError):
            make_backend("robot")

    def test_fully_approved_connect_runs_the_robot_sequence_not_the_sim(self):
        with mock.patch(f"{SDK}.SimDaemon") as sim_daemon, mock.patch(f"{SDK}.get_status") as rest, \
                mock.patch(f"{SDK}.port_answers") as probe, mock.patch(f"{SDK}.get_kinematics_info") as kin, \
                mock.patch.object(SdkBackend, "_connect_robot") as sequence:
            b = SdkBackend("robot", **self.kwargs())
            self.assertEqual(len(self.confirm.calls), 1)
            self.assertIs(self.confirm.calls[0][0][0], self.approval)
            self.assertTrue(b.capabilities.real_hardware)
            self.assertTrue(b.capabilities.torque_control)
            self.assertEqual(b.data_kind, "measured")
            self.assertEqual(b.host, self.request.host)
            self.assertIsInstance(b, Backend)
            b.recheck_approval()  # still valid
            head = np.eye(4)
            for call in (lambda: b.set_target(head, (0.0, 0.0), 0.0), lambda: b.present(),
                         lambda: b.goto_target(head, (0.0, 0.0), 0.0, 1.0, "minjerk")):
                with self.assertRaises(BackendError):  # not connected: nothing sent
                    call()
            b.connect()
            sequence.assert_called_once_with()  # the robot connection sequence (stubbed: no network)
            b.close()
            b.close()
            self.assertFalse(b.connected)
            self.assertEqual(b.commands, [])
        for m in (sim_daemon, rest, probe, kin):
            m.assert_not_called()
        self.assertNothingBuilt()

    def test_connect_rechecks_the_approval(self):
        b = SdkBackend("robot", **self.kwargs())
        with mock.patch(f"{APPROVAL}._now", return_value=datetime.now() + timedelta(hours=3)):
            with self.assertRaises(RobotApprovalError) as ctx:
                b.connect()
        self.assertIn("re-checked before use", str(ctx.exception))
        self.assertIn("expired", str(ctx.exception))
        self.edit_file()
        with self.assertRaises(RobotApprovalError) as ctx:
            b.connect()
        self.assertIn("changed since it was loaded", str(ctx.exception))
        with self.assertRaises(RobotApprovalError):
            b.recheck_approval()
        self.assertNothingBuilt()

    def test_robot_builds_no_client_when_the_sequence_refuses_before_it(self):
        import socket

        blocking = {"blocking": True, "data_kind": "measured", "derived": {"motor_mode": "disabled"},
                    "daemon_url": f"http://{self.request.host}:8000"}
        with mock.patch("reachy_mini.ReachyMini") as ctor, \
                mock.patch("reachy_motion.robot_r0.run_r0", return_value=blocking), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")):
            b = SdkBackend("robot", **self.kwargs(client_factory=None, daemon_factory=None))
            b.operator_confirmed = True
            with self.assertRaises(BackendError) as ctx:
                b.connect()
        self.assertIn("refused", str(ctx.exception))
        ctor.assert_not_called()
        self.assertNothingBuilt()
        self.assertEqual(b.connection_info["connect"]["stage"], "precondition")


# ------------------------------------------------------------------------------------------ sim fakes
class FakeStatus:
    def __init__(self, **fields) -> None:
        self.fields = fields

    def model_dump(self, mode: str = "python") -> dict:
        return dict(self.fields)


class FakeClient:
    """Like WSClient: caches the latest pushed state in ``_dispatch`` (io/ws_client.py:183-226)."""

    def __init__(self, events: list, host: str, status: dict) -> None:
        self.events, self.host, self.port, self.status = events, host, PORT, status
        self._last_joint_positions: JointPositionsMsg | None = None
        self._last_head_pose: HeadPoseMsg | None = None

    def get_status(self, timeout: float = 5.0) -> FakeStatus:
        self.events.append(("socket_status",))
        return FakeStatus(**self.status)

    def disconnect(self) -> None:
        self.events.append(("disconnect",))

    def _dispatch(self, msg) -> None:
        if isinstance(msg, JointPositionsMsg):
            self._last_joint_positions = msg
        elif isinstance(msg, HeadPoseMsg):
            self._last_head_pose = msg

    def get_current_joints(self) -> tuple[list[float], list[float]]:
        assert self._last_joint_positions is not None, "No joint positions received yet."
        m = self._last_joint_positions
        return list(m.head_joint_positions), list(m.antennas_joint_positions)

    def get_current_head_pose(self) -> np.ndarray:
        assert self._last_head_pose is not None, "No head pose received yet."
        return np.array(self._last_head_pose.head_pose)


class FakeMini:
    """Records every SDK call in the shared event list (same signatures as reachy_mini.ReachyMini)."""

    def __init__(self, events: list, host: str, status: dict) -> None:
        self.events = events
        self.client = FakeClient(events, host, status)
        self.set_target_calls: list[dict] = []
        self.goto_calls: list[dict] = []
        self.fail_set_target = False
        self.goto_fail: str | None = None

    def set_automatic_body_yaw(self, enabled: bool) -> None:
        self.events.append(("set_automatic_body_yaw", enabled))

    def disable_wobbling(self) -> None:
        self.events.append(("disable_wobbling",))

    def stop_head_tracking(self) -> None:
        self.events.append(("stop_head_tracking",))

    def set_target(self, head=None, antennas=None, body_yaw=None) -> None:
        if self.fail_set_target:
            raise ConnectionError("Lost connection with the server.")
        self.events.append(("set_target",))
        self.set_target_calls.append(dict(head=head, antennas=antennas, body_yaw=body_yaw))

    def goto_target(self, head=None, antennas=None, duration=0.5, method="minjerk", body_yaw=0.0) -> None:
        # the failure modes of reachy_mini.py:705-722 + io/ws_client.py:268-299
        if self.goto_fail == "dead":
            raise ConnectionError("Lost connection with the server.")  # before the send
        self.events.append(("goto_target",))
        self.goto_calls.append(dict(head=head, antennas=antennas, duration=duration, method=method,
                                    body_yaw=body_yaw))  # on the wire from here on
        if self.goto_fail == "timeout":
            raise TimeoutError("Task did not complete in time.")
        if self.goto_fail == "daemon_error":
            raise Exception("Task failed with error: boom")
        if self.goto_fail == "unknown":
            raise RuntimeError("something nobody expected")
        if self.goto_fail == "ctrl_c":
            raise KeyboardInterrupt()

    def get_current_head_pose(self) -> np.ndarray:  # reachy_mini.py:950-959
        return self.client.get_current_head_pose()

    def get_current_joint_positions(self) -> tuple[list[float], list[float]]:  # reachy_mini.py:926-937
        return self.client.get_current_joints()

    def push(self, joints=JOINTS, antennas=(-0.17, 0.18), z: float = 0.004, head: bool = True) -> None:
        """One daemon control tick: JointPositionsMsg, then HeadPoseMsg (daemon/backend/mujoco/backend.py:262-277)."""
        self.client._dispatch(JointPositionsMsg(head_joint_positions=list(joints),
                                                antennas_joint_positions=list(antennas)))
        if head:
            pose = np.eye(4)
            pose[2, 3] = z
            self.client._dispatch(HeadPoseMsg(head_pose=pose.tolist()))


class FakeDaemon:
    def __init__(self, events: list, start_exc: BaseException | None, **kwargs) -> None:
        self.events, self.start_exc, self.kwargs = events, start_exc, kwargs
        self.stops = 0
        events.append(("daemon_factory", kwargs))

    def start(self, timeout: float = 60.0) -> dict:
        self.events.append(("daemon.start",))
        if self.start_exc is not None:
            raise self.start_exc
        return dict(GOOD)

    def stop(self, timeout: float = 10.0) -> None:
        self.stops += 1
        self.events.append(("daemon.stop",))


class SimHarness:
    def __init__(self, rest_status: dict | None = GOOD, socket_status: dict = GOOD, ipv6_taken: bool = False,
                 start_exc: BaseException | None = None, client_host: str = "localhost",
                 client_exc: BaseException | None = None, dispatch: bool = True) -> None:
        self.events: list[tuple] = []
        self.rest_status, self.socket_status = rest_status, socket_status
        self.ipv6_taken, self.start_exc = ipv6_taken, start_exc
        self.client_host, self.client_exc, self.dispatch = client_host, client_exc, dispatch
        self.daemons: list[FakeDaemon] = []
        self.minis: list[FakeMini] = []
        self.client_kwargs: list[dict] = []

    # factories handed to SdkBackend
    def daemon_factory(self, **kwargs) -> FakeDaemon:
        d = FakeDaemon(self.events, self.start_exc, **kwargs)
        self.daemons.append(d)
        return d

    def client_factory(self, **kwargs) -> FakeMini:
        self.events.append(("client_factory",))
        self.client_kwargs.append(kwargs)
        if self.client_exc is not None:
            raise self.client_exc
        m = FakeMini(self.events, self.client_host, self.socket_status)
        if not self.dispatch:
            m.client._dispatch = None  # an SDK client without the receive hook
        self.minis.append(m)
        return m

    # module functions patched in reachy_motion.backends.sdk
    def get_status(self, port: int, timeout: float = 2.0) -> dict | None:
        self.events.append(("rest_status", port))
        return None if self.rest_status is None else dict(self.rest_status)

    def port_answers(self, host: str, port: int, timeout: float = 0.5) -> bool:
        self.events.append(("port_answers", host))
        return self.ipv6_taken and host == "::1"

    def get_kinematics_info(self, port: int, timeout: float = 2.0) -> dict:
        self.events.append(("kinematics_info",))
        return {"info": {"engine": "AnalyticalKinematics", "collision check": False}}

    def names(self) -> list[str]:
        return [e[0] for e in self.events]

    def index(self, name: str) -> int:
        return self.names().index(name)


class SimTestCase(unittest.TestCase):
    def harness(self, **kw) -> SimHarness:
        h = SimHarness(**kw)
        for name in ("get_status", "port_answers", "get_kinematics_info"):
            self.enterContext(mock.patch(f"{SDK}.{name}", getattr(h, name)))
        return h

    def backend(self, h: SimHarness, **kw) -> SdkBackend:
        kw.setdefault("clock", VirtualClock(start_ns=1_000))
        return SdkBackend("sim", port=PORT, client_factory=h.client_factory, daemon_factory=h.daemon_factory, **kw)

    def assertCleanedUp(self, h: SimHarness, b: SdkBackend, client_built: bool) -> None:
        self.assertFalse(b.connected)
        self.assertEqual(sum(d.stops for d in h.daemons), 1)
        self.assertEqual(h.names().count("disconnect"), 1 if client_built else 0)
        self.assertEqual([n for n in h.names() if n in COMMANDS], [])
        with self.assertRaises(BackendError):
            b.set_target(np.eye(4), (0.0, 0.0), 0.0)


# ------------------------------------------------------------------------------------------ sim target
class TestSimConnect(SimTestCase):
    def test_interlock_order(self):
        h = self.harness()
        b = self.backend(h)
        self.assertEqual(h.events, [])  # constructing does nothing
        b.connect()
        names = h.names()
        first_command = min(i for i, n in enumerate(names) if n in COMMANDS)
        self.assertLess(names.index("daemon.start"), names.index("rest_status"))
        self.assertLess(names.index("rest_status"), names.index("client_factory"))  # REST check before the client
        self.assertLess(h.events.index(("port_answers", "::1")), names.index("client_factory"))
        self.assertLess(names.index("socket_status"), first_command)  # socket check before any command
        self.assertEqual(names[first_command:first_command + 3],
                         ["set_automatic_body_yaw", "disable_wobbling", "stop_head_tracking"])
        self.assertIn(("set_automatic_body_yaw", True), h.events)
        self.assertTrue(b.connected)

    def test_client_and_daemon_arguments(self):
        h = self.harness()
        self.backend(h).connect()
        self.assertEqual(h.client_kwargs, [dict(robot_name=SIM_ROBOT_NAME, host=SIM_HOST, port=PORT,
                                                connection_mode="localhost_only", spawn_daemon=False,
                                                media_backend="no_media", timeout=10.0)])
        self.assertEqual(h.daemons[0].kwargs, dict(port=PORT, headless=True, log_path=None))

    def test_viewer_and_log_dir(self):
        h = self.harness()
        with tempfile.TemporaryDirectory() as tmp:
            b = self.backend(h, viewer=True, log_dir=tmp)
            b.connect()
            self.assertEqual(h.daemons[0].kwargs, dict(port=PORT, headless=False, log_path=Path(tmp) / SIM_DAEMON_LOG))
            b.close()

    def test_connection_info_records_status_and_kinematics(self):
        h = self.harness()
        b = self.backend(h)
        b.connect()
        info = b.connection_info
        self.assertEqual(info["data_kind"], "simulated")
        self.assertEqual(info["daemon_status_rest"]["robot_name"], SIM_ROBOT_NAME)
        self.assertTrue(info["daemon_status_socket"]["simulation_enabled"])
        self.assertEqual(info["kinematics_info"]["info"]["engine"], "AnalyticalKinematics")
        self.assertEqual(info["client_init"], {"automatic_body_yaw": True, "wobbling": False, "head_tracking": False})
        self.assertEqual(info["present_t_ns"], PRESENT_T_NS)

    def test_connect_twice_builds_once(self):
        h = self.harness()
        b = self.backend(h)
        b.connect()
        b.connect()
        self.assertEqual(len(h.daemons), 1)
        self.assertEqual(len(h.minis), 1)

    def test_capabilities(self):
        b = self.backend(self.harness())
        self.assertEqual(b.data_kind, "simulated")
        self.assertFalse(b.capabilities.real_hardware)
        self.assertFalse(b.capabilities.torque_control)
        self.assertIsInstance(b, Backend)
        b.recheck_approval()  # nothing to re-check for the sim

    def test_constructor_validation(self):
        with self.assertRaises(ValueError):
            SdkBackend("simulator")
        approval, request = valid_now_pair()
        for kw in (dict(armed=True), dict(approval=approval), dict(request=request), dict(confirm=lambda a: True)):
            with self.assertRaises(ValueError):
                SdkBackend("sim", **kw)


class TestSimRefusals(SimTestCase):
    def test_socket_reports_no_simulation(self):
        h = self.harness(socket_status=dict(GOOD, simulation_enabled=False))
        b = self.backend(h)
        with self.assertRaises(RuntimeError):
            b.connect()
        self.assertCleanedUp(h, b, client_built=True)
        self.assertEqual(h.minis[0].set_target_calls, [])

    def test_socket_host_not_loopback(self):
        h = self.harness(client_host="reachy-mini.local")
        b = self.backend(h)
        with self.assertRaises(RuntimeError):
            b.connect()
        self.assertCleanedUp(h, b, client_built=True)
        self.assertNotIn("socket_status", h.names())  # refused on the host before asking that socket anything

    def test_rest_status_not_sim(self):
        for status in (dict(GOOD, simulation_enabled=False, robot_name="reachy_mini"), None):
            h = self.harness(rest_status=status)
            b = self.backend(h)
            with self.assertRaises(RuntimeError):
                b.connect()
            self.assertNotIn("client_factory", h.names())
            self.assertCleanedUp(h, b, client_built=False)

    def test_ipv6_loopback_taken(self):
        h = self.harness(ipv6_taken=True)
        b = self.backend(h)
        with self.assertRaises(RuntimeError):
            b.connect()
        self.assertNotIn("client_factory", h.names())  # the constructor itself sends a command
        self.assertCleanedUp(h, b, client_built=False)

    def test_daemon_start_failure(self):
        h = self.harness(start_exc=TimeoutError("sim daemon did not become ready"))
        b = self.backend(h)
        with self.assertRaises(TimeoutError):
            b.connect()
        self.assertNotIn("rest_status", h.names())
        self.assertNotIn("client_factory", h.names())
        self.assertCleanedUp(h, b, client_built=False)

    def test_ctrl_c_while_connecting_still_cleans_up(self):
        h = self.harness(client_exc=KeyboardInterrupt())
        b = self.backend(h)
        with self.assertRaises(KeyboardInterrupt):
            b.connect()
        self.assertCleanedUp(h, b, client_built=False)

    def test_client_without_receive_hook_is_refused_before_any_command(self):
        h = self.harness(dispatch=False)
        b = self.backend(h)
        with self.assertRaises(RuntimeError) as ctx:
            b.connect()
        self.assertIn("_dispatch", str(ctx.exception))
        self.assertCleanedUp(h, b, client_built=True)


class TestSimCommands(SimTestCase):
    def setUp(self) -> None:
        self.h = self.harness()
        self.clock = VirtualClock(start_ns=5_000)
        self.b = self.backend(self.h, clock=self.clock)
        self.b.connect()
        self.mini = self.h.minis[0]
        self.head = np.eye(4)
        self.head[2, 3] = 0.01

    def test_set_target_forwards_explicit_body_yaw(self):
        self.b.set_target(self.head, (-0.2, 0.3), np.float64(0.25))
        call = self.mini.set_target_calls[-1]
        np.testing.assert_array_equal(call["head"], self.head)
        self.assertEqual(call["antennas"], [-0.2, 0.3])
        self.assertEqual(call["body_yaw"], 0.25)
        self.assertIs(type(call["body_yaw"]), float)  # SDK checks isinstance(body_yaw, (int, float))
        rec = self.b.commands[-1]
        self.assertIsInstance(rec, CommandRecord)
        self.assertEqual((rec.kind, rec.t_ns, rec.antennas, rec.body_yaw), ("set_target", 5_000, (-0.2, 0.3), 0.25))

    def test_goto_target_forwards_method_duration_and_body_yaw(self):
        from reachy_mini.utils.interpolation import InterpolationTechnique  # utils/interpolation.py:108-114

        self.clock.advance(20_000_000)
        self.b.goto_target(self.head, (0.1, -0.1), -0.4, 1.5, "cartoon")
        self.b.goto_target(self.head, (0.1, -0.1), 0.0, 0.8, Easing.EASE_IN_OUT)
        first, second = self.mini.goto_calls
        self.assertEqual(first["method"], InterpolationTechnique.CARTOON)
        self.assertIsInstance(first["method"], InterpolationTechnique)
        self.assertEqual((first["duration"], first["body_yaw"], first["antennas"]), (1.5, -0.4, [0.1, -0.1]))
        self.assertEqual(second["method"], InterpolationTechnique.EASE_IN_OUT)
        self.assertEqual(second["body_yaw"], 0.0)  # an explicit 0.0, never the SDK default
        rec = self.b.commands[0]
        self.assertEqual((rec.kind, rec.t_ns, rec.duration, rec.method), ("goto_target", 20_005_000, 1.5, "cartoon"))
        self.assertEqual(self.b.unconfirmed, {})

    def test_bad_commands_never_reach_the_sdk(self):
        bad = [
            lambda: self.b.set_target(self.head, (0.0, 0.0), None),  # body yaw must be explicit
            lambda: self.b.set_target(np.full((4, 4), np.nan), (0.0, 0.0), 0.0),
            lambda: self.b.set_target(np.eye(3), (0.0, 0.0), 0.0),
            lambda: self.b.set_target(self.head, (0.0,), 0.0),
            lambda: self.b.goto_target(self.head, (0.0, 0.0), 0.0, 0.0, "minjerk"),
            lambda: self.b.goto_target(self.head, (0.0, 0.0), 0.0, float("nan"), "minjerk"),
            lambda: self.b.goto_target(self.head, (0.0, 0.0), 0.0, 1.0, "bouncy"),
        ]
        for call in bad:
            with self.assertRaises(BackendError):
                call()
        self.assertEqual(self.mini.set_target_calls, [])
        self.assertEqual(self.mini.goto_calls, [])
        self.assertEqual(self.b.commands, [])

    def test_sdk_failure_becomes_backend_error_without_record(self):
        self.mini.fail_set_target = True
        with self.assertRaises(BackendError):
            self.b.set_target(self.head, (0.0, 0.0), 0.0)
        self.assertEqual(self.b.commands, [])

    def test_goto_that_was_never_sent_is_not_recorded(self):
        self.mini.goto_fail = "dead"  # send_task_request on a dead client (ws_client.py:270-271)
        with self.assertRaises(BackendError) as ctx:
            self.b.goto_target(self.head, (0.0, 0.0), 0.0, 1.0, "minjerk")
        self.assertNotIsInstance(ctx.exception, CommandNotConfirmedError)
        self.assertIn("not sent", str(ctx.exception))
        self.assertEqual((self.b.commands, self.b.unconfirmed, self.mini.goto_calls), ([], {}, []))

    def test_goto_sent_but_not_confirmed_is_recorded(self):
        for n, mode in enumerate(("timeout", "daemon_error"), start=1):
            self.mini.goto_fail = mode
            with self.assertRaises(CommandNotConfirmedError) as ctx, self.assertLogs(SDK, "WARNING") as logs:
                self.b.goto_target(self.head, (0.2, -0.2), 0.3, 1.5, "cartoon")
            self.assertIn("may still be running", logs.output[0])
            err = ctx.exception
            self.assertIsInstance(err, BackendError)  # executors that catch BackendError still see it
            self.assertIs(err.sent, True)
            self.assertEqual(len(self.mini.goto_calls), n)  # it reached the wire ...
            self.assertEqual(len(self.b.commands), n)  # ... so it is in the command log
            self.assertIs(err.record, self.b.commands[err.index])
            self.assertEqual((err.record.kind, err.record.duration, err.record.method, err.record.body_yaw),
                             ("goto_target", 1.5, "cartoon", 0.3))
            self.assertIn(err.index, self.b.unconfirmed)
            self.assertIn("may still be running", str(err))
        self.assertIn("TimeoutError", self.b.unconfirmed[0])
        self.assertIn("Task failed with error: boom", self.b.unconfirmed[1])

    def test_goto_with_an_unknown_failure_is_recorded_as_possibly_sent(self):
        self.mini.goto_fail = "unknown"
        with self.assertRaises(CommandNotConfirmedError) as ctx, self.assertLogs(SDK, "WARNING"):
            self.b.goto_target(self.head, (0.0, 0.0), 0.0, 1.0, "minjerk")
        self.assertIsNone(ctx.exception.sent)
        self.assertIn("outcome unknown", str(ctx.exception))
        self.assertEqual(list(self.b.unconfirmed), [0])

    def test_ctrl_c_during_the_goto_wait_is_recorded_and_propagates(self):
        self.mini.goto_fail = "ctrl_c"
        with self.assertRaises(KeyboardInterrupt), self.assertLogs(SDK, "WARNING"):
            self.b.goto_target(self.head, (0.0, 0.0), 0.0, 1.0, "minjerk")
        self.assertEqual(len(self.b.commands), 1)
        self.assertIn("interrupted", self.b.unconfirmed[0])

    def test_record_is_a_copy(self):
        self.b.set_target(self.head, (0.0, 0.0), 0.0)
        self.head[0, 3] = 1.0
        self.assertEqual(self.b.commands[0].head[0, 3], 0.0)

    def test_present_state_is_stamped_at_arrival(self):
        self.clock.advance(1_000)  # t = 6_000: one daemon tick arrives
        self.mini.push(z=0.004)
        self.clock.advance(15_000_000)  # the executor reads 15 ms later ...
        s1 = self.b.present()
        self.clock.advance(10_000_000)  # ... and again 10 ms later, no new push in between
        s2 = self.b.present()
        for s in (s1, s2):
            self.assertIsInstance(s, PresentState)
            self.assertEqual(s.t_ns, 6_000)  # the arrival, not the read time
            self.assertEqual(s.data_kind, "simulated")
        self.assertEqual(s1.head.shape, (4, 4))
        self.assertEqual(s1.head[2, 3], 0.004)
        self.assertEqual(s1.joints.shape, (7,))
        self.assertEqual(s1.body_yaw, 0.12)  # joints[0] = body yaw
        self.assertEqual(s1.antennas, (-0.17, 0.18))
        self.clock.advance(7)
        self.mini.push(joints=[0.2] + JOINTS[1:], z=0.006)
        s3 = self.b.present()
        self.assertEqual((s3.t_ns, s3.body_yaw, s3.head[2, 3]), (25_006_007, 0.2, 0.006))

    def test_present_waits_for_the_first_push_after_connect(self):
        self.b.push_timeout_s = 0.01
        with self.assertRaises(BackendError):  # nothing pushed since the hook was installed
            self.b.present()
        self.mini.push(head=False)  # joints only: the state is not complete yet
        with self.assertRaises(BackendError):
            self.b.present()
        self.clock.advance(100)
        self.mini.push()
        self.assertEqual(self.b.present().t_ns, 5_100)

    def test_receive_hook_sends_nothing(self):
        self.assertIn("_dispatch", vars(self.mini.client))  # the instance attribute wraps the class method
        before = list(self.h.events)
        self.mini.push()
        self.assertEqual(self.h.events, before)
        self.assertIsNotNone(self.mini.client._last_joint_positions)  # the client's own dispatch still ran

    def test_close_stops_daemon_once(self):
        self.b.close()
        self.b.close()
        names = self.h.names()
        self.assertEqual(names.count("disconnect"), 1)
        self.assertEqual(names.count("daemon.stop"), 1)
        self.assertLess(names.index("disconnect"), names.index("daemon.stop"))
        with self.assertRaises(BackendError):
            self.b.set_target(self.head, (0.0, 0.0), 0.0)
        with self.assertRaises(BackendError):
            self.b.present()

    def test_context_manager(self):
        h = self.harness()
        with self.backend(h) as b:
            b.set_target(self.head, (0.0, 0.0), 0.1)
        self.assertEqual(h.names().count("daemon.stop"), 1)
        self.assertFalse(b.connected)


# ------------------------------------------------------------------------------------------ pinned SDK code
class FakeSocket:
    """Stands in for the websocket under a real WSClient: records frames; may answer a task at once."""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.client = None
        self.task_reply: str | None = "finished"  # "finished", an error text, or None (never answers)
        self.closed = False

    def send(self, text: str) -> None:
        frame = json.loads(text)
        self.frames.append(frame)
        if frame.get("type") == "task" and self.task_reply is not None:
            error = None if self.task_reply == "finished" else self.task_reply
            self.client._dispatch(TaskProgress(uuid=frame["uuid"], finished=True, error=error,
                                               timestamp=datetime.now()))

    def close(self) -> None:
        self.closed = True


class TestWithPinnedSdkClientCode(SimTestCase):
    """reachy_mini 1.11.0's own ReachyMini / WSClient methods run; only the websocket is fake.

    ``object.__new__`` skips the constructors (they would open a socket and start a receive thread); the
    attributes set here are the ones those methods use (io/ws_client.py:53-83, reachy_mini.py:148-171).
    """

    def setUp(self) -> None:
        from reachy_mini.io.ws_client import WSClient
        from reachy_mini.reachy_mini import ReachyMini

        h = self.harness()
        self.sock = FakeSocket()
        ws = object.__new__(WSClient)
        ws.host, ws.port = "localhost", PORT
        ws.tasks, ws._tasks_lock, ws._is_alive = {}, threading.Lock(), True
        ws._last_joint_positions = ws._last_head_pose = None
        ws.joint_position_received, ws.head_pose_received = threading.Event(), threading.Event()
        ws.status_received, ws._last_status = threading.Event(), FakeStatus(**GOOD)
        ws.status_received.set()
        ws._stop_event = threading.Event()
        ws._ws = self.sock
        self.sock.client = ws
        mini = object.__new__(ReachyMini)
        mini.client, mini.logger, mini.is_recording, mini._last_head_pose = ws, logging.getLogger(__name__), False, None
        mini.media_manager = types.SimpleNamespace(disable_wobbling=lambda: None)
        self.ws, self.mini = ws, mini
        self.clock = VirtualClock(start_ns=0)
        self.b = SdkBackend("sim", port=PORT, client_factory=lambda **kw: mini, daemon_factory=h.daemon_factory,
                            clock=self.clock)
        self.b.connect()
        self.addCleanup(self.b.close)
        self.head = np.eye(4)

    def frame_types(self) -> list[str]:
        return [f["type"] for f in self.sock.frames]

    def test_connect_sends_only_the_three_init_commands(self):
        self.assertEqual(self.frame_types(), ["set_automatic_body_yaw", "set_wobbling", "set_head_tracking"])
        self.assertEqual([f.get("enabled") for f in self.sock.frames], [True, False, False])

    def test_present_is_stamped_by_the_wrapped_sdk_dispatch(self):
        self.clock.advance(3_000)
        self.ws._dispatch(JointPositionsMsg(head_joint_positions=JOINTS, antennas_joint_positions=[-0.17, 0.17]))
        self.ws._dispatch(HeadPoseMsg(head_pose=np.eye(4).tolist()))
        self.clock.advance(15_000_000)
        s1 = self.b.present()
        self.clock.advance(10_000_000)
        s2 = self.b.present()
        self.assertEqual((s1.t_ns, s2.t_ns), (3_000, 3_000))  # one push read twice: one time
        np.testing.assert_array_equal(s1.joints, JOINTS)
        self.assertEqual(s1.antennas, (-0.17, 0.17))
        self.assertTrue(self.ws.joint_position_received.is_set())  # the SDK's own dispatch still ran

    def test_confirmed_goto(self):
        self.b.goto_target(self.head, (0.1, -0.1), 0.25, 0.05, "cartoon")
        task = self.sock.frames[-1]
        self.assertEqual(task["type"], "task")
        self.assertEqual((task["req"]["method"], task["req"]["body_yaw"], task["req"]["duration"]),
                         ("cartoon", 0.25, 0.05))
        self.assertEqual((len(self.b.commands), self.b.unconfirmed, self.ws.tasks), (1, {}, {}))

    def test_daemon_error_after_the_send_is_recorded(self):
        self.sock.task_reply = "boom"
        with self.assertRaises(CommandNotConfirmedError) as ctx, self.assertLogs(SDK, "WARNING"):
            self.b.goto_target(self.head, (0.1, -0.1), 0.25, 0.05, "minjerk")
        self.assertIs(ctx.exception.sent, True)
        self.assertIn("Task failed with error: boom", str(ctx.exception))
        self.assertEqual(self.frame_types()[-1], "task")
        self.assertEqual(list(self.b.unconfirmed), [0])

    def test_timeout_after_the_send_is_recorded(self):
        self.sock.task_reply = None  # the daemon never reports: the SDK waits duration + 1 s (reachy_mini.py:722)
        with self.assertRaises(CommandNotConfirmedError) as ctx, self.assertLogs(SDK, "WARNING"):
            self.b.goto_target(self.head, (0.1, -0.1), 0.25, 0.01, "minjerk")
        self.assertIsInstance(ctx.exception.__cause__, TimeoutError)
        self.assertEqual(self.frame_types()[-1], "task")
        self.assertEqual(len(self.b.commands), 1)
        self.assertIn(0, self.b.unconfirmed)

    def test_dead_client_sends_and_records_nothing(self):
        self.ws._is_alive = False
        n = len(self.sock.frames)
        with self.assertRaises(BackendError) as ctx:
            self.b.goto_target(self.head, (0.1, -0.1), 0.25, 0.05, "minjerk")
        self.assertNotIsInstance(ctx.exception, CommandNotConfirmedError)
        with self.assertRaises(BackendError):
            self.b.set_target(self.head, (0.0, 0.0), 0.0)
        self.assertEqual((len(self.sock.frames), self.b.commands, self.b.unconfirmed), (n, [], {}))

    def test_set_target_goes_out_as_one_full_target(self):
        self.b.set_target(self.head, (0.1, -0.1), 0.25)
        frame = self.sock.frames[-1]
        self.assertEqual((frame["type"], frame["antennas"], frame["body_yaw"]), ("set_full_target", [0.1, -0.1], 0.25))
        self.assertEqual(len(self.b.commands), 1)

    def test_close_disconnects_the_sdk_client(self):
        self.b.close()
        self.assertTrue(self.sock.closed)
        self.assertTrue(self.ws._stop_event.is_set())
        self.assertIsNone(self.ws._ws)


# ------------------------------------------------------------------------------------------ factory
class TestMakeBackend(unittest.TestCase):
    def test_sim_is_built_but_not_connected(self):
        daemon_factory, client_factory = Recorder(), Recorder()
        b = make_backend("sim", port=PORT, daemon_factory=daemon_factory, client_factory=client_factory)
        self.assertIsInstance(b, SdkBackend)
        self.assertEqual(b.target, "sim")
        self.assertFalse(b.connected)
        self.assertEqual(daemon_factory.calls + client_factory.calls, [])

    def test_unknown_name(self):
        with self.assertRaises(ValueError):
            make_backend("hardware")

    def test_mock_is_imported_lazily(self):
        fake = types.ModuleType("reachy_motion.backends.mock")

        class MockBackend:
            def __init__(self, **kw) -> None:
                self.kw = kw

        fake.MockBackend = MockBackend
        with mock.patch.dict(sys.modules, {"reachy_motion.backends.mock": fake}):
            b = make_backend("mock", seed=3)
        self.assertIsInstance(b, MockBackend)
        self.assertEqual(b.kw, {"seed": 3})

    def test_real_mock_backend_if_present(self):
        if importlib.util.find_spec("reachy_motion.backends.mock") is None:
            self.skipTest("reachy_motion.backends.mock not written yet")
        with warnings.catch_warnings():
            # the SDK's AnalyticalKinematics leaves its data file open (kinematics/analytical_kinematics.py:37)
            warnings.simplefilter("ignore", ResourceWarning)
            b = make_backend("mock")
        self.assertEqual(type(b).__name__, "MockBackend")
        self.assertEqual(b.data_kind, "mock")
        self.assertFalse(b.capabilities.real_hardware)

    def test_importing_the_sdk_backend_does_not_import_the_mock(self):
        code = "import sys, reachy_motion.backends.sdk; print('reachy_motion.backends.mock' in sys.modules)"
        out = subprocess.run([sys.executable, "-B", "-c", code], cwd=REPO, capture_output=True, text=True,
                             timeout=60, check=True).stdout.split()
        self.assertEqual(out, ["False"])


if __name__ == "__main__":
    unittest.main()
