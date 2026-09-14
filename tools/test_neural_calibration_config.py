"""Offline schema tests; no Brain or production calibration is loaded."""
import copy
import unittest
from Runtime.Bridge.config import _DEFAULT, _validate, _merge, ConfigError


class NeuralCalibrationConfigTests(unittest.TestCase):
    def test_axis_defaults_and_legacy_read_compatibility(self):
        config = copy.deepcopy(_DEFAULT)
        self.assertEqual(config['neuralFeedback']['rawThresholdMv'], {'forward': None, 'turn': None})
        _validate(config)
        config['neuralFeedback']['rawThresholdMv'] = .1
        _validate(config)
        _merge(config, {'neuralFeedback': {'calibration': {'version': 'v1'},
               'rawThresholdMv': {'forward': .1, 'turn': .2}}}, 'fixture')
        _validate(config)

    def test_invalid_axis_thresholds_rejected(self):
        for value in ({'other': .1}, {'forward': True}, {'turn': 0}, {'forward': float('nan')},
                      {'turn': float('inf')}, {'forward': -1}, {'turn': '1'}, []):
            config = copy.deepcopy(_DEFAULT)
            config['neuralFeedback']['rawThresholdMv'] = value
            with self.assertRaises(ConfigError):
                _validate(config)

    def test_unknown_calibration_field_rejected(self):
        config = copy.deepcopy(_DEFAULT)
        config['neuralFeedback']['calibration'] = {'trustMe': True}
        with self.assertRaises(ConfigError):
            _validate(config)
