"""Calibration readiness fixtures; no Brain, Unity, server or API process."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from Runtime.Bridge.neural_calibration import Calibration, THRESHOLD_KEYS, AXES, axis_thresholds
from Runtime.Bridge.neural_response import NeuralResponseAnalyzer
from tools.test_neural_response import IDENTITY, frame, observe


class ClassificationReadyTests(unittest.TestCase):
    def config(self, changes=None):
        thresholds = {key: {axis: .1 for axis in AXES} for key in THRESHOLD_KEYS}
        for (key, axis), value in (changes or {}).items():
            thresholds[key][axis] = value
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'calibration.json'
        identity = {key: IDENTITY[key] for key in ('sourceHash', 'graphHash', 'configHash')}
        data = {'version': 'fixture-only', **identity, 'thresholds': thresholds}
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        return {**copy.deepcopy(thresholds), 'thresholdVersion': 'fixture-only', 'calibrationEvidence': 'trust me',
                'calibration': {'version': 'fixture-only', **identity, 'artifact': str(path),
                                'artifactSha256': hashlib.sha256(raw).hexdigest()}}

    def calibration(self, config):
        return Calibration(config, axis_thresholds(config))

    def test_full_artifact_and_identity_make_each_classification_ready(self):
        calibration = self.calibration(self.config())
        result = calibration.summary(IDENTITY)
        self.assertTrue(result['artifactVerified'])
        self.assertTrue(result['identityMatched'])
        self.assertTrue(result['valid'])
        self.assertEqual(set(result['classificationReady']),
                         {'responseForward', 'responseTurn', 'changeForward', 'changeTurn', 'stopResidual'})
        self.assertTrue(all(result['classificationReady'].values()))
        for key in THRESHOLD_KEYS:
            for axis in AXES:
                self.assertEqual(calibration.threshold(key, axis, IDENTITY), .1)

    def test_verified_all_null_artifact_is_not_classification_ready(self):
        calibration = self.calibration(self.config({(key, axis): None for key in THRESHOLD_KEYS for axis in AXES}))
        result = calibration.summary(IDENTITY)
        self.assertTrue(result['artifactVerified'])
        self.assertTrue(result['identityMatched'])
        self.assertTrue(result['valid'])
        self.assertFalse(any(result['classificationReady'].values()))

    def test_partial_thresholds_affect_only_required_classifications(self):
        direct = {('rawThresholdMv', 'forward'): 'responseForward', ('rawThresholdMv', 'turn'): 'responseTurn',
                  ('changeThresholdMv', 'forward'): 'changeForward', ('changeThresholdMv', 'turn'): 'changeTurn'}
        for key in THRESHOLD_KEYS:
            for axis in AXES:
                with self.subTest(key=key, axis=axis):
                    calibration = self.calibration(self.config({(key, axis): None}))
                    result = calibration.summary(IDENTITY)
                    self.assertTrue(result['valid'])
                    expected = dict.fromkeys(('responseForward', 'responseTurn', 'changeForward', 'changeTurn', 'stopResidual'), True)
                    if (key, axis) in direct:
                        expected[direct[(key, axis)]] = False
                    if key != 'changeThresholdMv':
                        expected['stopResidual'] = False
                    self.assertEqual(result['classificationReady'], expected)
                    self.assertIsNone(calibration.threshold(key, axis, IDENTITY))

    def test_missing_and_mismatched_artifacts_disable_all_classifications(self):
        for key, value in (('artifact', 'nonexistent-readiness-calibration.json'), ('artifactSha256', '0' * 64)):
            config = self.config()
            config['calibration'][key] = value
            calibration = self.calibration(config)
            result = calibration.summary(IDENTITY)
            self.assertFalse(result['artifactVerified'])
            self.assertFalse(result['identityMatched'])
            self.assertFalse(result['valid'])
            self.assertFalse(any(result['classificationReady'].values()))
            self.assertIsNone(calibration.threshold('rawThresholdMv', 'forward', IDENTITY))

    def test_identity_mismatch_preserves_artifact_verification_only(self):
        calibration = self.calibration(self.config())
        for key in ('sourceHash', 'graphHash', 'configHash'):
            identity = {**IDENTITY, key: 'f' * 64}
            result = calibration.summary(identity)
            self.assertTrue(result['artifactVerified'])
            self.assertFalse(result['identityMatched'])
            self.assertFalse(result['valid'])
            self.assertEqual(result['status'], 'brain_identity_mismatch')
            self.assertFalse(any(result['classificationReady'].values()))
            self.assertIsNone(calibration.threshold('rawThresholdMv', 'forward', identity))

    def test_free_text_and_legacy_scalar_never_enable_classifications(self):
        for scalars in (False, True):
            config = self.config()
            config.pop('calibration')
            if scalars:
                config.update({key: .1 for key in THRESHOLD_KEYS})
            result = self.calibration(config).summary(IDENTITY)
            self.assertFalse(result['artifactVerified'])
            self.assertFalse(any(result['classificationReady'].values()))

    def test_verified_threshold_snapshot_cannot_be_changed_through_input_config(self):
        config = self.config()
        thresholds = axis_thresholds(config)
        calibration = Calibration(config, thresholds)
        thresholds['rawThresholdMv']['forward'] = 999
        config['rawThresholdMv']['forward'] = None
        self.assertEqual(calibration.threshold('rawThresholdMv', 'forward', IDENTITY), .1)
        self.assertTrue(calibration.summary(IDENTITY)['classificationReady']['responseForward'])

    def test_analyzer_response_claims_match_partial_readiness(self):
        for action, field, present in (('FORWARD', 'responseForward', False), ('TURN_R', 'responseTurn', True),
                                       ('FORWARD_R', 'responseForward', False)):
            analyzer = NeuralResponseAnalyzer(self.config({('rawThresholdMv', 'forward'): None}))
            for sequence in range(4):
                result = observe(analyzer, frame(sequence, action, applied=1 if sequence == 0 else None, raw=(.3, .3)))
            self.assertEqual(result['calibration']['classificationReady'][field], present)
            self.assertEqual('selected_direction_response' in result['allowedClaims'], present)

    def test_analyzer_change_claims_match_partial_readiness(self):
        for axis in AXES:
            config = self.config({('changeThresholdMv', axis): None})
            analyzer = NeuralResponseAnalyzer(config)
            observe(analyzer, frame(0, 'STOP', applied=1))
            for n in range(1, 6):
                observe(analyzer, frame(n, 'FORWARD_R', applied=2 if n == 1 else None, raw=(.5, .5)))
            observe(analyzer, frame(6, 'STOP', applied=3))
            # Only the unavailable axis changes; the other axis cannot justify a claim.
            current = (.2, .5) if axis == 'forward' else (.5, .2)
            for n in range(7, 12):
                result = observe(analyzer, frame(n, 'FORWARD_R', applied=4 if n == 7 else None, raw=current))
            field = 'changeForward' if axis == 'forward' else 'changeTurn'
            self.assertFalse(result['calibration']['classificationReady'][field])
            self.assertEqual(result['comparison']['changedAxes'], [])
            self.assertNotIn('response_changed_observed_only', result['allowedClaims'])

    def test_stop_residual_claim_requires_all_six_thresholds(self):
        for missing in (None, *((key, axis) for key in THRESHOLD_KEYS[:3] for axis in AXES)):
            analyzer = NeuralResponseAnalyzer(self.config({missing: None} if missing else {}))
            for sequence in range(3):
                result = observe(analyzer, frame(sequence, 'STOP', applied=1 if sequence == 0 else None))
            self.assertEqual(result['calibration']['classificationReady']['stopResidual'], missing is None)
            self.assertEqual('post_stop_both' in result['allowedClaims'], missing is None)


if __name__ == '__main__':
    unittest.main()
