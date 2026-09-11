"""Fit one global matrix from pure calibration only, then fresh holdout seeds."""
import json
import time
import resource
import argparse
import numpy as np
from analog_controller import MaleCNSAnalogController,ROOT
from analog_motor_decoder import AnalogMotorDecoder


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-small-contamination',action='store_true')
    args=parser.parse_args()
    out=ROOT/'Docs/mac/checkpoints/six-action'
    old=json.loads((out/'validation.json').read_text())
    path=ROOT/'Brain/MaleCNS/config/analog_backend_v1.json'
    config=json.loads(path.read_text())
    frames=[f for r in old['calibration'] for i,f in enumerate(r['frames']) if i in (0,1,3,4,6,7,9)]
    labels={'STOP':[0,0],'FORWARD':[1,0],'TURN_R':[0,1],'TURN_L':[0,-1]}
    x=np.array([[f['raw']['forward_raw'],f['raw']['turn_raw']] for f in frames])
    y=np.array([labels[f['requestedAction']] for f in frames])
    matrix=np.linalg.lstsq(x,y,rcond=None)[0].T
    z=x@matrix.T
    fi=[i for i,f in enumerate(frames) if f['requestedAction']=='FORWARD']
    ti=[i for i,f in enumerate(frames) if f['requestedAction'].startswith('TURN')]
    si=[i for i,f in enumerate(frames) if f['requestedAction']=='STOP']
    reference=[float(np.percentile(z[fi,0],95)),float(np.percentile(abs(z[ti,1]),95))]
    deadzone=[max(1.1*float(max(z[ti,0])),1.1*float(max(z[si,0])),.02*reference[0]),
              max(1.1*float(np.percentile(abs(z[fi,1]),95)),1.1*float(max(abs(z[si,1]))),.02*reference[1])]
    if args.allow_small_contamination:
        # Solve (q95-d)/(reference-d)<=.15, rather than force all F to zero.
        deadzone[1]=max((float(np.percentile(abs(z[fi,1]),95))-.15*reference[1])/.85,
                        1.1*float(max(abs(z[si,1]))),.02*reference[1])
    config['decoder']={'baseline':[0,0],'matrix':matrix.tolist(),'reference':reference,'deadzone':deadzone,
        'method':'Least squares global 2x2 from pure calibration conditions and recovered STOP; no combined or holdout data in fit. Same contamination/recovery percentile rule after transform.'}
    if args.allow_small_contamination:
        config['decoder']['method']+=' Turn deadzone solves calibration F p95 normalized absolute contamination <= .15 instead of forcing zero.'
    path.write_text(json.dumps(config,indent=2)+'\n')
    sequence=['STOP','FORWARD','STOP','STOP','TURN_R','STOP','STOP','TURN_L','STOP','STOP','FORWARD_R','STOP','STOP','FORWARD_L','STOP','STOP']
    trials=[]; started=time.perf_counter()
    for seed in ((20261131,20261132,20261133) if args.allow_small_contamination else (20261121,20261122,20261123)):
        c=MaleCNSAnalogController(ROOT/'artifacts/neuron_checkpoint',config,seed,100).initialize(); fs=[]; checks=[]
        for i,a in enumerate(sequence):
            c.set_action(a); f=c.step(); fs.append(f); m=f['motor']; ok=True
            if a=='FORWARD': ok=m['forward']>0 and abs(m['turn'])<=.15
            elif a=='TURN_R': ok=m['turn']>0 and m['forward']<=.15
            elif a=='TURN_L': ok=m['turn']<0 and m['forward']<=.15
            elif a=='FORWARD_R': ok=m['forward']>0 and m['turn']>0
            elif a=='FORWARD_L': ok=m['forward']>0 and m['turn']<0
            elif i==0 or sequence[i-1]=='STOP': ok=m['forward']==0 and m['turn']==0
            checks.append(bool(ok))
        trials.append({'seed':seed,'frames':fs,'checks':checks,'passed':all(checks)})
        print(seed,all(checks),[(f['requestedAction'],f['motor']) for f in fs if f['requestedAction']!='STOP'],flush=True)
    result={'passed':all(r['passed'] for r in trials),'decoder':config['decoder'],'fitSeeds':list(range(20261101,20261106)),
        'validation':trials,'ready':False,'runtimeSeconds':time.perf_counter()-started,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (out/('unmixing_small_contamination.json' if args.allow_small_contamination else 'unmixing.json')).write_text(json.dumps(result,indent=2)+'\n')
    config['sixActionValidationPassed']=result['passed']
    path.write_text(json.dumps(config,indent=2)+'\n')
    print('PASSED',result['passed'],flush=True)


if __name__=='__main__': main()
