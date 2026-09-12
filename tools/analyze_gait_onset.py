import pathlib,csv,json,statistics,collections,math
root=pathlib.Path('artifacts/windows-malecns/coxa-check');result={}
for mode in ['baseline','bounded']:
 p=root/mode;legs=collections.defaultdict(list);body=collections.defaultdict(list);contacts=collections.defaultdict(list)
 for row in csv.DictReader(open(p/'legs.csv')):legs[row['trial']].append(row)
 for row in csv.DictReader(open(p/'body.csv')):body[row['trial']].append(row)
 for row in csv.DictReader(open(p/'contacts.csv')):
  if float(row['t'])<=.25:contacts[row['trial']].append(row)
 output=[]
 for trial,b in body.items():
  lr=legs[trial];first=[x for x in lr if float(x['t'])<=.02001];first_y=float(b[0]['yaw']);onset=next((float(x['t']) for x in b if abs(math.remainder(float(x['yaw'])-first_y,360))>1),None)
  perleg={}
  for leg in ['LF','LM','LH','RF','RM','RH']:
   rs=[x for x in lr if x['leg']==leg];a=rs[0];cs=[x for x in contacts[trial] if x['leg']==leg]
   perleg[leg]={'firstTargets':[float(a[k+'Target']) for k in ['coxa','femur','tibia']],'firstActual':[float(a[k+'Actual']) for k in ['coxa','femur','tibia']],'firstStance':a['stance']=='1','firstGround':next((float(x['t']) for x in rs if x['grounded']=='1'),None),'earlyContacts':len(cs),'earlyNormalImpulse':sum(float(x['normalImpulse']) for x in cs),'earlyAttachedSamples':sum(x['attached']=='1' for x in rs if float(x['t'])<=.25)}
  output.append({'trial':trial,'yawOnset1degSeconds':onset,'yawAt020':math.remainder(float(min(b,key=lambda x:abs(float(x['t'])-.2))['yaw'])-first_y,360),'perLeg':perleg,'earlyNonFootContacts':sum(x['leg']=='NON_FOOT' for x in contacts[trial])})
 result[mode]=output
pathlib.Path('Docs/windows/M1-gait-onset-results.json').write_text(json.dumps(result,indent=2))
for r in result['baseline']:
 if r['trial'].endswith('_0'):
  print(r['trial'],'onset',r['yawOnset1degSeconds'],'yaw.2',round(r['yawAt020'],2),'nonfoot',r['earlyNonFootContacts'])
  for k,v in r['perLeg'].items():print(k,'target',*[round(x,2) for x in v['firstTargets']],'stance',v['firstStance'],'ground',v['firstGround'],'contact',v['earlyContacts'])
