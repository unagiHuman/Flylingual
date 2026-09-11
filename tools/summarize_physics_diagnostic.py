import csv,json,math,statistics
from collections import defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=root/'artifacts/windows/physics-diagnostic'
out=root/'Docs/windows/physics-diagnostic'
initial=json.loads((base/'controlled-initial.json').read_text())
result={'initialState':initial,'resetChecks':[],'batches':{},'twoSecondLegs':{}}
for batch in ('baseline','phase','repro','ablation'):
    p=base/('controlled-'+batch)
    resets=[json.loads(s) for s in (p/'reset.jsonl').read_text().splitlines()]
    for r in resets:
        assert r['position']==initial['position'] and r['rotation']==initial['rotation']
        assert r['jointPositions']==initial['jointPositions']
        assert all(v==0 for v in r['jointVelocities']) and all(v==0 for v in r['linearVelocity'].values()) and all(v==0 for v in r['angularVelocity'].values())
        assert r['attached']==0
    result['resetChecks'].append({'batch':batch,'trials':len(resets),'allEqualExceptPhase':True})
    summary=json.loads((p/'summary.json').read_text())
    by_trial=defaultdict(list)
    for row in csv.DictReader((p/'body.csv').open()):by_trial[row['trial']].append(row)
    for s in summary:
        rows=by_trial[s['trial']]
        s['worldAngularMomentumYAt2s']=float(min(rows,key=lambda r:abs(float(r['t'])-2))['totalWorldLy'])
        s['dampingYawImpulseEstimate2s']=sum(float(r['dampingYawImpulseEstimate']) for r in rows if float(r['t'])<=2.001)
    result['batches'][batch]=summary
    grouped=defaultdict(lambda:defaultdict(list));ct=defaultdict(lambda:defaultdict(lambda:defaultdict(float)))
    for r in csv.DictReader((p/'legs.csv').open()):
        if float(r['t'])<=2.001:grouped[r['trial']][r['leg']].append(r)
    for r in csv.DictReader((p/'contacts.csv').open()):
        if float(r['t'])<=2.001:
            x=ct[r['trial']][r['leg']]
            for k in ('normalImpulse','tangentImpulse','yawImpulse'):x[k]+=float(r[k])
            x['contacts']+=1
    for trial,legs in grouped.items():
        data={}
        for name,rows in legs.items():
            data[name]={'contact':dict(ct[trial][name]),'normalAdhesionImpulse':sum(float(r['normalForce'])*.02 for r in rows),
                'shearAdhesionImpulse':sum(float(r['shearForce'])*.02 for r in rows),'adhesionYawImpulse':sum(float(r['adhesionYawImpulse']) for r in rows),
                'attachedTicks':sum(int(r['attached']) for r in rows),'overload':int(rows[-1]['overload']),'contactLost':int(rows[-1]['contactLost'])}
        data['NON_FOOT']=dict(ct[trial]['NON_FOOT'])
        result['twoSecondLegs'][batch+'/'+trial]=data
rig={r['name']:r for r in map(json.loads,(base/'controlled-repro/rig.jsonl').read_text().splitlines())}
audit=[]
def diff(a,b):return max(abs(a[k]-b[k]) for k in a)
def qmul(a,b):
    x,y,z,w=(a[k] for k in ('x','y','z','w'));X,Y,Z,W=(b[k] for k in ('x','y','z','w'))
    return dict(x=w*X+x*W+y*Z-z*Y,y=w*Y-x*Z+y*W+z*X,z=w*Z+x*Y-y*X+z*W,w=w*W-x*X-y*Y-z*Z)
def axis(q):
    norm=math.sqrt(sum(x*x for x in q.values()));x,y,z,w=(q[k]/norm for k in ('x','y','z','w'))
    return (1-2*y*y-2*z*z,2*x*y+2*z*w,2*x*z-2*y*w)
world={}
for side in ('L','R'):
    for prefix in ('F','M','H'):
        parent=dict(x=0,y=0,z=0,w=1)
        for part in ('Coxa','Femur','Tibia'):
            name=side+prefix+'_'+part;parent=qmul(parent,rig[name]['localRotation']);world[name]=parent
for prefix in ('F','M','H'):
    for part in ('Coxa','Femur','Tibia'):
        l,r=rig['L'+prefix+'_'+part],rig['R'+prefix+'_'+part]
        scalar={k:abs(l[k]-r[k]) for k in ('mass','lower','upper','stiffness','damping','forceLimit','maxVelocity')}
        mirror=lambda v:{'x':-v['x'],'y':v['y'],'z':v['z']}
        lrot=l['localRotation']; mirrored={'x':lrot['x'],'y':-lrot['y'],'z':-lrot['z'],'w':lrot['w']}
        qdot=abs(sum(mirrored[k]*r['localRotation'][k] for k in mirrored))/math.sqrt(sum(v*v for v in mirrored.values())*sum(v*v for v in r['localRotation'].values()))
        la=axis(qmul(world[l['name']],l['anchorRotation']));ra=axis(qmul(world[r['name']],r['anchorRotation']));ma=(-la[0],la[1],la[2])
        axis_error=min(math.sqrt(sum((ra[i]-sign*ma[i])**2 for i in range(3))) for sign in (-1,1))
        cs=[]
        for lc,rc in zip(map(json.loads,l['colliders'].split(';')),map(json.loads,r['colliders'].split(';'))):
            cs.append({'left':lc['name'],'right':rc['name'],'geometryMaxDifference':max(abs(lc[k]-rc[k]) for k in ('radius','height','direction')),
                       'centerMirrorError':diff(mirror(lc['center']),rc['center']),'sizeError':diff(lc['size'],rc['size']),'scaleError':diff(lc['scale'],rc['scale'])})
        audit.append({'left':l['name'],'right':r['name'],'scalarDifferences':scalar,'localPositionMirrorError':diff(mirror(l['localPosition']),r['localPosition']),
                      'localRotationMirrorErrorDegrees':math.degrees(2*math.acos(min(1,qdot))), 'centerOfMassMirrorError':diff(mirror(l['com']),r['com']),
                      'anchorPositionMirrorError':diff(mirror(l['anchor']),r['anchor']),'parentAnchorMirrorError':diff(mirror(l['parentAnchor']),r['parentAnchor']),
                      'worldAxisMirrorErrorUpToSign':axis_error,'leftWorldAxis':la,'rightWorldAxis':ra,'colliders':cs})
result['rigAudit']=audit
(out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
print('RESET_PASS',sum(r['trials'] for r in result['resetChecks']))
for batch,rows in result['batches'].items():
    groups=defaultdict(list)
    for r in rows:groups[r['trial'].rsplit('_',1)[0]].append(r)
    print(batch)
    for group,rs in groups.items():print(group,'yaw2 mean',round(statistics.mean(r['yaw']['2'] for r in rs),2),'range',tuple(round(f(r['yaw']['2'] for r in rs),2) for f in (min,max)),'yaw8',round(statistics.mean(r['yaw']['8'] for r in rs),2),'L2',round(statistics.mean(r['worldAngularMomentumYAt2s'] for r in rs),4))
print('RIG max COM error',max(x['centerOfMassMirrorError'] for x in audit))
