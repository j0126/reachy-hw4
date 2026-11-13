"""Executor and tick timing: hermetic tests (no daemon, no network, no robot).

The backend is a recorder defined in this file and time is a ``VirtualClock`` (plus one short
real-clock run that measures this PC's loop). Streaming timelines and passing reports are built by hand
so that every sent sample can be checked exactly against the plan (V2.5) and the tick statistics can be
checked against values computed by hand (V2.4). Goto plans come from the real planner
(``reachy_motion.planner.plan``), because a goto must be bound to the plan of exactly its spec.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import math
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from reachy_motion.backends.base import BackendError, Capabilities, PresentState
from reachy_motion.executor.clock import RealClock, VirtualClock
from reachy_motion.executor.executor import (
    EVENT_PREFIX,
    GOTO_IN_FLIGHT_WARNING,
    ExecutionRefused,
    Executor,
    SentCommand,
    current_thread_priority,
    set_current_thread_priority,
)
from reachy_motion.executor.timing import (
    CSV_COLUMNS,
    DEFAULT_LATE_THRESHOLD_MS,
    TickLog,
    TickRecord,
    measure_tick_timing,
    stationary_rest_motion,
)
from reachy_motion.library.pose import INIT_ANTENNAS, Pose6
from reachy_motion.library.spec import (
    AntennaKey,
    BodyKey,
    Easing,
    HeadKey,
    MotionSpec,
    Principle,
    PrincipleUse,
    SoundCue,
)
from reachy_motion.planner import plan
from reachy_motion.safety.policy import DEFAULT_POLICY, SafetyReport, Violation
from reachy_motion.timeline import PreparedMotion, Timeline
from reachy_motion.util.event_logger import EventLogger

MS = 1_000_000
PERIOD = 20 * MS  # 50 Hz
EXEC_LOGGER = "reachy_motion.executor.executor"


class Abort(BaseException):
    """Stands in for KeyboardInterrupt inside a backend call."""


# ---------------------------------------------------------------------- fixtures
def make_timeline(n: int = 11, rate_hz: float = 50.0, name: str = "aha_recommend", variant: str = "expressive",
                  seed: float = 0.0, body: np.ndarray | None = None, spec_digest: str = "") -> Timeline:
    """Distinct, finite samples so the order and identity of every sent sample can be checked."""
    k = np.arange(n, dtype=np.float64)
    head = np.repeat(np.eye(4)[None, :, :], n, axis=0)
    c, s = np.cos(0.01 * k), np.sin(0.01 * k)  # yaw
    head[:, 0, 0], head[:, 0, 1], head[:, 1, 0], head[:, 1, 1] = c, -s, s, c
    head[:, 0, 3] = 1e-4 * (k + seed)
    head[:, 2, 3] = -2e-4 * k
    antennas = np.stack([-0.17 + 0.01 * k, 0.17 - 0.01 * k], axis=1)
    keys = np.zeros(n, dtype=np.int64)
    return Timeline(name=name, variant=variant, rate_hz=rate_hz, duration=(n - 1) / rate_hz, t=k / rate_hz,
                    head=head, antennas=antennas, body_yaw=0.002 * k if body is None else body,
                    head_key=keys, antenna_key=keys.copy(), body_key=keys.copy(), spec_digest=spec_digest)


def report_for(tl: Timeline, passes: bool = True, violations: tuple[Violation, ...] = (),
               spec_digest: str | None = None) -> SafetyReport:
    """A report bound to ``tl`` (like the checker: ``spec_digest`` defaults to the timeline's label)."""
    return SafetyReport(name=tl.name, variant=tl.variant, policy=DEFAULT_POLICY, passes_policy=passes,
                        violations=violations, warnings=(), metrics={}, timeline_digest=tl.digest(),
                        spec_digest=tl.spec_digest if spec_digest is None else spec_digest)


def prepared_for(tl: Timeline, spec: MotionSpec | None = None) -> PreparedMotion:
    return PreparedMotion(timeline=tl, report=report_for(tl), spec=spec)


def spec_with_sound(at_s: float = 0.1, tempo: float = 1.0) -> MotionSpec:
    spec = MotionSpec(name="aha_recommend", variant="expressive", intent="cue test", valence=0.5, arousal=0.5,
                      principles=(PrincipleUse(Principle.TIMING, "test"),),
                      head=(HeadKey(duration=0.2, pose=Pose6()),), sound=SoundCue("aha.wav", at_s))
    return spec.scaled(tempo=tempo) if tempo != 1.0 else spec


class FakeBackend:
    """Records every call. Optional: virtual send cost, a failing call, a per-send hook, goto cost/error."""

    name = "fake"
    data_kind = "mock"

    def __init__(self, clock: VirtualClock | None = None, capabilities: Capabilities | None = None,
                 send_cost_ns=None, fail_at: int | None = None, fail_exc: BaseException | None = None, on_send=None,
                 goto_cost_ns: int = 0, goto_error: BaseException | None = None,
                 goto_error_after_dispatch: bool = False, present_error: Exception | None = None) -> None:
        self.capabilities = capabilities or Capabilities()
        self.clock = clock
        self.send_cost_ns = send_cost_ns
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.on_send = on_send
        self.goto_cost_ns = goto_cost_ns
        self.goto_error = goto_error
        self.goto_error_after_dispatch = goto_error_after_dispatch
        self.present_error = present_error
        self.calls: list[tuple] = []
        self.sent: list[tuple] = []  # (head copy, antennas, body_yaw, t_ns)
        self.received: list[np.ndarray] = []  # the head objects handed in
        self.gotos: list[tuple] = []  # gotos that reached the "daemon"

    def _now(self) -> int | None:
        return self.clock.now_ns() if self.clock is not None else None

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))

    def set_target(self, head, antennas, body_yaw) -> None:
        i = sum(1 for c in self.calls if c[0] == "set_target")
        self.calls.append(("set_target", i))
        if self.fail_at is not None and i == self.fail_at:
            raise self.fail_exc if self.fail_exc is not None else BackendError("link down")
        if self.send_cost_ns is not None and self.clock is not None:
            self.clock.advance(self.send_cost_ns(i))
        self.received.append(head)
        self.sent.append((np.array(head, copy=True), tuple(antennas), body_yaw, self._now()))
        if self.on_send is not None:
            self.on_send(i)

    def goto_target(self, head, antennas, body_yaw, duration, method) -> None:
        self.calls.append(("goto_target",))
        if self.goto_error is not None and not self.goto_error_after_dispatch:
            raise self.goto_error
        if self.clock is not None and self.goto_cost_ns:
            self.clock.advance(self.goto_cost_ns)
        self.gotos.append((np.array(head, copy=True), tuple(antennas), body_yaw, duration, method))
        if self.goto_error is not None:  # the task is on the wire, then the client gives up (reachy_mini.py:721-722)
            raise self.goto_error

    def present(self) -> PresentState:
        self.calls.append(("present",))
        if self.present_error is not None:
            raise self.present_error
        return PresentState(t_ns=self._now() or 0, head=np.eye(4), antennas=INIT_ANTENNAS, body_yaw=0.0)


def set_target_calls(fake: FakeBackend) -> int:
    return sum(1 for c in fake.calls if c[0] == "set_target")


