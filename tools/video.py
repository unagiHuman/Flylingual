#!/usr/bin/env python3
"""Manage only the independent, foreground video backend on this machine."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Runtime.Video.config import DEFAULT_PATH, load


def initialize(stream):
    folder = DEFAULT_PATH.parent
    paths = [folder / name for name in ('backend.json', 'publisher.json', 'publish-token.txt')]
    if any(path.exists() for path in paths):
        raise ValueError('Local video settings already exist; they have been preserved')
    folder.mkdir(parents=True, exist_ok=True)
    backend = {'port': 8880, 'tokenFile': 'publish-token.txt',
               'streams': ['unity-mac', 'unity-windows'], 'iceServers': [], 'maxViewers': 2}
    publisher = {'enabled': True, 'endpoint': 'http://127.0.0.1:8880', 'streamId': stream,
                 'tokenFile': 'publish-token.txt', 'label': stream, 'width': 960, 'height': 540,
                 'framesPerSecond': 15, 'jpegQuality': 75, 'requestTimeoutSeconds': 3, 'verticalFlip': 'auto'}
    for path, data in zip(paths, (json.dumps(backend, indent=2), json.dumps(publisher, indent=2), secrets.token_urlsafe(32))):
        # Exclusive creation and owner-only permissions; never echo credentials.
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as handle:
            handle.write(data + '\n')
    print(f'Created local settings: {folder}')
    print(f'Unity will publish {stream} on the next Play/Player launch with these settings.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Create Git-ignored local config and token, without overwriting')
    init.add_argument('--stream', choices=['unity-mac', 'unity-windows'], required=True)
    for name in ('doctor', 'serve'):
        p = sub.add_parser(name)
        p.add_argument('--config', default=str(DEFAULT_PATH))
    args = parser.parse_args()
    try:
        if args.command == 'init':
            initialize(args.stream)
            return
        config = load(args.config)
        versions = {name: importlib.metadata.version(name) for name in ('aiohttp', 'aiortc', 'av', 'Pillow')}
        if args.command == 'doctor':
            print(json.dumps({'configValid': True, 'bind': '127.0.0.1', 'port': config['port'],
                'streams': config['streams'], 'dependencies': versions,
                'unityCaptureVerified': False, 'webRtcVerified': False}, indent=2))
            return
        import logging
        from aiohttp import web
        from Runtime.Video.server import create_app
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s %(message)s')
        logging.getLogger('flylingual.video').setLevel(logging.INFO)
        print(f'Video backend: http://127.0.0.1:{config["port"]} (Ctrl+C to stop)', flush=True)
        web.run_app(create_app(config), host='127.0.0.1', port=config['port'], access_log=None, print=None)
    except (ValueError, OSError, importlib.metadata.PackageNotFoundError) as exc:
        # Configuration errors never include config values or credentials.
        print(f'Video startup failed ({type(exc).__name__}). Check local config and requirements.', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
