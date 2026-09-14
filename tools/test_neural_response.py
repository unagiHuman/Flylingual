"""Small analyzer fixtures only, never a replacement for live Brain testing."""
import copy
import json
import unittest

from Runtime.Bridge.neural_response import NeuralResponseAnalyzer


IDENTITY = {'instanceId': 'brain-1', 'sessionId': 'session-1', 'backendId': 'MALECNS_EXPERIMENTAL',
            'datasetId': 'male-cns:v1.0', 'sourceHash': 'a'*64, 'graphHash': 'b'*64, 'configHash': 'c'*64}
CALIBRATED = {'thresholdVersion': 'fixture-only-v1', 'calibrationEvidence': 'unit-fixture-not-production',
              'rawThresholdMv': .1, 'filteredThresholdMv': .1, 'motorThreshold': .1, 'changeThresholdMv': .2}
BODY_CALIBRATED = {'bodyThresholdVersion': 'fixture-only-v1', 'bodyCalibrationEvidence': 'unit-only-not-production',
                   'bodyResponseGraceMs': 100, 'bodySpeedThresholdMetersPerSecond': .05,
                   'bodyYawThresholdDegPerSec': 1, 'bodyMotorThreshold': .1, 'bodyYawSign': 1}


def frame(sequence, action='TURN_R', applied=None, raw=(.2, .3), window=50, end=None):
    return {'sequence': sequence, 'requestedAction': action, 'appliedRequestId': applied,
            'brainTimeMs': (sequence+1)*window if end is None else end, 'windowMs': window,
            'raw': {'forward_raw': raw[0], 'turn_raw': raw[1], 'filteredRaw': [.2, .3],
                    'populationDeltaMv': {'forward': {'L': .1, 'R': .2}, 'turn': {'L': .2, 'R': .4}},
                    'deltaV': [999]*100, 'bodyIds': list(range(100))},
            'motor': {'forward': .2, 'turn': .3},
            'brain': {'DNa02_R_Hz': 20}, 'performance': {'stepWallTimeMs': 10},
            'metadata': {'backendId': IDENTITY['backendId'], 'datasetId': IDENTITY['datasetId'], 'mode': 'LIVE', 'ready': False}}


def observe(analyzer, value, **kwargs):
    options = {'identity': IDENTITY, 'epoch': 1, 'generation': 1,
               'received_ms': value['sequence']*60, 'age_ms': 0}
    options.update(kwargs)
    return analyzer.observe(value, **options)


