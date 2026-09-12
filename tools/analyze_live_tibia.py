"""Summarize real Windows Brain trials; does not treat a sign change as a fix."""
import csv,json,statistics,sys,math
from pathlib import Path
base=Path(sys.argv[1]);results=[]
for p in sorted(base.iterdir()):
 if not p.is_dir() or not (p/'summary.json').exists():continue
 live=list(csv.DictReader((p/'live.csv').open()));support=list(csv.DictReader((p/'support.csv').open()));motion=json.loads((p/'summary.json').read_text())[0]
 manifest=json.loads((p/'manifest.json').read_text());condition=manifest['condition']
 wire=[json.loads(line) for line in (p/'live-wire.jsonl').read_text().splitlines()]
 frames=[r for r in wire if r['direction']=='receive' and r['message'].get('type')=='brain_frame']
 seq=[int(r['message']['sequence']) for r in frames]
 post=[r for r in support if r['stage']=='POST_PHYSICS'];pre=[r for r in support if r['stage']=='BEFORE_APPLY']
 assert len(live)==400 and len(post)==len(pre)==2400,p
 assert {(r['leg'],r['fixedTime']) for r in pre}=={(r['leg'],r['fixedTime']) for r in post},p
 mismatch=sum(r['commandStance']!=r['consumedStance'] for r in post)
 assert mismatch==0,(p,mismatch)
 contacts=list(csv.DictReader((p/'contacts.csv').open()))
 excludedContacts=sum(r['thisCollider']==condition+'_Tibia' for r in contacts) if condition!='NONE' else None
 if condition!='NONE':assert excludedContacts==0,(p,excludedContacts)
 moving=[r for r in live if r['action']=='FORWARD_L']
 row=dict(trial=p.name,condition=condition,endpoint='127.0.0.1:18766',samples=len(live),
 receivedBrainFrames=len(frames),sequenceProgress=len(seq)>1 and all(b>a for a,b in zip(seq,seq[1:])),
 backend=sorted(set(r['backend'] for r in live)),ready=sorted(set(r['ready'] for r in live)),
 errors=sorted(set(r['error'] for r in live if r['error'])),protocolErrors=[r for r in wire if r['direction']=='receive' and r['message'].get('type')=='error'],
 staleSamples=sum(float(r['age'])>.75 for r in live),maxAge=max(float(r['age']) for r in live),
 firstMovingSample=float(moving[0]['t']) if moving else None,
 meanMovingForward=statistics.mean(float(r['forward']) for r in moving) if moving else None,
 meanMovingTurn=statistics.mean(float(r['turn']) for r in moving) if moving else None,
 yaw=motion['yaw'],displacement=motion['displacement'],fall=motion['fall'],stanceMismatch=mismatch,
 excludedColliderContacts=excludedContacts,ignoredPairs=len((p/'ignored-collision-pairs.txt').read_text().splitlines()))
 body=list(csv.DictReader((p/'body.csv').open()))
 if moving:
  onset=float(moving[0]['t']);window=[r for r in body if onset-.001<=float(r['t'])<=onset+2.001]
  row['yawTwoSecondsAfterFirstMovingFrame']=sum(math.remainder(float(b['yaw'])-float(a['yaw']),360) for a,b in zip(window,window[1:]))
 results.append(row)
 print(p.name,'yaw2/8',round(row['yaw']['2'],2),round(row['yaw']['8'],2),'stale',row['staleSamples'],'mean motor',round(row['meanMovingForward'],3),round(row['meanMovingTurn'],3))
(base/'live-tibia-summary.json').write_text(json.dumps(results,indent=2)+'\n')
