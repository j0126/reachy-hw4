"""DaemonClient is read-only by construction.

Hermetic: the socket layer (``urllib.request.HTTPHandler.http_open``) is replaced by a fake daemon, so the client's
real urllib opener - redirect and error handling included - runs on top of it and every request that reaches the
fake is a request the client really sent. Opening a real connection fails the test (no network, no daemon, no robot).
"""

from __future__ import annotations

import ast
import email.message
import http.client
import inspect
import io
import json
import os
import socket
import unittest
import urllib.error
import urllib.request
import urllib.response
from dataclasses import dataclass, field
from typing import Any
from unittest import mock

from reachy_motion.backends import daemon_client
from reachy_motion.backends.base import BackendError
from reachy_motion.backends.daemon_client import (ALLOWED_GET_PATHS, ALLOWED_GET_QUERIES, HEAD_JOINTS_QUERY,
                                                  DaemonClient, loop_stats)
from reachy_motion.library.pose import Pose6

HOST = "127.0.0.1"
BASE = f"http://{HOST}:8000"
OTHER = "http://192.0.2.1:8000"  # TEST-NET-1 (RFC 5737): stands for any other host, e.g. the robot

#: CLAUDE.md rule 3: the REST GETs allowed on the robot daemon without approval.
CLAUDE_MD_GETS = {"/api/daemon/status", "/api/kinematics/info", "/api/state/full", "/api/state/present_body_yaw",
                  "/api/motors/status"}
#: ... and the one query string the user added on 2026-11-11 (cached joint read, R0 start-pose check).
CLAUDE_MD_QUERIES = {"/api/state/full?with_head_joints=true"}
HEAD_JOINTS = [0.1, 0.62, -0.63, 0.61, -0.6, 0.64, -0.62]

LOOP_STATS = {"mean_control_loop_frequency": 49.6, "max_control_loop_interval": 0.031, "nb_error": 0,
              "motor_controller": "stats"}
ROBOT_STATUS = {
    "type": "daemon_status", "robot_name": "reachy_mini", "state": "running", "wireless_version": True,
    "desktop_app_daemon": False, "simulation_enabled": False, "mockup_sim_enabled": False, "no_media": False,
    "backend_status": {"ready": True, "motor_control_mode": "enabled", "last_alive": 1.0,
                       "control_loop_stats": LOOP_STATS, "error": None},
    "error": None, "wlan_ip": "192.0.2.10", "version": "1.11.0",
}
SIM_STATUS = dict(ROBOT_STATUS, robot_name="hw4_sim", simulation_enabled=True, wireless_version=False,
                  backend_status={"motor_control_mode": "enabled", "error": None})
FULL_STATE = {"control_mode": "enabled", "body_yaw": 0.1, "antennas_position": [-0.17, 0.17],
              "head_pose": {"x": 0.001, "y": -0.002, "z": 0.003, "roll": 0.01, "pitch": -0.02, "yaw": 0.03},
              "timestamp": "2026-11-10T00:00:00Z"}
ROUTES: dict[str, Any] = {
    "/api/daemon/status": ROBOT_STATUS,
    "/api/kinematics/info": {"info": {"engine": "AnalyticalKinematics", "collision check": False}},
    "/api/state/full": FULL_STATE,
    "/api/state/full?with_head_joints=true": dict(FULL_STATE, head_joints=HEAD_JOINTS),
    "/api/state/present_body_yaw": 0.1,
    "/api/motors/status": {"mode": "enabled"},
}


def setUpModule() -> None:
    """Belt and braces: a request that bypasses the fake transport fails instead of opening a socket."""
    unittest.enterModuleContext(mock.patch.object(
        socket, "create_connection", side_effect=AssertionError("network access in a hermetic test")))


@dataclass
class Answer:
    """An HTTP answer with an explicit status (redirects, errors)."""

    code: int
    msg: str
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


def http_response(url: str, answer: Answer) -> urllib.response.addinfourl:
    """What ``HTTPHandler.http_open`` returns: urllib's error processor reads ``code``, ``msg`` and ``info()``."""
    hdrs = email.message.Message()
    for name, value in answer.headers.items():
        hdrs[name] = value
    resp = urllib.response.addinfourl(io.BytesIO(answer.body), hdrs, url, answer.code)
    resp.msg = answer.msg
    return resp


