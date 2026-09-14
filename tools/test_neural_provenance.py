"""Pure provenance fixtures; no graph, LIF, server or simulated Brain execution."""
import ast
import copy
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
# Load the actual pure function and Action table without importing numerical
# backends or constructing a controller. This suite exercises metadata only.
source = ast.parse((ROOT / 'Brain/MaleCNS/analog_controller.py').read_text())
definitions = [node for node in source.body
               if isinstance(node, ast.FunctionDef) and node.name == 'build_readout_provenance'
               or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'ACTIONS'
                                                       for target in node.targets)]
scope = {}
exec(compile(ast.Module(body=definitions, type_ignores=[]), 'analog_controller.py', 'exec'), scope)
build_readout_provenance = scope['build_readout_provenance']
ACTIONS = scope['ACTIONS']


class NeuralProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'Brain/MaleCNS/config/analog_temporal_v1.json').read_text())

    def metadata(self, action='FORWARD'):
        return build_readout_provenance(self.config['inputs'], self.config['readouts'], action)

    def test_current_config_and_each_action_eligibility(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                data = self.metadata(action)
                for side in ('L', 'R'):
                    item = data['DNg100_'+side+'_Hz']
                    self.assertEqual(item['configuredStimulusGroups'], ['F'])
                    self.assertEqual(item['eligibleForDirectStimulation'], 'F' in ACTIONS[action])
                    self.assertEqual(item['kind'], 'neuron_readout')
                self.assertEqual(data['DNg100_L_Hz']['bodyId'], 10045)
                self.assertEqual(data['DNa02_R_Hz']['configuredStimulusGroups'], [])
                self.assertFalse(data['DNa02_R_Hz']['eligibleForDirectStimulation'])

    def test_changed_input_config_same_backend_does_not_infer_by_name(self):
        self.config.update(backendId='MALECNS_EXPERIMENTAL', datasetId='male-cns:v1.0')
        self.config['inputs']['F'] = [10360]
        data = self.metadata()
        self.assertEqual(data['DNg100_L_Hz']['configuredStimulusGroups'], [])
        self.assertFalse(data['DNg100_L_Hz']['eligibleForDirectStimulation'])
        self.assertEqual(data['DNa02_R_Hz']['configuredStimulusGroups'], ['F'])
        self.assertTrue(data['DNa02_R_Hz']['eligibleForDirectStimulation'])

    def test_changed_readout_id_and_multiple_groups(self):
        self.config['readouts']['DNg100_L_Hz'] = self.config['inputs']['R'][0]
        self.config['inputs']['L'].append(self.config['inputs']['R'][0])
        right = self.metadata('TURN_R')['DNg100_L_Hz']
        self.assertEqual(right['bodyId'], int(self.config['inputs']['R'][0]))
        self.assertEqual(right['configuredStimulusGroups'], ['L', 'R'])
        self.assertTrue(right['eligibleForDirectStimulation'])
        self.assertFalse(self.metadata('FORWARD')['DNg100_L_Hz']['eligibleForDirectStimulation'])

    def test_derived_metrics_and_aggregates_are_not_neurons(self):
        data = self.metadata()
        for key, dependencies in [('DNp09_Hz', ['DNp09_L_Hz', 'DNp09_R_Hz']),
                                  ('DNa02Difference_Hz', ['DNa02_R_Hz', 'DNa02_L_Hz'])]:
            self.assertEqual(data[key], {'kind': 'derived_metric', 'derivedFrom': dependencies})
        for axis in ('forward', 'turn'):
            self.assertEqual(data[axis+'_raw'], {'kind': 'selected_vnc_aggregate',
                'derivedFrom': ['populationDeltaMv.'+axis+'.R', 'populationDeltaMv.'+axis+'.L']})

    def test_detached_snapshot_and_bounded_metadata(self):
        before = copy.deepcopy(self.config)
        first = self.metadata()
        self.assertEqual(self.config, before)
        self.assertEqual(first, self.metadata())
        first['DNg100_L_Hz']['configuredStimulusGroups'].append('R')
        self.assertEqual(self.metadata()['DNg100_L_Hz']['configuredStimulusGroups'], ['F'])
        self.assertEqual(len(first), 10)
        self.assertLess(len(json.dumps(first)), 4096)
        for n in range(100):
            self.config['readouts']['extra'+str(n)] = n+1
        self.assertEqual(len(self.metadata()), 10)

    def test_invalid_or_unknown_input_provenance_not_guessed(self):
        self.assertEqual(self.metadata('UNKNOWN'), {})
        self.assertEqual(build_readout_provenance(None, {}, 'FORWARD'), {})
        self.config['inputs']['F'] = [True]
        self.assertEqual(self.metadata(), {})
        self.config['inputs'] = {'long'*20: [10045]}
        self.assertEqual(self.metadata(), {})
        self.config['inputs'] = {str(n): [] for n in range(17)}
        self.assertEqual(self.metadata(), {})

    def test_unconfigured_readout_and_dependency_are_omitted(self):
        del self.config['readouts']['DNp09_L_Hz']
        data = self.metadata()
        self.assertNotIn('DNp09_L_Hz', data)
        self.assertNotIn('DNp09_Hz', data)


if __name__ == '__main__':
    unittest.main()
