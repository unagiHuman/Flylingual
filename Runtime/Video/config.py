"""Loopback-only configuration; secrets and machine paths stay outside Git."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / 'Runtime/Video/local/backend.json'


def load(path: str | Path = DEFAULT_PATH) -> dict:
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    data = json.loads(path.read_text(encoding='utf-8'))
    known = {'port', 'tokenFile', 'streams', 'allowedOrigins', 'iceServers', 'maxViewers'}
    if not isinstance(data, dict) or set(data) - known:
        raise ValueError('Unknown video configuration keys')
    port = data.get('port', 8880)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('port must be 1024..65535')
    maximum = data.get('maxViewers', 2)
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError('maxViewers must be 1..4')
    streams = data.get('streams', ['unity-mac', 'unity-windows'])
    import re
    if (not isinstance(streams, list) or not 1 <= len(streams) <= 8
            or any(not isinstance(s, str) or not re.fullmatch(r'[a-z0-9-]{1,40}', s) for s in streams)
            or len(set(streams)) != len(streams)):
        raise ValueError('Invalid or duplicate stream IDs')
    origins = data.get('allowedOrigins', [f'http://{host}:{p}'
        for host in ('127.0.0.1', 'localhost') for p in (8771, 18771, 4173, port)])
    if not isinstance(origins, list) or not origins:
        raise ValueError('allowedOrigins must be a nonempty list')
    for origin in origins:
        url = urlsplit(origin)
        if (url.scheme not in ('http', 'https') or url.hostname not in ('127.0.0.1', 'localhost', '::1')
                or url.username or url.password or url.path or url.query or url.fragment):
            raise ValueError('Only explicit loopback origins are supported; use SSH forwarding')
        _ = url.port
    ice = data.get('iceServers', [])
    if not isinstance(ice, list) or len(ice) > 4:
        raise ValueError('iceServers must be a list of at most 4 entries')
    for server in ice:
        if not isinstance(server, dict) or set(server) - {'urls', 'username', 'credential'}:
            raise ValueError('Invalid ICE server')
        urls = server.get('urls')
        urls = [urls] if isinstance(urls, str) else urls
        if not isinstance(urls, list) or not urls or any(not isinstance(u, str) or
                not u.startswith(('stun:', 'turn:', 'turns:')) for u in urls):
            raise ValueError('Invalid ICE URLs')
        if any(k in server and not isinstance(server[k], str) for k in ('username', 'credential')):
            raise ValueError('Invalid ICE credentials')
    token = os.environ.get('FLY_VIDEO_PUBLISH_TOKEN', '')
    if not token:
        token_path = Path(data.get('tokenFile', 'publish-token.txt'))
        if not token_path.is_absolute():
            token_path = path.parent / token_path
        token = token_path.read_text(encoding='utf-8').strip()
    if len(token) < 32 or len(token) > 256 or not token.isascii() or not token.isprintable():
        raise ValueError('A 32..256 character ASCII publisher token is required')
    return {**data, 'port': port, 'streams': streams, 'allowedOrigins': origins,
            'iceServers': ice, 'maxViewers': maximum, 'publishToken': token}