class FakeDaemon:
    """Replaces the socket layer: answers by path and records every request that reached it.

    Routes map a path of ``BASE`` to a JSON value, raw bytes, an ``Answer`` or an exception to raise. Any other URL
    (another host, an unknown path) gets 200 ``{}`` / 404, so a request the client should not have sent still
    completes and shows up in ``requests``.
    """

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = dict(ROUTES if routes is None else routes)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, req: urllib.request.Request) -> urllib.response.addinfourl:
        self.requests.append(req)
        url = req.full_url
        if not url.startswith(BASE + "/"):
            return http_response(url, Answer(200, "OK", b"{}"))
        answer = self.routes.get(url[len(BASE):], Answer(404, "Not Found", b'{"detail": "Not Found"}'))
        if isinstance(answer, BaseException):
            raise answer
        if not isinstance(answer, Answer):
            body = answer if isinstance(answer, bytes) else json.dumps(answer).encode("utf-8")
            answer = Answer(200, "OK", body, {"Content-Type": "application/json"})
        return http_response(url, answer)

    def patch(self) -> Any:
        """Context manager installing this fake as the transport of every urllib HTTPHandler."""
        return mock.patch.object(urllib.request.HTTPHandler, "http_open", self)


def answering(path: str, answer: Any) -> FakeDaemon:
    return FakeDaemon(dict(ROUTES, **{path: answer}))


