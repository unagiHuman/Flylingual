#!/usr/bin/env python3
"""Collect non-secret runtime facts without starting Unity or a brain model."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

PACKAGES = ['brian2', 'Cython', 'numpy', 'pandas', 'pyarrow', 'scipy', 'joblib', 'psutil', 'setuptools']

def command_output(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        return {'command': command, 'returncode': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'command': command, 'error': str(exc)}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--unity-project', type=Path)
    args = ap.parse_args()
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    info = {
        'capturedAtUtc': datetime.now(timezone.utc).isoformat(),
        'os': platform.platform(), 'machine': platform.machine(), 'processor': platform.processor(),
        'pythonExecutable': sys.executable, 'pythonVersion': sys.version,
        'logicalCpuCount': os.cpu_count(), 'packages': versions,
        'selectedEnvironment': {k: os.environ.get(k) for k in ['CONDA_DEFAULT_ENV', 'CC', 'CXX', 'MACOSX_DEPLOYMENT_TARGET']},
        'memory': None, 'compilerChecks': [],
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        info['memory'] = {'totalBytes': vm.total, 'availableBytes': vm.available}
    except ImportError:
        if sys.platform == 'darwin':
            info['memorySysctl'] = command_output(['sysctl', '-n', 'hw.memsize'])
    if sys.platform == 'darwin':
        info['hardwareModel'] = command_output(['sysctl', '-n', 'hw.model'])
        info['compilerChecks'] = [command_output(['/usr/bin/clang', '--version']), command_output(['/usr/bin/clang++', '--version'])]
    elif sys.platform == 'win32':
        info['compilerChecks'] = [command_output(['where.exe', 'cl'])]
    if args.unity_project:
        version_file = args.unity_project / 'ProjectSettings' / 'ProjectVersion.txt'
        info['unityProjectVersion'] = version_file.read_text(encoding='utf-8') if version_file.exists() else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    du = shutil.disk_usage(args.output.parent)
    info['outputDisk'] = {'freeBytes': du.free, 'totalBytes': du.total}
    args.output.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {args.output}')

if __name__ == '__main__':
    main()
