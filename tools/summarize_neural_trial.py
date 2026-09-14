"""Summarize the opt-in trial's bounded numeric evidence, without dialogue."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    values=sorted(values)
    position=(len(values)-1)*fraction
    lower=int(position)
    return values[lower] + (values[min(lower+1,len(values)-1)]-values[lower])*(position-lower)


def summarize(prefix):
    prefix=Path(prefix)
    result=json.loads(prefix.with_suffix('.json').read_text(encoding='utf-8'))
    result.pop('questionReplies',None)
    step, analysis, applied, events, diagnostics = [], [], [], Counter(), []
    sequences=set()
    identity=None
    identities={}
    for path in prefix.parent.glob(prefix.name+'-bridge.jsonl*'):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                record=json.loads(line)
                kind=record['event']; events[kind]+=1
                if kind=='brain_identity':
                    identities[record.get('sessionId')]={k:record.get(k) for k in ('sourceHash','configHash','graphHash')}
                if kind=='frame':
                    frame=record['frame']; key=(frame.get('metadata',{}).get('sessionId'),frame['sequence'])
                    if key not in sequences:
                        sequences.add(key)
                        step.append(frame.get('performance',{}).get('stepWallTimeMs'))
                        identity={k:frame.get('metadata',{}).get(k) for k in ('backendId','datasetId','mode','ready','sessionId','instanceId','sourceHash','configHash','graphHash')}
                elif kind=='neural_observation': analysis.append(record['analysisMs'])
                elif kind=='command_applied': applied.append(record['e2eMs'])
                elif kind=='voice_pipeline' and 'neuralDiagnostics' in record: diagnostics.append(record['neuralDiagnostics'])
    def distribution(values):
        values=[v for v in values if type(v) in (int,float) and math.isfinite(v)]
        return {'n':len(values),'p50Ms':percentile(values,.5),'p95Ms':percentile(values,.95),'maxMs':max(values) if values else None}
    metrics_path=prefix.parent/(prefix.name+'-metrics.json')
    metrics=json.loads(metrics_path.read_text(encoding='utf-8-sig')) if metrics_path.exists() else None
    if identity:
        identity.update(identities.get(identity.get('sessionId'),{}))
    summary={'player':result,'identity':identity,'uniqueBrainFramesInLog':len(sequences),
             'stepWall':distribution(step),'analysis':distribution(analysis),
             'submittedToApplied':distribution(applied),'operationLatencyNote':'Small command count; descriptive only, not stable latency acceptance.',
             'events':events,'resources':metrics,
             'queueAndAppendMax':{k:max((d.get(k,0) for d in diagnostics),default=None) for k in
                 ('pending','senderTasks','allTasks','intentTasks','controlQueueDepth','motorQueueDepth','contextAppends','maxSummaryChars')}}
    output=prefix.parent/(prefix.name+'-summary.json')
    output.write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('prefix')
    summarize(parser.parse_args().prefix)
