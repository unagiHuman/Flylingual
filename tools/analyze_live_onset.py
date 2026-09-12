"""Receive-clock anchored observations, preserving stale windows and command sign."""
import csv,json,math,statistics,sys,bisect,re
from datetime import datetime
from pathlib import Path
base=Path(sys.argv[1]);results=[]
def utc(s):return datetime.fromisoformat(re.sub(r'(\.\d{6})\d+',r'\1',s.replace('Z','+00:00'))).timestamp()
for p in sorted(base.iterdir()):
 if not p.is_dir() or not (p/'process-result.json').exists():continue
 action=json.loads((p/'manifest.json').read_text())['action']
 wire=[json.loads(line) for line in (p/'live-wire.jsonl').read_text().splitlines()]
 frames=[r for r in wire if r['direction']=='receive' and r['message'].get('type')=='brain_frame']
 origin=next(utc(r['utc']) for r in frames if r['message'].get('requestedAction')==action)
 live=list(csv.DictReader((p/'live.csv').open()));body=list(csv.DictReader((p/'body.csv').open()));used=list(csv.DictReader((p/'motor-use.csv').open()))
 assert len(live)==len(body)==len(used)==400,p
 assert all(abs(float(a['t'])-float(b['t']))<.0001 and abs(float(a['t'])-float(c['t']))<.0001 for a,b,c in zip(live,body,used)),p
 times=[utc(r['utc'])-origin for r in live];assert all(b>a for a,b in zip(times,times[1:])),p
 yaws=[float(body[0]['yaw'])]
 for a,b in zip(body,body[1:]):yaws.append(yaws[-1]+math.remainder(float(b['yaw'])-float(a['yaw']),360))
 def interp(t):
  i=bisect.bisect_right(times,t)
  if i==0 or i>=len(times):raise ValueError('Window outside recorded observations')
  w=(t-times[i-1])/(times[i]-times[i-1]);return yaws[i-1]+w*(yaws[i]-yaws[i-1])
 windows=[]
 for start,end in [(0,.5),(.5,1),(1,2),(2,4),(4,6),(0,2)]:
  if end>times[-1]:continue
  subset=[r for r in used if start<=utc(r['utc'])-origin<end]
  # Include the command held across the window's start as well as samples inside it.
  previous=[r for r in used if utc(r['utc'])-origin<start]
  held=([previous[-1]] if previous else [])+subset
  stale=sum(r['fresh']=='0' for r in held)
  expected=lambda r:float(r['cpgTurn'])<-.01 if action=='FORWARD_L' else float(r['cpgTurn'])>.01
  windows.append(dict(start=start,end=end,yawDelta=interp(end)-interp(start),samples=len(subset),staleSamplesIncludingBoundary=stale,fullyFresh=stale==0,
   expectedTurnSamples=sum(expected(r) for r in subset),meanCpgTurn=statistics.mean(float(r['cpgTurn']) for r in subset),meanCpgForward=statistics.mean(float(r['cpgForward']) for r in subset)))
 seq=[r['message']['sequence'] for r in frames]
 sign=-1 if action=='FORWARD_L' else 1
 rawTimes=[utc(r['utc'])-origin for r in used if r['action']==action and sign*float(r['turn'])>.01]
 cpgTimes=[utc(r['utc'])-origin for r in used if r['action']==action and sign*float(r['cpgTurn'])>.01]
 row=dict(firstExpectedRawTurn=min(rawTimes) if rawTimes else None,firstExpectedCpgTurn=min(cpgTimes) if cpgTimes else None,trial=p.name,action=action,originUtc=origin,receivedFrames=len(frames),sequenceProgress=all(b>a for a,b in zip(seq,seq[1:])),backend=sorted(set(r['backend'] for r in live)),ready=sorted(set(r['ready'] for r in live)),
  protocolErrors=[r for r in wire if r['direction']=='receive' and r['message'].get('type')=='error'],clientErrors=sorted(set(r['error'] for r in live if r['error'])),staleConsumedSamples=sum(r['fresh']=='0' for r in used),windows=windows)
 if cpgTimes:
  onset=min(cpgTimes)
  row['yawAfterExpectedCpgTurn']={str(length):interp(onset+length)-interp(onset) for length in [.5,1,2] if onset+length<times[-1]}
 results.append(row)
 print(p.name,'stale',row['staleConsumedSamples'],[(w['start'],w['end'],round(w['yawDelta'],2),w['fullyFresh'],round(w['meanCpgTurn'],3)) for w in windows])
(base/'onset-summary.json').write_text(json.dumps(results,indent=2)+'\n')
