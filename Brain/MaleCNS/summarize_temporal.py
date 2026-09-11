"""Latency comparison with identical calibration, EMA versus no EMA."""
import copy
import json
import numpy as np
import argparse
from evaluate_temporal_decoder import OUT,load,evaluate


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--hysteresis',action='store_true'); args=parser.parse_args()
    prefix='hysteresis_' if args.hysteresis else ''
    config=json.loads((OUT/(prefix+'selected_decoder.json')).read_text())['config']
    trials=load('validation_hysteresis' if args.hysteresis else 'validation'); assert len(trials)==5
    filtered=evaluate(trials,config)
    instant=copy.deepcopy(config); instant['tauMs']=[1e-9,1e-9]
    before=evaluate(trials,instant)
    comparisons=[]
    for r,b in zip(filtered['trials'],before['trials']):
        for f,u in zip(r['blocks'],b['blocks']):
            comparisons.append({'seed':r['seed'],'action':f['action'],'block':f['block'],
              'firstCorrectMs':f['firstCorrectMs'],'stableCorrectMs':f['stableCorrectMs'],
              'stableCorrectWallMs':f['stableCorrectWallMs'],
              'withoutEmaFirstCorrectMs':u['firstCorrectMs'],'withoutEmaStableCorrectMs':u['stableCorrectMs'],
              'addedFirstCorrectMs':f['firstCorrectMs']-u['firstCorrectMs'] if f['firstCorrectMs'] is not None and u['firstCorrectMs'] is not None else None})
    summary=[]
    for action in ('STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L'):
        blocks=[b for r in filtered['trials'] for b in r['blocks'] if b['action']==action]
        outputs=[m for b in blocks for m in (b['outputs'][-1:] if action=='STOP' else b['outputs'][-4:])]
        summary.append({'action':action,'passedBlocks':sum(b['passed'] for b in blocks),'totalBlocks':len(blocks),
              'forwardRange':[min(m['forward'] for m in outputs),max(m['forward'] for m in outputs)],
              'turnRange':[min(m['turn'] for m in outputs),max(m['turn'] for m in outputs)],
              'stableLatenciesMs':[b['stableCorrectMs'] for b in blocks]})
    report={'passed':filtered['passed'],'actions':summary,'latencies':comparisons,
        'runtimeSeconds':sum(t['runtimeSeconds'] for t in trials),'peakRssBytes':max(t['peakRssBytes'] for t in trials),
        'baselineComparison':'Same global normalization/deadzone; alpha=1 comparison. Original pre-temporal motor also retained in raw trajectories.',
        'limitation':'All times discretized at50ms brain windows; wall times sum recorded compute only, not network E2E.'}
    (OUT/(prefix+'latency_summary.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'actions':summary,'runtimeSeconds':report['runtimeSeconds'],'peakRssBytes':report['peakRssBytes']}),flush=True)


if __name__=='__main__': main()
