import unittest
from tools.package_judge import configurations, validate_public, package_selection


class PackageConfigurationTests(unittest.TestCase):
    def test_relative_public_config(self):
        bridge, native = configurations('https://judge.example/api/fly/translate')
        self.assertEqual(bridge['conversation']['mode'], 'text')
        self.assertEqual(native['bridgePython'], 'runtime/python/python.exe')

    def test_secret_fields_rejected(self):
        for key in ('API_KEY', 'keyFile', 'credentials', 'token'):
            with self.assertRaises(ValueError):
                validate_public({key: 'value'})

    def test_absolute_paths_rejected(self):
        for value in ('C:/secure/value', '/home/user/value', '../outside'):
            with self.assertRaises(ValueError):
                validate_public({'path': value})

    def test_endpoint_credentials_rejected(self):
        for value in ('https://user:pass@example.com/api', 'https://example.com/api?key=x',
                      'https://ai-gateway.vercel.sh/v1', 'http://example.com/api',
                      'https://example.com/api', 'https://example.com/api/fly/translate/',
                      'https://example.com:99999/api/fly/translate'):
            with self.assertRaises(ValueError):
                configurations(value)

    def test_packaged_endpoint_replaces_build_placeholder(self):
        endpoint = 'https://judge.example/api/fly/translate'
        for channel in ('Dev', 'Demo', 'Judge'):
            result = package_selection({'channel': channel, 'provider': 'Cloud',
                                        'backendUrl': 'https://example.vercel.app/api/fly/translate'}, endpoint)
            self.assertEqual(result, {'channel': channel, 'provider': 'Cloud', 'backendUrl': endpoint})
        self.assertEqual(package_selection(None, endpoint),
                         {'channel': 'Judge', 'provider': 'Cloud', 'backendUrl': endpoint})

    def test_invalid_or_local_build_selection_rejected(self):
        valid = {'channel': 'Judge', 'provider': 'Cloud', 'backendUrl': ''}
        for value in ({**valid, 'provider': 'Local'}, {**valid, 'channel': 'Unknown'},
                      {**valid, 'backendUrl': None}, {**valid, 'secret': 'x'}, {}, []):
            with self.assertRaises(ValueError):
                package_selection(value, 'https://judge.example/api/fly/translate')


if __name__ == '__main__':
    unittest.main()
