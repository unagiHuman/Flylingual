"""Compare actual Unity JsonUtility output with the unchanged Mac wire fixture."""
import json, math, hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
evidence = root / 'artifacts/windows/m1'
results = {}
for name in ('shiu', 'malecns'):
    filename = f'{name}_game_brain_controller_frames_wire_v1.jsonl'
    source = root / 'Contracts/fixtures' / filename
    original = [json.loads(s) for s in source.read_text().splitlines() if s.strip()]
    parsed = [json.loads(s) for s in (evidence / (filename+'.parsed.jsonl')).read_text().splitlines()]
    assert len(original) == len(parsed)
    for a, b in zip(original, parsed):
        for key in ('sequence', 'requestedAction'):
            assert a[key] == b[key], key
        for section, keys in [('motor', ('forward','turn')), ('performance', ('windowMs','stepWallTimeMs'))]:
            for key in keys:
                assert math.isclose(a[section][key], b[section][key], rel_tol=2e-6, abs_tol=1e-7), (section,key)
        if name == 'malecns':
            for key in ('backendId','model','motor_readout','ready'):
                assert a['metadata'][key] == b['metadata'][key]
            for axis in ('forward','turn'):
                for side in ('L','R'):
                    assert math.isclose(a['raw']['populationDeltaMv'][axis][side], b['raw']['populationDeltaMv'][axis][side], rel_tol=2e-6, abs_tol=1e-7)
    segments=[]
    for frame in original:
        if not segments or segments[-1]['action'] != frame['requestedAction']:
            segments.append({'action':frame['requestedAction'],'frames':[]})
        segments[-1]['frames'].append(frame)
    summary=[]
    for segment in segments:
        tail=segment['frames'][-4:]
        action=segment['action']
        def correct(f):
            forward, turn=f['motor']['forward'], f['motor']['turn']
            return ((forward > 0 if 'FORWARD' in action else forward <= .15)
                    and (turn > 0 if action.endswith('_R') else turn < 0 if action.endswith('_L') else abs(turn)<1e-6))
        summary.append({'action':action,'count':len(segment['frames']),'last4SignPass':all(map(correct,tail)), 'lastMotor':tail[-1]['motor']})
    results[name]={'frames':len(original),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'parserPass':True,'segments':summary}
print(json.dumps(results,indent=2))
