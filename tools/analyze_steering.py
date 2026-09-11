"""Summarize per-physics-step observations without replacing missing data."""
import csv,json,math,statistics,sys
from pathlib import Path
result=[]
for path in Path(sys.argv[1]).rglob('steering.csv'):
    all_rows=list(csv.DictReader(path.open()))
    rows=[r for r in all_rows if r['active']=='1' and r['leg']=='LF']
    if not rows: continue
    yaw=sum(math.remainder(float(b['yaw'])-float(a['yaw']),360) for a,b in zip(rows,rows[1:]))
    common=[r for r in rows if float(r['t'])-float(rows[0]['t'])<=10.01]
    common10=dict(steps=len(common),duration=float(common[-1]['t'])-float(common[0]['t']),
        yawDelta=sum(math.remainder(float(b['yaw'])-float(a['yaw']),360) for a,b in zip(common,common[1:])))
    means={k:statistics.mean(float(r[k]) for r in rows) for k in ('rawForward','rawTurn','cpgForward','cpgTurn','leftScale','rightScale','yawRate')}
    legs={}
    for leg in sorted({r['leg'] for r in all_rows}):
        sample=[r for r in all_rows if r['active']=='1' and r['leg']==leg]
        legs[leg]={k:[min(float(r[k]) for r in sample),max(float(r[k]) for r in sample)] for k in ('coxa','femur','tibia','attached','normalForce')}
    result.append(dict(path=str(path),steps=len(rows),duration=float(rows[-1]['t'])-float(rows[0]['t']),yawDelta=yaw,common10s=common10,means=means,start={k:float(rows[0][k]) for k in ('x','y','z','yaw')},end={k:float(rows[-1][k]) for k in ('x','y','z','yaw')},legs=legs))
print(json.dumps(result,indent=2))
