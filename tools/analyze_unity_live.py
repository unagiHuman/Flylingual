"""Summarize saved wire and observed body motion; never infer missing samples."""
import csv, json, math, sys, re
from pathlib import Path
from datetime import datetime

folder=Path(sys.argv[1])
wire=[json.loads(s) for s in (folder/'live-wire.jsonl').read_text().splitlines()]
rows=list(csv.DictReader((folder/'live-motion.csv').open()))
def stamp(s): return datetime.fromisoformat(re.sub(r'(\.\d{6})\d+',r'\1',s).replace('Z','+00:00'))
def seconds(a,b): return (stamp(a)-stamp(b)).total_seconds()
commands=[e for e in wire if e['direction']=='send']
received=[e for e in wire if e['direction']=='receive']
frames=[e for e in received if e['message'].get('type')=='brain_frame']
summary=dict(frames=len(frames),errors=[e for e in received if e['message'].get('type')=='error'],
             sequenceIncreasing=all(b['message']['sequence']>a['message']['sequence'] for a,b in zip(frames,frames[1:])),
             metadataMismatch=sum(e['message'].get('metadata',{}).get('backendId')!='MALECNS_EXPERIMENTAL' or e['message'].get('metadata',{}).get('ready') is not False for e in frames),actions=[])
for i,command in enumerate(commands):
    c=command['message']
    end=commands[i+1]['utc'] if i+1<len(commands) else '9999-01-01T00:00:00+00:00'
    segment=[e for e in frames if command['utc']<=e['utc']<end]
    matched=[e for e in segment if e['message'].get('appliedRequestId')==c['requestId']]
    zeros=[e for e in segment if e['message']['requestedAction']==c['action'] and abs(e['message']['motor']['forward'])<=.01 and abs(e['message']['motor']['turn'])<=.01]
    summary['actions'].append(dict(action=c['action'],sentUtc=command['utc'],frames=len(segment),
      firstCorrespondingMs=seconds(matched[0]['utc'],command['utc'])*1000 if matched else None,
      firstZeroMotorMs=seconds(zeros[0]['utc'],command['utc'])*1000 if zeros and c['action']=='STOP' else None))
fresh=[r for r in rows if r['sequence']!='-1']
summary['staleSamples']=sum(float(r['age'])>.75 for r in fresh)
summary['motionSamples']=len(rows)
summary['maxFrameAgeSeconds']=max((float(r['age']) for r in fresh),default=None)
summary['events']=(folder/'live-events.txt').read_text().splitlines()
inputs=[]
for line in summary['events']:
    match=re.search(r't=([\d.]+) INPUT (\w+)',line)
    if match: inputs.append((float(match[1]),match[2]))
summary['bodyResponses']=[]
for i,(start,action) in enumerate(inputs):
    end=inputs[i+1][0] if i+1<len(inputs) else float('inf')
    part=[r for r in rows if start<=float(r['time'])<end]
    if not part:continue
    base=part[0]
    def distance(a,b):return math.sqrt(sum((float(a[k])-float(b[k]))**2 for k in ('x','y','z')))
    onset=None;stop=None
    for j,r in enumerate(part):
        if action!='STOP' and onset is None:
            delta=abs(math.remainder(float(r['yaw'])-float(base['yaw']),360))
            if (delta>.5 if action.startswith('TURN') else distance(r,base)>.02):onset=float(r['time'])-start
        if action=='STOP' and stop is None:
            window=[p for p in part[:j+1] if float(r['time'])-float(p['time'])<=1.1]
            if len(window)>1 and float(window[-1]['time'])-float(window[0]['time'])>=1:
                if all(abs(float(p['forward']))<=.01 and abs(float(p['turn']))<=.01 and distance(p,window[0])<=.01 and abs(math.remainder(float(p['yaw'])-float(window[0]['yaw']),360))<=1 for p in window):
                    stop=float(window[0]['time'])-start
    summary['bodyResponses'].append(dict(action=action,inputTime=start,observedSeconds=float(part[-1]['time'])-start,
        onsetPoseThresholdSeconds=onset,stopPoseWindowStartSeconds=stop,
        displacement=distance(part[-1],base),yawDelta=sum(math.remainder(float(b['yaw'])-float(a['yaw']),360) for a,b in zip(part,part[1:]))))
summary['poseSegments']=[]
for stage in ('0','1','2'):
    r=[x for x in rows if x['stage']==stage]
    if not r:continue
    summary['poseSegments'].append(dict(stage=stage,rows=len(r),startTime=float(r[0]['time']),endTime=float(r[-1]['time']),
      displacement={k:float(r[-1][k])-float(r[0][k]) for k in ('x','y','z')},
      yawDelta=sum(math.remainder(float(b['yaw'])-float(a['yaw']),360) for a,b in zip(r,r[1:]))))
print(json.dumps(summary,indent=2))