class NeuralAnalyzerTests(unittest.TestCase):
    def test_determinism_input_unchanged_and_no_arrays_retained(self):
        inputs = [frame(n, applied=1 if n == 0 else None) for n in range(8)]
        originals = copy.deepcopy(inputs)
        runs = []
        for _ in range(2):
            analyzer = NeuralResponseAnalyzer()
            runs.append([observe(analyzer, f) for f in inputs])
        self.assertEqual(inputs, originals)
        self.assertEqual(runs[0], runs[1])
        encoded = json.dumps(runs[0], allow_nan=False)
        self.assertNotIn('deltaV', encoded)
        self.assertNotIn('bodyIds', encoded)

    def test_duplicate_does_not_refresh_and_snapshot_expires(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, applied=1))
        result = observe(analyzer, frame(0, applied=1), received_ms=600)
        self.assertFalse(result['fresh'])
        self.assertEqual(result['suppressionReason'], 'non_new_sequence')
        self.assertIsNone(analyzer.snapshot(751, 0, 1, 1)['current'])

    def test_old_epoch_generation_and_identity_are_rejected(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0), epoch=2, generation=2)
        for overrides in ({'epoch': 1, 'generation': 2}, {'epoch': 2, 'generation': 1},
                          {'epoch': 2, 'generation': 2, 'identity': {**IDENTITY, 'sessionId': 'old'}}):
            self.assertFalse(observe(analyzer, frame(1), **overrides)['fresh'])
        analyzer.reset()
        self.assertTrue(observe(analyzer, frame(0), identity={**IDENTITY, 'sessionId': 'new'})['fresh'])

    def test_wrong_request_not_admitted(self):
        analyzer = NeuralResponseAnalyzer()
        result = observe(analyzer, frame(0, applied=4), request={'requestId': 5, 'action': 'TURN_R'})
        self.assertEqual(result['suppressionReason'], 'request_mismatch')
        self.assertFalse(result['fresh'])

    def test_missing_invalid_raw_and_filtered_shape_stay_unknown(self):
        for value in (None, float('nan'), float('inf'), True, '1', [], 10**400):
            analyzer = NeuralResponseAnalyzer(CALIBRATED)
            source = frame(0, applied=1, raw=(value, .3))
            source['raw']['filteredRaw'] = [1]
            result = observe(analyzer, source)
            self.assertIsNone(result['current']['raw']['forward'])
            self.assertIsNone(result['current']['filteredRaw']['forward'])
            self.assertNotIn('selected_direction_response', result['allowedClaims'])
            json.dumps(result, allow_nan=False)

    def test_uncalibrated_numbers_never_become_strength_claim(self):
        analyzer = NeuralResponseAnalyzer({'rawThresholdMv': .1})
        for n in range(5):
            result = observe(analyzer, frame(n, applied=1 if n == 0 else None))
        self.assertEqual(result['eventType'], 'OBSERVATION_MEASURED')
        self.assertNotIn('selected_direction_response', result['allowedClaims'])

    def test_direction_sign_and_stability(self):
        analyzer = NeuralResponseAnalyzer(CALIBRATED)
        for n in range(4):
            result = observe(analyzer, frame(n, 'TURN_L', applied=1 if n == 0 else None, raw=(0, .5)))
        self.assertNotIn('selected_direction_response', result['allowedClaims'])
        first = observe(analyzer, frame(4, 'TURN_L', raw=(0, -.5)))
        second = observe(analyzer, frame(5, 'TURN_L', raw=(0, -.5)))
        self.assertNotIn('selected_direction_response', first['allowedClaims'])
        self.assertIn('selected_direction_response', second['allowedClaims'])

    def test_same_action_request_is_continuation_not_new_onset(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, 'STOP', applied=1))
        for n in range(1, 6):
            observe(analyzer, frame(n, applied=2 if n == 1 else None))
        result = observe(analyzer, frame(6, applied=3))
        self.assertTrue(result['current']['requestContinuation'])
        self.assertEqual(result['comparison']['reason'], 'continued_input')
        self.assertEqual(result['current']['appliedRequestId'], 3)

    def test_complete_comparison_is_numeric_not_causal_or_percent(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, 'STOP', applied=1))
        for n in range(1, 6):
            observe(analyzer, frame(n, applied=2 if n == 1 else None, raw=(0, .1)))
        observe(analyzer, frame(6, 'STOP', applied=3))
        for n in range(7, 12):
            result = observe(analyzer, frame(n, applied=4 if n == 7 else None, raw=(0, .5)))
        self.assertTrue(result['comparison']['eligible'])
        self.assertAlmostEqual(result['comparison']['deltaMeanMv']['turn'], .4)
        self.assertIsNone(result['comparison']['relativeChange'])
        self.assertFalse(result['comparison']['changed'])
        self.assertEqual(result['causalStatus'], 'observed_difference_only')
        self.assertEqual(result['cause'], 'stimulus_variability_not_excluded')
        self.assertEqual([p['timeMs'] for p in result['currentCurve']], [50, 100, 150, 200])
        self.assertEqual(len(result['previousCurve']), 4)

    def test_gap_and_short_commands_are_not_comparable(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, 'STOP', applied=1))
        result = observe(analyzer, frame(1, applied=2))
        self.assertEqual(result['comparison']['reason'], 'insufficient_window')
        result = observe(analyzer, frame(3))
        self.assertEqual(result['comparison']['reason'], 'missing_interval')

    def test_stop_residual_layers_are_separate(self):
        for raw, filtered, motor, layer in ((.2, .2, .2, 'both'), (.2, 0, 0, 'selected_neural_readout'),
                                           (0, .2, .2, 'decoder')):
            analyzer = NeuralResponseAnalyzer(CALIBRATED)
            for n in range(3):
                source = frame(n, 'STOP', applied=1 if n == 0 else None, raw=(raw, raw))
                source['raw']['filteredRaw'] = [filtered, filtered]
                source['motor'] = {'forward': motor, 'turn': motor}
                result = observe(analyzer, source)
            self.assertEqual(result['residualLayer'], layer)
            self.assertEqual(result['eventType'], 'POST_STOP_RESIDUAL')
            self.assertFalse(result['bodyMovementVerified'])

    def test_motor_without_body_and_inhibit_do_not_claim_motion(self):
        analyzer = NeuralResponseAnalyzer(CALIBRATED)
        result = observe(analyzer, frame(0, applied=1), inhibited=True)
        self.assertFalse(result['bodyMovementVerified'])
        self.assertEqual(result['allowedClaims'], [])
        self.assertEqual(result['body']['discrepancyReason'], 'output_inhibited')

    def test_delayed_body_correlates_to_retained_frame_only(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, applied=1))
        observe(analyzer, frame(1))
        body = {'source': 'unity', 'fresh': True, 'instanceId': IDENTITY['instanceId'],
                'sessionId': IDENTITY['sessionId'], 'controlEpoch': 1, 'conversationGeneration': 1,
                'brainSequence': 0, 'ageMs': 30, 'horizontalSpeed': .5}
        result = analyzer.snapshot(61, 1, 1, 1, body=body)
        self.assertTrue(result['body']['correlated'])
        self.assertEqual(result['body']['brainTimeOffsetMs'], 50)
        self.assertEqual(result['body']['horizontalSpeed'], .5)
        self.assertFalse(result['bodyMovementVerified'])
        for change in ({'sessionId': 'old'}, {'conversationGeneration': 0}, {'brainSequence': 999}, {'ageMs': 751}):
            bad = analyzer.snapshot(61, 1, 1, 1, body={**body, **change})
            self.assertFalse(bad['body']['correlated'])
            self.assertIsNone(bad['body']['horizontalSpeed'])

    def test_buffers_bounded_by_time_and_count(self):
        analyzer = NeuralResponseAnalyzer()
        for n in range(620):
            observe(analyzer, frame(n, window=1))
        self.assertEqual(analyzer.buffered_frames, 512)
        analyzer.reset()
        for n in range(250):
            observe(analyzer, frame(n))
        self.assertLessEqual(analyzer.buffered_frames, 200)

    def test_feature_off_returns_no_event(self):
        analyzer = NeuralResponseAnalyzer({'enabled': False})
        self.assertIsNone(observe(analyzer, frame(0)))
        self.assertIsNone(analyzer.snapshot(0, 0, 1, 1))

    def test_weighted_means_and_brain_wall_time_separation(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, 'STOP', applied=1))
        observe(analyzer, frame(1, applied=2), received_ms=80,
                request={'requestId': 2, 'action': 'TURN_R', 'sentMonotonicMs': 60})
        end = 100
        for n, window, turn in ((2, 25, 1), (3, 75, 3), (4, 50, 1), (5, 50, 1)):
            end += window
            result = observe(analyzer, frame(n, window=window, end=end, raw=(0, turn)))
        self.assertAlmostEqual(result['comparison']['currentMeanMv']['turn'], 1.75)
        self.assertEqual(result['current']['applicationLatencyMs'], 20)
        self.assertEqual(result['current']['brainEndMs'], 300)

    def test_zero_reference_does_not_create_percentage_or_strength_claim(self):
        analyzer = NeuralResponseAnalyzer(CALIBRATED)
        observe(analyzer, frame(0, 'STOP', applied=1))
        for n in range(1, 6):
            observe(analyzer, frame(n, applied=2 if n == 1 else None, raw=(0, 0)))
        observe(analyzer, frame(6, 'STOP', applied=3))
        for n in range(7, 12):
            result = observe(analyzer, frame(n, applied=4 if n == 7 else None, raw=(0, .5)))
        self.assertTrue(result['comparison']['eligible'])
        self.assertIsNone(result['comparison']['relativeChange'])
        self.assertFalse(result['comparison']['changed'])

    def test_body_ages_independently_and_snapshot_does_not_mutate_previous(self):
        analyzer = NeuralResponseAnalyzer()
        body = {'source': 'unity', 'fresh': True, 'instanceId': IDENTITY['instanceId'],
                'sessionId': IDENTITY['sessionId'], 'controlEpoch': 1, 'conversationGeneration': 1,
                'brainSequence': 0, 'ageMs': 700, 'horizontalSpeed': .5}
        original = observe(analyzer, frame(0), body=body)
        result = analyzer.snapshot(100, 100, 1, 1)
        self.assertTrue(original['body']['fresh'])
        self.assertFalse(result['body']['fresh'])
        self.assertIsNone(result['body']['horizontalSpeed'])

    def body_trial(self, config=None, action='FORWARD', motor=(.4, 0)):
        analyzer = NeuralResponseAnalyzer(BODY_CALIBRATED if config is None else config)
        observe(analyzer, frame(0, 'STOP', applied=1))
        for n in range(1, 5):
            value = frame(n, action, applied=2 if n == 1 else None)
            value['motor'] = {'forward': motor[0], 'turn': motor[1]}
            observe(analyzer, value)
        return analyzer

    @staticmethod
    def body_sample(sequence=1, brain_sequence=2, **changes):
        return {'source': 'unity', 'fresh': True, 'instanceId': IDENTITY['instanceId'],
                'sessionId': IDENTITY['sessionId'], 'controlEpoch': 1, 'conversationGeneration': 1,
                'sequence': sequence, 'brainSequence': brain_sequence, 'ageMs': 0,
                'horizontalSpeed': 0, 'forwardSpeed': 0, 'yawRateDegPerSec': 0, **changes}

    def test_body_uncalibrated_stays_unknown_even_with_motor(self):
        for missing in BODY_CALIBRATED:
            analyzer = self.body_trial({**BODY_CALIBRATED, missing: None})
            result = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample())
            self.assertIsNone(result['body']['discrepancy'])
            self.assertEqual(result['body']['discrepancyReason'], 'uncalibrated')
            self.assertNotIn('motor_body_discrepancy', result['allowedClaims'])

    def test_body_grace_uses_bridge_age_and_requires_new_stable_observations(self):
        analyzer = self.body_trial()
        # Capture age puts the sample before grace even though wall now is late.
        result = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample(ageMs=170))
        self.assertEqual(result['body']['discrepancyReason'], 'response_grace')
        first = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample())
        self.assertEqual(first['body']['stableObservationMs'], 0)
        duplicate = analyzer.snapshot(400, 160, 1, 1, body=self.body_sample(ageMs=100))
        self.assertEqual(duplicate['body']['stableObservationMs'], 0)
        self.assertIsNone(duplicate['body']['discrepancy'])
        second = analyzer.snapshot(400, 160, 1, 1, body=self.body_sample(2, 3))
        self.assertEqual(second['eventType'], 'MOTOR_BODY_DISCREPANCY')
        self.assertEqual(second['body']['stableObservationMs'], 100)
        self.assertEqual(second['body']['discrepancyAxes'], ['forward'])
        self.assertIn('motor_body_discrepancy', second['allowedClaims'])
        self.assertFalse(second['bodyMovementVerified'])
        self.assertEqual(second['causalStatus'], 'body_cause_unresolved')

    def test_body_matching_frame_and_inhibited_stale_missing_are_rejected(self):
        for override in ({'outputInhibited': True}, {'ageMs': 751}, {'fresh': False},
                         {'brainSequence': 1}, {'instanceId': 'old'}, {'forwardSpeed': None},
                         {'sequence': True}):
            analyzer = self.body_trial()
            result = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample(**override))
            self.assertNotEqual(result['eventType'], 'MOTOR_BODY_DISCREPANCY')
            self.assertIsNone(result['body']['discrepancy'])
        analyzer = self.body_trial()
        analyzer.snapshot(300, 60, 1, 1, body=self.body_sample())
        stale = analyzer.snapshot(1000, 760, 1, 1, body=self.body_sample(2, 3))
        self.assertFalse(stale['fresh'])
        self.assertNotIn('motor_body_discrepancy', stale['allowedClaims'])
        analyzer.reset()  # Disconnect / session invalidation owns reset.
        self.assertIsNone(analyzer.snapshot(1000, 0, 1, 1, body=self.body_sample()))

    def test_body_old_request_cannot_be_compared_to_new_action(self):
        analyzer = self.body_trial()
        observe(analyzer, frame(5, 'TURN_R', applied=3))
        result = analyzer.snapshot(500, 200, 1, 1, body=self.body_sample(2, 3))
        self.assertEqual(result['body']['discrepancyReason'], 'body_request_mismatch')

    def test_yaw_sign_uses_measured_motor_and_calibrated_body_convention(self):
        for sign in (-1, 1):
            analyzer = self.body_trial({**BODY_CALIBRATED, 'bodyYawSign': sign}, action='TURN_L', motor=(0, -.4))
            moving = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample(yawRateDegPerSec=-3*sign))
            self.assertFalse(moving['body']['discrepancy'])
            # Opposite measured yaw also means the motor direction is unverified.
            analyzer.snapshot(400, 160, 1, 1, body=self.body_sample(2, 3, yawRateDegPerSec=3*sign))
            result = analyzer.snapshot(500, 260, 1, 1, body=self.body_sample(3, 4, yawRateDegPerSec=3*sign))
            self.assertEqual(result['body']['discrepancyAxes'], ['turn'])
            self.assertEqual(result['eventType'], 'MOTOR_BODY_DISCREPANCY')

    def test_body_agreement_and_stop_never_claim_action_success(self):
        analyzer = self.body_trial()
        result = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample(forwardSpeed=.5))
        self.assertFalse(result['body']['discrepancy'])
        self.assertFalse(result['bodyMovementVerified'])
        analyzer = self.body_trial(action='STOP')
        result = analyzer.snapshot(300, 60, 1, 1, body=self.body_sample())
        self.assertEqual(result['body']['discrepancyReason'], 'stop_request')

    def test_comparison_time_origin_is_explicit(self):
        analyzer = NeuralResponseAnalyzer()
        observe(analyzer, frame(0, 'STOP', applied=1))
        result = observe(analyzer, frame(1, applied=2))
        self.assertEqual(result['comparison']['timeOrigin'], 'end_of_excluded_application_frame')
        self.assertEqual(result['comparison']['originBrainTimeMs'], 100)


if __name__ == '__main__':
    unittest.main()
