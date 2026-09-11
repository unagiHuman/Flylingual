"""Select one real late Live frame per action; retain its exact motor/neural values."""
import json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=root/'artifacts/windows/m1/live/unity-six-20260911-161958/live-wire.jsonl'
events=[json.loads(s) for s in source.read_text().splitlines()]
frames=[e['message'] for e in events if e['direction']=='receive' and e['message'].get('type')=='brain_frame']
out=root/'Docs/windows/physics-diagnostic/fixtures';out.mkdir(parents=True,exist_ok=True)
manifest={'source':str(source.relative_to(root)),'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'selection':'last received frame per requestedAction; exact frame retained; held constant by diagnostic replay source','frames':{}}
for action in ('STOP','FORWARD','TURN_L','TURN_R','FORWARD_R','FORWARD_L'):
    frame=[f for f in frames if f['requestedAction']==action][-1]
    data=json.dumps(frame,separators=(',',':'))+'\n'
    (out/(action+'.jsonl')).write_text(data,encoding='utf-8')
    manifest['frames'][action]={'sequence':frame['sequence'],'motor':frame['motor'],'sha256':hashlib.sha256(data.encode()).hexdigest()}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest['frames'],indent=2))
