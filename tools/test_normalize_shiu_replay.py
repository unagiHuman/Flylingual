import collections
import json
from pathlib import Path
import tempfile
import unittest

from normalize_shiu_replay import BRAIN_FIELDS, OUTPUT, SOURCE, normalize_file, normalize_frame


class NormalizeReplayTests(unittest.TestCase):
    def test_complete_recording_preserves_measurements_and_six_actions(self):
        original = SOURCE.read_bytes()
        source = [json.loads(line) for line in original.splitlines()]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "normalized.jsonl"
            result = normalize_file(SOURCE, target)
            frames = [json.loads(line) for line in target.read_bytes().splitlines()]
            self.assertEqual(result["frameCount"], 110)
            self.assertEqual(target.read_bytes(), OUTPUT.read_bytes())
        self.assertEqual(SOURCE.read_bytes(), original)
        self.assertEqual(collections.Counter(f["requestedAction"] for f in frames),
                         {"STOP": 60, "FORWARD": 10, "TURN_R": 10, "TURN_L": 10,
                          "FORWARD_R": 10, "FORWARD_L": 10})
        for old, new in zip(source, frames):
            self.assertEqual(new["motor"], old["motor"])
            self.assertEqual(new["sequence"], old["sequence"])
            self.assertEqual(new["brainTimeMs"], old["brainSimulationTimeMs"])
            self.assertEqual(new["brain"], {k: old[k] for k in BRAIN_FIELDS})
            self.assertEqual(new["performance"], {k: old[k] for k in ("windowMs", "stepWallTimeMs")})
            self.assertIsNone(new["appliedRequestId"])
            self.assertTrue(all(v is None for v in new["diagnostics"].values()))

    def test_missing_is_null_and_action_cannot_generate_motor(self):
        frame = normalize_frame({"requestedAction": "FORWARD", "DNa02_R_Hz": 3, "DNa02_L_Hz": 1})
        self.assertEqual(frame["motor"], {"forward": None, "turn": None})
        self.assertIsNone(frame["brain"]["DNp09_Hz"])
        self.assertIsNone(frame["brain"]["DNa02Difference_Hz"])
        self.assertIsNone(frame["sequence"])
        self.assertIsNone(frame["brainTimeMs"])

    def test_explicit_null_does_not_fall_back_to_legacy_value(self):
        frame = normalize_frame({"brain": {"DNp09_Hz": None}, "DNp09_Hz": 123,
                                 "performance": None, "windowMs": 50,
                                 "brainTimeMs": None, "brainSimulationTimeMs": 50})
        self.assertIsNone(frame["brain"]["DNp09_Hz"])
        self.assertIsNone(frame["performance"]["windowMs"])
        self.assertIsNone(frame["brainTimeMs"])

    def test_wire_round_trip_is_idempotent(self):
        for line in OUTPUT.read_text().splitlines():
            frame = json.loads(line)
            self.assertEqual(normalize_frame(frame), frame)

    def test_refuses_source_overwrite(self):
        with self.assertRaisesRegex(ValueError, "must not be overwritten"):
            normalize_file(SOURCE, SOURCE)

    def test_bad_input_leaves_destination_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "input", Path(directory) / "output"
            target.write_text("keep")
            for invalid in ('[]', '{"motor": []}', '{"type":"status"}', '{"sequence":NaN}', '{broken'):
                source.write_text('{}\n' + invalid)
                with self.assertRaisesRegex(ValueError, ":2:"):
                    normalize_file(source, target)
                self.assertEqual(target.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
