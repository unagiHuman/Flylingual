"""Offline bounds for independent intent admission and execution clocks."""
import copy
import unittest

from Runtime.Bridge.config import _DEFAULT, _validate, ConfigError


class IntentAgeConfigTests(unittest.TestCase):
    def test_short_execution_budget_does_not_shorten_admission_budget(self):
        config = copy.deepcopy(_DEFAULT)
        config['control'].update(defaultActionMs=500, maxActionMs=1000, maxIntentAgeMs=8000)
        _validate(config)

    def test_admission_budget_cannot_disable_or_exceed_existing_freshness_limit(self):
        for value in (0, -1, True, float('nan'), float('inf'), 8001):
            with self.subTest(value=value):
                config = copy.deepcopy(_DEFAULT)
                config['control']['maxIntentAgeMs'] = value
                with self.assertRaises(ConfigError):
                    _validate(config)


if __name__ == '__main__':
    unittest.main()
