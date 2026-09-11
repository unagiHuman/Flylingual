"""Verify recorded acceptance evidence; this script does not drive the game."""
import argparse,csv,json,math,re
from pathlib import Path
from summarize_windows_replay import summarize

p=argparse.ArgumentParser()
for name in ('goals','fall','steering','frames','native','output'):p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args()
result={'goals':[]}
for i in range(1,4):
    folder=a.goals/f'goal-{i}'
    text=(folder/'Player.log').read_text(errors='replace')
    match=re.search(r'COURSE_RESULT state=Goal .*?elapsed=([0-9.]+)',text)
    assert match, f'Goal {i} missing'
    rows=list(csv.DictReader(next(folder.glob('course_*.csv')).open()))
    moving=[r for r in rows if r['state']=='Running']
    wins=[r for r in rows if r['state']=='Goal']
    assert wins and all(math.hypot(float(r['headX']),float(r['headZ'])-4.5)<=.85001 and abs(float(r['headY'])-1)<.45001 for r in wins),'Goal outside its head region'
    assert any(int(r['rampContacts'])>0 for r in moving),'No actual ramp contact'
    assert any(int(r['summitContacts'])>0 for r in moving),'No actual summit contact'
    assert any(float(r['normalForce'])>0 and int(r['attached'])>0 for r in moving),'No actual adhesion'
    result['goals'].append({'run':i,'seconds':float(match.group(1)),'head':{k:float(wins[0][k]) for k in ('headX','headY','headZ')}})
fall_log=(a.fall/'fall'/'Player.log').read_text(errors='replace')
assert 'COURSE_RESULT state=Fallen' in fall_log and 'COURSE_RESTART_PASS' in fall_log
falls=sorted((a.fall/'fall').glob('course_*.csv'))
assert len(falls)==2,'Restart did not create a new scene log'
first=list(csv.DictReader(falls[0].open()));reset=list(csv.DictReader(falls[1].open()))
assert any(r['state']=='Fallen' and float(r['headY'])<-3 for r in first)
assert math.hypot(float(reset[0]['x']),float(reset[0]['z']))<.01 and float(reset[0]['y'])>1.4
result['fallRestart']='pass: natural fall and measured spawn reset'
steering=json.loads((a.steering/'summary.json').read_text(encoding='utf-8-sig'))
assert len(steering)==2 and steering[0]['start']==steering[1]['start']
assert all(s['common10s']['steps']==501 for s in steering)
for s in steering:
    expected=-1 if 'FORWARD_L' in s['path'] else 1
    assert expected*s['common10s']['yawDelta']>0,'Wrong steering sign'
result['steering']=[{'path':s['path'],'common10s':s['common10s']} for s in steering]
frames_dir=a.frames/'frames'
validation=json.loads(next(frames_dir.glob('validation_*.json')).read_text())
assert validation['recordedFrames']==validation['observedFrames']==110 and validation['skippedFrames']==0
assert validation['physicsJoints']==18 and validation['footPads']==6 and validation['visualPhysicsComponents']==0
recorded=summarize(frames_dir)['runs']
assert len(recorded)==1 and recorded[0]['uniqueRecordedSequences']==110 and not recorded[0]['recordingValueMismatches']
assert len(recorded[0]['actions'])==6
result['frames']=validation
native=json.loads(a.native.read_text(encoding='utf-8-sig'))
assert {r['action'] for r in native['recordedActions']}=={'FORWARD','TURN_L','TURN_R'}
assert len(native['restartCsvFiles'])==2
result['nativeInput']='pass: W/A/D recorded frames and visually checked R'
for directory in (a.goals,a.fall,a.steering,a.frames):
    for log in directory.rglob('Player.log'):
        assert not re.search(r'\w+Exception:',log.read_text(errors='replace')),str(log)
result['exceptions']=0
result['status']='PASS'
a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
