"""Package an existing Judge/Cloud Player; does not build Unity or run gameplay."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from package_judge import ROOT, assemble


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def package(player, python_root, destination):
    player, python_root, destination = map(lambda p: Path(p).resolve(), (player, python_root, destination))
    selection = json.loads((player / 'build-channel.json').read_text(encoding='utf-8-sig'))
    if selection.get('channel') != 'Judge' or selection.get('provider') != 'Cloud':
        raise ValueError('Build Judge / Cloud in Unity first.')
    required = ('FlylingualConversation.exe', 'FlylingualConversation_Data', 'UnityPlayer.dll', 'build-channel.json')
    optional = ('MonoBleedingEdge', 'D3D12', 'UnityCrashHandler64.exe', 'GameAssembly.dll', 'baselib.dll',
                'dstorage.dll', 'dstoragecore.dll')
    for name in required:
        if not (player / name).exists():
            raise ValueError('Missing Player component: ' + name)
    # Fail before creating an output that could be mistaken for a complete package.
    if not (python_root / 'python.exe').is_file():
        raise ValueError('Prepare portable Python with tools/prepare_judge_python.ps1 first.')
    destination.mkdir(parents=True, exist_ok=False)
    output = destination / 'Flylingual-Judge'
    output.mkdir()
    for name in required + optional:
        source = player / name
        if source.is_dir():
            shutil.copytree(source, output / name)
        elif source.is_file():
            shutil.copy2(source, output / name)
    print('Bundling Python and Brain...', flush=True)
    assemble(output, python_root, selection['backendUrl'])
    manifest = json.loads((output / 'judge-manifest.json').read_text(encoding='utf-8'))
    archive = destination / ('Flylingual-Judge-Windows-' + destination.name + '.zip')
    pending = archive.with_suffix('.zip.partial')
    print('Creating and verifying ZIP...', flush=True)
    with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                zipped.write(path, 'Flylingual-Judge/' + path.relative_to(output).as_posix())
    with zipfile.ZipFile(pending) as zipped:
        expected = {'Flylingual-Judge/' + item['path'] for item in manifest['files']}
        expected.add('Flylingual-Judge/judge-manifest.json')
        if set(zipped.namelist()) != expected:
            raise ValueError('ZIP file list differs from manifest')
        for item in manifest['files']:
            if digest(output / item['path']) != item['sha256']:
                raise ValueError('Source hash mismatch: ' + item['path'])
            value = hashlib.sha256()
            with zipped.open('Flylingual-Judge/' + item['path']) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(chunk)
            if value.hexdigest() != item['sha256']:
                raise ValueError('ZIP hash mismatch: ' + item['path'])
    pending.rename(archive)
    receipt = {'zip': str(archive), 'bytes': archive.stat().st_size, 'sha256': digest(archive),
               'manifestFiles': len(manifest['files']), 'manifestVerified': True, 'zipVerified': True,
               'playerSource': str(player), 'unityBuildPerformed': False, 'gameplayTestPerformed': False}
    (destination / 'archive-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('SUCCESS: ' + str(archive))
    print('SHA256: ' + receipt['sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--player', type=Path, default=ROOT / 'artifacts/hayeringual-builds/Judge-Cloud')
    parser.add_argument('--python-root', type=Path, default=ROOT / 'artifacts/judge-python/portable')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts' / ('submission-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    package(args.player, args.python_root, args.output)
