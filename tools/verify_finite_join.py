"""Verify the rest-start diagnostic against logged CPG phase and motor values."""
import csv,json,math,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=Path(sys.argv[1]) if len(sys.argv)>1 else root/'artifacts/windows-malecns/finite-join'
errors=[]; endpoints=[]; count=0
for row in csv.DictReader((p/'legs.csv').open()):
    v=lambda key:float(row[key])
    elapsed=max(0,v('t')-.02)
    u=min(1,elapsed/.64);w=u**3*(10+u*(-15+6*u))
    wave=math.sin(v('phase'));drive=v('gaitDrive')
    nominal=(-wave*38*drive*v('scale'),max(0,wave)*28*drive,-max(0,wave)*38*drive)
    actual=tuple(v(k) for k in ('coxaRaw','femurRaw','tibiaRaw'))
    errors.append(max(abs(a-w*n) for a,n in zip(actual,nominal)))
    if elapsed>=.64:endpoints.append(max(abs(a-n) for a,n in zip(actual,nominal)))
    count+=1
result=dict(samples=count,maxInterpolationErrorDegrees=max(errors),maxPostDeadlineErrorDegrees=max(endpoints),passed=count==28800 and max(errors)<.001 and max(endpoints)<.001)
(p/'transition-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result));assert result['passed']
