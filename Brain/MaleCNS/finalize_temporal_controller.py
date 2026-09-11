"""Gate-protected config and live controller equivalence against recorded raw."""
import gzip
import json
import numpy as np
from analog_controller import ROOT,MaleCNSAnalogController


def main():
    folder=ROOT/'Docs/mac/checkpoints/temporal'
    gate=json.loads((folder/'hysteresis_final_validation.json').read_text())
    if not gate['passed'] or gate['passedSeeds']!=5: raise RuntimeError('Temporal gate incomplete')
    cfg=json.loads((ROOT/'Brain/MaleCNS/config/analog_backend_v1.json').read_text())
    cfg['temporalDecoder']=gate['selected']['config']; cfg['sixActionValidationPassed']=True
    cfg['ready']=False; cfg['windowCalibrationMs']=50
    cfg['temporalValidationSeeds']=[r['seed'] for r in gate['trials']]
    cfg['integrationStatus']='Mac validation only; Windows Replay/Live verification required'
    path=ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json'
    path.write_text(json.dumps(cfg,indent=2)+'\n')
    original=json.load(gzip.open(folder/'validation_hysteresis_20261231.json.gz','rt'))
    c=MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',path,20261231,50).initialize()
    expected=[m for b in gate['trials'][0]['blocks'] for m in b['outputs']]
    errors=[]; frames=[]
    for old,e in zip(original['frames'],expected):
        c.set_action(old['requestedAction']); f=c.step(); frames.append(f)
        errors.append(max(abs(f['motor'][k]-e[k]) for k in ('forward','turn')))
        assert f['raw']['forward_raw']==old['raw']['forward_raw'] and f['raw']['turn_raw']==old['raw']['turn_raw']
    assert max(errors)<1e-12 and c.network_rebuild_count==1 and c.state_reset_count==0
    (folder/'controller_equivalence.json').write_text(json.dumps({'passed':True,'frames':len(frames),'maxMotorError':max(errors),
        'networkRebuildCount':1,'stateResetCount':0,'ready':False},indent=2)+'\n')
    fixture=ROOT/'Contracts/fixtures/malecns_game_brain_controller_frames_wire_v1.jsonl'
    with fixture.open('w',encoding='utf-8') as stream:
        for f in frames:
            f['metadata']['mode']='REPLAY'; f['metadata']['recordingSource']='live persistent controller'
            stream.write(json.dumps(f,separators=(',',':'))+'\n')
    print('controller equivalence and replay',len(frames),max(errors),flush=True)


if __name__=='__main__': main()
