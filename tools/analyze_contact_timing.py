"""Compare observed contact/adhesion inputs with targets at the same fixed tick.
Contact is not equivalent to load-bearing support. No friction-force closure is assumed.
"""
import csv,json,math,statistics,sys
from pathlib import Path
from collections import defaultdict,Counter
p=Path(sys.argv[1]); groups=defaultdict(list)
for row in csv.DictReader((p/'support.csv').open()):groups[row['trial']].append(row)
result=[]
for trial,rows in groups.items():
    stages={stage:[r for r in rows if r['stage']==stage] for stage in ('BEFORE_APPLY','POST_PHYSICS')}
    pre=stages['BEFORE_APPLY'];post=stages['POST_PHYSICS']
    assert len(pre)==len(post)==2400,(trial,len(pre),len(post))
    assert {(r['leg'],r['fixedTime']) for r in pre}=={(r['leg'],r['fixedTime']) for r in post}
    same=lambda r:abs(float(r['fixedTime'])-float(r['adhesionFixedTime']))<.0001
    mismatches=[r for r in post if r['commandStance']!=r['consumedStance']]
    by_leg={}
    for leg in ('LF','LM','LH','RF','RM','RH'):
        early=[r for r in post if r['leg']==leg][:25]
        seen=[float(r['t']) for r in post if r['leg']==leg and r['fresh']=='1']
        ages=[float(r['contactAge']) for r in early if r['fresh']=='1']
        by_leg[leg]=dict(firstFreshTime=min(seen) if seen else None,earlySamples=len(early),
          freshSamples=sum(r['fresh']=='1' for r in early),attachedSamples=sum(r['attached']=='1' for r in early),
          stanceWithoutFresh=sum(r['commandStance']=='1' and r['fresh']=='0' for r in early),
          swingWithFresh=sum(r['commandStance']=='0' and r['fresh']=='1' for r in early),
          meanFreshAge=statistics.mean(ages) if ages else None,
          meanNormalAdhesion=statistics.mean(float(r['normalForce']) for r in early))
    result.append(dict(trial=trial,preSamples=len(pre),postSamples=len(post),
        preAlreadyEvaluated=sum(same(r) for r in pre),
        preAlreadyEvaluatedByLeg=dict(Counter(r["leg"] for r in pre if same(r))),
        postStanceMismatchByLeg=dict(Counter(r["leg"] for r in mismatches)),postEvaluatedSameTick=sum(same(r) for r in post),
        postCommandConsumedStanceMismatch=len(mismatches),
        freshSources=dict(Counter(r['source'] for r in post if r['fresh']=='1')),
        earlyLegs=by_leg))
assert len(result)==12,len(result)
(p/'contact-timing-summary.json').write_text(json.dumps(result,indent=2)+'\n')
for r in result:print(r['trial'],'pre adhesion already evaluated',r['preAlreadyEvaluated'],'stance mismatch',r['postCommandConsumedStanceMismatch'],'early fresh', {k:v['freshSamples'] for k,v in r['earlyLegs'].items()})