class TestConstruction(unittest.TestCase):
    def test_host_is_required(self):
        with self.assertRaises(TypeError):
            DaemonClient()  # type: ignore[call-arg]
        self.assertIs(inspect.signature(DaemonClient.__init__).parameters["host"].default, inspect.Parameter.empty)
        for bad in ("", "   ", None, 42):
            with self.assertRaises(ValueError):
                DaemonClient(bad)  # type: ignore[arg-type]

    def test_host_cannot_smuggle_a_scheme_port_path_or_query(self):
        for bad in ("http://127.0.0.1", "127.0.0.1:8000", "127.0.0.1/api/move/goto", "127.0.0.1?with_doa=true",
                    "user@127.0.0.1", "reachy mini.local", "[127.0.0.1]", "[reachy-mini.local]", "fe80::1%eth0",
                    "127.0.0.1#frag"):
            with self.subTest(host=bad), self.assertRaises(ValueError):
                DaemonClient(bad)

    def test_valid_hosts_build_the_base_url(self):
        cases = {"127.0.0.1": "http://127.0.0.1:8000", " localhost ": "http://localhost:8000",
                 "reachy-mini.local": "http://reachy-mini.local:8000", "::1": "http://[::1]:8000",
                 "[::1]": "http://[::1]:8000"}
        for host, base in cases.items():
            with self.subTest(host=host):
                self.assertEqual(DaemonClient(host).base_url, base)
        self.assertEqual(DaemonClient(HOST, port=8123).base_url, "http://127.0.0.1:8123")

    def test_port_and_timeout_validation(self):
        for port in (0, 65536, -1, 80.0, True, "8000"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                DaemonClient(HOST, port=port)  # type: ignore[arg-type]
        for timeout in (0, -1.0, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                DaemonClient(HOST, timeout_s=timeout)  # type: ignore[arg-type]

    def test_construction_sends_nothing(self):
        fake = FakeDaemon()
        with fake.patch():
            DaemonClient("reachy-mini.local")
        self.assertEqual(fake.requests, [])


class TestWhitelist(unittest.TestCase):
    def test_whitelist_is_exactly_the_claude_md_list(self):
        self.assertEqual(set(ALLOWED_GET_PATHS), CLAUDE_MD_GETS)
        self.assertEqual(set(ALLOWED_GET_QUERIES), CLAUDE_MD_QUERIES)
        self.assertEqual(HEAD_JOINTS_QUERY, "/api/state/full?with_head_joints=true")

    def test_other_paths_are_refused_before_any_request(self):
        refused = ["/api/move/goto", "/api/move/set_target", "/api/motors/set_mode/disabled", "/api/daemon/stop",
                   "/api/daemon/start", "/api/daemon/restart", "/api/move/play/wake_up", "/api/move/ws/raw/write",
                   "/api/state/present_head_pose", "/api/state/doa", "/api/state/full/", "api/daemon/status",
                   "/API/DAEMON/STATUS", "", "/", "http://192.0.2.1:8000/api/daemon/status", None]
        fake = FakeDaemon()
        client = DaemonClient(HOST)
        with fake.patch():
            for path in refused:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    client.get(path)  # type: ignore[arg-type]
        self.assertEqual(fake.requests, [])

    def test_query_strings_are_refused(self):
        fake = FakeDaemon()
        client = DaemonClient(HOST)
        with fake.patch():
            for path in ("/api/state/full?with_doa=true", "/api/state/full?with_target_head_pose=true",
                         "/api/state/full?", "/api/daemon/status#x", "/api/motors/status?mode=disabled",
                         # only the exact allowed query: no other spelling, value, extra parameter, order or path
                         "/api/state/full?with_head_joints=1", "/api/state/full?with_head_joints=True",
                         "/api/state/full?with_head_joints=true&with_doa=true",
                         "/api/state/full?with_doa=true&with_head_joints=true",
                         "/api/state/full?with_head_joints=true&with_target_head_joints=true",
                         "/api/state/full?with_head_joints=true#x", "/api/state/full/?with_head_joints=true",
                         "/api/state/full?with_head_joints=true ", "/api/daemon/status?with_head_joints=true"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    client.get(path)
        self.assertEqual(fake.requests, [])

    def test_every_reader_sends_one_plain_get_to_its_path(self):
        fake = FakeDaemon()
        client = DaemonClient(HOST, timeout_s=1.5)
        expected = {
            "status": "/api/daemon/status", "kinematics_info": "/api/kinematics/info",
            "state_full": "/api/state/full", "present_head_pose": "/api/state/full",
            "state_full_with_head_joints": HEAD_JOINTS_QUERY, "present_head_joints": HEAD_JOINTS_QUERY,
            "present_body_yaw": "/api/state/present_body_yaw", "motors_status": "/api/motors/status",
            "motor_mode": "/api/motors/status", "control_loop_stats": "/api/daemon/status",
        }
        with fake.patch():
            for name, path in expected.items():
                with self.subTest(reader=name):
                    n = len(fake.requests)
                    getattr(client, name)()
                    self.assertEqual(len(fake.requests), n + 1)
                    req = fake.requests[-1]
                    self.assertEqual(req.full_url, BASE + path)
                    self.assertEqual((req.host, req.selector), (f"{HOST}:8000", path))  # direct, no proxy
                    self.assertEqual(req.get_method(), "GET")
                    self.assertIsNone(req.data)
            client.status(timeout_s=0.25)
        timeouts = [req.timeout for req in fake.requests]
        self.assertEqual(timeouts[:-1], [1.5] * len(expected))
        self.assertEqual(timeouts[-1], 0.25)


class TestReadOnlyByConstruction(unittest.TestCase):
    def test_no_write_capable_attribute(self):
        for name in ("post", "put", "patch", "delete", "request", "send", "set_motor_mode", "set_mode",
                     "enable_motors", "disable_motors", "goto", "goto_target", "set_target", "wake_up", "goto_sleep",
                     "start", "stop", "restart", "play_move", "write"):
            self.assertFalse(hasattr(DaemonClient, name), name)

    def test_public_api_is_the_reader_set(self):
        public = {n for n, _ in inspect.getmembers(DaemonClient, callable) if not n.startswith("_")}
        self.assertEqual(public, {"get", "status", "kinematics_info", "state_full", "present_head_pose",
                                  "present_body_yaw", "motors_status", "motor_mode", "control_loop_stats",
                                  "summary", "state_full_with_head_joints", "present_head_joints"})

    def test_source_sends_one_get_request_through_one_opener(self):
        """One Request (method="GET", URL only, no body), sent by the single ``_OPENER.open`` call; ``_OPENER`` is
        built once from the redirect-refusing handler and a proxy-free ProxyHandler; no other way to send."""
        tree = ast.parse(inspect.getsource(daemon_client))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

        def name(call: ast.Call) -> str | None:
            f = call.func
            return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None

        names = [name(c) for c in calls]
        requests = [c for c in calls if name(c) == "Request"]
        self.assertEqual(len(requests), 1)
        kw = {k.arg: k.value for k in requests[0].keywords}
        self.assertIsInstance(kw.get("method"), ast.Constant)
        self.assertEqual(kw["method"].value, "GET")
        self.assertNotIn("data", kw)
        self.assertEqual(len(requests[0].args), 1)  # the URL only
        opens = [c for c in calls if name(c) == "open"]
        self.assertEqual([ast.unparse(c.func) for c in opens], ["_OPENER.open"])
        builds = [c for c in calls if name(c) == "build_opener"]
        self.assertEqual(len(builds), 1)
        self.assertEqual([ast.unparse(a) for a in builds[0].args],
                         ["_RefuseRedirects", "urllib.request.ProxyHandler({})"])
        for forbidden in ("urlopen", "install_opener", "HTTPConnection", "HTTPSConnection", "urlretrieve",
                          "create_connection", "OpenerDirector"):
            self.assertNotIn(forbidden, names)

    def test_redirects_are_never_followed(self):
        """A 3xx answer is refused and NOTHING else is sent: urllib's default redirect handler would GET the
        Location (another host, a write route, a state-registering query) before the answer could be checked."""
        locations = [OTHER + "/api/state/full?with_doa=true", "/api/move/goto", "/api/state/full?with_doa=true", None]
        for code in (301, 302, 303, 307, 308):
            for location in locations:
                with self.subTest(code=code, location=location):
                    headers = {} if location is None else {"Location": location}
                    fake = answering("/api/state/full", Answer(code, "Redirect", headers=headers))
                    with fake.patch(), self.assertRaises(BackendError) as ctx:
                        DaemonClient(HOST).state_full()
                    self.assertEqual([r.full_url for r in fake.requests], [BASE + "/api/state/full"])
                    self.assertIn(f"GET {BASE}/api/state/full answered HTTP {code}", str(ctx.exception))
                    self.assertIn("not followed", str(ctx.exception))

    def test_no_proxy_is_used(self):
        """Environment (or Windows system) proxies would put one more party between the client and the daemon.

        ``ProxyHandler({})`` registers no method, so the opener has no proxy handler at all (its construction is
        pinned by the source test above); here: a proxy in the environment is not used either.
        """
        self.assertFalse(any(getattr(h, "proxies", None) for h in daemon_client._OPENER.handlers))
        fake = FakeDaemon()
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://192.0.2.1:3128"}), fake.patch():
            DaemonClient(HOST).status()
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual((fake.requests[0].host, fake.requests[0].selector), (f"{HOST}:8000", "/api/daemon/status"))


class TestAnswers(unittest.TestCase):
    def test_control_loop_stats_extraction(self):
        with FakeDaemon().patch():
            self.assertEqual(DaemonClient(HOST).control_loop_stats(), LOOP_STATS)
        cases = [(SIM_STATUS, None), (dict(ROBOT_STATUS, backend_status=None), None),
                 (dict(ROBOT_STATUS, backend_status={"control_loop_stats": {}}), None), ({}, None), (None, None),
                 ([1, 2], None)]
        for status, expected in cases:
            self.assertEqual(loop_stats(status), expected)
        stats = loop_stats(ROBOT_STATUS)
        stats["nb_error"] = 99  # a copy, not the answer itself
        self.assertEqual(ROBOT_STATUS["backend_status"]["control_loop_stats"]["nb_error"], 0)

    def test_typed_readers(self):
        client = DaemonClient(HOST)
        with FakeDaemon().patch():
            self.assertEqual(client.present_head_pose(), Pose6(0.001, -0.002, 0.003, 0.01, -0.02, 0.03))
            body = client.present_body_yaw()
            self.assertIsInstance(body, float)
            self.assertEqual(body, 0.1)
            self.assertEqual(client.motor_mode(), "enabled")
            self.assertEqual(client.kinematics_info()["info"]["engine"], "AnalyticalKinematics")
            self.assertEqual(client.state_full()["antennas_position"], [-0.17, 0.17])
            self.assertEqual(client.present_head_joints(), HEAD_JOINTS)
            snap = client.state_full_with_head_joints()
            self.assertEqual((snap["head_joints"], snap["head_pose"]), (HEAD_JOINTS, FULL_STATE["head_pose"]))

    def test_head_joint_answers_are_validated(self):
        for joints in (None, HEAD_JOINTS[:6], HEAD_JOINTS + [0.0], ["0.1"] * 7, [True] * 7, [float("nan")] * 7):
            with self.subTest(joints=joints), answering(HEAD_JOINTS_QUERY, dict(FULL_STATE, head_joints=joints)).patch():
                with self.assertRaises(BackendError):
                    DaemonClient(HOST).present_head_joints()

    def test_unexpected_answer_shapes(self):
        cases = [("present_head_pose", "/api/state/full", {"control_mode": "enabled"}),
                 ("present_head_pose", "/api/state/full", dict(FULL_STATE, head_pose={"m": [1.0] * 16})),
                 ("present_body_yaw", "/api/state/present_body_yaw", "0.1"),
                 ("present_body_yaw", "/api/state/present_body_yaw", True),
                 ("status", "/api/daemon/status", [1, 2, 3]),
                 ("motors_status", "/api/motors/status", None)]
        for reader, path, answer in cases:
            with self.subTest(reader=reader, answer=answer), answering(path, answer).patch():
                with self.assertRaises(BackendError):
                    getattr(DaemonClient(HOST), reader)()
        with answering("/api/motors/status", {"other": 1}).patch():
            self.assertIsNone(DaemonClient(HOST).motor_mode())

    def test_summary_of_robot_and_sim(self):
        with FakeDaemon().patch():
            info = DaemonClient(HOST).summary()
        self.assertEqual((info["robot_name"], info["daemon_version"], info["data_kind"]),
                         ("reachy_mini", "1.11.0", "measured"))
        self.assertEqual((info["motor_control_mode"], info["control_loop_stats"]), ("enabled", LOOP_STATS))
        self.assertEqual(info["kinematics"], {"engine": "AnalyticalKinematics", "collision check": False})
        with answering("/api/daemon/status", SIM_STATUS).patch():
            info = DaemonClient(HOST).summary()
        self.assertEqual((info["data_kind"], info["control_loop_stats"]), ("simulated", None))
        mockup = dict(SIM_STATUS, simulation_enabled=False, mockup_sim_enabled=True)
        with answering("/api/daemon/status", mockup).patch():
            self.assertIsNone(DaemonClient(HOST).summary()["data_kind"])

    def test_summary_is_best_effort(self):
        down = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        with answering("/api/daemon/status", down).patch():
            info = DaemonClient(HOST).summary()
        self.assertEqual(set(info), {"daemon_url", "client", "status_error"})
        self.assertIn(BASE + "/api/daemon/status", info["status_error"])
        with answering("/api/kinematics/info", TimeoutError("slow")).patch():
            info = DaemonClient(HOST).summary()
        self.assertEqual(info["robot_name"], "reachy_mini")
        self.assertIn("/api/kinematics/info", info["kinematics_error"])


class TestErrors(unittest.TestCase):
    def test_failures_become_backend_errors_naming_the_url(self):
        url = BASE + "/api/daemon/status"
        failures = [
            urllib.error.URLError("no route to host"),
            Answer(500, "Internal Server Error", b'{"detail": "boom"}'),
            Answer(404, "Not Found"),
            TimeoutError("timed out"),
            ConnectionResetError(10054, "reset"),
            http.client.RemoteDisconnected("closed"),
            b"<html>not json</html>",
            b"\xff\xfe",
        ]
        for failure in failures:
            with self.subTest(failure=repr(failure)), answering("/api/daemon/status", failure).patch():
                with self.assertRaises(BackendError) as ctx:
                    DaemonClient(HOST).status()
                self.assertIn(url, str(ctx.exception))

    def test_http_error_reports_the_status_code(self):
        with answering("/api/state/full", Answer(500, "Internal Server Error")).patch():
            with self.assertRaises(BackendError) as ctx:
                DaemonClient(HOST).state_full()
        self.assertIn("HTTP 500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
