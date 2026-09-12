"""Encode actual capture PNGs. Keep source frames and refuse overwrite."""
import argparse,json
from pathlib import Path
from PIL import Image
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('output',type=Path);p.add_argument('--fps',type=float);a=p.parse_args()
if a.output.exists():raise SystemExit('Output exists')
if a.fps is not None and a.fps<=0:raise SystemExit('FPS must be positive')
files=sorted(a.directory.glob('capture-*.png'))
if len(files)<2:raise SystemExit('At least two actual captures required')
images=[]
for f in files:
 with Image.open(f) as im:images.append(im.convert('RGB'))
if len({im.size for im in images})!=1:raise SystemExit('Mixed frame sizes')
if a.fps:durations=[max(10,round(100/a.fps)*10)]*len(files)
else:
 gaps=[b.stat().st_mtime-a.stat().st_mtime for a,b in zip(files,files[1:])]
 if any(x<=0 for x in gaps):raise SystemExit('Non-increasing capture mtimes; supply explicit FPS')
 durations=[max(10,round(x*100)*10) for x in gaps];durations.append(durations[-1])
a.output.parent.mkdir(parents=True,exist_ok=True)
images[0].save(a.output,save_all=True,append_images=images[1:],duration=durations,loop=0,optimize=False)
with Image.open(a.output) as gif:
 if gif.n_frames<2:raise SystemExit('No animated frames')
 print(json.dumps(dict(path=str(a.output.resolve()),frames=gif.n_frames,size=gif.size,seconds=sum(durations)/1000,timing='explicit FPS' if a.fps else 'approximate source mtime',bytes=a.output.stat().st_size)))
