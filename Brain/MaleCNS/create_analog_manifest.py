"""Freeze handoff asset hashes after all Mac gates; no ready=true claim."""
import json
from analog_controller import ROOT
from verify_analog_assets import digest


def main():
    graph=ROOT/'artifacts/neuron_checkpoint'; results=ROOT/'Docs/mac/checkpoints/temporal'
    assert json.loads((results/'hysteresis_final_validation.json').read_text())['passed']
    assert json.loads((results/'server_e2e.json').read_text())['passed']
    files=['Brain/MaleCNS/config/analog_temporal_v1.json','Contracts/fixtures/malecns_game_brain_controller_frames_wire_v1.jsonl',
           'Brain/MaleCNS/shiu_compatible.py','Brain/MaleCNS/analog_controller.py','Brain/MaleCNS/temporal_motor_decoder.py',
           'Brain/MaleCNS/brain_server_analog.py','Brain/MaleCNS/brain_server_malecns.py']
    manifest={'ready':False,'datasetManifest':json.loads((ROOT/'Brain/MaleCNS/results/download_manifest.json').read_text()),
              'graphFiles':{n:{'bytes':(graph/n).stat().st_size,'sha256':digest(graph/n)} for n in ('body_ids.npy','indptr.npy','targets.npy','weights.npy')},
              'repoFiles':{name:digest(ROOT/name) for name in files},
              'runtimeDependencies':'Brain/MaleCNS/requirements-runtime.txt',
              'windowsReplayVerified':False,'windowsLiveVerified':False}
    (ROOT/'Brain/MaleCNS/config/analog_handoff_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__': main()
