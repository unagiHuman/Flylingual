import unittest
import ast
from pathlib import Path
from tools.package_judge import configurations, validate_public, package_selection, runtime_sources, ROOT


class PackageConfigurationTests(unittest.TestCase):
    def packaged_sources(self):
        bridge, _ = configurations('https://judge.example/api/fly/translate')
        return set(runtime_sources(bridge))

    def test_all_brain_identity_sources_are_packaged(self):
        packaged = self.packaged_sources()
        self.assertIn(Path('Brain/MaleCNS/visual_threat.py'), packaged)
        self.assertIn(Path('Brain/MaleCNS/config/visual_threat_v1.json'), packaged)
        for origin in ('Runtime/Bridge/config.py', 'Brain/MaleCNS/brain_server_bridge.py'):
            tree = ast.parse((ROOT / origin).read_text(encoding='utf-8'))
            assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == '_SOURCE_FILES'
                                   for target in node.targets)]
            self.assertEqual(len(assignments), 1, origin)
            for name in ast.literal_eval(assignments[0].value):
                path = Path('Brain/MaleCNS') / name
                self.assertIn(path, packaged, f'{origin} requires {path}')
                self.assertTrue((ROOT / path).is_file(), str(path))

    def test_packaged_brain_import_closure(self):
        # No imports or graph loads: inspect local Python dependencies recursively
        # because every packaged module is checked, including newly added ones.
        packaged = self.packaged_sources()
        brain = Path('Brain/MaleCNS')
        for path in packaged:
            if path.parent != brain or path.suffix != '.py':
                continue
            tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                modules = ([item.name for item in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for module in modules:
                    local = brain / (module.split('.')[0] + '.py')
                    if (ROOT / local).is_file():
                        self.assertIn(local, packaged, f'{path} imports missing local module {local}')

    def test_packaged_launcher_import_closure(self):
        packaged = self.packaged_sources()
        for path in packaged:
            if path.parent != Path('tools') or path.suffix != '.py':
                continue
            tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                modules = ([item.name for item in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for module in modules:
                    local = Path('tools') / (module.removeprefix('tools.').split('.')[0] + '.py')
                    if (ROOT / local).is_file():
                        self.assertIn(local, packaged, f'{path} imports missing local module {local}')

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
