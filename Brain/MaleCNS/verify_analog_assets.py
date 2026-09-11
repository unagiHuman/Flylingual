"""Read-only SHA verification of portable graph/config/replay; no downloads."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',type=Path,default=root/'artifacts/neuron_checkpoint')
    parser.add_argument('--dataset',type=Path)
    args=parser.parse_args()
    manifest=json.loads((root/'Brain/MaleCNS/config/analog_handoff_manifest.json').read_text())
    checked=[]
    for name,info in manifest['graphFiles'].items():
        assert digest(args.graph/name)==info['sha256'], 'Graph hash mismatch: '+name
        checked.append(name)
    for name,expected in manifest['repoFiles'].items():
        assert digest(root/name)==expected, 'Repository asset mismatch: '+name
    if args.dataset:
        for info in manifest['datasetManifest']['files'].values():
            assert digest(args.dataset/info['filename'])==info['sha256'], 'Dataset mismatch: '+info['filename']
    print(json.dumps({'verified':True,'graphFiles':checked,'datasetChecked':args.dataset is not None}))


if __name__=='__main__': main()
