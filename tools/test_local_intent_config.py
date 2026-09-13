"""Configuration-only tests; no Brain, Unity or model server."""
import copy
import unittest
from Runtime.Bridge.config import _DEFAULT, _validate, ConfigError


class LocalIntentConfigTests(unittest.TestCase):
    def test_existing_default_stays_responses(self):
        config = copy.deepcopy(_DEFAULT)
        _validate(config)
        self.assertEqual(config['conversation']['intentProvider'], 'responses')
        self.assertFalse(config['conversation']['localIntentResponsesFallback'])
        config['conversation']['localIntentResponsesFallback'] = True
        _validate(config)
        config['conversation']['localIntentResponsesFallback'] = 'true'
        with self.assertRaises(ConfigError): _validate(config)

    def test_local_opt_in(self):
        config = copy.deepcopy(_DEFAULT)
        config['conversation']['intentProvider'] = 'ollama'
        _validate(config)
        self.assertEqual(config['conversation']['localIntentModel'], 'qwen3.5:4b')
        self.assertEqual(config['conversation']['localIntentFormat'], 'compact')

    def test_reject_remote_or_ambiguous_origin(self):
        for url in ('https://127.0.0.1:11435', 'http://192.168.1.2:11435', 'http://example.com:11435',
                    'http://name:secret@127.0.0.1:11435', 'http://127.0.0.1:11435/api/chat',
                    'http://127.0.0.1:11435?token=x', 'http://127.0.0.1:11435#x',
                    'http://127.0.0.1', ' http://127.0.0.1:11435', 'http://127.0.0.1:0'):
            config = copy.deepcopy(_DEFAULT)
            config['conversation']['localIntentUrl'] = url
            with self.subTest(url=url), self.assertRaises(ConfigError): _validate(config)

    def test_invalid_provider_and_timeout(self):
        for key, value in (('intentProvider', 'fallback'), ('localIntentFormat', 'unknown'), ('localIntentCachePrompt', 1), ('intentTimeoutMs', True),
                           ('intentTimeoutMs', 0), ('intentTimeoutMs', 60001), ('localIntentModel', '')):
            config = copy.deepcopy(_DEFAULT)
            config['conversation'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError): _validate(config)

    def test_native_label_cache_is_explicit_and_validated(self):
        config = copy.deepcopy(_DEFAULT)
        config['conversation'].update(intentProvider='llama_cpp', localIntentFormat='label',
                                      localIntentUrl='http://127.0.0.1:11436', localIntentCachePrompt=True)
        _validate(config)
        config['conversation']['localIntentCachePrompt'] = False
        _validate(config)
        config['conversation']['localIntentFormat'] = 'full'
        with self.assertRaises(ConfigError): _validate(config)


if __name__ == '__main__': unittest.main()
