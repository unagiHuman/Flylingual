"""Calibrate only on exploration trajectories; freeze before five-seed gate."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from analog_controller import ROOT
from temporal_motor_decoder import TemporalMotorDecoder

OUT=ROOT/'Docs/mac/checkpoints/temporal'


def load(phase):
    return [json.load(gzip.open(p,'rt')) for p in sorted(OUT.glob(phase+'_[0-9]*.json.gz'))]


def evaluate(trials, config):
    reports=[]
    for trial in trials:
        decoder=TemporalMotorDecoder(config); outputs=[]
        for f in trial['frames']:
            outputs.append(decoder.decode([f['raw']['forward_raw'],f['raw']['turn_raw']]))
        blocks=[]
        for b in sorted(set(f['experiment']['block'] for f in trial['frames'])):
            indices=[i for i,f in enumerate(trial['frames']) if f['experiment']['block']==b]
            action=trial['frames'][indices[0]]['requestedAction']; ms=[outputs[i] for i in indices]
            def correct(m):
                f,t=m['forward'],m['turn']; zero=.02 if config['mode']=='ema_only' else 1e-12
                if action=='STOP': return f<=zero and abs(t)<=zero
                if action=='FORWARD': return f>0 and abs(t)<=zero
                if action=='TURN_R': return f<=.15 and t>0
                if action=='TURN_L': return f<=.15 and t<0
                if action=='FORWARD_R': return f>0 and t>0
                if action=='FORWARD_L': return f>0 and t<0
            good=[bool(correct(m)) for m in ms]
            first=next(((k+1)*50 for k,v in enumerate(good) if v),None)
            stable=next(((k+1)*50 for k in range(len(good)) if all(good[k:])),None)
            passed=bool(all(good[-4:])) if action!='STOP' else bool(good[-1])
            cumulative=np.cumsum([trial['frames'][i]['performance']['stepWallTimeMs'] for i in indices])
            blocks.append({'action':action,'block':b,'passed':passed,'correctWindows':good,
                'firstCorrectMs':first,'stableCorrectMs':stable,
                'stableCorrectWallMs':float(cumulative[stable//50-1]) if stable else None,
                'outputs':ms})
        reports.append({'seed':trial['seed'],'passed':all(b['passed'] for b in blocks),'blocks':blocks})
    return {'passed':all(r['passed'] for r in reports),'passedSeeds':sum(r['passed'] for r in reports),
            'passedBlocks':sum(b['passed'] for r in reports for b in r['blocks']),'trials':reports}


def main():
    p=argparse.ArgumentParser(); p.add_argument('--validation',action='store_true'); args=p.parse_args()
    if args.validation:
        selected=json.loads((OUT/'selected_decoder.json').read_text()); trials=load('validation'); assert len(trials)==5
        report=evaluate(trials,selected['config'])
        report.update({'selected':selected,'ready':False,'selectionFrozenBeforeValidation':True,
                       'rawRuntimeSeconds':sum(t['runtimeSeconds'] for t in trials),'peakRssBytes':max(t['peakRssBytes'] for t in trials)})
        (OUT/'final_validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('passed','passedSeeds','passedBlocks')}),flush=True)
        return
    trials=load('calibration'); assert len(trials)==3
    classification=[]
    for tr in trials:
        values=[f['raw']['turn_raw'] for f in tr['frames'] if f['requestedAction']=='FORWARD_R']
        label='C_effectively_zero' if max(abs(x) for x in values)<1e-6 else ('A_positive_continuous' if min(values)>0 else 'B_sign_fluctuating')
        classification.append({'seed':tr['seed'],'turnRaw':values,'classification':label})
    old=json.loads((ROOT/'Brain/MaleCNS/config/analog_backend_v1.json').read_text())['decoder']['matrix']
    sweep=[]
    for mode in ('ema_only','ema_deadzone','ema_hysteresis','ema_unmixing'):
        if mode=='ema_hysteresis' and any(s.get('passed',False) for s in sweep):
            continue  # Hysteresis only if simpler EMA variants are insufficient.
        for tau in (100,150,200,300):
            cfg={'mode':mode,'tauMs':[tau,tau],'matrix':old if mode=='ema_unmixing' else [[1,0],[0,1]],'reference':[1,1],'on':[0,0],'off':[0,0]}
            samples=[]
            for tr in trials:
                d=TemporalMotorDecoder(cfg)
                for f in tr['frames']:
                    z=d.decode([f['raw']['forward_raw'],f['raw']['turn_raw']])['transformed']
                    samples.append((f['requestedAction'],f['experiment']['windowInBlock'],z))
            fz=np.array([z for a,k,z in samples if a=='FORWARD' and k>=4])
            tz=np.array([z for a,k,z in samples if a in ('TURN_R','TURN_L') and k>=4])
            sz=np.array([z for a,k,z in samples if a=='STOP' and k==5])
            ref=np.array([np.percentile(fz[:,0],95),np.percentile(abs(tz[:,1]),95)])
            contamination=np.array([max(0,np.percentile(tz[:,0],95)),np.percentile(abs(fz[:,1]),95)])*1.05
            recovery=np.max(abs(sz),axis=0)*1.05
            on=np.maximum(np.maximum(contamination,recovery),.02*ref)
            off=np.maximum(.5*on,recovery) if mode=='ema_hysteresis' else on
            if mode=='ema_only': on=off=np.zeros(2)
            cfg.update({'reference':ref.tolist(),'on':on.tolist(),'off':off.tolist()})
            if np.any(on>=ref) or np.any(off>=ref):
                sweep.append({'config':cfg,'invalid':'threshold >= reference','passedSeeds':0,'passedBlocks':-1}); continue
            report=evaluate(trials,cfg)
            sweep.append({'config':cfg,**report})
    rank={'ema_only':0,'ema_deadzone':1,'ema_hysteresis':2,'ema_unmixing':3}
    best=max((s for s in sweep if 'invalid' not in s),key=lambda s:(s['passedSeeds'],s['passedBlocks'],-rank[s['config']['mode']],-s['config']['tauMs'][0]))
    selected={'config':best['config'],'calibrationPassed':best['passed'],'calibrationPassedSeeds':best['passedSeeds'],
        'calibrationSeeds':[t['seed'] for t in trials],'ready':False,
        'selectionRule':'Max calibration passed seeds, then blocks; ties prefer simpler mode, shorter tau. No validation data used.',
        'gate':'Active final four 50ms windows correct; STOP by300ms. PureF turn exactly deadzone (EMA-only tolerance .02), TURN forward<=.15.',
        'parameterSource':'Thresholds from pureF/TURN and STOP only; combined used for ranking tau/mode, not neuron signs or thresholds.',
        'sourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('temporal_motor_decoder.py')]}}
    (OUT/'parameter_sweep.json').write_text(json.dumps({'classification':classification,'sweep':sweep},indent=2)+'\n')
    (OUT/'selected_decoder.json').write_text(json.dumps(selected,indent=2)+'\n')
    print(json.dumps({'classification':classification,'selected':selected,'scores':[(s['config']['mode'],s['config']['tauMs'][0],s['passedSeeds'],s['passedBlocks']) for s in sweep]}),flush=True)


if __name__=='__main__': main()