# ---------------------------------------------------------------------- streaming
class TestStreaming(unittest.TestCase):
    def test_sends_every_sample_exactly_in_order_on_the_absolute_schedule(self):
        tl = make_timeline(11)
        clock = VirtualClock(start_ns=7 * MS)
        fake = FakeBackend(clock)
        res = Executor(fake, clock=clock).run(prepared_for(tl))
        self.assertTrue(res.completed)
        self.assertFalse(res.cancelled)
        self.assertIsNone(res.error)
        self.assertIsNone(res.failed_command)
        self.assertTrue(res.end_state_known)
        self.assertEqual(res.spec_digest, "")  # ad-hoc timeline, no spec
        self.assertEqual((res.key, res.strategy, res.backend, res.data_kind, res.n_samples),
                         ("aha_recommend:expressive", "stream", "fake", "mock", 11))
        self.assertEqual(len(fake.sent), 11)
        for k, (head, ant, body, t_ns) in enumerate(fake.sent):
            np.testing.assert_array_equal(head, tl.head[k])  # V2.5: sent == planned, exactly
            self.assertEqual(ant, (float(tl.antennas[k, 0]), float(tl.antennas[k, 1])))
            self.assertIsInstance(body, float)  # body yaw always explicit
            self.assertEqual(body, float(tl.body_yaw[k]))
            self.assertEqual(t_ns, 7 * MS + k * PERIOD)
        self.assertEqual([c.k for c in res.commands], list(range(11)))
        for k, rec in res.commands:
            self.assertEqual((rec.kind, rec.t_ns, rec.duration, rec.method), ("set_target", 7 * MS + k * PERIOD,
                                                                              None, None))
            np.testing.assert_array_equal(rec.head, tl.head[k])
            self.assertEqual(rec.antennas, tuple(map(float, tl.antennas[k])))
            self.assertEqual(rec.body_yaw, float(tl.body_yaw[k]))
        recs = res.ticks.records
        self.assertEqual([r.planned_ns for r in recs], [7 * MS + k * PERIOD for k in range(11)])
        self.assertEqual([r.tick for r in recs], list(range(11)))
        self.assertTrue(all(r.late_ns == 0 and r.skipped_before == 0 and r.ok for r in recs))
        self.assertEqual(res.started_ns, 7 * MS)
        self.assertEqual(clock.sleeps, 11)
        head, ant, body = res.last_sample
        np.testing.assert_array_equal(head, tl.head[-1])  # ends exactly on the planned end state
        self.assertEqual((ant, body), (tuple(map(float, tl.antennas[-1])), float(tl.body_yaw[-1])))
        s = res.ticks.summary(PERIOD)
        self.assertEqual((s["n_ticks"], s["n_sent"], s["skipped_samples"], s["late_ticks"]), (11, 11, 0, 0))
        self.assertEqual(s["effective_hz"], 50.0)
        self.assertEqual(s["interval_ms"]["mean"], 20.0)
        self.assertEqual(s["jitter_ms"], 0.0)
        self.assertEqual(res.ticks.meta["clock"], "VirtualClock")
        self.assertTrue(res.ticks.meta["completed"])
        self.assertTrue(res.ticks.meta["end_state_known"])

    def test_non_integer_period_rounds_each_deadline_without_drift(self):
        tl = make_timeline(31, rate_hz=30.0)
        clock = VirtualClock()
        res = Executor(FakeBackend(clock), clock=clock, rate_hz=30.0).run(prepared_for(tl))
        planned = [r.planned_ns for r in res.ticks.records]
        self.assertEqual(planned, [round(k * 1e9 / 30.0) for k in range(31)])
        self.assertEqual(planned[-1], 1_000_000_000)
        self.assertEqual(res.ticks.summary()["skipped_samples"], 0)

    def test_due_sample_boundaries(self):
        ex = Executor(FakeBackend(), clock=VirtualClock(), rate_hz=30.0)
        self.assertEqual(ex.due_sample(ex.offset_ns(3), 3, 31), 3)
        self.assertEqual(ex.due_sample(ex.offset_ns(4) - 1, 3, 31), 3)
        self.assertEqual(ex.due_sample(ex.offset_ns(4), 3, 31), 4)
        self.assertEqual(ex.due_sample(ex.offset_ns(9) + 5, 3, 31), 9)
        self.assertEqual(ex.due_sample(10**12, 3, 31), 30)  # never past the final sample
        self.assertEqual(ex.due_sample(-5, 0, 31), 0)

    def test_late_wake_skips_samples_and_counts_them(self):
        tl = make_timeline(11)
        clock = VirtualClock(wake_delay_ns=lambda deadline: 45 * MS if deadline == 5 * PERIOD else 0)
        fake = FakeBackend(clock)
        res = Executor(fake, clock=clock).run(prepared_for(tl))
        self.assertEqual([c.k for c in res.commands], [0, 1, 2, 3, 4, 7, 8, 9, 10])
        for (k, _rec), sent in zip(res.commands, fake.sent):
            np.testing.assert_array_equal(sent[0], tl.head[k])
        r = res.ticks.records[5]
        self.assertEqual((r.k, r.tick, r.planned_ns, r.actual_ns, r.late_ns, r.skipped_before),
                         (7, 5, 100 * MS, 145 * MS, 45 * MS, 2))
        self.assertEqual(res.ticks.records[6].planned_ns, 160 * MS)  # back on the absolute grid
        s = res.ticks.summary(PERIOD)
        self.assertEqual((s["n_ticks"], s["skipped_samples"], s["late_ticks"]), (9, 2, 1))
        self.assertEqual(s["n_ticks"] + s["skipped_samples"], len(tl))
        self.assertEqual(s["late_ms"]["max"], 45.0)
        self.assertEqual(s["interval_ms"]["max"], 65.0)
        self.assertTrue(res.completed)

    def test_final_sample_is_never_skipped(self):
        tl = make_timeline(11)
        clock = VirtualClock(wake_delay_ns=lambda deadline: 500 * MS if deadline == 7 * PERIOD else 0)
        res = Executor(FakeBackend(clock), clock=clock).run(prepared_for(tl))
        self.assertEqual([c.k for c in res.commands], [0, 1, 2, 3, 4, 5, 6, 10])
        self.assertEqual(res.ticks.records[-1].skipped_before, 3)
        self.assertTrue(res.completed)
        np.testing.assert_array_equal(res.last_sample[0], tl.head[-1])

    def test_slow_send_overrun_skips_instead_of_bursting(self):
        tl = make_timeline(11)
        clock = VirtualClock()
        fake = FakeBackend(clock, send_cost_ns=lambda i: 50 * MS if i == 3 else 1 * MS)
        res = Executor(fake, clock=clock).run(prepared_for(tl))
        self.assertEqual([c.k for c in res.commands], [0, 1, 2, 3, 5, 6, 7, 8, 9, 10])
        by_k = {r.k: r for r in res.ticks.records}
        self.assertEqual(by_k[3].send_ns, 50 * MS)
        self.assertEqual((by_k[5].planned_ns, by_k[5].actual_ns, by_k[5].late_ns, by_k[5].skipped_before),
                         (80 * MS, 110 * MS, 30 * MS, 1))
        s = res.ticks.summary(PERIOD)
        self.assertEqual(s["send_ms"]["max"], 50.0)
        self.assertEqual(s["late_ticks"], 1)

    def test_cancel_mid_run_stops_sending(self):
        tl = make_timeline(11)
        clock = VirtualClock()
        cancel = threading.Event()
        fake = FakeBackend(clock, on_send=lambda i: cancel.set() if i == 4 else None)
        res = Executor(fake, clock=clock).run(prepared_for(tl), cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertFalse(res.completed)
        self.assertIsNone(res.error)
        self.assertTrue(res.end_state_known)  # the robot holds sample 4
        self.assertEqual(set_target_calls(fake), 5)
        self.assertEqual([c.k for c in res.commands], [0, 1, 2, 3, 4])
        self.assertEqual(len(res.ticks), 5)
        np.testing.assert_array_equal(res.last_sample[0], tl.head[4])  # the pose the robot holds
        self.assertTrue(res.ticks.meta["cancelled"])

    def test_cancel_set_while_sleeping_sends_nothing_more(self):
        # The cancel arrives during the sleep before sample 3: the loop-top check has already passed, only the
        # check after the sleep can stop that send.
        tl = make_timeline(11)
        cancel = threading.Event()
        clock = VirtualClock(wake_delay_ns=lambda d: (cancel.set(), 0)[1] if d == 3 * PERIOD else 0)
        fake = FakeBackend(clock)
        res = Executor(fake, clock=clock).run(prepared_for(tl), cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertFalse(res.completed)
        self.assertEqual(set_target_calls(fake), 3)
        self.assertEqual([c.k for c in res.commands], [0, 1, 2])
        self.assertEqual(len(res.ticks), 3)
        self.assertEqual(clock.sleeps, 4)  # it slept for sample 3, then did not send it
        np.testing.assert_array_equal(res.last_sample[0], tl.head[2])

    def test_cancel_before_start_sends_nothing(self):
        clock = VirtualClock()
        fake = FakeBackend(clock)
        cancel = threading.Event()
        cancel.set()
        res = Executor(fake, clock=clock).run(prepared_for(make_timeline(11)), cancel=cancel)
        self.assertTrue(res.cancelled)
        self.assertEqual(fake.calls, [])
        self.assertEqual(clock.sleeps, 0)
        self.assertEqual(res.commands, [])
        self.assertIsNone(res.last_sample)

    def test_backend_exception_stops_the_run(self):
        tl = make_timeline(11)
        clock = VirtualClock()
        fake = FakeBackend(clock, fail_at=3)
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res = Executor(fake, clock=clock).run(prepared_for(tl))
        self.assertFalse(res.completed)
        self.assertFalse(res.cancelled)
        self.assertIn("link down", res.error)
        self.assertIn("sample 3", res.error)
        self.assertEqual(fake.calls[-1], ("set_target", 3))  # nothing after the failing call
        self.assertEqual(set_target_calls(fake), 4)
        self.assertEqual([c.k for c in res.commands], [0, 1, 2])
        self.assertEqual([(r.k, r.ok) for r in res.ticks.records], [(0, True), (1, True), (2, True), (3, False)])
        s = res.ticks.summary(PERIOD)
        self.assertEqual((s["n_ticks"], s["n_sent"]), (4, 3))
        np.testing.assert_array_equal(res.last_sample[0], tl.head[2])  # last call that returned
        k, rec = res.failed_command  # the call that raised is kept: it may have reached the robot
        self.assertEqual((k, rec.kind), (3, "set_target"))
        np.testing.assert_array_equal(rec.head, tl.head[3])
        self.assertFalse(res.end_state_known)
        summary = res.summary()
        self.assertEqual((summary["failed_k"], summary["failed_kind"], summary["end_state_known"]),
                         (3, "set_target", False))
        json.dumps(summary)
        self.assertEqual(res.ticks.meta["error"], res.error)
        self.assertFalse(res.ticks.meta["end_state_known"])

    def test_interrupt_inside_set_target_is_recorded_then_propagates(self):
        tl = make_timeline(11)
        clock = VirtualClock()
        fake = FakeBackend(clock, fail_at=2, fail_exc=Abort("ctrl-c"))
        ex = Executor(fake, clock=clock)
        with self.assertRaises(Abort):
            ex.run(prepared_for(tl))
        res = ex.last_result
        self.assertFalse(res.completed)
        self.assertIn("interrupted during set_target at sample 2", res.error)
        self.assertEqual(res.failed_command.k, 2)
        self.assertFalse(res.end_state_known)
        self.assertEqual([c.k for c in res.commands], [0, 1])
        self.assertEqual(res.ticks.meta["error"], res.error)
        self.assertFalse(ex.busy)

    def test_on_tick_runs_after_each_send_and_cannot_stop_the_motion(self):
        tl = make_timeline(11)
        clock = VirtualClock()
        fake = FakeBackend(clock)
        seen = []
        Executor(fake, clock=clock).run(prepared_for(tl),
                                        on_tick=lambda k, rec: seen.append((k, rec.k, rec.tick, len(fake.sent))))
        self.assertEqual(seen, [(k, k, k, k + 1) for k in range(11)])

        def broken(_k, _rec):
            raise ValueError("gui closed")

        fake2 = FakeBackend(clock)
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res = Executor(fake2, clock=clock).run(prepared_for(tl), on_tick=broken)
        self.assertTrue(res.completed)
        self.assertEqual(len(fake2.sent), 11)
        self.assertEqual(len(res.warnings), 1)
        self.assertIn("on_tick raised 11 time(s)", res.warnings[0])

    def test_record_present_after_each_send(self):
        tl = make_timeline(5)
        clock = VirtualClock()
        fake = FakeBackend(clock)
        res = Executor(fake, clock=clock).run(prepared_for(tl), record_present=True)
        self.assertEqual([c[0] for c in fake.calls], ["set_target", "present"] * 5)
        self.assertEqual(len(res.present), 5)
        self.assertTrue(all(isinstance(p, PresentState) for p in res.present))

        fake2 = FakeBackend(clock, present_error=BackendError("read failed"))
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res2 = Executor(fake2, clock=clock).run(prepared_for(tl), record_present=True)
        self.assertTrue(res2.completed)
        self.assertEqual(len(fake2.sent), 5)
        self.assertIn("present() raised 5 time(s)", res2.warnings[0])

    def test_sent_records_are_private_read_only_copies(self):
        tl = make_timeline(3)
        original = tl.head.copy()
        clock = VirtualClock()
        fake = FakeBackend(clock)
        res = Executor(fake, clock=clock).run(prepared_for(tl))
        fake.received[0][0, 3] = 99.0  # a backend scribbling on what it was given
        self.assertNotEqual(res.commands[0].record.head[0, 3], 99.0)
        self.assertFalse(res.commands[0].record.head.flags.writeable)
        np.testing.assert_array_equal(tl.head, original)
        self.assertIsInstance(res.commands[0], tuple)  # (k, CommandRecord) pairs
        self.assertIsInstance(res.commands[0], SentCommand)

    def test_streams_the_checked_snapshot_not_the_callers_live_arrays(self):
        # Timeline is frozen but its arrays are writeable: a writer holding the same timeline (another thread;
        # here on_tick, deterministic) changes samples after the check. What was checked must be what is sent.
        tl = make_timeline(11)
        checked_head, checked_ant, checked_body = tl.head.copy(), tl.antennas.copy(), tl.body_yaw.copy()
        p = prepared_for(tl)
        clock = VirtualClock()
        fake = FakeBackend(clock)

        def writer(k, _rec):
            if k == 2:
                tl.head[5, 2, 3] = 0.050  # z = +50 mm: outside the envelope (IK NaN from +24.3 mm)
                tl.antennas[6] = (1.0, -1.0)
                tl.body_yaw[7] = 1.0

        res = Executor(fake, clock=clock).run(p, on_tick=writer)
        self.assertTrue(res.completed)
        self.assertEqual(tl.head[5, 2, 3], 0.050)  # the caller's array did change ...
        self.assertEqual(len(fake.sent), 11)
        for k, (head, ant, body, _t) in enumerate(fake.sent):  # ... but every sent sample is the checked one
            np.testing.assert_array_equal(head, checked_head[k])
            self.assertEqual(ant, tuple(map(float, checked_ant[k])))
            self.assertEqual(body, float(checked_body[k]))
        sent_tl = dataclasses.replace(tl, head=np.stack([s[0] for s in fake.sent]),
                                      antennas=np.array([s[1] for s in fake.sent]),
                                      body_yaw=np.array([s[2] for s in fake.sent]))
        self.assertEqual(sent_tl.digest(), p.report.timeline_digest)  # the digest describes what was sent
        self.assertEqual(res.timeline_digest, p.report.timeline_digest)

    def test_events_run_start_and_run_end_with_summary(self):
        tl = make_timeline(11)
        clock = VirtualClock()
        events = EventLogger(None)
        res = Executor(FakeBackend(clock), clock=clock, events=events).run(prepared_for(tl))
        kinds = [r["kind"] for r in events.recent(EVENT_PREFIX)]
        self.assertEqual(kinds, ["executor.run_start", "executor.run_end"])
        start = events.recent("executor.run_start")[0]
        self.assertEqual((start["n_samples"], start["timeline_digest"], start["rate_hz"], start["spec_digest"]),
                         (11, tl.digest(), 50.0, ""))
        end = events.recent("executor.run_end")[0]
        self.assertTrue(end["completed"])
        self.assertTrue(end["end_state_known"])
        self.assertEqual(end["n_commands"], 11)
        self.assertEqual(end["ticks"]["n_sent"], 11)
        self.assertEqual(end["ticks"]["effective_hz"], 50.0)
        json.dumps(res.summary())  # serialisable as is

    def test_second_run_while_busy_is_refused(self):
        tl = make_timeline(6)
        clock = VirtualClock()
        fake = FakeBackend(clock)
        ex = Executor(fake, clock=clock)
        p = prepared_for(tl)
        outcome = {}

        def on_tick(k, _rec):
            if k == 2:
                before = len(fake.calls)
                try:
                    ex.run(p)
                except ExecutionRefused as exc:
                    outcome["refused"] = str(exc)
                outcome["calls_delta"] = len(fake.calls) - before

        res = ex.run(p, on_tick=on_tick)
        self.assertIn("busy", outcome["refused"])
        self.assertEqual(outcome["calls_delta"], 0)
        self.assertTrue(res.completed)
        self.assertFalse(ex.busy)
        self.assertIs(ex.last_result, res)


# ---------------------------------------------------------------------- refusals
class TestRefusals(unittest.TestCase):
    def setUp(self):
        self.clock = VirtualClock()
        self.fake = FakeBackend(self.clock)
        self.ex = Executor(self.fake, clock=self.clock)
        self.tl = make_timeline(11)

    def assert_refused(self, fn, fragment: str, fake: FakeBackend | None = None) -> None:
        fake = fake or self.fake
        with self.assertRaises(ExecutionRefused) as cm:
            fn()
        self.assertIn(fragment, str(cm.exception))
        self.assertEqual(fake.calls, [])  # ZERO backend calls
        self.assertEqual(self.clock.sleeps, 0)

    def test_failing_report(self):
        p = PreparedMotion(self.tl, report_for(self.tl, passes=False,
                                               violations=(Violation("stewart_margin", "too close"),)))
        self.assert_refused(lambda: self.ex.run(p), "stewart_margin")
        self.assertIsNone(self.ex.last_result)

    def test_report_of_other_commands(self):
        other = make_timeline(11, seed=1.0)
        self.assertNotEqual(other.digest(), self.tl.digest())
        self.assert_refused(lambda: self.ex.run(PreparedMotion(self.tl, report_for(other))), "digest mismatch")

    def test_timeline_changed_after_its_report(self):
        report = report_for(self.tl)
        self.tl.head[3, 0, 3] += 0.01  # the caller edits the checked arrays before the run
        self.assert_refused(lambda: self.ex.run(PreparedMotion(self.tl, report)), "digest mismatch")

    def test_rate_mismatch(self):
        tl100 = make_timeline(21, rate_hz=100.0)
        self.assert_refused(lambda: self.ex.run(prepared_for(tl100)), "100 Hz")

    def test_invalid_timeline_even_with_a_matching_report(self):
        body = 0.002 * np.arange(11.0)
        body[3] = np.nan
        self.assert_refused(lambda: self.ex.run(prepared_for(make_timeline(11, body=body))), "invalid timeline")

    def test_malformed_arrays(self):
        bad = dataclasses.replace(self.tl, head=np.array([["not a number"]], dtype=object))
        self.assert_refused(lambda: self.ex.run(PreparedMotion(bad, report_for(self.tl))), "invalid timeline")

    def test_backend_capabilities(self):
        no_stream = FakeBackend(self.clock, capabilities=Capabilities(stream=False))
        self.assert_refused(lambda: Executor(no_stream, clock=self.clock).run(prepared_for(self.tl)),
                            "cannot stream", no_stream)
        no_present = FakeBackend(self.clock, capabilities=Capabilities(present=False))
        self.assert_refused(lambda: Executor(no_present, clock=self.clock).run(prepared_for(self.tl),
                                                                              record_present=True),
                            "present", no_present)

    def test_only_prepared_motions(self):
        self.assert_refused(lambda: self.ex.run(self.tl), "PreparedMotion")

    def test_component_types(self):
        report = report_for(self.tl)
        self.assert_refused(lambda: self.ex.run(PreparedMotion("timeline", report)), "not a Timeline")
        self.assert_refused(lambda: self.ex.run(PreparedMotion(self.tl, {"passes_policy": True})),
                            "not a SafetyReport")
        self.assert_refused(lambda: self.ex.run(PreparedMotion(self.tl, report, spec="aha_recommend")),
                            "not a MotionSpec")

    def test_constructor_arguments(self):
        with self.assertRaises(TypeError):
            Executor(object())
        with self.assertRaises(TypeError):
            Executor(self.fake, clock=object())
        for rate in (0.0, -50.0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                Executor(self.fake, rate_hz=rate)
        with self.assertRaises(ValueError):
            Executor(self.fake, late_threshold_ms=-1.0)
        self.assertEqual(self.fake.calls, [])


# ---------------------------------------------------------------------- sound cue
class TestSoundCue(unittest.TestCase):
    def run_with(self, spec, wake_delay=None, spec_digest: str | None = None):
        """Stream an 11-sample timeline labelled as planned from ``spec`` (or from ``spec_digest`` if given)."""
        clock = VirtualClock(wake_delay_ns=wake_delay)
        events = EventLogger(None)
        label = spec_digest if spec_digest is not None else (spec.digest() if spec is not None else "")
        tl = make_timeline(11, spec_digest=label)
        res = Executor(FakeBackend(clock), clock=clock, events=events).run(prepared_for(tl, spec))
        return res, events

    def test_logged_once_when_its_time_is_reached(self):
        spec = spec_with_sound(0.1)
        res, events = self.run_with(spec)
        self.assertEqual(len(res.sound_cues), 1)
        cue = res.sound_cues[0]
        self.assertEqual((cue["file"], cue["at_s"], cue["k"], cue["played"]), ("aha.wav", 0.1, 5, False))
        self.assertAlmostEqual(cue["t_s"], 0.1, places=12)
        logged = events.recent("executor.sound_cue")
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["k"], 5)
        self.assertEqual(res.spec_digest, spec.digest())
        self.assertEqual(res.warnings, [])

    def test_logged_once_when_its_sample_is_skipped(self):
        res, events = self.run_with(spec_with_sound(0.1),
                                    wake_delay=lambda d: 45 * MS if d == 4 * PERIOD else 0)
        self.assertNotIn(5, [c.k for c in res.commands])
        self.assertEqual([c["k"] for c in res.sound_cues], [6])
        self.assertEqual(len(events.recent("executor.sound_cue")), 1)

    def test_tempo_scales_the_cue_time(self):
        res, _ = self.run_with(spec_with_sound(0.1, tempo=2.0))  # effective at_s = 0.05 s -> first sample 0.06 s
        self.assertEqual([(c["k"], c["at_s"]) for c in res.sound_cues], [(3, 0.05)])

    def test_no_cue_without_a_spec_or_a_sound(self):
        res, events = self.run_with(None)
        self.assertEqual(res.sound_cues, [])
        self.assertEqual(events.recent("executor.sound_cue"), [])
        silent = dataclasses.replace(spec_with_sound(0.1), sound=None)
        res2, events2 = self.run_with(silent)
        self.assertEqual(res2.sound_cues, [])
        self.assertEqual(res2.warnings, [])

    def test_spec_the_timeline_was_not_planned_from_is_ignored(self):
        planned = spec_with_sound(0.1)
        other = dataclasses.replace(planned, name="failure", sound=SoundCue("failure.wav", 0.15))
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res, events = self.run_with(other, spec_digest=planned.digest())
        self.assertTrue(res.completed)  # the commands come from the checked timeline either way
        self.assertEqual(res.sound_cues, [])  # no cue of an unrelated motion
        self.assertEqual(events.recent("executor.sound_cue"), [])
        self.assertEqual(res.spec_digest, planned.digest())  # provenance = the timeline's own label
        self.assertEqual(events.recent("executor.run_start")[0]["spec_digest"], planned.digest())
        self.assertTrue(any("prepared.spec ignored" in w and "mismatch" in w for w in res.warnings))
        # an ad-hoc timeline (no spec label) does not take the spec's identity either
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res2, events2 = self.run_with(other, spec_digest="")
        self.assertEqual(res2.spec_digest, "")
        self.assertEqual(events2.recent("executor.run_start")[0]["spec_digest"], "")
        self.assertEqual(events2.recent("executor.run_end")[0]["spec_digest"], "")
        self.assertEqual(res2.sound_cues, [])
        self.assertTrue(any("ad hoc" in w for w in res2.warnings))


# ---------------------------------------------------------------------- tick statistics
def synthetic_log() -> TickLog:
    planned_ms = [0, 20, 40, 60, 80, 100]
    actual_ms = [0, 20, 40, 60, 85, 100]  # intervals 20 20 20 25 15
    send_ms = [1, 2, 3, 4, 5, 6]
    return TickLog([TickRecord(k=i, tick=i, planned_ns=p * MS, actual_ns=a * MS, send_ns=s * MS,
                               skipped_before=1 if i == 3 else 0, ok=i != 5)
                    for i, (p, a, s) in enumerate(zip(planned_ms, actual_ms, send_ms))])


class TestTickStatistics(unittest.TestCase):
    def test_summary_matches_hand_computed_values(self):
        s = synthetic_log().summary(PERIOD, late_threshold_ms=5.0)
        self.assertEqual((s["n_ticks"], s["n_sent"], s["skipped_samples"]), (6, 5, 1))
        self.assertAlmostEqual(s["duration_s"], 0.1, places=12)
        self.assertAlmostEqual(s["effective_hz"], 50.0, places=9)
        self.assertEqual(s["period_ms"], 20.0)
        iv = s["interval_ms"]
        expected_iv = {"mean": 20.0, "std": math.sqrt(10.0), "min": 15.0, "p50": 20.0, "p95": 24.0, "p99": 24.8,
                       "max": 25.0}
        for key, value in expected_iv.items():
            self.assertAlmostEqual(iv[key], value, places=9, msg=key)
        self.assertAlmostEqual(s["jitter_ms"], math.sqrt(10.0), places=9)
        self.assertAlmostEqual(s["jitter_rms_ms"], math.sqrt(10.0), places=9)
        late = s["late_ms"]
        for key, value in {"mean": 5.0 / 6.0, "p50": 0.0, "p95": 3.75, "p99": 4.75, "max": 5.0}.items():
            self.assertAlmostEqual(late[key], value, places=9, msg=key)
        self.assertEqual(s["late_ticks"], 0)  # strictly later than the threshold
        self.assertEqual(synthetic_log().summary(PERIOD, late_threshold_ms=4.0)["late_ticks"], 1)
        send = s["send_ms"]
        for key, value in {"mean": 3.5, "p95": 5.75, "max": 6.0}.items():
            self.assertAlmostEqual(send[key], value, places=9, msg=key)
        json.dumps(s)

    def test_jitter_rms_includes_a_mean_period_error(self):
        log = TickLog([TickRecord(k=i, tick=i, planned_ns=20 * i * MS, actual_ns=21 * i * MS) for i in range(4)])
        s = log.summary(PERIOD)
        self.assertAlmostEqual(s["jitter_ms"], 0.0, places=12)
        self.assertAlmostEqual(s["jitter_rms_ms"], 1.0, places=12)
        self.assertAlmostEqual(s["effective_hz"], 3 / 0.063, places=9)

    def test_summary_is_robust_for_zero_and_one_record(self):
        s0 = TickLog().summary(PERIOD)
        self.assertEqual((s0["n_ticks"], s0["n_sent"], s0["skipped_samples"], s0["late_ticks"]), (0, 0, 0, 0))
        self.assertEqual(s0["duration_s"], 0.0)
        self.assertIsNone(s0["effective_hz"])
        self.assertIsNone(s0["jitter_ms"])
        for group in ("interval_ms", "late_ms", "send_ms"):
            self.assertTrue(all(v is None for v in s0[group].values()), group)
        json.dumps(s0)
        s1 = TickLog([TickRecord(0, 0, 5 * MS, 7 * MS, 1 * MS)]).summary(PERIOD)
        self.assertEqual(s1["n_ticks"], 1)
        self.assertIsNone(s1["effective_hz"])
        self.assertTrue(all(v is None for v in s1["interval_ms"].values()))
        self.assertEqual((s1["late_ms"]["mean"], s1["late_ms"]["max"], s1["send_ms"]["mean"]), (2.0, 2.0, 1.0))
        json.dumps(s1)

    def test_nominal_period_from_meta(self):
        self.assertEqual(TickLog(meta={"period_ns": PERIOD}).summary()["period_ms"], 20.0)
        with self.assertRaises(ValueError):
            TickLog().summary()

    def test_late_threshold_follows_the_executor_setting(self):
        # Every tick 3 ms late with a 2 ms executor threshold: every summary of the run must count them.
        tl = make_timeline(11)
        clock = VirtualClock(wake_delay_ns=lambda _d: 3 * MS)
        res = Executor(FakeBackend(clock), clock=clock, late_threshold_ms=2.0).run(prepared_for(tl))
        self.assertEqual(res.ticks.meta["late_threshold_ms"], 2.0)
        self.assertEqual(res.summary()["ticks"]["late_ticks"], 11)
        self.assertEqual(res.ticks.summary()["late_ticks"], 11)
        self.assertEqual(res.ticks.summary(PERIOD)["late_ticks"], 11)  # what the CLI's _save_run calls
        self.assertEqual(res.ticks.summary(PERIOD)["late_threshold_ms"], 2.0)
        self.assertEqual(res.ticks.summary(PERIOD, late_threshold_ms=5.0)["late_ticks"], 0)  # explicit wins
        bare = TickLog(list(res.ticks.records), meta={"period_ns": PERIOD})  # no executor meta -> default
        self.assertEqual(bare.summary()["late_threshold_ms"], DEFAULT_LATE_THRESHOLD_MS)
        self.assertEqual(bare.summary()["late_ticks"], 0)

    def test_csv_columns_and_values(self):
        log = TickLog([TickRecord(0, 0, 1000 * MS, 1000 * MS + 300_000, 200_000),
                       TickRecord(3, 1, 1020 * MS, 1065 * MS, 1_500_000, skipped_before=2)])
        self.assertEqual(list(CSV_COLUMNS), ["tick", "k", "planned_s", "actual_s", "late_ms", "interval_ms",
                                             "send_ms", "skipped_before"])
        rows = log.to_rows()
        self.assertIsNone(rows[0]["interval_ms"])
        self.assertAlmostEqual(rows[1]["interval_ms"], 64.7, places=9)
        with tempfile.TemporaryDirectory() as d:
            path = log.to_csv(Path(d) / "sub" / "ticks.csv")
            with path.open(newline="", encoding="utf-8") as fh:
                table = list(csv.reader(fh))
            empty = TickLog().to_csv(Path(d) / "empty.csv")
            with empty.open(newline="", encoding="utf-8") as fh:
                empty_table = list(csv.reader(fh))
        self.assertEqual(table[0], list(CSV_COLUMNS))
        self.assertEqual(table[1], ["0", "0", "0.000000000", "0.000300000", "0.300000", "", "0.200000", "0"])
        self.assertEqual(table[2], ["1", "3", "0.020000000", "0.065000000", "45.000000", "64.700000", "1.500000",
                                    "2"])
        self.assertEqual(empty_table, [list(CSV_COLUMNS)])

    def test_executor_log_csv_round_trip(self):
        clock = VirtualClock(start_ns=123 * MS)
        res = Executor(FakeBackend(clock), clock=clock).run(prepared_for(make_timeline(4)))
        rows = res.ticks.to_rows()
        self.assertEqual([r["planned_s"] for r in rows], [0.0, 0.02, 0.04, 0.06])  # relative to the first tick
        self.assertEqual([r["k"] for r in rows], [0, 1, 2, 3])


# ---------------------------------------------------------------------- real clock (this PC)
def sleep_overshoot_p95_ms(n: int = 10, period_s: float = 0.02) -> float:
    """p95 overshoot (ms) of ``n`` bare ``time.sleep(period_s)`` calls: a load probe independent of the executor."""
    over = []
    for _ in range(n):
        t = time.perf_counter_ns()
        time.sleep(period_s)
        over.append((time.perf_counter_ns() - t) / 1e6 - period_s * 1e3)
    return float(np.percentile(over, 95))


class TestRealClock(unittest.TestCase):
    """0.4 s at 50 Hz with the real clock and a no-op backend (pc_measured, this PC only).

    Invariants that hold under any load are asserted on every attempt. The V2.4 rate / jitter target
    (interval p95 <= 21 ms, lateness < one period, effective rate within 10 % of 50 Hz) is asserted
    against the loop itself: an attempt that misses it fails the test when bare 20 ms sleeps around it
    were quiet (p95 overshoot <= 5 ms), so a systematically slow or jittery loop cannot pass; only when
    the machine itself was overloaded around every missed attempt is the target skipped.
    """

    ATTEMPTS = 3
    QUIET_PROBE_MS = 5.0

    def assert_invariants(self, res, s, n: int) -> None:
        self.assertTrue(res.completed)
        self.assertEqual(res.commands[-1].k, n - 1)  # the final sample is always sent
        self.assertEqual(s["n_ticks"] + s["skipped_samples"], n)
        self.assertEqual(s["n_sent"], s["n_ticks"])
        t0 = res.started_ns
        for r in res.ticks.records:
            self.assertEqual(r.planned_ns, t0 + round((r.k - r.skipped_before) * 1e9 / 50.0))  # absolute grid
            self.assertGreaterEqual(r.actual_ns, r.planned_ns - 1 * MS)  # never wakes (much) early
        actual = [r.actual_ns for r in res.ticks.records]
        self.assertEqual(actual, sorted(actual))
        self.assertEqual(len(res.ticks.to_rows()), s["n_ticks"])
        self.assertIsNotNone(s["interval_ms"]["p95"])  # intervals recorded whatever the load
        self.assertEqual(res.ticks.meta["clock"], "RealClock")

    def test_short_real_clock_run_measures_the_loop(self):
        tl = make_timeline(21)  # 0.4 s at 50 Hz
        attempts = []
        for _ in range(self.ATTEMPTS):
            before = sleep_overshoot_p95_ms()
            res = Executor(FakeBackend(), clock=RealClock(), rate_hz=50.0).run(prepared_for(tl))
            after = sleep_overshoot_p95_ms()
            s = res.ticks.summary(PERIOD)
            self.assert_invariants(res, s, len(tl))
            met = (s["interval_ms"]["p95"] <= 21.0 and s["late_ms"]["max"] < 20.0
                   and 45.0 <= s["effective_hz"] <= 55.0)
            attempts.append({"met_v2_4": met, "quiet": max(before, after) <= self.QUIET_PROBE_MS,
                             "probe_p95_ms": [round(before, 3), round(after, 3)],
                             "interval_p95_ms": s["interval_ms"]["p95"], "late_max_ms": s["late_ms"]["max"],
                             "effective_hz": s["effective_hz"], "skipped": s["skipped_samples"]})
            if met:
                return
        if not any(a["quiet"] for a in attempts):
            self.skipTest("machine overloaded around every attempt (bare 20 ms sleeps overshoot p95 > "
                          f"{self.QUIET_PROBE_MS} ms); V2.4 target not asserted: {json.dumps(attempts)}")
        self.fail(f"the loop missed the V2.4 target with a quiet machine: {json.dumps(attempts)}")


# ---------------------------------------------------------------------- measure_tick_timing
class TestMeasureTickTiming(unittest.TestCase):
    def test_virtual_clock_smoke(self):
        clock = VirtualClock(wake_delay_ns=lambda d: (d // PERIOD) % 7 * 300_000)  # 0..1.8 ms late
        fake = FakeBackend(clock, send_cost_ns=lambda _i: 100_000)
        log = measure_tick_timing(fake, duration_s=10.0, rate_hz=50.0, clock=clock)
        self.assertEqual(len(log), 501)
        s = log.summary()
        self.assertEqual((s["skipped_samples"], s["late_ticks"]), (0, 0))
        self.assertAlmostEqual(s["late_ms"]["max"], 1.8, places=9)
        self.assertAlmostEqual(s["effective_hz"], 50.0, delta=0.01)
        self.assertAlmostEqual(s["send_ms"]["mean"], 0.1, places=9)
        self.assertIn("REST", log.meta["purpose"])
        self.assertTrue(log.meta["completed"])
        for head, ant, body, _t in fake.sent:
            np.testing.assert_array_equal(head, np.eye(4))
            self.assertEqual(ant, INIT_ANTENNAS)
            self.assertEqual(body, 0.0)

    def test_refuses_real_hardware_backends(self):
        clock = VirtualClock()
        fake = FakeBackend(clock, capabilities=Capabilities(real_hardware=True))
        with self.assertRaises(ExecutionRefused):
            measure_tick_timing(fake, duration_s=1.0, clock=clock)
        self.assertEqual(fake.calls, [])

    def test_backend_error_raises(self):
        clock = VirtualClock()
        with self.assertLogs(EXEC_LOGGER, level="WARNING"), self.assertRaises(BackendError):
            measure_tick_timing(FakeBackend(clock, fail_at=10), duration_s=1.0, clock=clock)

    def test_stationary_rest_plan_is_checked_and_on_the_grid(self):
        p = stationary_rest_motion(0.41, 50.0)
        tl = p.timeline
        self.assertEqual(len(tl), 22)  # K = ceil(20.5) = 21
        self.assertEqual(tl.validate(), [])
        self.assertTrue(p.runnable)
        self.assertGreater(p.report.metrics["min_stewart_margin_deg"], DEFAULT_POLICY.min_stewart_margin_deg)
        self.assertLess(p.report.metrics["auto_body_shift_deg"], 1e-6)
        self.assertEqual([w.code for w in p.report.warnings], ["constant_hold_check"])
        self.assertTrue(np.all(tl.head == np.eye(4)))
        self.assertTrue(np.all(tl.antennas == np.array(INIT_ANTENNAS)))
        self.assertEqual(len(stationary_rest_motion(0.0).timeline), 1)
        self.assertEqual(len(stationary_rest_motion(10.0).timeline), 501)
        with self.assertRaises(ValueError):
            stationary_rest_motion(-1.0)


# ---------------------------------------------------------------------- goto
GOTO_TARGET = Pose6(z=0.005, pitch=0.1)
GOTO_ANT = (-0.3, 0.3)
GOTO_BODY = 0.2


def goto_spec(method: Easing = Easing.CARTOON, duration: float = 0.5, head_keys: int = 1,
              sound: SoundCue | None = None) -> MotionSpec:
    return MotionSpec(
        name="success", variant="neutral", intent="goto test", valence=0.0, arousal=0.0,
        principles=(PrincipleUse(Principle.SLOW_IN_SLOW_OUT, "test"),),
        head=tuple(HeadKey(duration=duration, pose=GOTO_TARGET, easing=method) for _ in range(head_keys)),
        antennas=(AntennaKey(duration, GOTO_ANT, method),), body=(BodyKey(duration, GOTO_BODY, method),),
        sound=sound)


def goto_plan(method: Easing = Easing.CARTOON, duration: float = 0.5, head_keys: int = 1,
              sound: SoundCue | None = None, passes: bool = True, spec: MotionSpec | None = None) -> PreparedMotion:
    """The planner's timeline of the spec (spec_digest = spec.digest()) + a report bound to it, like the checker."""
    spec = spec if spec is not None else goto_spec(method, duration, head_keys, sound)
    tl = plan(spec)
    return PreparedMotion(tl, report_for(tl, passes=passes,
                                         violations=() if passes else (Violation("ik_nan", "x"),)), spec)


def call_goto(ex: Executor, prepared: PreparedMotion, duration: float = 0.5, method: Easing | str = "cartoon",
              **kwargs):
    return ex.goto(GOTO_TARGET.matrix(), GOTO_ANT, GOTO_BODY, duration, method, prepared=prepared, **kwargs)


class TestGoto(unittest.TestCase):
    def assert_goto_refused(self, prepared: PreparedMotion, duration: float, method: Easing | str,
                            fragment: str) -> None:
        fake = FakeBackend(VirtualClock())
        ex = Executor(fake, clock=fake.clock)
        with self.assertRaises(ExecutionRefused) as cm:
            call_goto(ex, prepared, duration, method)
        self.assertIn(fragment, str(cm.exception))
        self.assertEqual(fake.calls, [])  # ZERO backend calls
        self.assertIsNone(ex.last_result)

    def test_goto_sends_one_blocking_call_with_explicit_body_yaw(self):
        clock = VirtualClock(start_ns=MS)
        fake = FakeBackend(clock, goto_cost_ns=500 * MS)
        p = goto_plan()
        self.assertEqual(p.timeline.spec_digest, p.spec.digest())
        ex = Executor(fake, clock=clock)
        res = call_goto(ex, p, record_present=True)
        self.assertTrue(res.completed)
        self.assertIsNone(res.error)
        self.assertIsNone(res.failed_command)
        self.assertTrue(res.end_state_known)
        self.assertEqual(res.strategy, "goto")
        self.assertEqual(res.spec_digest, p.spec.digest())
        self.assertEqual([c[0] for c in fake.calls], ["present", "goto_target", "present"])
        head, ant, body, duration, method = fake.gotos[0]
        np.testing.assert_array_equal(head, GOTO_TARGET.matrix())
        self.assertEqual((ant, body, duration, method), (GOTO_ANT, GOTO_BODY, 0.5, "cartoon"))
        self.assertIsInstance(body, float)
        (k, rec), = res.commands
        self.assertEqual(k, len(p.timeline) - 1)
        self.assertEqual((rec.kind, rec.t_ns, rec.duration, rec.method), ("goto_target", MS, 0.5, "cartoon"))
        self.assertEqual(len(res.ticks), 1)
        self.assertEqual(res.ticks.records[0].send_ns, 500 * MS)
        self.assertEqual(len(res.present), 2)
        res2 = ex.goto(GOTO_TARGET.matrix(), list(GOTO_ANT), GOTO_BODY, 0.5, Easing.CARTOON, prepared=p)
        self.assertTrue(res2.completed)
        self.assertEqual(fake.gotos[1][4], "cartoon")

    def test_goto_refusals_make_zero_backend_calls(self):
        good = dict(head=GOTO_TARGET.matrix(), antennas=GOTO_ANT, body_yaw=GOTO_BODY, duration=0.5,
                    method="cartoon", prepared=goto_plan())
        bad_head = GOTO_TARGET.matrix()
        bad_head[0, 0] = np.nan
        cases = {
            "method differs from the checked plan": dict(method="minjerk"),
            "unknown method": dict(method="bouncy"),
            "duration differs": dict(duration=0.4),
            "head target differs": dict(head=Pose6(z=0.005, pitch=0.11).matrix()),
            "antennas differ": dict(antennas=(-0.3, 0.31)),
            "body differs": dict(body_yaw=0.25),
            "body yaw omitted": dict(body_yaw=None),
            "non-finite head": dict(head=bad_head),
            "zero duration": dict(duration=0.0),
            "no spec": dict(prepared=PreparedMotion(goto_plan().timeline, goto_plan().report, None)),
            "two head keys": dict(prepared=goto_plan(head_keys=2)),
            "failing report": dict(prepared=goto_plan(passes=False)),
        }
        for label, override in cases.items():
            with self.subTest(label):
                fake = FakeBackend(VirtualClock())
                args = {**good, **override}
                with self.assertRaises(ExecutionRefused):
                    Executor(fake, clock=fake.clock).goto(args["head"], args["antennas"], args["body_yaw"],
                                                          args["duration"], args["method"],
                                                          prepared=args["prepared"])
                self.assertEqual(fake.calls, [])
        for caps, kwargs in ((Capabilities(goto=False), {}), (Capabilities(present=False), {"record_present": True})):
            with self.subTest(caps=caps):
                fake = FakeBackend(VirtualClock(), capabilities=caps)
                with self.assertRaises(ExecutionRefused):
                    Executor(fake, clock=fake.clock).goto(good["head"], GOTO_ANT, GOTO_BODY, 0.5, "cartoon",
                                                          prepared=good["prepared"], **kwargs)
                self.assertEqual(fake.calls, [])

    def test_goto_refuses_a_spec_the_checked_plan_was_not_planned_from(self):
        slow = goto_plan(Easing.MIN_JERK, 2.0)  # a gentle plan: planned and checked
        fast = goto_spec(Easing.CARTOON, 0.1)  # same end state, never checked (about 50x the Stewart speed)
        self.assertTrue(slow.runnable)
        swapped = dataclasses.replace(slow, spec=fast)
        self.assertTrue(swapped.runnable)  # the contract alone does not bind the spec
        self.assert_goto_refused(swapped, 0.1, "cartoon", "spec_digest mismatch")
        # A multi-key plan with the same end state is not the plan of a one-key goto either.
        multi_spec = dataclasses.replace(
            goto_spec(), variant="expressive",
            head=(HeadKey(0.5, Pose6(pitch=-0.2)), HeadKey(0.5, Pose6(yaw=0.4)), HeadKey(0.5, GOTO_TARGET)))
        self.assert_goto_refused(dataclasses.replace(goto_plan(spec=multi_spec), spec=fast), 0.1, "cartoon",
                                 "spec_digest mismatch")
        # The same samples without the planner's label (ad hoc): the spec cannot be bound to them.
        adhoc = dataclasses.replace(slow.timeline, spec_digest="")
        self.assertEqual(adhoc.digest(), slow.timeline.digest())
        self.assert_goto_refused(PreparedMotion(adhoc, report_for(adhoc), slow.spec), 2.0, "minjerk", "ad hoc")
        # The report says it checked another spec.
        other_report = dataclasses.replace(slow.report, spec_digest=fast.digest())
        self.assert_goto_refused(PreparedMotion(slow.timeline, other_report, slow.spec), 2.0, "minjerk",
                                 "report spec_digest mismatch")
        # A relabelled timeline under a report without a spec label is still caught by its duration.
        relabelled = dataclasses.replace(slow.timeline, spec_digest=fast.digest())
        self.assert_goto_refused(PreparedMotion(relabelled, report_for(relabelled, spec_digest=""), fast), 0.1,
                                 "cartoon", "checked plan lasts 2 s")
        # Control: the checked spec itself runs, and the result names it.
        fake = FakeBackend(VirtualClock())
        res = call_goto(Executor(fake, clock=fake.clock), slow, 2.0, "minjerk")
        self.assertTrue(res.completed)
        self.assertEqual(res.spec_digest, slow.spec.digest())
        self.assertEqual(fake.gotos[0][3:], (2.0, "minjerk"))

    def test_goto_sweep_needs_one_checked_plan_per_spec(self):
        base = goto_plan(Easing.CARTOON, 0.5)
        for d in (0.1, 0.25, 0.75, 1.0):  # Phase 3 duration sweep reusing one checked plan
            with self.subTest(duration=d):
                self.assert_goto_refused(dataclasses.replace(base, spec=goto_spec(Easing.CARTOON, d)), d, "cartoon",
                                         "spec_digest mismatch")
        for method in (Easing.LINEAR, Easing.MIN_JERK, Easing.EASE_IN_OUT):  # easing sweep
            with self.subTest(method=method):
                self.assert_goto_refused(dataclasses.replace(base, spec=goto_spec(method, 0.5)), 0.5, method.value,
                                         "spec_digest mismatch")
        with self.subTest("tempo knob"):
            self.assert_goto_refused(dataclasses.replace(base, spec=base.spec.scaled(tempo=2.0)), 0.25, "cartoon",
                                     "spec_digest mismatch")
        # The intended sweep: plan and check every spec, then run each.
        fake = FakeBackend(VirtualClock())
        ex = Executor(fake, clock=fake.clock)
        for d in (0.25, 0.5, 1.0):
            self.assertTrue(call_goto(ex, goto_plan(Easing.CARTOON, d), d).completed)
        self.assertTrue(call_goto(ex, goto_plan(spec=base.spec.scaled(tempo=2.0)), 0.25).completed)
        self.assertEqual([g[3] for g in fake.gotos], [0.25, 0.5, 1.0, 0.25])

    def test_goto_timeout_after_dispatch_keeps_the_attempted_command(self):
        # SDK: send_task_request puts the task on the wire, then wait_for_task_completion raises TimeoutError
        # (reachy_mini.py:721-722, io/ws_client.py:278, 292); SdkBackend wraps it in BackendError.
        clock = VirtualClock()
        fake = FakeBackend(clock, goto_cost_ns=1500 * MS, goto_error_after_dispatch=True,
                           goto_error=BackendError("goto_target failed: Task did not complete in time."))
        p = goto_plan()
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res = call_goto(Executor(fake, clock=clock), p)
        self.assertEqual(len(fake.gotos), 1)  # the daemon received the task
        self.assertFalse(res.completed)
        self.assertIn("did not complete", res.error)
        self.assertEqual(res.commands, [])  # no call returned without error ...
        self.assertIsNone(res.last_sample)
        k, rec = res.failed_command  # ... but the attempted command is kept
        self.assertEqual(k, len(p.timeline) - 1)
        self.assertEqual((rec.kind, rec.duration, rec.method, rec.antennas, rec.body_yaw),
                         ("goto_target", 0.5, "cartoon", GOTO_ANT, GOTO_BODY))
        np.testing.assert_array_equal(rec.head, GOTO_TARGET.matrix())
        self.assertFalse(res.end_state_known)
        self.assertIn(GOTO_IN_FLIGHT_WARNING, res.warnings)
        self.assertEqual([(r.ok, r.send_ns) for r in res.ticks.records], [(False, 1500 * MS)])
        s = res.summary()
        self.assertEqual((s["failed_k"], s["failed_kind"], s["end_state_known"], s["n_commands"]),
                         (k, "goto_target", False, 0))
        json.dumps(s)

    def test_goto_backend_error_is_recorded(self):
        clock = VirtualClock()
        fake = FakeBackend(clock, goto_error=BackendError("timeout"))
        with self.assertLogs(EXEC_LOGGER, level="WARNING"):
            res = call_goto(Executor(fake, clock=clock), goto_plan())
        self.assertFalse(res.completed)
        self.assertIn("timeout", res.error)
        self.assertEqual(res.commands, [])
        self.assertEqual(res.failed_command.record.kind, "goto_target")  # whether it got through is unknown
        self.assertFalse(res.end_state_known)
        self.assertEqual([r.ok for r in res.ticks.records], [False])

    def test_goto_interrupt_is_recorded_then_propagates(self):
        clock = VirtualClock()
        fake = FakeBackend(clock, goto_error=Abort("ctrl-c"), goto_error_after_dispatch=True)
        ex = Executor(fake, clock=clock)
        with self.assertRaises(Abort):
            call_goto(ex, goto_plan())
        res = ex.last_result
        self.assertIn("interrupted during goto_target", res.error)
        self.assertIsNotNone(res.failed_command)
        self.assertFalse(res.end_state_known)
        self.assertFalse(ex.busy)

    def test_goto_does_not_log_sound_cues(self):
        clock = VirtualClock()
        res = call_goto(Executor(FakeBackend(clock), clock=clock), goto_plan(sound=SoundCue("x.wav", 0.0)))
        self.assertTrue(res.completed)
        self.assertEqual(res.sound_cues, [])
        self.assertTrue(any("sound cue" in w for w in res.warnings))


# ---------------------------------------------------------------------- thread priority
class TestThreadPriority(unittest.TestCase):
    def test_rejects_unknown_names(self):
        with self.assertRaises(ValueError):
            set_current_thread_priority("realtime")

    def test_normal_leaves_the_thread_alone(self):
        self.assertFalse(set_current_thread_priority("normal"))

    @unittest.skipUnless(sys.platform == "win32", "Windows thread priorities")
    def test_sets_the_priority_of_the_calling_thread_only(self):
        main_before = current_thread_priority()
        out = {}

        def work():
            out["before"] = current_thread_priority()
            out["below"] = set_current_thread_priority("below_normal")
            out["after_below"] = current_thread_priority()
            out["above"] = set_current_thread_priority("above_normal")
            out["after_above"] = current_thread_priority()

        t = threading.Thread(target=work)
        t.start()
        t.join(5.0)
        self.assertEqual(out, {"before": 0, "below": True, "after_below": -1, "above": True, "after_above": 1})
        self.assertEqual(current_thread_priority(), main_before)


if __name__ == "__main__":
    unittest.main()
