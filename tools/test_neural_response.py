"""Small analyzer fixtures only, never a replacement for live Brain testing."""
import copy
import json
import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from Runtime.Bridge.neural_response import NeuralResponseAnalyzer


IDENTITY = {'instanceId': 'brain-1', 'sessionId': 'session-1', 'backendId': 'MALECNS_EXPERIMENTAL',
            'datasetId': 'male-cns:v1.0', 'sourceHash': 'a'*64, 'graphHash': 'b'*64, 'configHash': 'c'*64}
CALIBRATED = {'thresholdVersion': 'fixture-only-v1', 'calibrationEvidence': 'unit-fixture-not-production',
              **{key: {'forward': value, 'turn': value} for key, value in
                 [('rawThresholdMv', .1), ('filteredThresholdMv', .1), ('motorThreshold', .1), ('changeThresholdMv', .2)]}}
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
    def calibrated(self, thresholds=None, artifact_changes=None):
        config = copy.deepcopy(CALIBRATED)
        if thresholds:
            config.update(thresholds)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'calibration.json'
        data = {'version': config['thresholdVersion'],
                **{key: IDENTITY[key] for key in ('sourceHash', 'graphHash', 'configHash')},
                'thresholds': {key: config[key] for key in ('rawThresholdMv', 'filteredThresholdMv', 'motorThreshold', 'changeThresholdMv')}}
        data.update(artifact_changes or {})
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        config['calibration'] = {'version': config['thresholdVersion'], 'artifact': str(path),
                                'artifactSha256': hashlib.sha256(raw).hexdigest(),
                                **{key: IDENTITY[key] for key in ('sourceHash', 'graphHash', 'configHash')}}
        return config

    def comparison_trial(self, action, previous, current, config=None):
        analyzer = NeuralResponseAnalyzer(self.calibrated() if config is None else config)
        observe(analyzer, frame(0, 'STOP', applied=1))
        for n in range(1, 6):
            observe(analyzer, frame(n, action, applied=2 if n == 1 else None, raw=previous))
        observe(analyzer, frame(6, 'STOP', applied=3))
        for n in range(7, 12):
            result = observe(analyzer, frame(n, action, applied=4 if n == 7 else None, raw=current))
        return result

    def test_composite_axes_independent_and_directional(self):
        for action, sign in [('FORWARD_R', 1), ('FORWARD_L', -1)]:
            for current, changed in [((.1, .5), ['forward']), ((.5, .1), ['turn']),
                                     ((.1, .1), ['forward', 'turn']), ((.4, .4), [])]:
                result = self.comparison_trial(action, (.5, sign*.5), (current[0], sign*current[1]))
                self.assertEqual(result['comparison']['changedAxes'], changed)
                self.assertEqual(result['comparison']['changed'], bool(changed))
                self.assertEqual(set(result['comparison']['axes']), {'forward', 'turn'})
            reverse = self.comparison_trial(action, (.5, sign*.5), (.5, -sign*.5))
            self.assertFalse(reverse['comparison']['axes']['turn']['changed'])
            self.assertNotEqual(reverse['comparison']['axes']['turn']['deltaMeanMv'], 0)

    def test_distinct_axis_thresholds_and_composite_response(self):
        config = self.calibrated({'rawThresholdMv': {'forward': .1, 'turn': .4},
                                  'changeThresholdMv': {'forward': .1, 'turn': .4}})
        for action, present in [('FORWARD', True), ('TURN_R', False), ('FORWARD_R', False)]:
            analyzer = NeuralResponseAnalyzer(config)
            for n in range(4):
                result = observe(analyzer, frame(n, action, applied=1 if n == 0 else None, raw=(.3, .3)))
            self.assertEqual('selected_direction_response' in result['allowedClaims'], present)
        result = self.comparison_trial('FORWARD_R', (.5, .5), (.3, .3), config)
        self.assertEqual(result['comparison']['changedAxes'], ['forward'])

    def test_calibration_fail_closed(self):
        configs = [CALIBRATED, self.calibrated(artifact_changes={'version': 'wrong'}),
                   self.calibrated(artifact_changes={'sourceHash': 'd'*64}),
                   self.calibrated(artifact_changes={'thresholds': {}})]
        for key, value in [('artifact', 'missing-calibration.json'), ('artifactSha256', '0'*64),
                           ('version', 'wrong'), ('graphHash', 'e'*64)]:
            config = self.calibrated()
            config['calibration'][key] = value
            configs.append(config)
        config = self.calibrated()
        config['rawThresholdMv']['forward'] = .001
        configs.append(config)
        config = self.calibrated()
        config['rawThresholdMv'] = .1
        configs.append(config)
        for config in configs:
            result = self.comparison_trial('FORWARD_R', (.5, .5), (.1, .1), config)
            self.assertFalse(result['calibration']['valid'])
            self.assertEqual(result['eventType'], 'OBSERVATION_MEASURED')
            self.assertFalse(result['comparison']['changed'])

    def test_identity_mismatch_and_no_per_frame_artifact_io(self):
        config = self.calibrated()
        analyzer = NeuralResponseAnalyzer(config)
        with patch.object(Path, 'open', side_effect=AssertionError('per-frame IO')):
            for n in range(4):
                result = observe(analyzer, frame(n, applied=1 if n == 0 else None))
            self.assertTrue(result['calibration']['valid'])
            analyzer.reset()
            result = observe(analyzer, frame(0), identity={**IDENTITY, 'configHash': 'd'*64})
            self.assertFalse(result['calibration']['valid'])

    def test_readout_metadata_scoped_to_known_backend(self):
        result = observe(NeuralResponseAnalyzer(), frame(0))
        self.assertIsNone(result['selectedVncAggregation'])
        self.assertEqual(result['readoutProvenance'], {})
        value = frame(0)
        value['metadata']['backendId'] = 'OTHER'
        result = observe(NeuralResponseAnalyzer(), value, identity={**IDENTITY, 'backendId': 'OTHER'})
        self.assertIsNone(result['selectedVncAggregation'])
        self.assertEqual(result['readoutProvenance'], {})

    def test_explicit_producer_metadata_is_bounded_detached_and_not_carried_forward(self):
        analyzer = NeuralResponseAnalyzer()
        value = frame(0)
        provenance = {'DNg100_L_Hz': {'kind': 'neuron_readout', 'bodyId': 10045,
            'configuredStimulusGroups': ['F'], 'eligibleForDirectStimulation': False},
            'DNp09_Hz': {'kind': 'derived_metric', 'derivedFrom': ['DNp09_L_Hz', 'DNp09_R_Hz']},
            'forward_raw': {'kind': 'selected_vnc_aggregate', 'derivedFrom': ['populationDeltaMv.forward.R', 'populationDeltaMv.forward.L']}}
        value['metadata'].update(readoutProvenance=copy.deepcopy(provenance), selectedVncAggregation={
            'version': 'v1', 'method': 'cell_type_equal_weight_mean_delta_v', 'unit': 'mV'})
        result = observe(analyzer, value)
        self.assertEqual(result['readoutProvenance'], provenance)
        self.assertEqual(result['selectedVncAggregation']['method'], 'cell_type_equal_weight_mean_delta_v')
        value['metadata']['readoutProvenance']['DNg100_L_Hz']['configuredStimulusGroups'].append('R')
        result['readoutProvenance']['DNg100_L_Hz']['bodyId'] = 99
        self.assertEqual(analyzer.snapshot(1, 1, 1, 1)['readoutProvenance'], provenance)
        missing = observe(analyzer, frame(1))
        self.assertEqual(missing['readoutProvenance'], {})
        self.assertIsNone(missing['selectedVncAggregation'])
        value['sequence'] = 2
        value['brainTimeMs'] = 150
        value['metadata']['readoutProvenance']['DNg100_L_Hz']['configuredStimulusGroups'] = ['F'] * 17
        malformed = observe(analyzer, value)
        self.assertNotIn('DNg100_L_Hz', malformed['readoutProvenance'])
        invalid = observe(analyzer, value)
        self.assertEqual(invalid['readoutProvenance'], {})
        self.assertIsNone(invalid['selectedVncAggregation'])

    def test_freshness_duration_contract(self):
        analyzer = NeuralResponseAnalyzer({'staleMs': 400})
        result = observe(analyzer, frame(0), age_ms=300)
        self.assertEqual(result['staleAfterMs'], 400)
        self.assertTrue(analyzer.snapshot(50, 350, 1, 1)['fresh'])
        stale = analyzer.snapshot(150, 450, 1, 1)
        self.assertFalse(stale['fresh'])
        self.assertEqual(stale['staleAfterMs'], 400)
        invalid = observe(analyzer, frame(1), age_ms=401)
        self.assertFalse(invalid['fresh'])
        self.assertEqual(invalid['staleAfterMs'], 400)

    def test_missing_null_threshold_and_stop_stay_fail_closed(self):
        config = self.calibrated({'rawThresholdMv': {'forward': None, 'turn': .1},
                                  'changeThresholdMv': {'forward': None, 'turn': None}})
        result = self.comparison_trial('FORWARD_R', (.5, .5), (.1, .1), config)
        self.assertEqual(result['eventType'], 'OBSERVATION_MEASURED')
        self.assertFalse(result['comparison']['changed'])
        result = self.comparison_trial('STOP', (.5, .5), (.1, .1))
        self.assertFalse(result['comparison']['eligible'])
        self.assertEqual(result['comparison']['axes'], {})

    def test_artifact_bounded_and_strict_numbers(self):
        for contents in (b'{' , b'x'*65537):
            config = self.calibrated()
            Path(config['calibration']['artifact']).write_bytes(contents)
            config['calibration']['artifactSha256'] = hashlib.sha256(contents).hexdigest()
            self.assertFalse(observe(NeuralResponseAnalyzer(config), frame(0))['calibration']['valid'])
        config = self.calibrated({'rawThresholdMv': {'forward': 1, 'turn': 1}})
        path = Path(config['calibration']['artifact'])
        data = json.loads(path.read_bytes())
        data['thresholds']['rawThresholdMv']['forward'] = True
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        config['calibration']['artifactSha256'] = hashlib.sha256(raw).hexdigest()
        self.assertFalse(observe(NeuralResponseAnalyzer(config), frame(0))['calibration']['valid'])

    def test_relative_artifact_uses_project_root(self):
        config = self.calibrated()
        path = Path(config['calibration']['artifact'])
        config['calibration']['artifact'] = path.name
        with patch('Runtime.Bridge.neural_calibration.ROOT', path.parent):
            result = observe(NeuralResponseAnalyzer(config), frame(0))
        self.assertTrue(result['calibration']['valid'])

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
            analyzer = NeuralResponseAnalyzer(self.calibrated())
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
        analyzer = NeuralResponseAnalyzer(self.calibrated())
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
            analyzer = NeuralResponseAnalyzer(self.calibrated())
            for n in range(3):
                source = frame(n, 'STOP', applied=1 if n == 0 else None, raw=(raw, raw))
                source['raw']['filteredRaw'] = [filtered, filtered]
                source['motor'] = {'forward': motor, 'turn': motor}
                result = observe(analyzer, source)
            self.assertEqual(result['residualLayer'], layer)
            self.assertEqual(result['eventType'], 'POST_STOP_RESIDUAL')
            self.assertFalse(result['bodyMovementVerified'])

    def test_motor_without_body_and_inhibit_do_not_claim_motion(self):
        analyzer = NeuralResponseAnalyzer(self.calibrated())
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
        analyzer = NeuralResponseAnalyzer(self.calibrated())
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
