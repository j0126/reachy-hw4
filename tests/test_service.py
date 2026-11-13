"""MotionService with the Mock backend in real time (short motions; no daemon, no robot)."""

import math
import time
import unittest

import numpy as np

from reachy_motion.backends.mock import MockBackend
from reachy_motion.library.pose import REST, Pose6, pose_from_matrix
from reachy_motion.library.spec import Easing, HeadKey, MotionSpec, Principle, PrincipleUse
from reachy_motion.service import HandleState, MotionService, Priority, same_state


def nod(pitch_deg: float = 8.0, dur: float = 0.25, name: str = "success", variant: str = "neutral",
        z_mm: float = 0.0) -> MotionSpec:
    return MotionSpec(name=name, variant=variant, intent="test nod", valence=0.1, arousal=0.0,
                      principles=(PrincipleUse(Principle.TIMING, "test"),),
                      head=(HeadKey(dur, Pose6.from_deg_mm(pitch_deg=pitch_deg, z_mm=z_mm), Easing.MIN_JERK),
                            HeadKey(dur, Pose6(), Easing.MIN_JERK)))


def hold_away(pitch_deg: float = 12.0, dur: float = 0.3, hold: float = 1.5) -> MotionSpec:
    """Ends away from rest is not allowed by the drafts' rule, but a long hold mid-motion is: used for preemption."""
    return MotionSpec(name="boredom", variant="neutral", intent="long", valence=0.0, arousal=0.0,
                      principles=(PrincipleUse(Principle.TIMING, "test"),),
                      head=(HeadKey(dur, Pose6.from_deg_mm(pitch_deg=pitch_deg), Easing.MIN_JERK, hold),
                            HeadKey(dur, Pose6(), Easing.MIN_JERK)))


class ServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MockBackend(structure="robot")
        self.backend.connect()
        self.events: list[dict] = []
        self.svc = MotionService(self.backend, record_present=True)
        self.svc.on_event(self.events.append)
        self.svc.start()

    def tearDown(self) -> None:
        self.svc.close()
        self.backend.close()

    def kinds(self, key: str | None = None) -> list[str]:
        return [e["kind"] for e in self.events if key is None or e["key"] == key]


class TestPlay(ServiceTestCase):
    def test_play_runs_planned_samples_and_ends_done(self):
        h = self.svc.play(nod())
        self.assertTrue(h.wait(10.0))
        self.assertEqual(h.state, HandleState.DONE, h.reason)
        self.assertTrue(h.result.completed)
        self.assertEqual(self.backend.motor_command_count, len(h.prepared.timeline))  # starts at rest: no blend
        last = self.backend.commands[-1]
        self.assertTrue(np.allclose(last.head, np.eye(4), atol=1e-12))
        self.assertEqual(self.kinds(), ["started", "finished"])

    def test_play_never_blocks(self):
        first = self.svc.play(hold_away(hold=1.0))
        t = time.perf_counter()
        second = self.svc.play(nod())
        self.assertLess(time.perf_counter() - t, 0.05)
        self.assertTrue(second.wait(15.0))
        self.assertEqual(first.state, HandleState.DONE)
        self.assertEqual(second.state, HandleState.DONE)

    def test_rejected_motion_sends_nothing(self):
        h = self.svc.play(nod(z_mm=30.0))  # z +30 mm: IK NaN / envelope
        self.assertTrue(h.wait(10.0))
        self.assertEqual(h.state, HandleState.REJECTED)
        self.assertIn("initial policy", h.reason)
        self.assertEqual(self.backend.motor_command_count, 0)
        self.assertEqual(self.kinds(), ["rejected"])

    def test_unknown_motion_is_rejected_not_raised(self):
        h = self.svc.play("dance", "expressive")
        self.assertTrue(h.wait(1.0))
        self.assertEqual(h.state, HandleState.REJECTED)


