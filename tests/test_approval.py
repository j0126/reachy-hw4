"""Robot approval gate: validation matrix, policy binding, strict file loading with provenance, human-only
template, terminal confirmation.

No robot, no network, no files outside a temporary directory. Times are injected (``now`` / ``_now``).
Writing an approval file here stands in for the HUMAN supervisor saving one; it only ever happens inside a
temporary directory of a test.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np

from reachy_motion.safety.approval import (
    APPROVAL_KEYS,
    MAX_APPROVAL_FILE_BYTES,
    MAX_VALIDITY_DAYS,
    METRIC_MARGIN_DEG,
    METRIC_SPEED_RATIO,
    ApprovalError,
    ApprovalRequest,
    ApprovalSource,
    RobotApproval,
    approval_template,
    confirm_interactively,
    format_problems,
    gate_problems,
    load_approval,
    policy_digest,
    policy_relaxations,
    require_approval,
    source_problems,
    validate_approval,
    worst_metrics,
)
from reachy_motion.safety.policy import DEFAULT_POLICY, SafetyPolicy, SafetyReport, Violation
from reachy_motion.timeline import PreparedMotion, Timeline

HOST = "192.168.0.15"
NOW = datetime(2026, 11, 12, 10, 0, 0)  # naive = local time of this PC
APPROVED_ID = "R2-20261112-a"
DEFAULT_SHA = policy_digest(DEFAULT_POLICY)
# A relaxed policy of the kind the review found accepted: wide envelope, detectors off, speeds unbounded.
LAX_POLICY = SafetyPolicy(name="my-relaxed", max_pitch_deg=89.0, max_roll_deg=89.0, max_psi_step_deg=1e9,
                          max_body_step_deg=1e9, z_range_mm=(-100.0, 100.0), max_antenna_abs_rad=1e9,
                          max_antenna_speed_ratio=100.0, max_body_speed_ratio=100.0, max_auto_body_shift_deg=1e9,
                          min_stewart_margin_deg=0.0, max_stewart_speed_ratio=1.0)


def tiny_timeline(name: str = "success", variant: str = "expressive", dz: float = 0.002) -> Timeline:
    """3 samples at 50 Hz: a real Timeline, so that digests are real Timeline.digest() values."""
    n = 3
    head = np.repeat(np.eye(4)[None], n, axis=0)
    head[:, 2, 3] = np.linspace(0.0, dz, n)
    return Timeline(name=name, variant=variant, rate_hz=50.0, duration=0.04, t=np.arange(n) / 50.0, head=head,
                    antennas=np.tile([-0.1745, 0.1745], (n, 1)), body_yaw=np.zeros(n),
                    head_key=np.zeros(n, dtype=int), antenna_key=np.zeros(n, dtype=int),
                    body_key=np.zeros(n, dtype=int))


def report_for(tl: Timeline, passes: bool = True, speed: float | None = 0.2, margin: float | None = 15.0,
               digest: str | None = None, policy: SafetyPolicy = DEFAULT_POLICY) -> SafetyReport:
    metrics = {}
    if speed is not None:
        metrics[METRIC_SPEED_RATIO] = speed
    if margin is not None:
        metrics[METRIC_MARGIN_DEG] = margin
    violations = () if passes else (Violation("stewart_margin", "joint too close to its limit", value=3.0,
                                              limit=10.0),)
    return SafetyReport(name=tl.name, variant=tl.variant, policy=policy, passes_policy=passes,
                        violations=violations, warnings=(), metrics=metrics,
                        timeline_digest=tl.digest() if digest is None else digest)


def make_request(stage: str = "R2", host: str = HOST, **report_kw) -> ApprovalRequest:
    tl1, tl2 = tiny_timeline("success", "expressive"), tiny_timeline("failure", "neutral", dz=-0.003)
    prepared = [PreparedMotion(tl1, report_for(tl1, **report_kw)), PreparedMotion(tl2, report_for(tl2))]
    return ApprovalRequest.from_prepared(host, stage, prepared)


def request_with(report: SafetyReport, tl: Timeline | None = None) -> ApprovalRequest:
    """One-plan request whose only report is ``report``."""
    tl = tiny_timeline("success", "expressive") if tl is None else tl
    return ApprovalRequest.from_prepared(HOST, "R2", [PreparedMotion(tl, report)])


def make_approval(request: ApprovalRequest, **kw) -> RobotApproval:
    """An approval built in code: fine for the content checks, refused by the robot gate (no file)."""
    base = dict(approval_id=APPROVED_ID, stage=request.stage, approved_by="Kim Supervisor",
                approved_on="2026-11-12", expires="2026-11-12T18:00:00", host=HOST, motions=request.motions,
                timeline_digests=request.timeline_digests, max_stewart_speed_ratio=0.3,
                min_stewart_margin_deg=12.0, policy_name=DEFAULT_POLICY.name, policy_sha256=DEFAULT_SHA,
                notes="unit test")
    base.update(kw)
    return RobotApproval(**base)


def valid_now_pair(stage: str = "R2") -> tuple[RobotApproval, ApprovalRequest]:
    """An approval that is valid at the real current time (for callers that cannot inject ``now``)."""
    request = make_request(stage=stage)
    now = datetime.now()
    approval = make_approval(request, approved_on=date.today().isoformat(),
                             expires=(now + timedelta(hours=2)).isoformat(timespec="seconds"))
    return approval, request


def write_approval(directory: str | Path, data: RobotApproval | dict | str, name: str = "approval.json") -> Path:
    """Stands in for the human saving the file (tests write only into a temporary directory)."""
    p = Path(directory) / name
    if isinstance(data, RobotApproval):
        data = data.to_dict()
    p.write_text(data if isinstance(data, str) else json.dumps(data, indent=2), encoding="utf-8")
    return p


def loaded_valid_now_pair(directory: str | Path, stage: str = "R2") -> tuple[RobotApproval, ApprovalRequest]:
    """``valid_now_pair`` saved to ``directory`` and read back with ``load_approval`` (has a ``source``)."""
    approval, request = valid_now_pair(stage)
    return load_approval(write_approval(directory, approval)), request


def problems_text(approval: RobotApproval, request: ApprovalRequest, now: datetime = NOW) -> str:
    return "\n".join(validate_approval(approval, request, now=now))


class TestValidationMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.request = make_request()
        self.approval = make_approval(self.request)

    def assertProblem(self, approval: RobotApproval, request: ApprovalRequest, fragment: str,
                      now: datetime = NOW) -> None:
        text = problems_text(approval, request, now)
        self.assertIn(fragment, text)
        with self.assertRaises(ApprovalError):
            require_approval(approval, request, now=now)

    def test_valid_approval_has_no_problems(self):
        self.assertEqual(validate_approval(self.approval, self.request, now=NOW), [])
        self.assertIs(require_approval(self.approval, self.request, now=NOW), self.approval)

    def test_request_from_prepared_uses_real_digests(self):
        tl = tiny_timeline("success", "expressive")
        self.assertEqual(self.request.motions, ("success:expressive", "failure:neutral"))
        self.assertEqual(self.request.timeline_digests[0], tl.digest())
        self.assertEqual(len(self.request.timeline_digests[0]), 64)
        self.assertEqual(len(self.request.reports), 2)

    # --- time
    def test_expired(self):
        self.assertProblem(self.approval, self.request, "expired", now=datetime(2026, 11, 12, 18, 0, 0))
        self.assertProblem(self.approval, self.request, "expired", now=datetime(2026, 11, 13, 9, 0, 0))

    def test_not_yet_valid(self):
        self.assertProblem(self.approval, self.request, "not yet valid", now=datetime(2026, 11, 11, 23, 59))

    def test_expires_before_approved_on(self):
        a = replace(self.approval, expires="2026-11-11T23:00:00")
        self.assertProblem(a, self.request, "is not after approved_on")

    def test_validity_window_is_capped(self):
        a = replace(self.approval, expires=f"2026-11-{12 + MAX_VALIDITY_DAYS}T10:00:00")
        self.assertProblem(a, self.request, f"more than {MAX_VALIDITY_DAYS} days")

    def test_timezone_aware_expiry(self):
        # 18:00 KST = 09:00 UTC; approved the day before so that the PC's own timezone does not matter
        a = replace(self.approval, approved_on="2026-11-11", expires="2026-11-12T18:00:00+09:00")
        utc = timezone.utc
        self.assertEqual(validate_approval(a, self.request, now=datetime(2026, 11, 12, 8, 59, tzinfo=utc)), [])
        self.assertProblem(a, self.request, "expired", now=datetime(2026, 11, 12, 9, 0, 1, tzinfo=utc))

    def test_naive_expiry_with_aware_now(self):
        before = datetime(2026, 11, 12, 17, 59).astimezone()  # local, aware
        after = datetime(2026, 11, 12, 18, 0, 1).astimezone()
        self.assertEqual(validate_approval(self.approval, self.request, now=before), [])
        self.assertProblem(self.approval, self.request, "expired", now=after)

    def test_dates_at_the_edge_of_the_range_give_problems_not_crashes(self):
        # Windows cannot convert naive times near 1970 or in year 9999 to local time (OSError 22)
        old = replace(self.approval, approved_on="1960-01-01", expires="1960-01-02T00:00:00")
        self.assertIn("expired", problems_text(old, self.request))
        far = replace(self.approval, approved_on="9999-12-31", expires="9999-12-31T23:59:59")
        self.assertTrue(validate_approval(far, self.request, now=NOW))

    def test_default_now_is_the_current_time(self):
        approval, request = valid_now_pair()
        self.assertEqual(validate_approval(approval, request), [])
        old = replace(approval, approved_on="2020-01-01", expires="2020-01-02T00:00:00")
        self.assertIn("expired", "\n".join(validate_approval(old, request)))
        with mock.patch("reachy_motion.safety.approval._now", return_value=datetime.now() + timedelta(hours=3)):
            self.assertIn("expired", "\n".join(validate_approval(approval, request)))

    def test_now_must_be_a_datetime(self):
        for now in (date(2026, 11, 12), "2026-11-12T10:00", 1_700_000_000):
            text = "\n".join(validate_approval(self.approval, self.request, now=now))  # type: ignore[arg-type]
            self.assertIn("now must be a datetime", text)

    # --- host / stage
    def test_host_mismatch(self):
        self.assertProblem(self.approval, make_request(host="reachy-mini.local"), "host mismatch")

    def test_host_comparison_ignores_case_and_trailing_dot(self):
        request = make_request(host="Reachy-Mini.local.")
        approval = make_approval(request, host="reachy-mini.local")
        self.assertEqual(validate_approval(approval, request, now=NOW), [])

    def test_empty_host(self):
        self.assertProblem(replace(self.approval, host="  "), self.request, "host is empty")

    def test_stage_mismatch(self):
        self.assertProblem(self.approval, make_request(stage="R1"), "stage mismatch")

    def test_r0_never_allows_motion(self):
        request = make_request(stage="R0")
        approval = make_approval(request, stage="R0")
        text = problems_text(approval, request)
        self.assertIn("R0 is REST GET only", text)
        with self.assertRaises(ApprovalError):
            require_approval(approval, request, now=NOW)

    def test_unknown_stage(self):
        request = make_request(stage="R9")
        self.assertProblem(make_approval(request, stage="R9"), request, "unknown approval stage")

    def test_stage_is_normalised(self):
        a = make_approval(self.request, stage=" r2 ")
        self.assertEqual(a.stage, "R2")
        self.assertEqual(validate_approval(a, self.request, now=NOW), [])

    # --- coverage
    def test_motion_not_covered(self):
        a = replace(self.approval, motions=("success:expressive",))
        self.assertProblem(a, self.request, "motion failure:neutral is not covered")

    def test_digest_not_covered(self):
        a = replace(self.approval, timeline_digests=self.request.timeline_digests[:1])
        self.assertProblem(a, self.request, "is not covered by approval")

    def test_digest_of_a_changed_timeline_is_not_covered(self):
        changed = tiny_timeline("success", "expressive", dz=0.0021)  # 0.1 mm more: other commands
        req = ApprovalRequest.from_prepared(HOST, "R2", [PreparedMotion(changed, report_for(changed))])
        self.assertProblem(make_approval(req, timeline_digests=self.request.timeline_digests), req,
                           "is not covered by approval")

    def test_uppercase_digest_is_normalised(self):
        a = replace(self.approval, timeline_digests=tuple(d.upper() for d in self.request.timeline_digests))
        self.assertEqual(validate_approval(a, self.request, now=NOW), [])

    def test_malformed_motion_and_digest_entries(self):
        a = replace(self.approval, motions=self.approval.motions + ("success",),
                    timeline_digests=self.approval.timeline_digests + ("abc123",))
        text = problems_text(a, self.request)
        self.assertIn("is not 'name:variant'", text)
        self.assertIn("is not a 64-character SHA-256", text)

    def test_empty_request_is_refused(self):
        empty = ApprovalRequest(host=HOST, stage="R2", motions=(), timeline_digests=(), reports=())
        text = problems_text(self.approval, empty)
        self.assertIn("request names no motions", text)
        self.assertIn("request lists no timeline digests", text)
        self.assertIn("request has no safety reports", text)

    def test_reports_must_match_the_request(self):
        stray = tiny_timeline("boredom", "expressive", dz=0.005)  # other commands -> other digest
        request = replace(self.request, reports=self.request.reports[:1] + (report_for(stray),))
        text = problems_text(self.approval, request)
        self.assertIn("report boredom:expressive is not one of the requested motions", text)
        self.assertIn("which is not in the request", text)
        self.assertIn("no safety report for timeline digest", text)
        self.assertIn("no safety report for motion failure:neutral", text)

    # --- reports vs policy and caps
    def test_report_not_passing_policy(self):
        request = make_request(passes=False)
        text = problems_text(make_approval(request), request)
        self.assertIn("does not pass policy", text)
        self.assertIn("stewart_margin", text)

    def test_passes_policy_must_be_exactly_true(self):
        tl = tiny_timeline()
        for value in (1, "yes", None):
            request = request_with(replace(report_for(tl), passes_policy=value), tl)
            self.assertProblem(make_approval(request), request, "does not pass policy")

    def test_report_that_passes_but_lists_violations_is_refused(self):
        tl = tiny_timeline()
        bad = replace(report_for(tl), violations=(Violation("ik_nan", "IK returned NaN at t=0.02 s", t=0.02),))
        request = request_with(bad, tl)
        self.assertProblem(make_approval(request), request, "inconsistent report")
        self.assertIn("ik_nan", problems_text(make_approval(request), request))

    def test_report_data_kind_must_be_computed(self):
        tl = tiny_timeline()
        for kind in ("mock", "simulated", "measured", ""):
            request = request_with(replace(report_for(tl), data_kind=kind), tl)
            self.assertProblem(make_approval(request), request, "data_kind")

    def test_report_with_malformed_fields_gives_problems_not_crashes(self):
        tl = tiny_timeline()
        for bad in (replace(report_for(tl), policy=None), replace(report_for(tl), violations=5),
                    replace(report_for(tl), metrics=None)):
            request = request_with(bad, tl)
            self.assertTrue(validate_approval(make_approval(request), request, now=NOW))

    def test_speed_ratio_above_cap(self):
        self.assertProblem(replace(self.approval, max_stewart_speed_ratio=0.15), self.request,
                           "above the approval cap")

    def test_negative_speed_ratio_is_refused(self):
        request = make_request(speed=-0.5)
        self.assertProblem(make_approval(request), request, "is negative")

    def test_margin_below_floor(self):
        self.assertProblem(replace(self.approval, min_stewart_margin_deg=20.0), self.request,
                           "below the approval floor")

    def test_values_exactly_at_the_caps_pass(self):
        a = replace(self.approval, max_stewart_speed_ratio=0.2, min_stewart_margin_deg=15.0)
        self.assertEqual(validate_approval(a, self.request, now=NOW), [])

    def test_missing_or_nan_metrics_are_refused(self):
        request = make_request(speed=None)
        self.assertProblem(make_approval(request), request, f"no finite {METRIC_SPEED_RATIO}")
        request = make_request(margin=math.nan)
        self.assertProblem(make_approval(request), request, f"no finite {METRIC_MARGIN_DEG}")
        request = make_request(speed=10 ** 400)  # float() overflows: no finite value, not a crash
        self.assertProblem(make_approval(request), request, f"no finite {METRIC_SPEED_RATIO}")

    def test_bad_caps(self):
        for cap in (math.nan, 0.0, -0.1, 1.5, math.inf):
            self.assertProblem(replace(self.approval, max_stewart_speed_ratio=cap), self.request,
                               "max_stewart_speed_ratio")
        for floor in (-1.0, math.nan, math.inf):
            self.assertProblem(replace(self.approval, min_stewart_margin_deg=floor), self.request,
                               "min_stewart_margin_deg")

    # --- the approved policy
    def test_report_checked_under_another_policy_is_not_covered(self):
        tl = tiny_timeline()
        request = request_with(report_for(tl, policy=LAX_POLICY), tl)  # passes ITS (relaxed) policy
        self.assertProblem(make_approval(request), request, "not the approved policy")

    def test_approval_bound_to_the_relaxed_policy_covers_it(self):
        tl = tiny_timeline()
        request = request_with(report_for(tl, policy=LAX_POLICY), tl)
        approval = make_approval(request, policy_name=LAX_POLICY.name, policy_sha256=policy_digest(LAX_POLICY))
        self.assertEqual(validate_approval(approval, request, now=NOW), [])

    def test_approval_must_name_a_policy(self):
        text = problems_text(replace(self.approval, policy_name="", policy_sha256="abc"), self.request)
        self.assertIn("names no safety policy", text)
        self.assertIn("policy_sha256", text)

    def test_policy_name_must_match_the_digest(self):
        self.assertProblem(replace(self.approval, policy_name="something-else"), self.request,
                           "is not the name of the policy")

    def test_policy_sha256_is_normalised(self):
        a = replace(self.approval, policy_sha256=" " + DEFAULT_SHA.upper() + " ")
        self.assertEqual(a.policy_sha256, DEFAULT_SHA)
        self.assertEqual(validate_approval(a, self.request, now=NOW), [])

    # --- who
    def test_empty_approved_by(self):
        for who in ("", "   "):
            self.assertProblem(replace(self.approval, approved_by=who), self.request, "approved_by is empty")

    def test_placeholder_approved_by(self):
        for who in ("<your name>", "<Kim>", "TODO", "n/a", "the user", "Supervisor"):
            self.assertProblem(replace(self.approval, approved_by=who), self.request, "is a placeholder")

    def test_assistant_or_agent_names_are_refused(self):
        for who in ("assistant", "Agent", "Claude", "claude-code", "Claude Code agent", "Claude Opus",
                    "AI assistant", "GPT-4", "gpt4o", "ASSISTANT ", "ChatGPT", "workflow script", "LLM"):
            self.assertProblem(replace(self.approval, approved_by=who), self.request, "not a person")

    def test_real_signatures_are_accepted(self):
        for who in ("Kim Supervisor <kim@example.com>", "김지도", "Dr. Lee (DGIST HRI)", "Park Ji-hoon"):
            self.assertEqual(validate_approval(replace(self.approval, approved_by=who), self.request, now=NOW), [],
                             who)

    def test_approval_id_must_be_typeable(self):
        for aid in ("", "ab", " R2-x-1", "R2-x-1 ", "R2-2026 1112", "R2-АВ-1", "R2 x 1", "x" * 65):
            self.assertProblem(replace(self.approval, approval_id=aid), self.request, "approval_id")

    def test_control_characters_in_code_built_approvals(self):
        for kw in (dict(notes="ok\x1b[2A\r  caps : 0.05"), dict(approved_by="Kim‮Supervisor"),
                   dict(host=HOST + "\r"), dict(motions=self.approval.motions + ("x\x1b[1A:y",))):
            self.assertProblem(replace(self.approval, **kw), self.request, "control / format characters")

    def test_problem_messages_never_carry_raw_control_characters(self):
        a = replace(self.approval, approved_by="\x1b[2J", motions=("x\x1b[1A:y",))
        with self.assertRaises(ApprovalError) as ctx:
            require_approval(a, self.request, now=NOW)
        self.assertNotIn("\x1b", str(ctx.exception))
        self.assertEqual(format_problems(["a\rb"]), "robot approval refused:\n  - a\\rb")

    # --- API shape
    def test_require_approval_lists_every_problem(self):
        bad = replace(self.approval, host="10.0.0.1", approved_by="")
        with self.assertRaises(ApprovalError) as ctx:
            require_approval(bad, self.request, now=datetime(2026, 11, 13, 9, 0))
        msg = str(ctx.exception)
        for fragment in ("host mismatch", "approved_by is empty", "expired"):
            self.assertIn(fragment, msg)

    def test_non_approval_objects_give_problems_not_crashes(self):
        self.assertTrue(validate_approval(None, self.request, now=NOW))  # type: ignore[arg-type]
        self.assertTrue(validate_approval(self.approval, {"host": HOST}, now=NOW))  # type: ignore[arg-type]

    def test_types_are_normalised(self):
        self.assertIsInstance(self.approval.approved_on, date)
        self.assertIsInstance(self.approval.expires, datetime)
        self.assertIsInstance(self.approval.motions, tuple)
        for motions in ("success:expressive", {"success:expressive": 1}, {"success:expressive"}):
            with self.assertRaises(ApprovalError):
                make_approval(self.request, motions=motions)  # a str / dict / set is not a list
        with self.assertRaises(ApprovalError):
            make_approval(self.request, max_stewart_speed_ratio=True)
        with self.assertRaises(ApprovalError):
            make_approval(self.request, max_stewart_speed_ratio=10 ** 400)  # OverflowError -> ApprovalError

    def test_worst_metrics(self):
        request = make_request(speed=0.4, margin=11.0)
        self.assertEqual(worst_metrics(request.reports), {METRIC_SPEED_RATIO: 0.4, METRIC_MARGIN_DEG: 11.0})
        self.assertEqual(worst_metrics([object()]), {METRIC_SPEED_RATIO: None, METRIC_MARGIN_DEG: None})

    def test_foreign_report_objects_are_problems(self):
        request = replace(self.request, reports=self.request.reports + ("not a report",))
        self.assertIn("is not a SafetyReport", problems_text(self.approval, request))
        self.assertIn("n/a", approval_template(replace(self.request, reports=("x",)))["notes"])


class TestPolicyDigest(unittest.TestCase):
    def test_digest_is_stable_and_binds_every_threshold(self):
        self.assertEqual(policy_digest(DEFAULT_POLICY), policy_digest(SafetyPolicy()))
        self.assertRegex(DEFAULT_SHA, r"^[0-9a-f]{64}$")
        for change in (dict(max_pitch_deg=40.5), dict(z_range_mm=(-40.0, 24.5)), dict(name="phase2-initial-v2"),
                       dict(notes=("tuned",)), dict(check_rate_hz=100.0)):
            self.assertNotEqual(policy_digest(replace(DEFAULT_POLICY, **change)), DEFAULT_SHA, change)
        with self.assertRaises(ApprovalError):
            policy_digest({"name": "x"})  # type: ignore[arg-type]

    def test_relaxations_against_the_default(self):
        self.assertEqual(policy_relaxations(DEFAULT_POLICY), [])
        tighter = replace(DEFAULT_POLICY, max_pitch_deg=30.0, min_stewart_margin_deg=15.0, z_range_mm=(-30.0, 20.0))
        self.assertEqual(policy_relaxations(tighter), [])
        text = "\n".join(policy_relaxations(LAX_POLICY))
        for key in ("max_pitch_deg", "max_psi_step_deg", "z_range_mm", "min_stewart_margin_deg",
                    "max_stewart_speed_ratio"):
            self.assertIn(key, text)
        startup = replace(DEFAULT_POLICY, name=DEFAULT_POLICY.name + "+startup", x_range_mm=(-30.0, 25.0),
                          z_range_mm=(-50.0, 24.0))  # the sim start-up ramp policy of cli_phase2
        self.assertEqual([r.split()[0] for r in policy_relaxations(startup)], ["x_range_mm", "z_range_mm"])
        self.assertIn("max_roll_deg", "\n".join(policy_relaxations(replace(DEFAULT_POLICY, max_roll_deg=math.nan))))
        self.assertIn("stream_rate_hz", "\n".join(policy_relaxations(replace(DEFAULT_POLICY, stream_rate_hz=100.0))))


class TestLoadApproval(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.request = make_request()
        self.data = make_approval(self.request).to_dict()

    def write(self, data, name: str = "approval.json", encoding: str = "utf-8") -> Path:
        p = Path(self.tmp.name) / name
        p.write_text(data if isinstance(data, str) else json.dumps(data, indent=2), encoding=encoding)
        return p

    def load_error(self, data) -> str:
        with self.assertRaises(ApprovalError) as ctx:
            load_approval(self.write(data))
        return str(ctx.exception)

    def test_round_trip(self):
        a = load_approval(self.write(self.data))
        self.assertEqual(a, make_approval(self.request))  # ``source`` is not compared
        self.assertIsInstance(a.approved_on, date)
        self.assertIsInstance(a.expires, datetime)
        self.assertEqual(validate_approval(a, self.request, now=NOW), [])
        self.assertEqual(tuple(a.to_dict()), APPROVAL_KEYS)

    def test_source_is_recorded_by_load_approval_only(self):
        p = self.write(self.data)
        a = load_approval(p)
        self.assertIsInstance(a.source, ApprovalSource)
        self.assertEqual(Path(a.source.path), p.resolve())
        self.assertEqual(a.source.sha256, hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(a.source.size, len(p.read_bytes()))
        self.assertIsNotNone(a.source.loaded_at.tzinfo)
        self.assertNotIn("source", APPROVAL_KEYS)
        self.assertIsNone(make_approval(self.request).source)  # built in code
        self.assertIsNone(replace(a, notes="edited in code").source)  # a copy is not the file
        with self.assertRaises(TypeError):
            RobotApproval(**self.data, source=a.source)  # not a constructor argument

    def test_utf8_bom_is_tolerated(self):
        self.assertEqual(load_approval(self.write(self.data, encoding="utf-8-sig")).approval_id, APPROVED_ID)

    def test_unknown_key_with_hint_and_missing_key(self):
        data = dict(self.data)
        data["max_stewart_speed_ratoi"] = data.pop("max_stewart_speed_ratio")
        msg = self.load_error(data)
        self.assertIn("unknown key 'max_stewart_speed_ratoi' (did you mean 'max_stewart_speed_ratio'?)", msg)
        self.assertIn("missing keys: max_stewart_speed_ratio", msg)

    def test_wrong_types(self):
        msg = self.load_error(dict(self.data, motions="success:expressive", max_stewart_speed_ratio="0.3",
                                   min_stewart_margin_deg=True, notes=5))
        self.assertIn("motions: expected a list of strings", msg)
        self.assertIn("max_stewart_speed_ratio: expected a number", msg)
        self.assertIn("min_stewart_margin_deg: expected a number", msg)
        self.assertIn("notes: expected a string", msg)
        self.assertGreaterEqual(msg.count("\n  - "), 4)  # every problem reported at once

    def test_bad_dates(self):
        msg = self.load_error(dict(self.data, approved_on="12/11/2026", expires="2026-11-12"))
        self.assertIn("approved_on: expected an ISO date", msg)
        self.assertIn("needs a date AND a time", msg)

    def test_not_json_and_not_an_object(self):
        self.assertIn("not valid JSON (line", self.load_error('{"approval_id": "x",\n}'))
        self.assertIn("top level must be a JSON object", self.load_error([self.data]))

    def test_missing_or_unreadable_file(self):
        with self.assertRaises(ApprovalError):
            load_approval(Path(self.tmp.name) / "nope.json")
        with self.assertRaises(ApprovalError):
            load_approval(Path(self.tmp.name))  # a directory
        p = Path(self.tmp.name) / "utf16.json"
        p.write_text(json.dumps(self.data), encoding="utf-16")  # e.g. PowerShell 5.1 "Out-File" default
        with self.assertRaises(ApprovalError):
            load_approval(p)

    def test_duplicate_keys_are_refused(self):
        body = json.dumps(self.data, indent=1)
        tightened_then_loosened = body.replace('"max_stewart_speed_ratio": 0.3',
                                               '"max_stewart_speed_ratio": 0.1,\n "max_stewart_speed_ratio": 1.0')
        self.assertIn("duplicate key(s) 'max_stewart_speed_ratio'", self.load_error(tightened_then_loosened))
        self.assertIn("duplicate key(s) 'stage'", self.load_error(body.replace('"stage": "R2"',
                                                                               '"stage": "R1", "stage": "R2"')))

    def test_non_finite_numbers_are_refused(self):
        body = json.dumps(self.data)
        for literal in ("NaN", "Infinity", "-Infinity"):
            text = body.replace('"max_stewart_speed_ratio": 0.3', f'"max_stewart_speed_ratio": {literal}')
            self.assertIn(f"{literal} is not allowed", self.load_error(text))
        msg = self.load_error(body.replace('"min_stewart_margin_deg": 12.0', '"min_stewart_margin_deg": 1e400'))
        self.assertIn("min_stewart_margin_deg: expected a finite number", msg)

    def test_huge_numbers_and_deep_nesting_give_approval_errors(self):
        body = json.dumps(self.data)
        for digits in (400, 5000):  # float() overflow / beyond sys.get_int_max_str_digits()
            msg = self.load_error(body.replace('"min_stewart_margin_deg": 12.0',
                                               '"min_stewart_margin_deg": 1' + "0" * digits))
            self.assertIn("min_stewart_margin_deg" if digits == 400 else "not a valid approval JSON", msg)
        self.assertIn("not a valid approval JSON", self.load_error("[" * 100_000 + "]" * 100_000))

    def test_control_characters_are_refused(self):
        for key, value in (("notes", "ok\x1b[2A\r  caps : <= 0.05"), ("notes", "two\nlines"),
                           ("approved_by", "Kim‮Supervisor"), ("host", HOST + "\x00"),
                           ("motions", list(self.data["motions"]) + ["x\x1b[1A:y"])):
            msg = self.load_error(dict(self.data, **{key: value}))
            self.assertIn(f"{key}: control / format characters are not allowed", msg)
            self.assertNotIn("\x1b", msg)

    def test_oversized_file_is_refused(self):
        msg = self.load_error(dict(self.data, notes="x" * (MAX_APPROVAL_FILE_BYTES + 1)))
        self.assertIn("bytes", msg)


class TestSourceProblems(unittest.TestCase):
    """The robot gate needs an approval FILE that is unchanged since it was loaded."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.approval, self.request = loaded_valid_now_pair(self.tmp.name)
        self.path = Path(self.approval.source.path)

    def test_loaded_file_passes(self):
        self.assertEqual(source_problems(self.approval), [])
        self.assertEqual(gate_problems(self.approval, self.request), [])

    def test_approval_built_or_copied_in_code_is_refused(self):
        built, request = valid_now_pair()
        self.assertEqual(validate_approval(built, request), [])  # the content is fine ...
        for a in (built, replace(self.approval, notes="copy")):
            self.assertIn("not loaded from a file", "\n".join(gate_problems(a, request)))  # ... but not a file

    def test_file_changed_after_loading_is_refused(self):
        self.path.write_text(self.path.read_text(encoding="utf-8").replace('"unit test"', '"edited"'),
                             encoding="utf-8")
        self.assertIn("changed since it was loaded", "\n".join(source_problems(self.approval)))
        self.assertEqual(validate_approval(self.approval, self.request), [])  # content checks stay pure

    def test_file_removed_after_loading_is_refused(self):
        self.path.unlink()
        self.assertIn("cannot be read any more", "\n".join(gate_problems(self.approval, self.request)))

    def test_gate_problems_include_the_content_checks(self):
        later = datetime.now() + timedelta(hours=3)
        self.assertIn("expired", "\n".join(gate_problems(self.approval, self.request, now=later)))


class TestTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.request = make_request()

    def test_template_has_every_key_and_no_approval(self):
        t = approval_template(self.request)
        self.assertEqual(tuple(t), APPROVAL_KEYS)
        for key in ("approval_id", "approved_by", "approved_on", "expires"):
            self.assertEqual(t[key], "", key)
        self.assertIsNone(t["max_stewart_speed_ratio"])
        self.assertIsNone(t["min_stewart_margin_deg"])
        self.assertEqual(t["stage"], "R2")
        self.assertEqual(t["host"], HOST)
        self.assertEqual(t["motions"], list(self.request.motions))
        self.assertEqual(t["timeline_digests"], list(self.request.timeline_digests))
        self.assertEqual((t["policy_name"], t["policy_sha256"]), (DEFAULT_POLICY.name, DEFAULT_SHA))
        self.assertIn(f"{METRIC_SPEED_RATIO}=0.2", t["notes"])
        self.assertNotIn("LOOSER", t["notes"])
        json.dumps(t)  # JSON-able

    def test_template_saved_as_is_does_not_load(self):
        t = approval_template(self.request)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "approval.json"
            p.write_text(json.dumps(t), encoding="utf-8")
            with self.assertRaises(ApprovalError) as ctx:
                load_approval(p)
        msg = str(ctx.exception)
        self.assertIn("approved_on", msg)
        self.assertIn("max_stewart_speed_ratio: fill in a number", msg)
        with self.assertRaises(ApprovalError):
            RobotApproval(**t)

    def test_template_never_touches_files(self):
        with mock.patch("builtins.open", side_effect=AssertionError("template must not open files")), \
                mock.patch.object(Path, "write_text", side_effect=AssertionError("no writes")):
            approval_template(self.request)

    def test_r0_has_no_template(self):
        with self.assertRaises(ApprovalError):
            approval_template(make_request(stage="R0"))

    def test_relaxed_policy_is_named_and_its_relaxations_listed(self):
        tl = tiny_timeline()
        t = approval_template(request_with(report_for(tl, policy=LAX_POLICY), tl))
        self.assertEqual((t["policy_name"], t["policy_sha256"]), (LAX_POLICY.name, policy_digest(LAX_POLICY)))
        self.assertIn("LOOSER than the default", t["notes"])
        self.assertIn("max_pitch_deg 89", t["notes"])

    def test_mixed_policies_have_no_template(self):
        tl1, tl2 = tiny_timeline("success"), tiny_timeline("failure", "neutral", dz=-0.003)
        request = ApprovalRequest.from_prepared(HOST, "R2", [PreparedMotion(tl1, report_for(tl1)),
                                                             PreparedMotion(tl2, report_for(tl2, policy=LAX_POLICY))])
        with self.assertRaises(ApprovalError) as ctx:
            approval_template(request)
        self.assertIn("different safety policies", str(ctx.exception))

    def test_human_filled_template_validates(self):
        t = approval_template(self.request)
        t.update(approval_id=APPROVED_ID, approved_by="Kim Supervisor", approved_on="2026-11-12",
                 expires="2026-11-12T18:00:00", max_stewart_speed_ratio=0.3, min_stewart_margin_deg=12.0)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "approval.json"
            p.write_text(json.dumps(t), encoding="utf-8")
            approval = load_approval(p)
        self.assertEqual(validate_approval(approval, self.request, now=NOW), [])


