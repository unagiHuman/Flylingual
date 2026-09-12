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
from Runtime.Video.launcher import LaunchError, absolute_path, readonly_status, supervise


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
                 'framesPerSecond': 15, 'jpegQuality': 75, 'requestTimeoutSeconds': 3,
                 'verticalFlip': 'auto', 'diagnosticsOverlay': False}
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
    up = sub.add_parser('up', help='Foreground local backend or SSH tunnel supervisor')
    up.add_argument('--config', default=str(DEFAULT_PATH), help='Backend config path')
    up.add_argument('--player', help='Optional Unity Player executable or macOS .app bundle')
    up.add_argument('--publisher-config', help='Publisher config passed to the optional Player')
    up.add_argument('--ssh-target', help='Explicit user@host or host for a remote loopback backend')
    up.add_argument('--duration', type=int, help='Stop owned children after this many seconds (1..86400)')
    up.add_argument('--metrics-output', help='Optional JSONL health samples written once per second')
    status = sub.add_parser('status', help='Read loopback video health only; never starts or stops processes')
    status.add_argument('--config', default=str(DEFAULT_PATH), help='Backend config path')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            initialize(args.stream)
            return
        config_path = absolute_path(args.config)
        config = load(config_path)
        if args.command == 'doctor':
            versions = {name: importlib.metadata.version(name)
                        for name in ('aiohttp', 'aiortc', 'av', 'Pillow', 'psutil')}
            print(json.dumps({'configValid': True, 'bind': '127.0.0.1', 'port': config['port'],
                'streams': config['streams'], 'dependencies': versions,
                'unityCaptureVerified': False, 'webRtcVerified': False}, indent=2))
            return
        if args.command == 'status':
            print(json.dumps(readonly_status(config), separators=(',', ':')))
            return
        if args.command == 'up':
            publisher_path = absolute_path(args.publisher_config) if args.publisher_config else None
            metrics_path = absolute_path(args.metrics_output) if args.metrics_output else None
            code = supervise(config_path=config_path, config=config, player_value=args.player,
                             publisher_path=publisher_path, ssh_target=args.ssh_target,
                             duration=args.duration, metrics_output=metrics_path)
            if code:
                sys.exit(code)
            return
        import logging
        from aiohttp import web
        from Runtime.Video.server import create_app
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s %(message)s')
        logging.getLogger('flylingual.video').setLevel(logging.INFO)
        print(f'Video backend: http://127.0.0.1:{config["port"]} (Ctrl+C to stop)', flush=True)
        web.run_app(create_app(config), host='127.0.0.1', port=config['port'], access_log=None, print=None)
    except (LaunchError, ValueError, OSError, importlib.metadata.PackageNotFoundError) as exc:
        # Configuration errors never include config values or credentials.
        print(f'Video startup failed ({type(exc).__name__}). Check local config and requirements.', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
