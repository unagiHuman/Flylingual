import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.windows_native import apply_build_selection, NativeError


class BuildSelectionTests(unittest.TestCase):
    def run_selection(self, channel, provider, source=None, endpoint='https://example.com/api/fly/translate'):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = source or {'brain': {'graph': 'artifacts/neuron_checkpoint'},
                                  'conversation': {'mode': 'live', 'intentProvider': 'responses',
                                                   'localIntentUrl': 'http://127.0.0.1:11436',
                                                   'voice': 'stone', 'personaText': '常体'}}
            config = root / 'local.json'
            config.write_text(json.dumps(original), encoding='utf-8')
            selection = root / 'build-channel.json'
            selection.write_text(json.dumps({'channel': channel, 'provider': provider, 'backendUrl': endpoint}), encoding='utf-8')
            stack = {'bridgeLocalConfig': config, 'keyFile': root / 'external-key.txt'}
            result = apply_build_selection(stack, selection, root / 'private/status.json')
            self.assertEqual(json.loads(config.read_text(encoding='utf-8')), original)
            self.assertEqual(stack['bridgeLocalConfig'], config)
            generated = json.loads(result['bridgeLocalConfig'].read_text(encoding='utf-8'))
            return result, generated

    def test_all_channels_support_local_independently(self):
        for channel in ('Dev', 'Demo', 'Judge'):
            result, config = self.run_selection(channel, 'Local')
            self.assertEqual(config['conversation']['intentProvider'], 'llama_cpp')
            self.assertEqual(config['conversation']['mode'], 'live')
            self.assertEqual(config['conversation']['localIntentUrl'], 'http://127.0.0.1:11436')
            self.assertEqual(config['conversation']['voice'], 'stone')
            self.assertEqual(config['brain']['graph'], 'artifacts/neuron_checkpoint')
            self.assertIn('keyFile', result)

    def test_all_channels_support_cloud_without_key(self):
        for channel in ('Dev', 'Demo', 'Judge'):
            result, config = self.run_selection(channel, 'Cloud')
            self.assertEqual(config['conversation']['intentProvider'], 'vercel')
            self.assertEqual(config['conversation']['mode'], 'text')
            self.assertEqual(config['conversation']['intentTimeoutMs'], 5000)
            self.assertFalse(config['conversation']['localIntentResponsesFallback'])
            self.assertNotIn('keyFile', result)

    def test_unknown_and_credential_config_rejected(self):
        for source in ({'OPENAI_API_KEY': 'not-real'}, {'conversation': {'apiKey': 'not-real'}}):
            with self.assertRaises(NativeError):
                self.run_selection('Dev', 'Cloud', source)

    def test_bad_selection_rejected(self):
        for channel, provider, endpoint in (
                ('Unknown', 'Local', ''), ('Dev', 'Other', ''),
                ('Dev', 'Cloud', 'https://user:password@example.com/api/fly/translate')):
            with self.assertRaises(NativeError):
                self.run_selection(channel, provider, endpoint=endpoint)


if __name__ == '__main__':
    unittest.main()