class TestConfirmInteractively(unittest.TestCase):
    def setUp(self) -> None:
        self.approval = make_approval(make_request())
        self.out = io.StringIO()

    def confirm(self, answer=None, tty=True, side_effect=None) -> tuple[bool, mock.Mock]:
        input_fn = mock.Mock(return_value=answer, side_effect=side_effect)
        ok = confirm_interactively(self.approval, input_fn=input_fn, isatty_fn=lambda: tty, out=self.out)
        return ok, input_fn

    def test_non_tty_refuses_without_prompting(self):
        ok, input_fn = self.confirm(APPROVED_ID, tty=False)
        self.assertFalse(ok)
        input_fn.assert_not_called()
        self.assertIn("not an interactive terminal", self.out.getvalue())

    def test_isatty_failure_refuses(self):
        def broken() -> bool:
            raise ValueError("I/O operation on closed file")

        input_fn = mock.Mock(return_value=APPROVED_ID)
        self.assertFalse(confirm_interactively(self.approval, input_fn=input_fn, isatty_fn=broken, out=self.out))
        input_fn.assert_not_called()

    def test_default_isatty_without_stdin_refuses(self):
        input_fn = mock.Mock(return_value=APPROVED_ID)
        with mock.patch.object(sys, "stdin", None):
            self.assertFalse(confirm_interactively(self.approval, input_fn=input_fn, out=self.out))
        input_fn.assert_not_called()

    def test_null_device_and_pipe_are_not_terminals(self):
        # Windows reports isatty() == True for NUL; the default check must still say "not a terminal"
        code = "from reachy_motion.safety.approval import _stdin_isatty; print(_stdin_isatty())"
        repo = Path(__file__).resolve().parents[1]
        for kw in (dict(stdin=subprocess.DEVNULL), dict(input="R2-20261112-a\n")):
            out = subprocess.run([sys.executable, "-B", "-c", code], cwd=repo, capture_output=True, text=True,
                                 timeout=60, check=True, **kw).stdout.strip()
            self.assertEqual(out, "False", kw)

    def test_default_out_is_current_stdout(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            confirm_interactively(self.approval, input_fn=mock.Mock(), isatty_fn=lambda: False)
        self.assertIn("NOT confirmed", buf.getvalue())

    def test_default_input_is_looked_up_at_call_time(self):
        # a patched builtins.input must be the prompt that is used (and can therefore be guarded in tests)
        answer = mock.Mock(return_value=APPROVED_ID)
        with mock.patch("builtins.input", answer):
            self.assertTrue(confirm_interactively(self.approval, isatty_fn=lambda: True, out=self.out))
        answer.assert_called_once()
        guard = mock.Mock(side_effect=AssertionError("must not prompt"))
        with mock.patch("reachy_motion.safety.approval._stdin_isatty", return_value=True), \
                mock.patch("builtins.input", guard), mock.patch("sys.stdin", io.StringIO(APPROVED_ID + "\n")):
            with self.assertRaises(AssertionError):
                confirm_interactively(self.approval, out=self.out)  # stdin is never read behind the patch
        guard.assert_called_once()

    def test_wrong_id_refuses(self):
        for answer in ("yes", "y", "", APPROVED_ID.lower(), " " + APPROVED_ID, APPROVED_ID + " "):
            ok, _ = self.confirm(answer)
            self.assertFalse(ok, answer)
        self.assertIn("does not match", self.out.getvalue())

    def test_right_id_accepts_and_shows_summary(self):
        ok, input_fn = self.confirm(APPROVED_ID)
        self.assertTrue(ok)
        input_fn.assert_called_once()
        text = self.out.getvalue()
        for fragment in ("PHYSICAL motors", HOST, "R2", "success:expressive", "Kim Supervisor", "confirmed",
                         f"policy      : {DEFAULT_POLICY.name} (sha256 {DEFAULT_SHA[:12]}...; the default Phase 2 "
                         "policy)", "not loaded from a file"):
            self.assertIn(fragment, text)

    def test_summary_flags_a_non_default_policy_and_shows_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tl = tiny_timeline()
            request = request_with(report_for(tl, policy=LAX_POLICY), tl)
            approval = make_approval(request, policy_name=LAX_POLICY.name, policy_sha256=policy_digest(LAX_POLICY))
            self.approval = load_approval(write_approval(tmp, approval))
            self.confirm(APPROVED_ID)
        text = self.out.getvalue()
        self.assertIn(f"NOT the default policy {DEFAULT_POLICY.name}", text)
        self.assertIn(f"file        : {self.approval.source.path} (sha256 {self.approval.source.sha256[:12]}", text)

    def test_summary_never_prints_raw_control_characters(self):
        self.approval = replace(self.approval, notes="ok\x1b[2A\r  caps : 0.05", approved_by="Kim‮X",
                                motions=("x\x1b[1A:y",))
        self.confirm("nope")
        text = self.out.getvalue()
        for raw in ("\x1b", "\r", "‮"):
            self.assertNotIn(raw, text)
        self.assertIn("\\x1b[2A\\r", text)

    def test_eof_or_ctrl_c_refuses(self):
        for exc in (EOFError(), KeyboardInterrupt()):
            ok, _ = self.confirm(side_effect=exc)
            self.assertFalse(ok)

    def test_untypeable_id_refuses_without_prompting(self):
        for aid in ("ab", "R2-2026 1112"):
            self.approval = replace(self.approval, approval_id=aid)
            ok, input_fn = self.confirm(aid)
            self.assertFalse(ok)
            input_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
