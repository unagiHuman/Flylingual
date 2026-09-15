"""Assemble a relocatable Judge runtime around an existing Unity Player.

Python must be a prepared portable CPython distribution with runtime dependencies,
not a virtual environment. No development configuration is copied.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
GRAPH_FILES = ('body_ids.npy', 'indptr.npy', 'targets.npy', 'weights.npy')
BRAIN_FILES = ('brain_server_bridge.py', 'brain_server_analog.py', 'brain_server_malecns.py',
               'analog_controller.py', 'neural_visualization.py', 'analog_motor_decoder.py',
               'game_controller.py', 'shiu_compatible.py', 'lif_kernels.py', 'temporal_motor_decoder.py',
               'motor_decoder.py', 'malecns_brain.py', 'visual_threat.py')


def validate_public(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r'key|secret|password|token|credential', key, re.I):
                raise ValueError('Credential fields are forbidden in package configuration')
            validate_public(item)
    elif isinstance(value, list):
        for item in value:
            validate_public(item)
    elif isinstance(value, str):
        if value.startswith(('https://', 'http://')):
            url = urlsplit(value)
            if url.username or url.password or url.query or url.fragment:
                raise ValueError('Endpoint credentials/query/fragment are forbidden')
        elif value.startswith(('/', '\\')) or Path(value).is_absolute() or PureWindowsPath(value).is_absolute() or '..' in PureWindowsPath(value).parts:
            raise ValueError('Package configuration must use relative paths')
        if re.search(r'\b(?:sk-|vcp_|AIza)[A-Za-z0-9_-]{12,}', value):
            raise ValueError('Potential provider credential found')


def configurations(endpoint, voice=False):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.hostname == 'ai-gateway.vercel.sh'
            or parsed.path != '/api/fly/translate' or any(c.isspace() for c in endpoint)
            or parsed.port is not None and not 1 <= parsed.port <= 65535):
        raise ValueError('Use the HTTPS application backend, not AI Gateway directly')
    bridge = {
        'brain': {'host': '127.0.0.1', 'port': 18766, 'python': 'runtime/python/python.exe',
                  'graph': 'artifacts/neuron_checkpoint',
                  'config': 'Brain/MaleCNS/config/analog_temporal_v1.json',
                  'visualizationAtlas': 'UnityProject/Assets/BrainVisualization/Resources/BrainVisualization/malecns-atlas.json'},
        'conversation': {'mode': 'text', 'intentProvider': 'vercel', 'cloudIntentUrl': endpoint,
                         'intentTimeoutMs': 5000, 'localIntentResponsesFallback': False,
                         'language': 'en', 'voice': 'stone'},
        'control': {'owner': 'gpt'}, 'logPath': 'artifacts/bridge/events.jsonl'}
    native = {'bridgePython': 'runtime/python/python.exe',
              'bridgeLocalConfig': 'Runtime/Config/judge.json', 'runRoot': 'artifacts/judge-runs',
              'startupSeconds': 45, 'heartbeatSeconds': 10}
    if voice:
        bridge['conversation'].update(mode='live', model='gpt-live-1',
            voiceSessionUrl=endpoint.removesuffix('/translate') + '/voice/session',
            voiceAccessFile='Runtime/Config/voice-access.txt')
    validate_public(bridge)
    validate_public(native)
    return bridge, native


def package_selection(selection, endpoint):
    """Use the packaged endpoint at launch, never an earlier build placeholder."""
    configurations(endpoint)  # Apply the same public endpoint validation.
    if selection is None:
        selection = {'channel': 'Judge', 'provider': 'Cloud', 'backendUrl': endpoint}
    if (type(selection) is not dict or set(selection) != {'channel', 'provider', 'backendUrl'}
            or selection['channel'] not in ('Dev', 'Demo', 'Judge')
            or selection['provider'] != 'Cloud' or type(selection['backendUrl']) is not str):
        raise ValueError('Package a valid Cloud build selection, not a Local build')
    return {**selection, 'backendUrl': endpoint}


def runtime_sources(bridge):
    """Explicit application allowlist shared by packaging and dependency tests."""
    sources = [Path('tools') / name for name in ('dev.py', 'windows_native.py', 'windows_native_job.py', 'native_local_intent.py')]
    sources += [p.relative_to(ROOT) for p in (ROOT / 'Runtime/Bridge').glob('*.py')]
    sources += [Path('Runtime/Bridge/blind_run_script.json'), Path('Runtime/Bridge/player.html')]
    sources += [Path('Runtime/Config/profiles/windows-local.json')]
    sources += [Path('Brain/MaleCNS') / name for name in BRAIN_FILES]
    sources += [Path('Brain/MaleCNS/config/analog_temporal_v1.json'), Path('Brain/MaleCNS/config/analog_handoff_manifest.json'),
                Path('Brain/MaleCNS/config/visual_threat_v1.json')]
    sources += [Path('artifacts/neuron_checkpoint') / name for name in GRAPH_FILES]
    sources += [Path(bridge['brain']['visualizationAtlas'])]
    return sources


def assemble(output, python_root, endpoint, voice_access=None):
    output, python_root = Path(output).resolve(), Path(python_root).resolve()
    bridge, native = configurations(endpoint, voice=voice_access is not None)
    access = None
    if voice_access is not None:
        access = Path(voice_access).read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'flyvoice_[A-Za-z0-9_-]{40,128}', access):
            raise ValueError('A scoped Flylingual voice access pass is required, never a provider API key')
    if not (output / 'FlylingualConversation.exe').is_file():
        raise ValueError('Build the Judge Unity Player into output first')
    selection_path = output / 'build-channel.json'
    selection = package_selection(json.loads(selection_path.read_text(encoding='utf-8'))
                                  if selection_path.is_file() else None, endpoint)
    if (output / 'Runtime').exists() or (output / 'runtime').exists():
        raise ValueError('Runtime already exists; use a fresh build directory')
    if (python_root / 'pyvenv.cfg').exists() or not (python_root / 'python.exe').is_file():
        raise ValueError('A portable CPython root is required; virtual environments are not portable')
    if not list(python_root.glob('python*.dll')):
        raise ValueError('Portable Python DLL missing')
    subprocess.run([str(python_root / 'python.exe'), '-I', '-c',
                    'import numpy,numba,llvmlite,psutil,aiohttp; print("PORTABLE_DEPENDENCIES_OK")'], check=True)
    if access:
        subprocess.run([str(python_root / 'python.exe'), '-I', '-c',
                        'import aiortc,av; print("PORTABLE_VOICE_OK")'], check=True)
    sources = runtime_sources(bridge)
    for relative in sources:
        source = ROOT / relative
        if not source.is_file():
            raise ValueError(f'Required runtime asset missing: {relative}')
    # Portable runtime is an explicit distribution supplied by the builder. Reject
    # credentials and developer environments instead of silently carrying them.
    for path in python_root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Portable Python must not contain symlinks')
        if path.name == 'pyvenv.cfg' or path.name.startswith('.env') or path.suffix.lower() in ('.pem', '.key', '.pfx'):
            raise ValueError('Forbidden file in portable Python distribution')
    (output / 'Runtime').mkdir(exist_ok=True)  # CPython namespace imports require canonical case on Windows.
    shutil.copytree(python_root, output / 'runtime/python', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.nbc', '*.nbi'))
    # Embeddable CPython deliberately excludes script directories from sys.path.
    # Preserve its isolation while making only the bundled application importable.
    for pth in (output / 'runtime/python').glob('python*._pth'):
        entries = pth.read_text(encoding='utf-8').splitlines()
        # Keep the trailing slash: embedded Windows CPython normalizes a final
        # bare '..' unexpectedly; '../../' resolves the intended package root.
        for entry in ('Lib/site-packages', '../../', '../../tools', '../../Brain/MaleCNS', 'import site'):
            if entry not in entries:
                entries.append(entry)
        pth.write_text('\n'.join(entries) + '\n', encoding='utf-8')
    for relative in sources:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    for name, config in [('judge.json', bridge), ('judge-native.json', native)]:
        (output / 'Runtime/Config' / name).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    selection_path.write_text(json.dumps(selection, indent=2) + '\n', encoding='utf-8')
    readme = (
        'Flylingual Judge — Windows 64-bit\n\n'
        'Extract the entire folder, then launch FlylingualConversation.exe.\n'
        'Python and Brain are bundled. Initial preparation can take time.\n'
        'The game interface and fly replies are in English.\n'
        'Wait on the title screen while connections are prepared. Start becomes available when ready.\n'
        'Read the first-run instructions. The swatter timer runs only after gameplay starts.\n'
        'Guide the fly toward the goal and watch for danger. Try "forward", "right", "left", or "stop".\n'
        'You can ask questions while the fly walks; a question does not cancel its current movement.\n'
        'If a movement request is unclear, fresh course guidance may allow a short steering attempt.\n'
        'This is bounded assistance, not a promise of reaching the goal or avoiding every hazard.\n'
        'The expanded finish area and course assistance are game features, not evidence of neural learning.\n'
        'The neural model is experimental. Fly-like feelings are character expressions, not measured emotions.\n'
        'App exit closes the local services it started. No OpenAI API key is bundled.\n'
    )
    if access:
        (output / 'Runtime/Config/voice-access.txt').write_text(access + '\n', encoding='utf-8')
        readme += (
            '\nVoice edition: use a microphone and headphones or speakers, with internet access.\n'
            'GPT Live voice conversation is enabled; no OpenAI API key entry is required.\n'
            'Voice dependencies are bundled. Review access expires on the server.\n'
            'Do not publicly redistribute the review access pass. Contact the issuer if access expires.\n'
        )
    else:
        readme += (
            '\nText edition: GPT Live voice and microphone control are not included.\n'
            'Cloud interpretation of free-form text needs internet access.\n'
            'Supported short basic commands remain available through FastRule if Cloud fails.\n'
            'The public Cloud endpoint is recorded in build-channel.json.\n'
        )
    (output / 'README.txt').write_text(readme, encoding='utf-8')
    files = []
    for path in sorted(output.rglob('*')):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            files.append({'path': path.relative_to(output).as_posix(), 'bytes': path.stat().st_size,
                          'sha256': digest.hexdigest()})
    manifest = {'schemaVersion': 1, 'channel': selection['channel'], 'provider': 'vercel', 'files': files}
    validate_public(manifest)
    (output / 'judge-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': 'packaged', 'files': len(files)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--python-root', required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--voice-access', type=Path)
    args = parser.parse_args()
    assemble(args.output, args.python_root, args.endpoint, args.voice_access)
