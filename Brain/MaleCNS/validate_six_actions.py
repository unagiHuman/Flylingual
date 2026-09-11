"""Calibration and independent persistent gate, before live integration."""
import json
import resource
import time
from pathlib import Path
import numpy as np
from analog_controller import MaleCNSAnalogController,ROOT
from analog_motor_decoder import AnalogMotorDecoder

OUT=ROOT/'Docs/mac/checkpoints/six-action'
CONFIG=ROOT/'Brain/MaleCNS/config/analog_backend_v1.json'


def main():
    started=time.perf_counter(); OUT.mkdir(parents=True,exist_ok=True)
    f=json.loads((ROOT/'Docs/mac/checkpoints/forward/selection.json').read_text())['calibration']
    t=f['turnCalibrationUnchanged']
    config={'inputs':{'F':f['inputIds'],'R':t['stimulusMapping']['groups']['R'],'L':t['stimulusMapping']['groups']['L']},
            'populations':{'forward':f['populations'],'turn':t['populations']},
            'readouts':{'DNa02_R_Hz':10360,'DNa02_L_Hz':523769,'DNg100_L_Hz':10045,'DNg100_R_Hz':10056,'DNp09_L_Hz':10783,'DNp09_R_Hz':11177},
            'decoder':None,'ready':False,'sixActionValidationPassed':False,'stimulusRateHz':100,'windowCalibrationMs':100}
    graph=ROOT/'artifacts/neuron_checkpoint'
    def run(seed,actions,window=100):
        c=MaleCNSAnalogController(graph,config,seed,window).initialize(); frames=[]
        for action in actions:
            c.set_action(action); frames.append(c.step())
        print('completed',seed,window,flush=True)
        return {'seed':seed,'windowMs':window,'initializationMs':c.initialization_ms,'frames':frames}
    pure=['STOP','FORWARD','STOP','STOP','TURN_R','STOP','STOP','TURN_L','STOP','STOP']
    cal=[run(s,pure) for s in range(20261101,20261106)]
    forward=[r['frames'][1]['raw'] for r in cal]
    contamination=np.array([x['turn_raw'] for x in forward])
    turnraw=[f['raw'] for r in cal for f in r['frames'] if f['requestedAction'] in ('TURN_R','TURN_L')]
    recovered=[r['frames'][i]['raw'] for r in cal for i in (0,3,6,9)]
    reference=[float(np.percentile([x['forward_raw'] for x in forward],95)),float(np.percentile([abs(x['turn_raw']) for x in turnraw],95))]
    deadzone=[max(1.1*max(x['forward_raw'] for x in turnraw),1.1*max(x['forward_raw'] for x in recovered),reference[0]*.02),
              max(1.1*float(np.percentile(abs(contamination),95)),1.1*max(abs(x['turn_raw']) for x in recovered),reference[1]*.02)]
    if any(d>=r for d,r in zip(deadzone,reference)): raise RuntimeError('Simple calibration insufficient')
    config['decoder']={'baseline':[0,0],'matrix':[[1,0],[0,1]],'reference':reference,'deadzone':deadzone,
        'method':'global scale/deadzone only; forward deadzone 1.1*max TURN leakage, turn deadzone 1.1*p95 pure FORWARD abs turn; recovered STOP and 2% reference floors'}
    CONFIG.write_text(json.dumps(config,indent=2)+'\n')
    decoder=AnalogMotorDecoder(config['decoder'])
    for r in cal:
        for f in r['frames']: f['motor']=decoder.decode([f['raw']['forward_raw'],f['raw']['turn_raw']])
    sequence=pure[:-1]+['STOP','FORWARD_R','STOP','STOP','FORWARD_L','STOP','STOP']
    valid=[run(s,sequence) for s in (20261111,20261112,20261113)]
    checks=[]
    for r in valid:
        ok=[]
        for i,f in enumerate(r['frames']):
            a=f['requestedAction']; m=f['motor']; passed=True
            if a=='FORWARD': passed=m['forward']>0 and abs(m['turn'])<=.15
            elif a=='TURN_R': passed=m['turn']>0 and m['forward']<=.15
            elif a=='TURN_L': passed=m['turn']<0 and m['forward']<=.15
            elif a=='FORWARD_R': passed=m['forward']>0 and m['turn']>0
            elif a=='FORWARD_L': passed=m['forward']>0 and m['turn']<0
            elif i==0 or r['frames'][i-1]['requestedAction']=='STOP': passed=m['forward']==0 and m['turn']==0
            ok.append({'sequence':i,'action':a,'passed':bool(passed),'motor':m})
        checks.append({'seed':r['seed'],'passed':all(x['passed'] for x in ok),'checks':ok})
    result={'passed':all(c['passed'] for c in checks),'ready':False,'calibration':cal,'validation':valid,'checks':checks,
        'contamination':{'seeds':list(range(20261101,20261106)),'mean':float(contamination.mean()),'median':float(np.median(contamination)),
          'std':float(contamination.std(ddof=1)),'absoluteP95':float(np.percentile(abs(contamination),95)),
          'positiveCount':int((contamination>0).sum()),'negativeCount':int((contamination<0).sum()),
          'classification':'mixed-sign variability; five seeds do not exclude systematic bias'},
        'decoder':config['decoder'],'runtimeSeconds':time.perf_counter()-started,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (OUT/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    config['sixActionValidationPassed']=result['passed']
    CONFIG.write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'decoder':config['decoder'],'contamination':result['contamination'],'checks':checks}),flush=True)


if __name__=='__main__': main()
