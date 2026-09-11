import csv,json,math,statistics,sys
from pathlib import Path
from collections import defaultdict
p=Path(sys.argv[1]); bodies=defaultdict(list); legs=defaultdict(list); contact=defaultdict(lambda:defaultdict(lambda:defaultdict(float)))
for r in csv.DictReader((p/'body.csv').open()):bodies[r['trial']].append(r)
for r in csv.DictReader((p/'legs.csv').open()):legs[r['trial']].append(r)
for r in csv.DictReader((p/'contacts.csv').open()):
    c=contact[r['trial']][r['leg']];c['count']+=1
    for k in ('normalImpulse','tangentImpulse','yawImpulse'):c[k]+=float(r[k])
result=[]
for trial,b in bodies.items():
    if len(b)<400:continue
    yaw=0;yaws={}
    for a,r in zip(b,b[1:]):
        yaw+=math.remainder(float(r['yaw'])-float(a['yaw']),360)
        for t in (.5,1,2,8):
            if abs(float(r['t'])-t)<.005:yaws[str(t)]=yaw
    lr={}
    for leg in ('LF','LM','LH','RF','RM','RH'):
        rs=[r for r in legs[trial] if r['leg']==leg];settled=[r for r in rs if float(r['t'])>=1]
        lr[leg]=dict(scale=statistics.mean(float(r['scale']) for r in settled),
            coxaRmse=math.sqrt(statistics.mean((float(r['coxaTarget'])-float(r['coxaActual']))**2 for r in rs)),
            femurRmse=math.sqrt(statistics.mean((float(r['femurTarget'])-float(r['femurActual']))**2 for r in rs)),
            tibiaRmse=math.sqrt(statistics.mean((float(r['tibiaTarget'])-float(r['tibiaActual']))**2 for r in rs)),
            jointClamp=sum(int(r['jointClamp']) for r in rs),scaleClamp=sum(int(r['scaleClamped']) for r in rs),
            attachedTicks=sum(int(r['attached']) for r in rs),
            normalAdhesionImpulse=sum(float(r['normalForce'])*.02 for r in rs),shearAdhesionImpulse=sum(float(r['shearForce'])*.02 for r in rs),
            adhesionYawImpulse=sum(float(r['adhesionYawImpulse']) for r in rs),
            overload=int(rs[-1]['overload']),contactLost=int(rs[-1]['contactLost']),
            coxaTargetRange=[min(float(r['coxaTarget']) for r in rs),max(float(r['coxaTarget']) for r in rs)],contact=dict(contact[trial][leg]))
    result.append(dict(trial=trial,yaw=yaws,displacement={k:float(b[-1][k])-float(b[0][k]) for k in ('x','y','z')},fall=any(r['fall']=='1' for r in b),legs=lr,nonFoot=dict(contact[trial]['NON_FOOT']),
        contactYaw=sum(c['yawImpulse'] for c in contact[trial].values()),adhesionYaw=sum(x['adhesionYawImpulse'] for x in lr.values())))
(p/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
for r in result:print(r['trial'], 'yaw', {t:round(v,2) for t,v in r['yaw'].items()},'contactYaw',round(r['contactYaw'],4),'adhesionYaw',round(r['adhesionYaw'],4))
