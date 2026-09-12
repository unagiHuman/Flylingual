"""Summarize bounded goal-reaching tests, not a proof of arbitrary navigation."""
import csv,json,math,sys
from pathlib import Path
base=Path(sys.argv[1]);out=[]
for p in sorted(base.iterdir()):
 if not p.is_dir() or not (p/'goal-result.json').exists() or not (p/'process-result.json').exists():continue
 result=json.loads((p/'goal-result.json').read_text());config=json.loads((p/'goal-config.json').read_text());target=config['target']
 body=list(csv.DictReader((p/'body.csv').open()));live=list(csv.DictReader((p/'live.csv').open()));motor=list(csv.DictReader((p/'motor-use.csv').open()));goals=list(csv.DictReader((p/'goal.csv').open()))
 assert len(body)==len(live)==len(motor)
 distances=[math.hypot(float(r['x'])-target['x'],float(r['z'])-target['z']) for r in body]
 wire=[json.loads(line) for line in (p/'live-wire.jsonl').read_text().splitlines()]
 frames=[r['message'] for r in wire if r['direction']=='receive' and r['message'].get('type')=='brain_frame'];seq=[r['sequence'] for r in frames]
 result.update(direction=config['direction'],minDistance=min(distances),firstWithinTolerance=next((float(r['t']) for r,d in zip(body,distances) if d<=.4),None),samples=len(body),staleConsumed=sum(r['fresh']=='0' for r in motor),actions=sorted(set(r['action'] for r in goals)),sequenceProgress=len(seq)>1 and all(b>a for a,b in zip(seq,seq[1:])),backend=sorted(set(r['backend'] for r in live)),ready=sorted(set(r['ready'] for r in live)),clientErrors=sorted(set(r['error'] for r in live if r['error'])),protocolErrors=[r for r in wire if r['direction']=='receive' and r['message'].get('type')=='error'])
 out.append(result);print(json.dumps(result))
(base/'goal-summary.json').write_text(json.dumps(out,indent=2)+'\n')
