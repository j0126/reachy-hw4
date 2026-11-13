"""library.io: human-editable motion files (schema reachy-motion/v1) <-> MotionSpec.

Hermetic: temporary directories only, no SDK, no robot, no network.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from reachy_motion.library import io
from reachy_motion.library.pose import INIT_ANTENNAS, REST, Pose6, RobotState
from reachy_motion.library.registry import default_library
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

PRINCIPLES = (
    PrincipleUse(Principle.ANTICIPATION, "작은 끄덕임: dip before the lift"),
    PrincipleUse(Principle.FOLLOW_THROUGH, "antennas settle 0.2 s after the head"),
)


def full_spec(**changes: Any) -> MotionSpec:
    """Every feature: custom start, sound, draft false, scale knobs, all easings, unicode and multi-line text."""
    spec = MotionSpec(
        name="aha_recommend", variant="expressive", intent="Aha! 추천 - 'I have an idea'", valence=0.7, arousal=0.6,
        principles=PRINCIPLES,
        head=(
            HeadKey(0.25, Pose6.from_deg_mm(pitch_deg=6, z_mm=-4), Easing.MIN_JERK, 0.0, "dip"),
            HeadKey(0.4, Pose6.from_deg_mm(roll_deg=-3.5, pitch_deg=-12, yaw_deg=8.25, x_mm=2.5, y_mm=-1, z_mm=6),
                    Easing.CARTOON, 0.35, "lift: up"),
            HeadKey(0.6, Pose6(), Easing.EASE_IN_OUT, 0.1, "back"),
            HeadKey(0.3, Pose6(yaw=0.123456789012345, z=0.0012345678901234), Easing.LINEAR, 0.0, "odd values"),
        ),
        antennas=(
            AntennaKey(0.2, (0.0, 0.0), Easing.EASE_IN_OUT, 0.3, "perk"),
            AntennaKey(0.5, INIT_ANTENNAS, Easing.MIN_JERK, 0.0, "rest"),
        ),
        body=(BodyKey(1.0, math.radians(10), Easing.MIN_JERK, 0.0, "turn"), BodyKey(0.8, 0.0, Easing.LINEAR, 0.2)),
        start=RobotState(head=Pose6.from_deg_mm(yaw_deg=2, z_mm=1), antennas=(math.radians(-15), math.radians(15)),
                         body_yaw=math.radians(-5)),
        description="line one\nline two: with colon\n", amplitude_scale=1.25, tempo_scale=0.8,
        sound=SoundCue("aha.wav", 0.3), draft=False,
    )
    return replace(spec, **changes)


def minimal_doc() -> dict[str, Any]:
    """Smallest valid file content (everything optional left out)."""
    return {
        "schema": "reachy-motion/v1", "name": "boredom", "variant": "neutral", "intent": "bored",
        "expected": {"valence": -0.3, "arousal": -0.5},
        "principles": [{"principle": "timing", "how": "slow"}],
        "tracks": {"head": [{"duration_s": 1.0, "pose": {"pitch_deg": 10}}]},
    }


def assert_specs_close(tc: unittest.TestCase, a: MotionSpec, b: MotionSpec, tol: float = 1e-12) -> None:
    """Floats (SI: rad, m, s) within ``tol``, everything else (strings, bools, structure) exact."""

    def cmp(x: Any, y: Any, path: str) -> None:
        if isinstance(x, dict):
            tc.assertIsInstance(y, dict, path)
            tc.assertEqual(list(x), list(y), path)
            for k in x:
                cmp(x[k], y[k], f"{path}.{k}")
        elif isinstance(x, list):
            tc.assertIsInstance(y, list, path)
            tc.assertEqual(len(x), len(y), path)
            for i, (u, v) in enumerate(zip(x, y)):
                cmp(u, v, f"{path}[{i}]")
        elif isinstance(x, float) and not isinstance(x, bool):
            tc.assertIsInstance(y, float, path)
            tc.assertLessEqual(abs(x - y), tol, path)
        else:
            tc.assertEqual(type(x), type(y), path)
            tc.assertEqual(x, y, path)

    cmp(a.to_dict(), b.to_dict(), a.key)


def _at(doc: dict[str, Any], path: tuple[Any, ...]) -> Any:
    node: Any = doc
    for p in path:
        node = node[p]
    return node


class TestRoundTrip(unittest.TestCase):
    def test_fixture_is_a_valid_spec(self):
        self.assertEqual(full_spec().validate(), [])

    def test_yaml_round_trip(self):
        spec = full_spec()
        back = io.loads_spec(io.dumps_yaml(spec))
        assert_specs_close(self, spec, back)
        self.assertEqual(back.sound, SoundCue("aha.wav", 0.3))
        self.assertIs(back.draft, False)
        self.assertEqual((back.amplitude_scale, back.tempo_scale), (1.25, 0.8))
        self.assertEqual(back.intent, spec.intent)
        self.assertEqual(back.description, spec.description)

    def test_json_round_trip(self):
        spec = full_spec(draft=True, sound=None)
        back = io.loads_spec(io.dumps_json(spec), "json")
        assert_specs_close(self, spec, back)
        self.assertIsNone(back.sound)
        self.assertIs(back.draft, True)

    def test_dict_round_trip_without_text(self):
        spec = full_spec()
        assert_specs_close(self, spec, io.spec_from_dict(io.spec_to_dict(spec)))

    def test_custom_start_round_trip(self):
        back = io.loads_spec(io.dumps_yaml(full_spec()))
        self.assertAlmostEqual(back.start.head.yaw, math.radians(2), delta=1e-15)
        self.assertAlmostEqual(back.start.head.z, 0.001, delta=1e-15)
        self.assertEqual(back.start.antennas, (math.radians(-15), math.radians(15)))
        self.assertEqual(back.start.body_yaw, math.radians(-5))

    def test_rest_start_is_written_as_rest_and_restored_exactly(self):
        spec = full_spec(start=REST)
        d = io.spec_to_dict(spec)
        self.assertEqual(d["start"], "rest")
        back = io.spec_from_dict(d)
        self.assertEqual(back.start, REST)
        self.assertEqual(back.start.antennas, (-0.1745, 0.1745))  # the SDK constants, not radians(10)

    def test_text_is_stable_after_one_round_trip(self):
        for spec in (full_spec(), full_spec(start=REST, draft=True, variant="neutral")):
            text = io.dumps_yaml(spec)
            self.assertEqual(io.dumps_yaml(io.loads_spec(text)), text)
            js = io.dumps_json(spec)
            self.assertEqual(io.dumps_json(io.loads_spec(js, "json")), js)

    def test_output_is_standard_yaml(self):
        spec = full_spec()
        text = io.dumps_yaml(spec)
        self.assertEqual(yaml.safe_load(text), io.spec_to_dict(spec))
        self.assertNotIn("!!", text)  # no python-specific tags
        self.assertNotIn("&id", text)  # no anchors / aliases

    def test_all_fields_written_explicitly(self):
        d = io.spec_to_dict(full_spec(body=()))
        self.assertEqual(list(d), ["schema", "name", "variant", "draft", "intent", "description", "expected",
                                   "principles", "scale", "start", "tracks", "sound"])
        for k in d["tracks"]["head"]:
            self.assertEqual(list(k), ["label", "duration_s", "hold_s", "easing", "pose"])
            self.assertEqual(list(k["pose"]), list(io.HEAD_FIELDS))  # all six, zeros included
        for k in d["tracks"]["antennas"]:
            self.assertEqual(list(k), ["label", "duration_s", "hold_s", "easing", "right_deg", "left_deg"])
        self.assertEqual(d["tracks"]["body"], [])
        self.assertEqual(list(d["start"]), ["head", "antennas_deg", "body_yaw_deg"])
        self.assertEqual(json.loads(json.dumps(d)), d)  # JSON-able, no tuples

    def test_numpy_scalars_are_written_as_plain_numbers(self):
        spec = full_spec(head=(HeadKey(np.float32(0.5), Pose6(pitch=np.float32(0.25), z=np.float64(-0.004))),),
                         amplitude_scale=np.float64(1.5))
        d = io.spec_to_dict(spec)
        key = d["tracks"]["head"][0]
        self.assertIs(type(key["duration_s"]), float)
        self.assertIs(type(key["pose"]["pitch_deg"]), float)
        self.assertIs(type(d["scale"]["amplitude"]), float)
        back = io.loads_spec(io.dumps_yaml(spec))
        self.assertEqual(back.head[0].pose.pitch, float(np.float32(0.25)))
        self.assertEqual(back.head[0].pose.z, -0.004)

    def test_awkward_strings_round_trip_exactly(self):
        labels = ["on", "yes", "null", "1.5", "010", "rest", "a: b", "# not a comment", " leading", "trailing ", "",
                  "끄덕", "two\nlines\n", "quote ' and \" both", "x" * 150 + " " + "y" * 30,
                  "x\x85y", "\x85", "a b", "c ", "two\nlines\x85", "cr\r\nlf", "tab\there"]
        spec = full_spec(head=tuple(HeadKey(0.1, Pose6(), label=s) for s in labels), description="d\x85e\n")
        for text, fmt in ((io.dumps_yaml(spec), "yaml"), (io.dumps_json(spec), "json")):
            back = io.loads_spec(text, fmt)
            self.assertEqual([k.label for k in back.head], labels, fmt)
            self.assertEqual(back.description, "d\x85e\n", fmt)

    def test_values_from_a_file_are_exact_and_the_text_is_stable(self):
        # Seeded fuzz over every number kind (deg, mm, rad constants, s): file -> spec -> file -> spec.
        rng = random.Random(20261110)
        for _ in range(150):
            pose = Pose6(rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05),
                         rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-3, 3))
            spec = full_spec(head=(HeadKey(rng.uniform(0.02, 3.0), pose, hold=rng.uniform(0, 1)),),
                             antennas=(AntennaKey(0.5, (rng.uniform(-3, 3), rng.uniform(-3, 3))),),
                             body=(BodyKey(0.5, rng.uniform(-2.7, 2.7)),),
                             start=RobotState(head=Pose6(yaw=rng.uniform(-1, 1), z=rng.uniform(-0.01, 0.01)),
                                              antennas=(rng.uniform(-1, 1), INIT_ANTENNAS[1]),
                                              body_yaw=rng.uniform(-1, 1)))
            text1 = io.dumps_yaml(spec)
            from_file = io.loads_spec(text1)  # its values now "came from a file"
            text2 = io.dumps_yaml(from_file)
            self.assertEqual(text2, text1)  # saving again writes the same text ...
            self.assertEqual(io.loads_spec(text2).to_dict(), from_file.to_dict())  # ... and the same values
            assert_specs_close(self, spec, from_file, tol=1e-15)  # other values: within one ulp

    def test_long_decimals_typed_in_a_file_survive_a_save(self):
        # Review case: yaw_deg -11.405466835863766 used to come back as -11.405466835863768 (one ulp off).
        for typed in ("-11.405466835863766", "12.345678901234567", "0.1", "6", "-89.99999999999999"):
            doc = minimal_doc()
            doc["tracks"]["head"][0]["pose"] = {"yaw_deg": float(typed), "z_mm": float(typed) / 10}
            first = io.spec_from_dict(doc)
            again = io.loads_spec(io.dumps_yaml(first))
            self.assertEqual(again.head[0].pose, first.head[0].pose, typed)
            self.assertEqual(io.dumps_yaml(again), io.dumps_yaml(first), typed)


class TestUnits(unittest.TestCase):
    def test_degrees_to_radians_exact(self):
        doc = minimal_doc()
        doc["tracks"] = {
            "head": [{"duration_s": 0.5, "pose": {"pitch_deg": 10, "roll_deg": -3.5, "yaw_deg": 12.25}}],
            "antennas": [{"duration_s": 0.5, "right_deg": 30, "left_deg": -45.5}],
            "body": [{"duration_s": 1.0, "yaw_deg": -20}],
        }
        spec = io.spec_from_dict(doc)
        self.assertEqual(spec.head[0].pose.pitch, math.radians(10))
        self.assertEqual(spec.head[0].pose.roll, math.radians(-3.5))
        self.assertEqual(spec.head[0].pose.yaw, math.radians(12.25))
        self.assertEqual(spec.antennas[0].antennas, (math.radians(30), math.radians(-45.5)))
        self.assertEqual(spec.body[0].yaw, math.radians(-20))

    def test_millimetres_to_metres_exact(self):
        doc = minimal_doc()
        doc["tracks"]["head"][0]["pose"] = {"x_mm": 7.5, "y_mm": -12, "z_mm": -4}
        p = io.spec_from_dict(doc).head[0].pose
        self.assertEqual((p.x, p.y, p.z), (0.0075, -0.012, -0.004))

    def test_omitted_pose_components_are_zero_and_absolute(self):
        doc = minimal_doc()
        doc["tracks"]["head"] = [{"duration_s": 0.5, "pose": {"pitch_deg": 10}},
                                 {"duration_s": 0.5, "pose": {"yaw_deg": 5}},
                                 {"duration_s": 0.5, "pose": {}}]
        k0, k1, k2 = io.spec_from_dict(doc).head
        self.assertEqual(k0.pose, Pose6(pitch=math.radians(10)))
        self.assertEqual(k1.pose, Pose6(yaw=math.radians(5)))  # pitch back to 0: values are not relative
        self.assertEqual(k2.pose, Pose6())

    def test_omitted_start_is_rest_with_sdk_constants(self):
        for start in ("omitted", None, "rest"):
            doc = minimal_doc()
            if start != "omitted":
                doc["start"] = start
            spec = io.spec_from_dict(doc)
            self.assertEqual(spec.start, REST, start)
            self.assertEqual(spec.start.antennas, (-0.1745, 0.1745), start)

    def test_partial_start_mapping_fills_rest_values(self):
        doc = minimal_doc()
        doc["start"] = {"head": {"yaw_deg": 5}}
        s = io.spec_from_dict(doc).start
        self.assertEqual(s, RobotState(head=Pose6(yaw=math.radians(5))))
        self.assertEqual(s.antennas, INIT_ANTENNAS)
        doc["start"] = {"antennas_deg": {"right": -10}}
        s = io.spec_from_dict(doc).start
        self.assertEqual(s.antennas, (math.radians(-10), INIT_ANTENNAS[1]))
        self.assertEqual((s.head, s.body_yaw), (Pose6(), 0.0))

    def test_defaults(self):
        spec = io.spec_from_dict(minimal_doc())
        k = spec.head[0]
        self.assertEqual((k.hold, k.easing, k.label), (0.0, Easing.MIN_JERK, ""))
        self.assertEqual((spec.amplitude_scale, spec.tempo_scale), (1.0, 1.0))
        self.assertIs(spec.draft, True)
        self.assertIsNone(spec.sound)
        self.assertEqual(spec.description, "")
        self.assertEqual((spec.antennas, spec.body), ((), ()))

    def test_null_tracks_and_scale_read_as_empty_and_default(self):
        doc = minimal_doc()
        doc["tracks"]["body"] = None
        doc["scale"] = {"tempo": 2.0}
        spec = io.spec_from_dict(doc)
        self.assertEqual(spec.body, ())
        self.assertEqual((spec.amplitude_scale, spec.tempo_scale), (1.0, 2.0))

    def test_written_numbers_are_short(self):
        spec = full_spec(head=(HeadKey(0.5, Pose6.from_deg_mm(pitch_deg=6, roll_deg=0.1, z_mm=-4.2)),))
        self.assertNotEqual(math.degrees(math.radians(6)), 6.0)  # why the shortest-decimal search exists
        pose = io.spec_to_dict(spec)["tracks"]["head"][0]["pose"]
        self.assertEqual(pose, {"x_mm": 0.0, "y_mm": 0.0, "z_mm": -4.2, "roll_deg": 0.1, "pitch_deg": 6.0,
                                "yaw_deg": 0.0})
        self.assertIn("pose: {x_mm: 0.0, y_mm: 0.0, z_mm: -4.2, roll_deg: 0.1, pitch_deg: 6.0, yaw_deg: 0.0}",
                      io.dumps_yaml(spec))


class TestStrictness(unittest.TestCase):
    UNKNOWN_KEY_CASES = (
        ((), "duration", "top level"),
        (("expected",), "valance", "expected"),
        (("principles", 0), "principel", "principles[0]"),
        (("scale",), "amp", "scale"),
        (("start",), "body_yaw", "start"),
        (("start", "head"), "pich_deg", "start.head"),
        (("start", "antennas_deg"), "centre", "start.antennas_deg"),
        (("tracks",), "antenna", "tracks"),
        (("tracks", "head", 1), "hold", "tracks.head[1]"),
        (("tracks", "head", 1, "pose"), "pich_deg", "tracks.head[1].pose"),
        (("tracks", "antennas", 0), "right", "tracks.antennas[0]"),
        (("tracks", "body", 0), "yaw", "tracks.body[0]"),
        (("sound",), "time_s", "sound"),
    )

    def test_unknown_keys_at_every_depth(self):
        base = io.spec_to_dict(full_spec())
        for path, bad, where in self.UNKNOWN_KEY_CASES:
            with self.subTest(where=where):
                doc = copy.deepcopy(base)
                _at(doc, path)[bad] = 1.0
                with self.assertRaises(ValueError) as cm:
                    io.spec_from_dict(doc)
                msg = str(cm.exception)
                self.assertIn(f"{where}: unknown key {bad!r}", msg)
                self.assertIn("allowed keys:", msg)

    def test_unknown_key_message_lists_allowed_keys_and_a_close_match(self):
        doc = io.spec_to_dict(full_spec())
        doc["tracks"]["head"][0]["pose"]["pich_deg"] = 3
        with self.assertRaisesRegex(ValueError, r"did you mean 'pitch_deg'\?.*allowed keys: x_mm, y_mm, z_mm, "
                                                r"roll_deg, pitch_deg, yaw_deg"):
            io.spec_from_dict(doc)

    def test_missing_required_keys(self):
        cases = (
            ((), "schema"), ((), "name"), ((), "variant"), ((), "intent"), ((), "expected"), ((), "principles"),
            ((), "tracks"), (("expected",), "arousal"), (("principles", 0), "how"), (("sound",), "at_s"),
            (("tracks", "head", 0), "duration_s"), (("tracks", "head", 0), "pose"),
            (("tracks", "antennas", 0), "left_deg"), (("tracks", "body", 0), "yaw_deg"),
        )
        base = io.spec_to_dict(full_spec())
        for path, key in cases:
            with self.subTest(path=path, key=key):
                doc = copy.deepcopy(base)
                del _at(doc, path)[key]
                with self.assertRaisesRegex(ValueError, f"missing key '{key}'"):
                    io.spec_from_dict(doc)

    def test_invalid_easing_name(self):
        doc = io.spec_to_dict(full_spec())
        doc["tracks"]["antennas"][1]["easing"] = "min_jerk"
        with self.assertRaises(ValueError) as cm:
            io.spec_from_dict(doc)
        msg = str(cm.exception)
        self.assertIn("tracks.antennas[1].easing: unknown easing 'min_jerk'", msg)
        self.assertIn("did you mean 'minjerk'", msg)
        self.assertIn("allowed: linear, minjerk, ease_in_out, cartoon", msg)

    def test_invalid_principle_name(self):
        doc = io.spec_to_dict(full_spec())
        doc["principles"][1]["principle"] = "follow_through"
        with self.assertRaises(ValueError) as cm:
            io.spec_from_dict(doc)
        msg = str(cm.exception)
        self.assertIn("principles[1].principle: unknown principle 'follow_through'", msg)
        self.assertIn("follow_through_and_overlapping_action", msg)

    def test_wrong_types(self):
        cases = (
            (("tracks", "head", 0), "duration_s", "abc", "tracks.head[0].duration_s: expected a number"),
            (("tracks", "head", 0), "duration_s", True, "expected a number, got the boolean true"),
            (("tracks", "head", 0, "pose"), "pitch_deg", "1e-3", "write 1.0e-3"),
            (("tracks", "head", 0), "label", 5, "tracks.head[0].label: expected text"),
            (("tracks", "head", 0), "pose", [1, 2], "tracks.head[0].pose: expected a mapping"),
            (("tracks",), "head", {"duration_s": 1.0}, "tracks.head: expected a list"),
            ((), "draft", "yes", "draft: expected true or false"),
            ((), "start", "home", "start: expected 'rest' or a mapping"),
            ((), "name", "aha.recommend", "name: expected a name made of letters"),
            ((), "name", "success\n", "name: expected a name made of letters"),  # '$' would allow the newline
            ((), "variant", "neutral\n", "variant: expected a name made of letters"),
            (("tracks", "antennas", 0), "right_deg", "Rest", "did you mean 'rest'"),
            ((), "schema", "reachy-motion/v2", "schema: expected 'reachy-motion/v1'"),
            (("expected",), "valence", None, "expected.valence: expected a number, got nothing"),
        )
        base = io.spec_to_dict(full_spec())
        for path, key, value, pattern in cases:
            with self.subTest(key=key, value=value):
                doc = copy.deepcopy(base)
                _at(doc, path)[key] = value
                with self.assertRaises(ValueError) as cm:
                    io.spec_from_dict(doc)
                self.assertIn(pattern, str(cm.exception))

    def test_non_finite_numbers_rejected(self):
        for value in (math.inf, -math.inf, math.nan):
            doc = io.spec_to_dict(full_spec())
            doc["tracks"]["head"][0]["pose"]["pitch_deg"] = value
            with self.assertRaisesRegex(ValueError, "pitch_deg: .* is not a finite number"):
                io.spec_from_dict(doc)
        with self.assertRaisesRegex(ValueError, "not a finite number"):
            io.loads_spec(io.dumps_yaml(full_spec()).replace("duration_s: 0.25", "duration_s: .nan"))

    def test_spec_to_dict_refuses_values_a_file_cannot_hold(self):
        with self.assertRaisesRegex(ValueError, r"tracks.head\[0\].pose.pitch_deg: cannot store"):
            io.spec_to_dict(full_spec(head=(HeadKey(0.5, Pose6(pitch=math.nan)),)))
        with self.assertRaisesRegex(ValueError, "name"):
            io.spec_to_dict(full_spec(name="a/b"))

    def test_yaml_text_problems_are_value_errors(self):
        text = io.dumps_yaml(full_spec())
        dup = text.replace("    hold_s: 0.35\n", "    hold_s: 0.35\n    hold_s: 0.5\n")
        self.assertNotEqual(dup, text)
        with self.assertRaisesRegex(ValueError, "duplicate key 'hold_s'"):
            io.loads_spec(dup)
        with self.assertRaisesRegex(ValueError, "invalid YAML"):
            io.loads_spec("schema: [unclosed\n")
        with self.assertRaisesRegex(ValueError, "empty"):
            io.loads_spec("# only a comment\n")
        with self.assertRaisesRegex(ValueError, "write 1.0e-3"):
            io.loads_spec(text.replace("duration_s: 0.25", "duration_s: 1e-3"))

    def test_json_duplicate_key_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON: duplicate key 'name'"):
            io.loads_spec('{"name": "a", "name": "b"}', "json")
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            io.loads_spec("{not json", "json")


PITCH_DOC = (
    "schema: reachy-motion/v1\nname: success\nvariant: expressive\nintent: x\n"
    "expected: {valence: 0.1, arousal: 0.1}\nprinciples: []\n"
    "tracks:\n  head:\n  - {duration_s: 0.5, pose: {pitch_deg: PITCH}}\n"
)


def load_pitch_deg(text: str) -> float:
    return math.degrees(io.loads_spec(PITCH_DOC.replace("PITCH", text)).head[0].pose.pitch)


class TestNumbers(unittest.TestCase):
    """Hand-typed numbers: YAML 1.1 forms that silently change the value are refused with a hint."""

    def test_yaml_1_1_integer_and_float_forms_are_refused(self):
        cases = {  # without the check: 010 -> 8, -010 -> -8, 012 -> 10, 0x0A -> 10, 1:30 -> 90, 1_000 -> 1000
            "010": "write 10, without leading zeros (YAML 1.1 reads 010 as octal 8)",
            "-010": "write -10, without leading zeros",
            "012": "write 12",
            "00": "write 0",
            "0x0A": "hexadecimal",
            "0b11": "binary",
            "1:30": "base-60",
            "1:30.5": "base-60",
            "1_000": "without '_' separators",
            "1_0.5": "without '_' separators",
            "!!int 09": "write 9",
            "!!float abc": "write a plain decimal number",
        }
        for text, hint in cases.items():
            with self.subTest(text=text), self.assertRaises(ValueError) as cm:
                load_pitch_deg(text)
            msg = str(cm.exception)
            self.assertIn("invalid YAML", msg)
            self.assertIn(hint, msg)
            self.assertIn("line 9", msg)  # the YAML mark points at the value

    def test_number_like_text_gets_a_hint(self):
        cases = {
            "08": "write 8, not 08",  # YAML 1.1 reads 08 / 09 as text
            "-08": "write -8, not -08",
            "-.5": "write -0.5, not -.5",
            "1e-3": "write 1.0e-3",
            "1.0e5": "write 1.0e-3",
            "inf": "only finite numbers",
            "Infinity": "only finite numbers",
            "'5'": "write it without quotes",
        }
        for text, hint in cases.items():
            with self.subTest(text=text), self.assertRaises(ValueError) as cm:
                load_pitch_deg(text)
            self.assertIn("tracks.head[0].pose.pitch_deg: expected a number", str(cm.exception))
            self.assertIn(hint, str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            load_pitch_deg("5 deg")
        self.assertNotIn("(", str(cm.exception).split("got the text")[1])  # no misleading hint

    def test_plain_decimal_forms_are_accepted(self):
        for text, deg in (("10", 10.0), ("+10", 10.0), ("-0", 0.0), ("0", 0.0), ("-2.5", -2.5), ("5.", 5.0),
                          (".5", 0.5), ("010.5", 10.5), ("1.0e+1", 10.0), ("1.5e-1", 0.15)):
            with self.subTest(text=text):
                self.assertAlmostEqual(load_pitch_deg(text), deg, places=12)

    def test_non_finite_and_huge_numbers_are_value_errors(self):
        for text in (".inf", "-.inf", ".nan", "1.0e+999"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "is not a finite number"):
                load_pitch_deg(text)
        with self.assertRaisesRegex(ValueError, "pitch_deg: a 401-character number is too large"):
            load_pitch_deg("1" + "0" * 400)  # used to raise OverflowError
        with self.assertRaisesRegex(ValueError, "invalid YAML: found a number with 5001 digits"):
            load_pitch_deg("1" + "0" * 5000)
        js = json.dumps(io.spec_to_dict(full_spec())).replace('"duration_s": 0.25', '"duration_s": 1' + "0" * 400)
        with self.assertRaisesRegex(ValueError, "duration_s: a 401-character number is too large"):
            io.loads_spec(js, "json")
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            io.loads_spec('{"schema": 1' + "0" * 5000 + "}", "json")
        with self.assertRaisesRegex(ValueError, r"tracks.head\[0\].duration_s: cannot store .* too large"):
            io.spec_to_dict(full_spec(head=(HeadKey(10 ** 400, Pose6()),)))

    def test_malformed_explicit_tags_and_nesting_are_value_errors(self):
        for text in ("!!timestamp abc", "!!float ''", "!!binary 'x'", "[" * 3000 + "]" * 3000):
            with self.subTest(text=text[:20]), self.assertRaisesRegex(ValueError, "invalid YAML"):
                load_pitch_deg(text)
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            io.loads_spec('{"schema": ' + "[" * 3000 + "]" * 3000 + "}", "json")


class TestAntennaRest(unittest.TestCase):
    def test_rest_angle_is_written_as_rest_and_read_back_exactly(self):
        spec = full_spec(antennas=(AntennaKey(0.5, INIT_ANTENNAS, label="settle"),
                                   AntennaKey(0.5, (INIT_ANTENNAS[0], 0.5), label="one side"),
                                   AntennaKey(0.5, (math.radians(-10), math.radians(10)), label="ten")),
                         start=RobotState(head=Pose6.from_deg_mm(yaw_deg=2)))
        d = io.spec_to_dict(spec)
        keys = d["tracks"]["antennas"]
        self.assertEqual((keys[0]["right_deg"], keys[0]["left_deg"]), ("rest", "rest"))
        self.assertEqual(keys[1]["right_deg"], "rest")  # per side
        self.assertAlmostEqual(keys[1]["left_deg"], math.degrees(0.5), places=12)
        self.assertEqual((keys[2]["right_deg"], keys[2]["left_deg"]), (-10.0, 10.0))  # -10/+10 deg is not rest
        self.assertEqual(d["start"]["antennas_deg"], {"right": "rest", "left": "rest"})
        text = io.dumps_yaml(spec)
        self.assertIn("right_deg: rest", text)
        self.assertIn("antennas_deg: {right: rest, left: rest}", text)
        for back in (io.loads_spec(text), io.loads_spec(io.dumps_json(spec), "json")):
            self.assertEqual(back.antennas[0].antennas, INIT_ANTENNAS)  # the SDK constants, exactly
            self.assertEqual(back.antennas[1].antennas[0], INIT_ANTENNAS[0])
            self.assertEqual(back.antennas[2].antennas, (math.radians(-10), math.radians(10)))
            self.assertEqual(back.start.antennas, INIT_ANTENNAS)

    def test_rest_in_a_hand_written_file(self):
        doc = minimal_doc()
        doc["tracks"]["antennas"] = [{"duration_s": 0.3, "right_deg": -40, "left_deg": "rest"}]
        doc["start"] = {"antennas_deg": {"right": "rest", "left": 30}}
        spec = io.spec_from_dict(doc)
        self.assertEqual(spec.antennas[0].antennas, (math.radians(-40), INIT_ANTENNAS[1]))
        self.assertEqual(spec.start.antennas, (INIT_ANTENNAS[0], math.radians(30)))
        for bad in ("REST", "rest ", None, True):
            doc["tracks"]["antennas"][0]["left_deg"] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(
                    ValueError, r"tracks.antennas\[0\].left_deg: expected a number \(deg\) or 'rest'"):
                io.spec_from_dict(doc)


class TestFiles(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_then_load_yaml(self):
        spec = full_spec()
        path = io.save_spec_file(spec, self.dir / "aha_recommend.expressive.yaml")
        self.assertEqual(path, self.dir / "aha_recommend.expressive.yaml")
        assert_specs_close(self, spec, io.load_spec_file(path))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["aha_recommend.expressive.yaml"])  # no .tmp

    def test_save_then_load_json(self):
        spec = full_spec()
        path = io.save_spec_file(spec, self.dir / "aha_recommend.expressive.json")
        text = path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text)["schema"], "reachy-motion/v1")
        self.assertIn("추천", text)  # unicode kept readable
        assert_specs_close(self, spec, io.load_spec_file(path))

    def test_save_into_a_directory_uses_the_canonical_name(self):
        path = io.save_spec_file(full_spec(variant="neutral"), self.dir)
        self.assertEqual(path.name, "aha_recommend.neutral.yaml")
        self.assertEqual(io.load_spec_file(path).variant, "neutral")

    def test_header_comment(self):
        text = io.save_spec_file(full_spec(draft=True), self.dir).read_text(encoding="utf-8")
        header = text.split("schema:")[0]
        self.assertTrue(header.startswith("# "))
        self.assertTrue(all(line.startswith("# ") for line in header.splitlines()))
        for needle in ("DRAFT", "degrees", "millimetres", "seconds", "hold_s", "minjerk", "absolute", "not measured",
                       "'rest' = the SDK rest angle exactly", "-9.998/+9.998 deg", "plain decimal numbers"):
            self.assertIn(needle, header)
        self.assertNotIn("about -10/+10", header)  # -10/+10 deg is not the rest angle
        signed = io.dumps_yaml(full_spec(draft=False))
        self.assertNotIn("DRAFT", signed)
        self.assertIn("Signed-off", signed)
        neutral = io.dumps_yaml(full_spec(variant="neutral"))
        self.assertIn("Neutral variant", neutral)
        self.assertIn("leave tracks.antennas empty", neutral)
        self.assertNotIn("#", io.dumps_yaml(full_spec(), header=False).split("\n")[0])

    def test_file_name_rule(self):
        spec = full_spec()
        text = io.dumps_yaml(spec)
        for bad in ("aha.yaml", "aha_recommend.expressive.v2.yaml", "aha_recommend.expressive.txt",
                    "aha_recommend..yaml"):
            p = self.dir / bad
            p.write_text(text, encoding="utf-8")
            with self.subTest(name=bad), self.assertRaisesRegex(ValueError, "motion file must"):
                io.load_spec_file(p)
        wrong = self.dir / "aha_recommend.neutral.yaml"
        wrong.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "rename it to aha_recommend.expressive.yaml"):
            io.load_spec_file(wrong)
        with self.assertRaisesRegex(ValueError, "file name does not match"):
            io.save_spec_file(spec, self.dir / "boredom.expressive.yaml")
        self.assertEqual(io.parse_motion_file_name("x/boredom.neutral.YML"), ("boredom", "neutral", ".yml"))
        self.assertEqual(io.motion_file_name("success", "neutral", ".json"), "success.neutral.json")
        with self.assertRaisesRegex(ValueError, "motion file must"):
            io.parse_motion_file_name("success\n.expressive.yaml")
        with self.assertRaisesRegex(ValueError, "name: expected a name"):  # not an OSError from the file system
            io.save_spec_file(full_spec(name="success\n"), self.dir)
        with self.assertRaisesRegex(ValueError, "name: expected a name"):  # name: | (literal block) adds a newline
            io.loads_spec(io.dumps_yaml(full_spec()).replace("name: aha_recommend\n", "name: |\n  aha_recommend\n"))

    def test_load_errors_name_the_file(self):
        p = self.dir / "boredom.neutral.yaml"
        p.write_text("schema: reachy-motion/v1\nname: boredom\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"^boredom.neutral.yaml: top level: missing keys"):
            io.load_spec_file(p)
        p.write_text(io.dumps_yaml(full_spec(name="boredom", variant="neutral")).replace(
            "duration_s: 0.25", "duration_s: 1" + "0" * 400), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"^boredom.neutral.yaml: .*duration_s: .* too large"):
            io.load_spec_file(p)  # used to escape as OverflowError

    def test_non_utf8_file_names_the_file(self):
        # A Korean Windows editor may save cp949; the error must still be a ValueError naming the file.
        p = self.dir / "success.expressive.yaml"
        p.write_bytes(io.dumps_yaml(full_spec(name="success", description="성공 끄덕임")).encode("cp949"))
        with self.assertRaisesRegex(ValueError, r"^success.expressive.yaml: not UTF-8 text \(save the file as UTF-8\)"):
            io.load_spec_file(p)

    def test_byte_order_mark_is_tolerated(self):
        spec = full_spec()
        p = self.dir / "aha_recommend.expressive.yaml"
        p.write_text("﻿" + io.dumps_yaml(spec), encoding="utf-8")
        assert_specs_close(self, spec, io.load_spec_file(p))
        j = self.dir / "aha_recommend.expressive.json"
        j.write_text("﻿" + io.dumps_json(spec), encoding="utf-8")
        assert_specs_close(self, spec, io.load_spec_file(j))

    def test_registry_loads_saved_files(self):
        ex, ne = full_spec(), full_spec(variant="neutral", sound=None)
        io.save_spec_file(ex, self.dir)
        io.save_spec_file(ne, self.dir)
        lib = default_library(self.dir)
        self.assertEqual(len(lib), 2)
        assert_specs_close(self, ex, lib.get("aha_recommend", "expressive"))
        assert_specs_close(self, ne, lib.get("aha_recommend", "neutral"))

    def test_hand_written_file(self):
        p = self.dir / "success.expressive.yaml"
        p.write_text(
            "schema: reachy-motion/v1\n"
            "name: success\n"
            "variant: expressive   # comments are fine\n"
            "intent: task done\n"
            "expected: {valence: 0.8, arousal: 0.7}\n"
            "principles:\n"
            "- {principle: exaggeration, how: big nod}\n"
            "tracks:\n"
            "  head:\n"
            "  - {label: nod, duration_s: 0.3, easing: cartoon, pose: {pitch_deg: 12, z_mm: -5}}\n"
            "  - {duration_s: 0.4, hold_s: 0.2, pose: {}}\n"
            "  antennas:\n"
            "  - {duration_s: 0.2, right_deg: -40, left_deg: 40}\n"
            "  body:\n"
            "sound: {file: ding.wav, at_s: 0.1}\n",
            encoding="utf-8")
        spec = io.load_spec_file(p)
        self.assertEqual(spec.validate(), [])
        self.assertEqual(spec.head[0].pose, Pose6(pitch=math.radians(12), z=-0.005))
        self.assertEqual(spec.head[0].easing, Easing.CARTOON)
        self.assertEqual((spec.head[1].hold, spec.head[1].pose), (0.2, Pose6()))
        self.assertEqual(spec.antennas[0].antennas, (math.radians(-40), math.radians(40)))
        self.assertEqual((spec.body, spec.start, spec.sound), ((), REST, SoundCue("ding.wav", 0.1)))


class TestSdkFree(unittest.TestCase):
    def test_io_imports_no_sdk_and_only_library_modules(self):
        tree = ast.parse(Path(io.__file__).read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse([m for m in modules if m.split(".")[0] == "reachy_mini"], modules)
        own = [m for m in modules if m.startswith("reachy_motion")]
        self.assertTrue(all(m.startswith("reachy_motion.library.") for m in own), own)


if __name__ == "__main__":
    unittest.main()
