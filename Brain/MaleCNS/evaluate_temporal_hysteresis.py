"""Second stage after EMA holdout failure; fit on original calibration only."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from evaluate_temporal_decoder import OUT,load,evaluate
from temporal_motor_decoder import TemporalMotorDecoder


def main():
    p=argparse.ArgumentParser(); p.add_argument('--validation',action='store_true'); args=p.parse_args()
    if args.validation:
        selected=json.loads((OUT/'hysteresis_selected_decoder.json').read_text())
        data=load('validation_hysteresis'); assert len(data)==5
        result=evaluate(data,selected['config'])
        result.update({'selected':selected,'ready':False,'rawRuntimeSeconds':sum(t['runtimeSeconds'] for t in data),
                       'peakRssBytes':max(t['peakRssBytes'] for t in data)})
        (OUT/'hysteresis_final_validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print('hysteresis holdout',result['passed'],result['passedSeeds'],flush=True)
        return
    assert not json.loads((OUT/'final_validation.json').read_text())['passed']
    data=load('calibration'); base=json.loads((OUT/'parameter_sweep.json').read_text())
    candidates=[]
    for original in base['sweep']:
        if original['config']['mode']!='ema_deadzone' or 'invalid' in original: continue
        cfg=dict(original['config']); cfg['mode']='ema_hysteresis'; cfg['hysteresisAxes']=['turn']
        recovery=[]
        for trial in data:
            d=TemporalMotorDecoder(original['config'])
            for f in trial['frames']:
                z=d.decode([f['raw']['forward_raw'],f['raw']['turn_raw']])['transformed']
                if f['requestedAction']=='STOP' and f['experiment']['windowInBlock']==5: recovery.append(abs(z[1]))
        cfg['off']=[cfg['on'][0],max(.5*cfg['on'][1],1.05*max(recovery))]
        result=evaluate(data,cfg); candidates.append({'config':cfg,**result})
    best=max(candidates,key=lambda r:(r['passedSeeds'],r['passedBlocks'],-r['config']['tauMs'][0]))
    selected={'config':best['config'],'calibrationPassed':best['passed'],'calibrationSeeds':[t['seed'] for t in data],
              'ready':False,'rationale':'EMA holdout failed; turn-only symmetric hysteresis with off=max(on/2, calibration recovered STOP max*1.05); no held-out values used for thresholds.',
              'sourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('temporal_motor_decoder.py')]}}
    (OUT/'hysteresis_selected_decoder.json').write_text(json.dumps(selected,indent=2)+'\n')
    (OUT/'hysteresis_sweep.json').write_text(json.dumps(candidates,indent=2)+'\n')
    print(json.dumps(selected),flush=True)


if __name__=='__main__': main()
