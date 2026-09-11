"""Report physical course observations; GOAL comes only from game state logs."""
import csv,json,sys
from pathlib import Path
results=[]
for path in Path(sys.argv[1]).rglob('course_*.csv'):
    rows=list(csv.DictReader(path.open()))
    if not rows:continue
    results.append(dict(file=str(path),samples=len(rows),lastState=rows[-1]['state'],seconds=float(rows[-1]['t']),
        start={k:float(rows[0][k]) for k in ('x','y','z')},end={k:float(rows[-1][k]) for k in ('x','y','z')},
        maxY=max(float(r['y']) for r in rows),minY=min(float(r['y']) for r in rows),
        maxZ=max(float(r['z']) for r in rows),attachedSamples=sum(int(r['attached'])>0 for r in rows),
        maxNormalForce=max(float(r['normalForce']) for r in rows),
        rampContactSamples=sum(int(r.get('rampContacts',0))>0 for r in rows),
        summitContactSamples=sum(int(r.get('summitContacts',0))>0 for r in rows),
        states=sorted({r['state'] for r in rows})))
print(json.dumps(results,indent=2))