class TestPreemptionAndCancel(ServiceTestCase):
    def test_reaction_preempts_with_a_continuous_blend(self):
        long = self.svc.play(hold_away(pitch_deg=12.0, hold=2.0))
        time.sleep(0.5)  # inside the hold at pitch 12
        n_before = self.backend.motor_command_count
        r = self.svc.play(nod(pitch_deg=6.0, name="success", variant="expressive"), priority=Priority.REACTION)
        self.assertTrue(r.wait(15.0))
        self.assertEqual(long.state, HandleState.PREEMPTED)
        self.assertEqual(r.state, HandleState.DONE, r.reason)
        self.assertIn("transition", r.reason or "")
        pitches = [math.degrees(pose_from_matrix(c.head).pitch) for c in self.backend.commands[n_before - 1:]]
        self.assertLess(max(abs(np.diff(pitches))), 1.5)  # no jump at the switch (50 Hz steps of the blend)
        self.assertTrue(same_state(self.svc._last_state, REST))

    def test_equal_priority_queues_and_interrupt_preempts(self):
        a = self.svc.play(hold_away(hold=0.4))
        b = self.svc.play(nod())
        self.assertTrue(b.wait(15.0))
        self.assertEqual((a.state, b.state), (HandleState.DONE, HandleState.DONE))
        c = self.svc.play(hold_away(hold=2.0))
        time.sleep(0.4)
        d = self.svc.play(nod(), interrupt=True)
        self.assertTrue(d.wait(15.0))
        self.assertEqual((c.state, d.state), (HandleState.PREEMPTED, HandleState.DONE))

    def test_lower_priority_cannot_interrupt(self):
        a = self.svc.play(hold_away(hold=0.8), priority=Priority.REACTION)
        time.sleep(0.3)
        b = self.svc.play(nod(), priority=Priority.NORMAL, interrupt=True)
        self.assertTrue(b.wait(15.0))
        self.assertEqual((a.state, b.state), (HandleState.DONE, HandleState.DONE))

    def test_cancel_running_and_pending(self):
        a = self.svc.play(hold_away(hold=2.0))
        b = self.svc.play(nod())
        time.sleep(0.4)
        b.cancel()
        a.cancel()
        self.assertTrue(a.wait(5.0) and b.wait(5.0))
        self.assertEqual(a.state, HandleState.CANCELLED)
        self.assertEqual(b.state, HandleState.CANCELLED)

    def test_stop_blends_to_rest(self):
        self.svc.play(hold_away(hold=2.0))
        time.sleep(0.5)
        rest = self.svc.stop(blend_to_rest=True)
        self.assertTrue(rest.wait(10.0))
        self.assertEqual(rest.state, HandleState.DONE)
        self.assertTrue(np.allclose(self.backend.commands[-1].head, np.eye(4), atol=1e-9))


class TestIdle(ServiceTestCase):
    def test_idle_starts_after_quiet_time_and_is_preempted(self):
        self.svc.set_idle(hold_away(hold=2.0), after_s=0.3)
        deadline = time.perf_counter() + 5.0
        while "started" not in self.kinds() and time.perf_counter() < deadline:
            time.sleep(0.02)
        self.assertIn("started", self.kinds())
        self.svc.clear_idle()
        h = self.svc.play(nod())
        self.assertTrue(h.wait(15.0))
        self.assertEqual(h.state, HandleState.DONE)
        self.assertIn("preempted", self.kinds())


class TestClose(unittest.TestCase):
    def test_close_joins_and_cancels(self):
        backend = MockBackend()
        backend.connect()
        svc = MotionService(backend).start()
        h = svc.play(hold_away(hold=3.0))
        time.sleep(0.3)
        t = time.perf_counter()
        svc.close()
        self.assertLess(time.perf_counter() - t, 2.0)
        self.assertTrue(h.done)
        self.assertEqual(svc.play(nod()).state, HandleState.CANCELLED)
        backend.close()


if __name__ == "__main__":
    unittest.main()
