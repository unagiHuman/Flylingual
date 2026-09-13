"""Offline tests for verify_native_voice helpers; never launch Unity or Brain."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_native_voice as runner


class NativeVoiceRunnerTests(unittest.TestCase):
    def test_external_manifest_and_wav_hashes_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "sample.wav"
            wav.write_bytes(b"RIFFfixture")
            digest = hashlib.sha256(wav.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schemaVersion": 1, "fixtures": [{"file": "sample.wav", "sha256": digest}]}), encoding="utf-8-sig")
            result = runner.collect_hashes(manifest)
            self.assertEqual(result["fixtures"][str(manifest)], runner.sha256(manifest))
            self.assertEqual(result["fixtureWavs"][str(wav)], digest)

    def test_missing_probe_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            report = runner.read_report(Path(directory))
            self.assertEqual(report["status"], "blocked")

    def test_pass_requires_probe_shutdown_and_clean_process_result(self):
        report = {"status": "pass", "pass": True, "stopped": True}
        clean = dict(timeout=False, remaining=[], ports_free=True, exit_code=0, exceptions=0, runner_error=None)
        self.assertEqual(runner.evaluate_status(report, **clean), "pass")
        for field, value in (("timeout", True), ("remaining", [12]), ("ports_free", False),
                             ("exit_code", 1), ("exceptions", 1)):
            with self.subTest(field=field):
                self.assertEqual(runner.evaluate_status(report, **{**clean, field: value}), "incomplete")
        self.assertEqual(runner.evaluate_status({**report, "stopped": False}, **clean), "incomplete")
        self.assertEqual(runner.evaluate_status({"status": "blocked"}, **clean), "blocked")
        self.assertEqual(runner.evaluate_status({"status": "fail"}, **clean), "fail")


if __name__ == "__main__":
    unittest.main()
